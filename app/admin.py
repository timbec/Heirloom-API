"""Admin panel (SQLAdmin) at /admin, for admins only. Sees every user's data.

Mostly read-only: records are viewed, searched and deleted here, but created and edited through
the app, where validation lives. Users are created with the CLI (passwords need hashing).
"""

from math import ceil
from pathlib import Path
from statistics import mean
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from markupsafe import Markup, escape
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.config import get_settings
from app.db import SessionLocal
from app.models import InterviewSession, Narrative, Subject, Transcript, Turn, User
from app.rate_limit import RateLimiter, client_ip
from app.security import verify_password
from app.services.turn_scoring import rescore_transcript
from app.services.turns import TurnParseError

admin_login_limiter = RateLimiter(max_attempts=5, window_seconds=60)

EIGHT_HOURS = 8 * 60 * 60
TURNS_PER_PAGE = 10


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        try:
            admin_login_limiter.hit(client_ip(request))
        except HTTPException:
            return False

        form = await request.form()
        email = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == email))
        if not verify_password(password, user.password_hash if user else None):
            return False
        if not user.is_admin:
            return False
        request.session.update({"user_id": user.id})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Checked on every request, so removing someone's admin flag locks them out at once."""
        user_id = request.session.get("user_id")
        if user_id is None:
            return False
        async with SessionLocal() as db:
            user = await db.get(User, user_id)
        return user is not None and user.is_admin


def _truncate(length: int):
    def format(model, attribute) -> str:
        value = getattr(model, attribute) or ""
        return value if len(value) <= length else value[:length].rstrip() + "…"

    return format


def _long_text(model, attribute) -> Markup:
    """Show long text with its line breaks on detail pages."""
    value = getattr(model, attribute) or ""
    return Markup('<div style="white-space: pre-wrap; max-width: 60rem">{}</div>').format(
        escape(value)
    )


class UserAdmin(ModelView, model=User):
    name_plural = "Users"
    icon = "fa-solid fa-user"
    column_list = [User.id, User.email, User.name, User.is_admin, User.created_at]
    column_searchable_list = [User.email, User.name]
    column_sortable_list = [User.id, User.email, User.created_at]
    column_details_exclude_list = [User.password_hash, User.tokens]
    form_columns = [User.name, User.is_admin]
    can_create = False
    can_export = False


class SubjectAdmin(ModelView, model=Subject):
    name_plural = "Subjects"
    icon = "fa-solid fa-person"
    column_list = [Subject.id, Subject.name, Subject.user, Subject.birth_year, Subject.created_at]
    column_searchable_list = [Subject.name]
    column_sortable_list = [Subject.id, Subject.name, Subject.created_at]
    column_default_sort = [(Subject.id, True)]
    can_create = False
    can_edit = False


class SessionAdmin(ModelView, model=InterviewSession):
    name = "Session"
    name_plural = "Sessions"
    icon = "fa-solid fa-microphone"
    column_list = [
        InterviewSession.id,
        InterviewSession.subject,
        InterviewSession.title,
        InterviewSession.status,
        InterviewSession.created_at,
    ]
    column_searchable_list = [InterviewSession.title]
    column_sortable_list = [
        InterviewSession.id,
        InterviewSession.status,
        InterviewSession.created_at,
    ]
    column_default_sort = [(InterviewSession.id, True)]
    can_create = False
    can_edit = False


