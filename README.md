# Heirloom API

This is the **backend** for Heirloom: the part that stores everything, runs the AI, and serves the website. You don't see it directly. The website people use (the `heirloom-web` project) talks to it behind the scenes.

**Status:** working on Tim's computer. Not online yet.

## What Heirloom does

An adult child interviews an elderly parent. Heirloom helps turn those conversations into a life story:

1. **Record or paste the interview.** Type or paste a transcript, or upload a recording (a phone voice memo works) and the AI writes it out.
2. **Find what matters.** The AI goes through the interview answer by answer. It marks the lines worth keeping word for word ("gold"), the threads worth following up next time, and the places to leave alone.
3. **Review it.** The interviewer sees the transcript marked up, with notes in the margin, and can add their own marks and notes.
4. **Plan the next session.** A memo suggests questions for next time, which the interviewer can tick, edit or add to.
5. **Write the story.** The AI writes a first-person narrative in the parent's voice (a memoir, a letter, or a timeline), built from all the sessions so far. Every version is kept, so the story can grow over time.

## What works today

| | |
|---|---|
| **Accounts** | People log in with email and password. Each person only ever sees their own family's interviews. There's no public sign-up yet: Tim creates accounts. |
| **Interviews** | Add the person being interviewed, then one session per interview. |
| **Transcripts** | Paste one in, or upload a recording (up to 25 MB) for the AI to transcribe. The original recording is kept. |
| **Finding the gold** | The AI scores every answer and picks out quotes to keep and threads to follow up. Still being tuned: see "Where things stand". |
| **The story** | The AI writes the narrative in the parent's own voice, and keeps every version. |
| **Review page** | The marked-up transcript and the plan for the next session (on the website). |
| **Admin panel** | A behind-the-scenes view for Tim (and Rindy) of everything in the system: every account, interview, score and story. |

## How the pieces fit

```
  The website (heirloom-web)          what families use
            │
            ▼
  This backend (heirloom-api)  ──►  Groq, the AI service: transcription,
            │                       scoring and story writing
            ▼
  The database                      where everything is stored
```

The AI's instructions (its "prompts") are what decide how good the marks and stories are. They're plain English, and Tim can show you them. The product's guiding idea: *if the story moves the reader, there's a product; if it feels flat, fix the prompt, not the app.*

## Where things stand

Working, but still to do:

- **Scoring quality.** The AI is good at spotting vivid details, but it used to miss quiet, plain-spoken lines like *"I want them to know somebody pushed."* A revised set of instructions does better, and it's being tested against sample interviews.
- **Speed.** Long interviews make you wait while the AI works, and the free AI plan limits how fast it can go. Both are fixable: a paid plan, and doing the work in the background.
- **Planning the next session.** The "notes for next session" memo is designed and built, but for now it shows sample content. The step that writes it from a real interview isn't built yet.
- **Recordings with two voices.** The AI writes out a recording as one block of text, without separating the interviewer from the parent. That needs solving before recordings can be scored.
- **Going online.** Not deployed yet.

### Questions worth brainstorming

- Who is the first real user, and what should their first session feel like?
- How much should the interviewer see (scores, marks, suggestions) versus just a calm list of next questions?
- How should someone pick which version of the story to keep or share?
- What's paid for, and when: per session, per family, or per finished story?
- What does "handle with care" look like for painful memories, or when the parent says "don't put that in"?

## Trying it yourself (Mac)

The easiest way to see Heirloom is for **Tim to show you on his computer**, or to wait until it's online. Running it yourself takes about 30 minutes and means typing commands into the Terminal app. Each step below is copy and paste, and you'll need a few things from Tim along the way: an AI key, and possibly a hand if something doesn't match.

<details>
<summary>Step-by-step instructions</summary>

You'll type commands into **Terminal** (in Applications → Utilities). Copy each grey box, paste it into Terminal, and press Return.

1. **Install Homebrew** (a tool for installing other tools), if you don't have it. Follow the one-line instruction at [brew.sh](https://brew.sh).

2. **Install uv**, which runs the backend:
   ```bash
   brew install uv
   ```

