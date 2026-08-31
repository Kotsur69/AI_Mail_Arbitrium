"""The JSON the dashboard reads, and the built dashboard itself.

One process serves both, so running the UI is one command with no CORS story
in production. In development Vite serves the pages and proxies `/api` here,
which is why the dev origins below are allowed and nothing else is.

Every route is a GET. The pipeline writes; this reads. That is not a decision
to revisit lightly: a dashboard that could re-run a classification is a
dashboard that could quietly overwrite a verdict a person has already acted on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from arbitrium.config import DEFAULT_CONFIG_PATH, load_config
from arbitrium.web import queries

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "arbitrium.db"
DEFAULT_DIST_DIR = REPO_ROOT / "web" / "dist"

# Vite's dev server, on both hostnames it answers to. Nothing wider: this
# process reads a file full of supplier correspondence, and it is meant to be
# reachable from the LAN.
DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def campaign_summary(config_path: Path) -> dict[str, Any]:
    """What the suppliers were actually asked, so the reviewer judges the same question.

    Missing configuration is a state to render, not an error: a fresh checkout
    has no mailboxes.toml, and the dashboard should say so rather than 500.
    """
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError):
        return {"configured": False, "subject": "", "description": "", "model": None}
    return {
        "configured": config.campaign.configured,
        "subject": config.campaign.subject,
        "description": config.campaign.description,
        "model": config.llm.model,
    }


def create_app(
    db_path: Path = DEFAULT_DB_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    dist_dir: Path = DEFAULT_DIST_DIR,
) -> FastAPI:
    app = FastAPI(title="Arbitrium", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def missing() -> JSONResponse:
        """The empty state, as data. The UI renders it as instructions, not as a crash."""
        return JSONResponse(
            {"dbPresent": False, "dbPath": str(db_path), "campaign": campaign_summary(config_path)}
        )

    @app.get("/api/overview")
    def overview(mailbox: str | None = None) -> Any:
        try:
            with queries.connect(db_path) as connection:
                payload = queries.overview(connection, mailbox)
        except queries.DatabaseMissing:
            return missing()
        return {
            **payload,
            "dbPresent": True,
            "dbPath": str(db_path),
            "campaign": campaign_summary(config_path),
        }

    @app.get("/api/suppliers")
    def suppliers(mailbox: str | None = None) -> Any:
        try:
            with queries.connect(db_path) as connection:
                return {"items": queries.suppliers(connection, mailbox)}
        except queries.DatabaseMissing:
            return {"items": []}

    @app.get("/api/messages")
    def messages(
        mailbox: str | None = None,
        status: str | None = None,
        supplier: str | None = None,
        review: bool = False,
        q: str | None = None,
        limit: int = Query(queries.DEFAULT_PAGE_SIZE, ge=1, le=queries.MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ) -> Any:
        try:
            with queries.connect(db_path) as connection:
                return queries.messages(
                    connection,
                    mailbox=mailbox,
                    status=status,
                    supplier=supplier,
                    review_only=review,
                    query=q,
                    limit=limit,
                    offset=offset,
                )
        except queries.DatabaseMissing:
            return {"total": 0, "items": []}

    _mount_dashboard(app, dist_dir)
    return app


def _mount_dashboard(app: FastAPI, dist_dir: Path) -> None:
    """Serve the built single-page app, if it has been built.

    Mounted last so `/api/*` always wins, and skipped entirely when `web/dist`
    is absent -- during development the pages come from Vite, and a missing
    build should not stop the API from starting.

    `html=True` serves index.html at the root and still serves the real files
    beside it, which a catch-all route would have swallowed: bundled fonts and
    the favicon have to come back as themselves, not as the page.
    """
    if not (dist_dir / "index.html").exists():
        return

    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="dashboard")