class TranscriptAdmin(ModelView, model=Transcript):
    name_plural = "Transcripts"
    icon = "fa-solid fa-file-lines"
    column_list = [
        Transcript.id,
        Transcript.session,
        Transcript.source,
        Transcript.status,
        Transcript.transcript_text,
        Transcript.created_at,
    ]
    column_labels = {Transcript.transcript_text: "Text"}
    column_formatters = {Transcript.transcript_text: _truncate(80)}
    column_formatters_detail = {Transcript.transcript_text: _long_text}
    column_searchable_list = [Transcript.transcript_text]
    column_sortable_list = [Transcript.id, Transcript.created_at]
    column_default_sort = [(Transcript.id, True)]
    can_create = False
    can_edit = False

    def _action_url(self, request: Request, name: str, pk: int, **params: str) -> str:
        return f"{self._url_for_action(request, name)}?{urlencode({'pks': pk, **params})}"

    @action(
        name="score-turns",
        label="Score turns",
        confirmation_message=(
            "Split the selected transcript(s) into turns and score each one with the AI? "
            "Earlier scores are replaced. This can take a minute or two per transcript."
        ),
    )
    async def score_turns(self, request: Request) -> Response:
        """Runs the same scoring as the API, then shows the results (or the list, for several)."""
        pks = [int(pk) for pk in request.query_params.get("pks", "").split(",") if pk]
        message = ""
        for pk in pks:
            async with SessionLocal() as db:
                transcript = await db.scalar(
                    select(Transcript)
                    .where(Transcript.id == pk)
                    .options(joinedload(Transcript.session).joinedload(InterviewSession.subject))
                )
                if transcript is None:
                    continue
                try:
                    turns, scored = await rescore_transcript(db, transcript)
                except TurnParseError as exc:
                    message = str(exc)
                    continue
                if scored < len(turns):
                    message = (
                        f"{len(turns) - scored} of {len(turns)} turns couldn't be scored "
                        "(usually the AI's rate limit). Score again to retry."
                    )
        if len(pks) == 1:
            params = {"message": message} if message else {}
            return RedirectResponse(
                self._action_url(request, "view-turns", pks[0], **params), status_code=303
            )
        return RedirectResponse(request.url_for("admin:list", identity="turn"), status_code=303)

    @action(name="view-turns", label="View turns", add_in_list=False)
    async def view_turns(self, request: Request) -> Response:
        pk = int(request.query_params.get("pks", "0").split(",")[0] or 0)
        async with SessionLocal() as db:
            transcript = await db.scalar(
                select(Transcript)
                .where(Transcript.id == pk)
                .options(
                    joinedload(Transcript.session).joinedload(InterviewSession.subject),
                    selectinload(Transcript.turns),
                )
            )
        if transcript is None:
            return RedirectResponse(request.url_for("admin:list", identity="transcript"))

        turns = transcript.turns
        pages = max(1, ceil(len(turns) / TURNS_PER_PAGE))
        try:
            page = min(max(1, int(request.query_params.get("page", 1))), pages)
        except ValueError:
            page = 1
        shown = turns[(page - 1) * TURNS_PER_PAGE : page * TURNS_PER_PAGE]
        scored = [t for t in turns if t.scored_at]
        summary = {
            "total": len(turns),
            "scored": len(scored),
            "gold": sum(t.is_gold for t in scored),
            "avg_specificity": round(mean(t.specificity for t in scored), 1) if scored else "–",
            "avg_charge": round(mean(t.emotional_charge for t in scored), 1) if scored else "–",
            "open_threads": [(t.turn_index, t.open_thread) for t in scored if t.open_thread],
            "scored_with": sorted({t.scored_with for t in scored if t.scored_with}),
        }
        return await self.templates.TemplateResponse(
            request,
            "heirloom/transcript_turns.html",
            {
                "title": "Turns",
                "transcript": transcript,
                "session": transcript.session,
                "subject": transcript.session.subject,
                "turns": shown,
                "summary": summary,
                "page": page,
                "pages": pages,
                "first_index": shown[0].turn_index if shown else 0,
                "last_index": shown[-1].turn_index if shown else 0,
                "page_url": lambda p: self._action_url(request, "view-turns", pk, page=str(p)),
                "message": request.query_params.get("message"),
                "score_url": self._action_url(request, "score-turns", pk),
                "transcript_url": request.url_for("admin:details", identity="transcript", pk=pk),
            },
        )


class TurnAdmin(ModelView, model=Turn):
    name_plural = "Turns"
    icon = "fa-solid fa-comments"
    column_list = [
        Turn.transcript,
        Turn.turn_index,
        Turn.specificity,
        Turn.emotional_charge,
        Turn.thread_type,
        Turn.is_gold,
        Turn.gold_quote,
        Turn.open_thread,
        Turn.sensitivity,
    ]
    column_labels = {Turn.turn_index: "#", Turn.emotional_charge: "Charge"}
    column_formatters = {Turn.gold_quote: _truncate(60), Turn.open_thread: _truncate(40)}
    column_searchable_list = [Turn.question, Turn.answer, Turn.gold_quote]
    column_sortable_list = [Turn.turn_index, Turn.specificity, Turn.emotional_charge, Turn.is_gold]
    column_default_sort = [(Turn.transcript_id, True), (Turn.turn_index, False)]
    page_size = 25
    can_create = False
    can_edit = False


class NarrativeAdmin(ModelView, model=Narrative):
    name_plural = "Narratives"
    icon = "fa-solid fa-book-open"
    column_list = [
        Narrative.id,
        Narrative.subject,
        Narrative.format,
        Narrative.status,
        Narrative.model,
        Narrative.session_ids,
        Narrative.narrative_text,
        Narrative.created_at,
    ]
    column_labels = {Narrative.session_ids: "Sessions", Narrative.narrative_text: "Text"}
    column_formatters = {Narrative.narrative_text: _truncate(60)}
    column_formatters_detail = {Narrative.narrative_text: _long_text, Narrative.error: _long_text}
    column_searchable_list = [Narrative.narrative_text]
    column_sortable_list = [Narrative.id, Narrative.status, Narrative.created_at]
    column_default_sort = [(Narrative.id, True)]
    can_create = False
    can_edit = False


def mount_admin(app: FastAPI) -> Admin:
    settings = get_settings()
    admin = Admin(
        app,
        session_maker=SessionLocal,
        base_url="/admin",
        title="Heirloom admin",
        templates_dir=str(Path(__file__).parent / "templates"),
        authentication_backend=AdminAuth(
            secret_key=settings.secret_key,
            max_age=EIGHT_HOURS,
            https_only=settings.secure_cookies,
            same_site="lax",
        ),
    )
    for view in (UserAdmin, SubjectAdmin, SessionAdmin, TranscriptAdmin, TurnAdmin, NarrativeAdmin):
        admin.add_view(view)
    return admin
