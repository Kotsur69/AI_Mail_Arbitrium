"""Serve the read-only dashboard over the verdicts already on disk.

Nothing here classifies or ingests. Point it at the same --db the backfill
writes and it shows what has been decided so far, including while a run is
still going: SQLite in WAL mode lets this read a database the CLI is writing.

Binds to localhost by default. The blueprint wants this reachable at
192.168.x.x eventually, but a file of supplier correspondence should go onto
the LAN because someone typed --host, not because a default did it quietly.

Examples:
  .venv/Scripts/python.exe scripts/serve_dashboard.py
  .venv/Scripts/python.exe scripts/serve_dashboard.py --db data/demo.db
  .venv/Scripts/python.exe scripts/serve_dashboard.py --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn  # noqa: E402

from arbitrium.config import DEFAULT_CONFIG_PATH  # noqa: E402
from arbitrium.web.api import DEFAULT_DB_PATH, DEFAULT_DIST_DIR, create_app  # noqa: E402

LOCALHOST = "127.0.0.1"
DEFAULT_PORT = 8000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Verdict database to read")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="mailboxes.toml")
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST_DIR, help="Built web/dist")
    parser.add_argument(
        "--host",
        default=LOCALHOST,
        help=f"Interface to bind. Default {LOCALHOST}, this machine only",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def announce(args: argparse.Namespace) -> None:
    """Say what will be served, and what is missing, before uvicorn takes the terminal."""
    missing_db = "" if args.db.exists() else "   (brak -- dashboard bedzie pusty)"
    built = (args.dist / "index.html").exists()
    print(f"  baza      {args.db}{missing_db}")
    print(f"  interfejs {args.dist}{'' if built else '   (niezbudowany -- uzyj npm run dev)'}")
    print(f"  adres     http://{args.host}:{args.port}")
    if args.host != LOCALHOST:
        print("  UWAGA: dashboard pokazuje tresc korespondencji i jest widoczny w sieci.")
    print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    announce(args)
    uvicorn.run(
        create_app(db_path=args.db, config_path=args.config, dist_dir=args.dist),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