3. **Install Postgres.app**, the database. Download it from [postgresapp.com](https://postgresapp.com/), drag it to Applications, open it, and click **Initialize**. Leave it running.

4. **Download the code.** This puts it in a folder called `heirloom-api` in your home folder:
   ```bash
   cd ~ && git clone https://github.com/timbec/Heirloom-API.git heirloom-api && cd heirloom-api
   ```

5. **Install the backend's parts:**
   ```bash
   uv sync
   ```

6. **Create the two databases** (one for using it, one for its self-tests):
   ```bash
   /Applications/Postgres.app/Contents/Versions/latest/bin/createdb heirloom
   /Applications/Postgres.app/Contents/Versions/latest/bin/createdb heirloom_test
   ```

7. **Create the settings file:**
   ```bash
   cp .env.example .env && open -e .env
   ```
   This opens it in TextEdit. Make two changes and save:
   - After `SECRET_KEY=`, type any long string of random letters and numbers (at least 40).
   - After `GROQ_API_KEY=`, paste the AI key Tim gives you. Without it everything works except the AI parts.

8. **Set up the database:**
   ```bash
   uv run alembic upgrade head
   ```

9. **Create your login.** It asks for a password (nothing shows as you type; that's normal):
   ```bash
   uv run python -m app.cli create-user --email your@email.com --name "Rindy" --admin
   ```

10. **Load a sample interview** ("Frances"), so there's something to look at:
    ```bash
    uv run python -m app.cli seed-review
    ```

11. **Start it:**
    ```bash
    uv run uvicorn app.main:app --reload
    ```
    Leave this window open while you use it. To stop it, press Control-C.

12. **Look around** in your web browser:
    - **Admin panel:** http://localhost:8000/admin. Log in with the email and password from step 9, then open **Transcripts** and click **Review** on Frances's transcript.
    - **API documentation:** http://localhost:8000/api/docs, a technical list of everything the website can ask the backend to do.

**Next time**, you only need to open Postgres.app, then run `cd ~/heirloom-api && uv run uvicorn app.main:app --reload`.

To see the website itself (not just the admin panel), the `heirloom-web` project needs setting up the same way. Ask Tim.

</details>

---

## For developers

FastAPI (Python 3.13) · PostgreSQL 17 with SQLAlchemy 2 and Alembic · SQLAdmin · Groq (Whisper, gpt-oss) · pytest · uv · ruff. `CLAUDE.md` has fuller conventions for working with Claude Code.

**Setup** is the steps above. Postgres via Homebrew or Docker works too: for Docker, set `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/heirloom` and `TEST_DATABASE_URL` to the matching `heirloom_test` URL. Generate a `SECRET_KEY` with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Model names (`GROQ_*`) live in `.env` because Groq retires models without notice. `SCORING_PROMPT` picks the scoring prompt (`v1` or the draft `v2`). `.env` changes need a server restart.

**Commands**

```bash
uv run uvicorn app.main:app --reload                 # run (API under /api, docs at /api/docs, admin at /admin)
uv run pytest                                        # tests (always the heirloom_test database; AI calls faked)
uv run ruff format . && uv run ruff check .          # format and lint
uv run alembic revision --autogenerate -m "..."      # after changing a model; review the generated file
uv run python -m app.cli create-user --email … --name … [--admin]   # also: set-password, seed-review
uv run python -m scripts.score_fixtures --prompts v1 v2   # score sample interviews with the real AI; report in reports/
```

**Frontend:** in `heirloom-web`, set `NEXT_PUBLIC_API_URL=http://localhost:8000/api` in `.env.local`, then `npm install && npm run dev` (http://localhost:3000).

**Layout**

```
app/main.py          app setup: routes under /api, CORS, error format, admin
app/config.py        settings from .env
app/models/          database tables
app/api/             endpoints: auth, subjects, sessions, transcripts, narratives, turns, review
app/services/        groq.py (the only AI client), narratives.py and scoring.py (the prompts),
                     turns.py (transcript → turns), annotations.py (Review marks)
app/admin.py         admin panel; templates in app/templates/
app/cli.py           create-user, set-password, seed-review
migrations/          schema changes (Alembic)
tests/               pytest; sample interviews in tests/fixtures/interviews/
```

**Conventions:** routes keep the old Laravel API's paths, so the frontend didn't change. Errors are Laravel-shaped (`{"message"}`, plus `"errors"` for validation). Every record belongs to a subject, and every subject to one user; another user's record returns 403. Only the admin panel sees across users.
