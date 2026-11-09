"""Admin commands for the RQ3 study database.

    python -m rq3.admin list                      every participant and how far they got
    python -m rq3.admin show P001                 everything stored for P001 (JSON)
    python -m rq3.admin delete P001               delete P001 and all their data
    python -m rq3.admin delete-all                delete every participant (asks first)
    python -m rq3.admin links P001 P002 --base https://<app>.onrender.com

Uses RQ3_DATABASE_URL when set (e.g. the Render database's external URL), and the
local development database in .rq3_dev_db/ otherwise. Deleting is permanent and
also frees that participant's feed order for balancing; the same ID can then
start over from the beginning.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote, urlsplit

from rq3 import storage
from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.devdb import database_url_or_local
from rq3.study import Study, StudyError

DEFAULT_BASE = "http://127.0.0.1:5001"


def describe(url: str, is_local: bool) -> str:
    return "the local development database" if is_local else f"the database at {urlsplit(url).hostname}"


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def cmd_list(db: storage.Connection, _args) -> int:
    rows = storage.list_participants(db)
    if not rows:
        print("No participants yet.")
        return 0
    print(f"{'participant':<16}{'order':<7}{'parts done':<12}{'videos':<8}{'created (UTC)':<22}completed")
    for row in rows:
        print(
            f"{row['id']:<16}{row['feed_order']:<7}{row['parts_done']}/3{'':<8}{row['videos_shown']:<8}"
            f"{row['created_at'][:19]:<22}{'yes' if row['completed_at'] else 'no'}"
        )
    return 0


def cmd_show(db: storage.Connection, args) -> int:
    study = Study(load_catalog(), DEFAULT_CONFIG)
    try:
        print(json.dumps(study.export(db, args.participant_id), indent=2, ensure_ascii=False))
    except StudyError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def cmd_delete(db: storage.Connection, args) -> int:
    if storage.get_participant(db, args.participant_id) is None:
        print(f"No participant {args.participant_id}.", file=sys.stderr)
        return 1
    if not confirm(f"Permanently delete {args.participant_id} and all their data from {args.where}?", args.yes):
        print("Nothing deleted.")
        return 1
    storage.delete_participant(db, args.participant_id)
    print(f"Deleted {args.participant_id}.")
    return 0


def cmd_delete_all(db: storage.Connection, args) -> int:
    count = len(storage.list_participants(db))
    if not count:
        print("No participants to delete.")
        return 0
    if not confirm(f"Permanently delete all {count} participants from {args.where}?", args.yes):
        print("Nothing deleted.")
        return 1
    storage.clear_all(db)
    print(f"Deleted {count} participants.")
    return 0


def cmd_links(_db, args) -> int:
    base = args.base.rstrip("/")
    for participant_id in args.participant_ids:
        Study.check_participant_id(participant_id)
        print(f"{participant_id}: {base}/participant?pid={quote(participant_id)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admin commands for the RQ3 study database.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="every participant and how far they got")
    show = commands.add_parser("show", help="everything stored for one participant")
    show.add_argument("participant_id")
    delete = commands.add_parser("delete", help="delete one participant and all their data")
    delete.add_argument("participant_id")
    delete.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    delete_all = commands.add_parser("delete-all", help="delete every participant")
    delete_all.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    links = commands.add_parser("links", help="print participant links")
    links.add_argument("participant_ids", nargs="+")
    links.add_argument("--base", default=DEFAULT_BASE, help=f"where the study runs (default {DEFAULT_BASE})")
    args = parser.parse_args(argv)

    if args.command == "links":
        return cmd_links(None, args)

    url, is_local = database_url_or_local()
    args.where = describe(url, is_local)
    with storage.connect(url) as db:
        storage.init_schema(db)
        handler = {"list": cmd_list, "show": cmd_show, "delete": cmd_delete, "delete-all": cmd_delete_all}
        return handler[args.command](db, args)


if __name__ == "__main__":
    sys.exit(main())
