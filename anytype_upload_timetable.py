#!/usr/bin/env python3
"""Upload timetable.md into Anytype as a page.

Creates or updates a page in the ``ASV x SS`` space with the contents of
``timetable.md``.

Configuration is read from environment variables:

* ``ANYTYPE_API_KEY`` or ``ANTYPE_KEY`` - required Anytype API key
* ``ANYTYPE_BASE_URL`` - defaults to ``http://localhost:31009``
* ``ANYTYPE_VERSION`` - defaults to ``2025-11-08``
* ``TIMETABLE_FILE`` - defaults to ``timetable.md``
* ``ANYTYPE_SPACE_NAME`` - defaults to ``ASV x SS``

Usage:

    python anytype_upload_timetable.py --dry-run
    python anytype_upload_timetable.py
    python anytype_upload_timetable.py timetable.md --title "India Wildlife Timetable"
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Iterable, List, Optional

import requests


BASE_URL = os.getenv("ANYTYPE_BASE_URL", "http://localhost:31009")
API_KEY = os.getenv("ANYTYPE_API_KEY") or os.getenv("ANTYPE_KEY")
API_VERSION = os.getenv("ANYTYPE_VERSION", "2025-11-08")

SPACE_NAME = os.getenv("ANYTYPE_SPACE_NAME", "ASV x SS")
TYPE_KEY = "page"
TIMETABLE_FILE = os.getenv("TIMETABLE_FILE", "timetable.md")


class AnytypeClient:
    def __init__(self, base_url: str, api_key: str, version: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Anytype-Version": version,
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        max_retries = int(os.getenv("ANYTYPE_MAX_RETRIES", "5"))
        base_delay = float(os.getenv("ANYTYPE_RETRY_DELAY", "0.5"))
        for attempt in range(max_retries):
            response = self.session.request(method, self._url(path), **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response

            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = base_delay * (2**attempt)
            else:
                delay = base_delay * (2**attempt)
            time.sleep(delay)

        response.raise_for_status()
        return response

    def list_spaces(self) -> List[dict]:
        response = self._request("GET", "/v1/spaces")
        return response.json().get("data", [])

    def search_objects(self, space_id: str, query: str, types: List[str]) -> List[dict]:
        payload = {"query": query, "types": types, "limit": 50}
        response = self._request(
            "POST", f"/v1/spaces/{space_id}/search", data=json.dumps(payload)
        )
        return response.json().get("data", [])

    def create_page(self, space_id: str, title: str, markdown: str) -> dict:
        payload = {"name": title, "type_key": TYPE_KEY, "body": markdown}
        response = self._request(
            "POST", f"/v1/spaces/{space_id}/objects", data=json.dumps(payload)
        )
        return response.json()

    def update_page(self, space_id: str, object_id: str, title: str, markdown: str) -> dict:
        payload = {"name": title, "type_key": TYPE_KEY, "markdown": markdown}
        response = self._request(
            "PATCH", f"/v1/spaces/{space_id}/objects/{object_id}", data=json.dumps(payload)
        )
        return response.json()


def find_space_id(spaces: Iterable[dict], space_name: str) -> Optional[str]:
    for space in spaces:
        if space.get("name") == space_name:
            return space.get("id")
    return None


def select_object_match(objects: Iterable[dict], name: str) -> Optional[dict]:
    for obj in objects:
        if obj.get("name") == name:
            return obj
    for obj in objects:
        if obj.get("name", "").lower() == name.lower():
            return obj
    return None


def title_from_markdown(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip() or fallback
    return fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload timetable.md into Anytype as a page."
    )
    parser.add_argument(
        "markdown_file",
        nargs="?",
        default=TIMETABLE_FILE,
        help=f"Markdown file to upload (default: {TIMETABLE_FILE})",
    )
    parser.add_argument(
        "--title",
        help="Anytype page title. Defaults to the first H1 in the markdown file.",
    )
    parser.add_argument(
        "--space",
        default=SPACE_NAME,
        help=f"Anytype space name (default: {SPACE_NAME})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned changes without writing to Anytype.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not API_KEY:
        print("Missing API key. Set ANYTYPE_API_KEY or ANTYPE_KEY.")
        return 1

    markdown_path = Path(args.markdown_file)
    if not markdown_path.is_file():
        print(f"Markdown file not found: {markdown_path}")
        return 1

    markdown = markdown_path.read_text(encoding="utf-8")
    title = args.title or title_from_markdown(markdown, markdown_path.stem.replace("_", " ").title())

    client = AnytypeClient(BASE_URL, API_KEY, API_VERSION)
    space_id = find_space_id(client.list_spaces(), args.space)
    if not space_id:
        print(f"Space '{args.space}' not found.")
        return 1

    results = client.search_objects(space_id, title, [TYPE_KEY])
    match = select_object_match(results, title)

    if args.dry_run:
        action = "update" if match else "create"
        print(
            f"DRY RUN: would {action} page '{title}' in space '{args.space}' "
            f"from {markdown_path} ({len(markdown)} characters)."
        )
        return 0

    if match:
        client.update_page(space_id, match["id"], title, markdown)
        print(f"Updated page: {title}")
    else:
        client.create_page(space_id, title, markdown)
        print(f"Created page: {title}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())