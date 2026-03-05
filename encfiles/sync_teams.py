#!/usr/bin/env python3
"""Sync eCTF team names from `uvx ectf api list` into a text file.

Behavior:
- Reads team names from `uvx ectf api list`
- Appends only new team names to the text file
- Runs `uvx ectf api get <teamname>` for each newly added team
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LIST_CMD = ["uvx", "ectf", "api", "list"]
GET_CMD_PREFIX = ["uvx", "ectf", "api", "get"]


def run_list_command() -> str:
    try:
        completed = subprocess.run(
            LIST_CMD,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("Error: `uvx` not found in PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print("Error running `uvx ectf api list`.", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        sys.exit(exc.returncode)

    return completed.stdout


def parse_team_names(list_output: str) -> list[str]:
    teams: list[str] = []
    seen: set[str] = set()
    token_pattern = re.compile(r"^[A-Za-z0-9_-]+$")

    for raw_line in list_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("the following packages are available"):
            continue

        # Valid team names in this output are single tokens like `cwru`, `mitre`, etc.
        if not token_pattern.fullmatch(line):
            continue

        if line not in seen:
            seen.add(line)
            teams.append(line)

    return teams


def read_existing_teams(path: Path) -> set[str]:
    if not path.exists():
        return set()

    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_new_teams(path: Path, new_teams: list[str]) -> None:
    if not new_teams:
        return

    with path.open("a", encoding="utf-8") as f:
        for team in new_teams:
            f.write(f"{team}\n")


def fetch_team(team: str) -> int:
    try:
        completed = subprocess.run(GET_CMD_PREFIX + [team], check=False)
    except FileNotFoundError:
        print("Error: `uvx` not found in PATH.", file=sys.stderr)
        return 1

    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync eCTF teams and fetch new ones")
    parser.add_argument(
        "--file",
        default="teams.txt",
        help="Path to the team list text file (default: teams.txt)",
    )
    args = parser.parse_args()

    output = run_list_command()
    listed_teams = parse_team_names(output)

    if not listed_teams:
        print("No team names found in list output.")
        return 0

    file_path = Path(args.file)
    existing = read_existing_teams(file_path)

    new_teams = [team for team in listed_teams if team not in existing]
    append_new_teams(file_path, new_teams)

    if not new_teams:
        print("No new teams found.")
        return 0

    print(f"Found {len(new_teams)} new team(s). Appended to {file_path}.")

    failures = 0
    for team in new_teams:
        print(f"Fetching team: {team}")
        rc = fetch_team(team)
        if rc != 0:
            failures += 1
            print(f"Failed to fetch {team} (exit code {rc}).", file=sys.stderr)

    if failures:
        print(f"Done with {failures} fetch failure(s).", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
