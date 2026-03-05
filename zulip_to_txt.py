#!/usr/bin/env python3
"""Read `team: hash` messages from a Zulip stream and persist new entries.

Behavior:
- Fetches messages from a Zulip stream (and optional topic)
- Parses lines matching `team: hash`
- Writes only new team names to a text file as `team: hash`
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

TEAM_HASH_RE = re.compile(r"\*{0,2}([A-Za-z0-9_-]+)\*{0,2}\s*:\s*`?([A-Za-z0-9+/=_-]{16,})`?")

# Edit these defaults directly if you prefer not to pass CLI arguments.
ZULIP_SITE = "CHANGE"
ZULIP_EMAIL = "CHCHANGE"
ZULIP_STREAM = "CHANGE"
ZULIP_TOPIC = 'CHANGE'
OUTPUT_FILE = "team_hashes.txt"
PAGE_SIZE = 200
MAX_PAGES = 20


def build_messages_url(site: str, stream: str, topic: str | None, anchor: str | int, num_before: int) -> str:
    narrow = [{"operator": "stream", "operand": stream}]
    if topic:
        narrow.append({"operator": "topic", "operand": topic})

    narrow_encoded = quote(json.dumps(narrow, separators=(",", ":")), safe="")
    anchor_encoded = quote(str(anchor), safe="")

    return (
        f"{site.rstrip('/')}/api/v1/messages"
        f"?anchor={anchor_encoded}&num_before={num_before}&num_after=0"
        f"&apply_markdown=false&narrow={narrow_encoded}"
    )


def fetch_messages_page(
    site: str,
    email: str,
    api_key: str,
    stream: str,
    topic: str | None,
    anchor: str | int,
    num_before: int,
) -> dict:
    url = build_messages_url(site, stream, topic, anchor, num_before)
    credentials = f"{email}:{api_key}".encode("utf-8")
    auth = base64.b64encode(credentials).decode("ascii")

    req = Request(url, headers={"Authorization": f"Basic {auth}"})

    with urlopen(req, timeout=30) as response:
        payload = response.read().decode("utf-8")

    data = json.loads(payload)
    if data.get("result") != "success":
        msg = data.get("msg", "unknown Zulip API error")
        raise RuntimeError(f"Zulip API error: {msg}")

    return data


def iter_team_hash_pairs(messages: Iterable[dict]) -> Iterable[tuple[str, str]]:
    for message in messages:
        content = message.get("content") or ""
        for line in content.splitlines():
            cleaned = line.strip()
            if cleaned.startswith("- "):
                cleaned = cleaned[2:].strip()
            elif cleaned.startswith("* "):
                cleaned = cleaned[2:].strip()
            match = TEAM_HASH_RE.search(cleaned)
            if match:
                yield match.group(1), match.group(2)


def read_existing_teams(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    existing: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = TEAM_HASH_RE.match(line)
        if match:
            existing[match.group(1)] = match.group(2)

    return existing


def append_entries(path: Path, entries: list[tuple[str, str]]) -> None:
    if not entries:
        return

    with path.open("a", encoding="utf-8") as f:
        for team, digest in entries:
            f.write(f"{team}: {digest}\n")


def collect_messages(
    site: str,
    email: str,
    api_key: str,
    stream: str,
    topic: str | None,
    page_size: int,
    max_pages: int,
) -> list[dict]:
    all_messages: list[dict] = []
    anchor: str | int = "newest"

    for _ in range(max_pages):
        data = fetch_messages_page(
            site=site,
            email=email,
            api_key=api_key,
            stream=stream,
            topic=topic,
            anchor=anchor,
            num_before=page_size,
        )

        messages = data.get("messages", [])
        if not messages:
            break

        all_messages.extend(messages)

        found_oldest = bool(data.get("found_oldest"))
        if found_oldest:
            break

        oldest_id = min((msg.get("id") for msg in messages if isinstance(msg.get("id"), int)), default=None)
        if oldest_id is None:
            break

        anchor = oldest_id

    return all_messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull `team: hash` messages from Zulip to a text file")
    parser.add_argument("--site", default=ZULIP_SITE, help="Zulip site URL (e.g. https://your-org.zulipchat.com)")
    parser.add_argument("--email", default=ZULIP_EMAIL, help="Zulip bot/user email")
    parser.add_argument("--api-key", default=ZULIP_API_KEY, help="Zulip API key")
    parser.add_argument("--stream", default=ZULIP_STREAM, help="Zulip stream/channel name")
    parser.add_argument("--topic", default=ZULIP_TOPIC, help="Optional topic filter")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output .txt file")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE, help="Messages to fetch per API call")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="Maximum API pages to fetch")

    args = parser.parse_args()

    placeholders = {
        "https://YOUR-ORG.zulipchat.com",
        "YOUR_BOT_EMAIL",
        "YOUR_API_KEY",
        "YOUR_STREAM",
    }
    required_values = [args.site, args.email, args.api_key, args.stream]
    if any(value in placeholders for value in required_values):
        print(
            "Set Zulip values in the config block at the top of this script "
            "or pass --site/--email/--api-key/--stream.",
            file=sys.stderr,
        )
        return 2

    try:
        messages = collect_messages(
            site=args.site,
            email=args.email,
            api_key=args.api_key,
            stream=args.stream,
            topic=args.topic,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    except Exception as exc:
        print(f"Failed to fetch Zulip messages: {exc}", file=sys.stderr)
        return 1

    existing = read_existing_teams(Path(args.output))
    to_append: list[tuple[str, str]] = []
    parsed_count = 0

    for team, digest in iter_team_hash_pairs(messages):
        parsed_count += 1
        if team in existing:
            continue
        existing[team] = digest
        to_append.append((team, digest))

    append_entries(Path(args.output), to_append)

    print(f"Scanned {len(messages)} message(s).")
    print(f"Parsed {parsed_count} team/hash entr{'y' if parsed_count == 1 else 'ies'} from messages.")
    print(f"Added {len(to_append)} new team entr{'y' if len(to_append) == 1 else 'ies'} to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
