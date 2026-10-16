"""Admin panel (SQLAdmin) at /admin, for admins only. Sees every user's data.

Mostly read-only: records are viewed, searched and deleted here, but created and edited through
the app, where validation lives. Users are created with the CLI (passwords need hashing).
"""

from fastapi import FastAPI, HTTPException
from markupsafe import Markup, escape
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request

from app.config import get_settings
from app.db import SessionLocal
from app.models import InterviewSession, Narrative, Subject, Transcript, Turn, User
from app.rate_limit import RateLimiter, client_ip
from app.security import verify_password

admin_login_limiter = RateLimiter(max_attempts=5, window_seconds=60)

EIGHT_HOURS = 8 * 60 * 60


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
