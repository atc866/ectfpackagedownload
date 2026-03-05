#!/usr/bin/env python3
"""Decrypt team .enc files using keys from team_hashes.txt and extract packages.

For each line in keys file:
    team: key

The script runs:
    openssl enc -d -aes-256-cbc -pbkdf2 -salt -k <key> -in <team>.enc -out <team>.zip

Then extracts <team>.zip into <team>_package.
If <team>_package already exists, that team is skipped.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

TEAM_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(\S+)\s*$")


def load_team_keys(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Key file not found: {path}")

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = TEAM_KEY_RE.match(line)
        if not match:
            print(f"Skipping malformed line {line_no}: {raw_line}", file=sys.stderr)
            continue

        team, key = match.group(1), match.group(2)
        if team in seen:
            continue

        seen.add(team)
        pairs.append((team, key))

    return pairs


def decrypt_zip(enc_path: Path, zip_path: Path, key: str) -> None:
    cmd = [
        "openssl",
        "enc",
        "-d",
        "-aes-256-cbc",
        "-pbkdf2",
        "-salt",
        "-k",
        key,
        "-in",
        str(enc_path),
        "-out",
        str(zip_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if completed.stderr else "openssl command failed"
        raise RuntimeError(stderr)


def extract_zip(zip_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path, "r") as zf:
        zf.extractall(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decrypt .enc team files and extract team packages")
    parser.add_argument("--keys", default="team_hashes.txt", help="Path to team:key file (default: team_hashes.txt)")
    parser.add_argument("--enc-dir", default="encfile", help="Directory containing <team>.enc files")
    parser.add_argument("--out-dir", default=".", help="Base directory for output zips/folders")
    parser.add_argument("--keep-zip", action="store_true", help="Keep decrypted <team>.zip after extraction")

    args = parser.parse_args()

    keys_path = Path(args.keys)
    enc_dir = Path(args.enc_dir)
    out_dir = Path(args.out_dir)

    if not enc_dir.exists() and args.enc_dir == "encfile":
        fallback = Path("encfiles")
        if fallback.exists():
            enc_dir = fallback
            print("Using encfiles/ as --enc-dir fallback.")

    try:
        team_keys = load_team_keys(keys_path)
    except Exception as exc:
        print(f"Error reading keys file: {exc}", file=sys.stderr)
        return 1

    if not team_keys:
        print("No valid team keys found.")
        return 0

    success = 0
    skipped_existing_folder = 0
    skipped_missing_enc = 0
    failed = 0

    for team, key in team_keys:
        package_dir = out_dir / f"{team}_package"
        enc_path = enc_dir / f"{team}.enc"
        zip_path = out_dir / f"{team}.zip"

        if package_dir.exists() and package_dir.is_dir():
            print(f"Skipping {team}: {package_dir} already exists")
            skipped_existing_folder += 1
            continue

        if not enc_path.exists():
            print(f"Skipping {team}: missing {enc_path}")
            skipped_missing_enc += 1
            continue

        print(f"Decrypting {enc_path.name} -> {zip_path.name}")
        try:
            decrypt_zip(enc_path, zip_path, key)
            extract_zip(zip_path, package_dir)
        except BadZipFile:
            failed += 1
            print(f"Failed {team}: decrypted output is not a valid zip", file=sys.stderr)
            if zip_path.exists() and not args.keep_zip:
                zip_path.unlink()
            continue
        except Exception as exc:
            failed += 1
            print(f"Failed {team}: {exc}", file=sys.stderr)
            if zip_path.exists() and not args.keep_zip:
                zip_path.unlink()
            continue

        if zip_path.exists() and not args.keep_zip:
            zip_path.unlink()

        success += 1
        print(f"Extracted to {package_dir}")

    print("\nSummary")
    print(f"Successful: {success}")
    print(f"Skipped (package exists): {skipped_existing_folder}")
    print(f"Skipped (missing .enc): {skipped_missing_enc}")
    print(f"Failed: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
