#!/usr/bin/env python3
"""Import parsed wildlife/birding destinations into Anytype.

Creates (or reuses) a ``Destination`` type in the ``ASV x SS`` space, then
creates or updates one Destination object for each row parsed by
``parse_destinations.py`` from ``destinations.md``.

Configuration is read from environment variables:

* ``ANYTYPE_API_KEY`` or ``ANTYPE_KEY`` - required Anytype API key
* ``ANYTYPE_BASE_URL`` - defaults to ``http://localhost:31009``
* ``ANYTYPE_VERSION`` - defaults to ``2025-11-08``
* ``DESTINATIONS_FILE`` - defaults to ``destinations.md``

Usage:

    python anytype_import_destinations.py --dry-run
    python anytype_import_destinations.py
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Iterable, List, Optional

import requests

from parse_destinations import parse_markdown_tables


BASE_URL = os.getenv("ANYTYPE_BASE_URL", "http://localhost:31009")
API_KEY = os.getenv("ANYTYPE_API_KEY") or os.getenv("ANTYPE_KEY")
API_VERSION = os.getenv("ANYTYPE_VERSION", "2025-11-08")

SPACE_NAME = "ASV x SS"
TYPE_NAME = "Destination"
TYPE_KEY = "destination"
TYPE_PLURAL_NAME = "Destinations"
DESTINATIONS_FILE = os.getenv("DESTINATIONS_FILE", "destinations.md")

DESTINATION_PROPERTIES = [
    {"key": "state", "name": "State", "format": "text"},
    {"key": "best_time", "name": "Best Time", "format": "text"},
    {"key": "ease_get", "name": "Ease Get", "format": "text"},
    {"key": "ease_stay", "name": "Ease Stay", "format": "text"},
    {"key": "transit", "name": "Transit", "format": "text"},
    {"key": "expect", "name": "Expect", "format": "text"},
    {"key": "birding", "name": "Birding", "format": "text"},
    {"key": "wildlife", "name": "Wildlife", "format": "text"},
    {"key": "source_section", "name": "Source Section", "format": "text"},
]


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

    def list_types(self, space_id: str) -> List[dict]:
        response = self._request("GET", f"/v1/spaces/{space_id}/types?limit=1000")
        return response.json().get("data", [])

    def create_type(self, space_id: str) -> dict:
        payload = {
            "key": TYPE_KEY,
            "name": TYPE_NAME,
            "plural_name": TYPE_PLURAL_NAME,
            "layout": "basic",
            "icon": {"format": "emoji", "emoji": "🗺️"},
            "properties": DESTINATION_PROPERTIES,
        }
        response = self._request(
            "POST", f"/v1/spaces/{space_id}/types", data=json.dumps(payload)
        )
        return response.json()

    def search_objects(self, space_id: str, query: str, types: List[str]) -> List[dict]:
        payload = {"query": query, "types": types, "limit": 50}
        response = self._request(
            "POST", f"/v1/spaces/{space_id}/search", data=json.dumps(payload)
        )
        return response.json().get("data", [])

    def create_object(
        self, space_id: str, name: str, properties: List[dict], body: str
    ) -> dict:
        payload = {
            "name": name,
            "type_key": TYPE_KEY,
            "properties": properties,
            "body": body,
        }
        response = self._request(
            "POST", f"/v1/spaces/{space_id}/objects", data=json.dumps(payload)
        )
        return response.json()

    def update_object(
        self, space_id: str, object_id: str, properties: List[dict], body: str
    ) -> dict:
        payload = {"properties": properties, "markdown": body, "type_key": TYPE_KEY}
        response = self._request(
            "PATCH", f"/v1/spaces/{space_id}/objects/{object_id}", data=json.dumps(payload)
        )
        return response.json()


def find_space_id(spaces: Iterable[dict], space_name: str) -> Optional[str]:
    for space in spaces:
        if space.get("name") == space_name:
            return space.get("id")
    return None


def find_destination_type(types: Iterable[dict]) -> Optional[dict]:
    for type_info in types:
        if type_info.get("key") == TYPE_KEY or type_info.get("name") == TYPE_NAME:
            return type_info
    return None


def ensure_destination_type(
    client: AnytypeClient, space_id: str, dry_run: bool = False
) -> dict:
    existing = find_destination_type(client.list_types(space_id))
    if existing:
        print(f"Using existing type: {existing.get('name')} ({existing.get('key')})")
        return existing

    if dry_run:
        print(f"DRY RUN: would create type '{TYPE_NAME}' in space '{SPACE_NAME}'.")
        return {"name": TYPE_NAME, "key": TYPE_KEY, "dry_run": True}

    created = client.create_type(space_id)
    type_data = created.get("type") or created.get("data") or created
    print(f"Created type: {TYPE_NAME} ({TYPE_KEY})")
    return type_data


def destination_properties(destination: dict) -> List[dict]:
    field_map = {
        "state": "state",
        "best_time": "best_time",
        "ease_get": "ease_get",
        "ease_stay": "ease_stay",
        "transit": "transit",
        "expect": "expect",
        "birding": "birding",
        "wildlife": "wildlife",
        "source_section": "section",
    }
    return [
        {"key": property_key, "text": str(destination.get(source_key, ""))}
        for property_key, source_key in field_map.items()
        if destination.get(source_key)
    ]


def destination_body(destination: dict) -> str:
    rows = [
        ("State", destination.get("state")),
        ("Best time", destination.get("best_time")),
        ("Ease to get", destination.get("ease_get")),
        ("Ease to stay", destination.get("ease_stay")),
        ("Transit", destination.get("transit")),
        ("Expect", destination.get("expect")),
        ("Birding", destination.get("birding")),
        ("Wildlife", destination.get("wildlife")),
        ("Source section", destination.get("section")),
    ]
    return "\n".join(
        f"- **{label}:** {value}" for label, value in rows if value
    )


def select_object_match(objects: Iterable[dict], name: str) -> Optional[dict]:
    for obj in objects:
        if obj.get("name") == name:
            return obj
    for obj in objects:
        if obj.get("name", "").lower() == name.lower():
            return obj
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload parse_destinations.py output into Anytype."
    )
    parser.add_argument(
        "destinations_file",
        nargs="?",
        default=DESTINATIONS_FILE,
        help=f"Markdown file to parse (default: {DESTINATIONS_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report planned changes without writing to Anytype.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not API_KEY:
        print("Missing API key. Set ANYTYPE_API_KEY or ANTYPE_KEY.")
        return 1

    destinations = parse_markdown_tables(args.destinations_file)
    print(f"Parsed {len(destinations)} destinations from {args.destinations_file}.")

    client = AnytypeClient(BASE_URL, API_KEY, API_VERSION)
    space_id = find_space_id(client.list_spaces(), SPACE_NAME)
    if not space_id:
        print(f"Space '{SPACE_NAME}' not found.")
        return 1

    ensure_destination_type(client, space_id, dry_run=args.dry_run)

    for destination in destinations:
        name = destination["name"]
        properties = destination_properties(destination)
        body = destination_body(destination)

        if args.dry_run:
            print(f"DRY RUN: would upsert Destination '{name}' ({len(properties)} properties).")
            continue

        results = client.search_objects(space_id, name, [TYPE_KEY])
        match = select_object_match(results, name)
        if match:
            client.update_object(space_id, match["id"], properties, body)
            print(f"Updated Destination: {name}")
        else:
            client.create_object(space_id, name, properties, body)
            print(f"Created Destination: {name}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())