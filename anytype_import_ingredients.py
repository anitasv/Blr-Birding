#!/usr/bin/env python3
"""Import Ingredient objects into Anytype from food_recommendations.md.

Creates/updates Ingredient objects in the "For Good Health" space and sets
"Sindhu Recommendation" to the recommendation value.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests

BASE_URL = os.getenv("ANYTYPE_BASE_URL", "http://localhost:31009")
API_KEY = os.getenv("ANYTYPE_API_KEY") or os.getenv("ANTYPE_KEY")
print(API_KEY)
API_VERSION = os.getenv("ANYTYPE_VERSION", "2025-11-08")

SPACE_NAME = "For Good Health"
TYPE_KEY = "ingredient"
PROPERTY_NAME = "Sindhu Recommendation"
RECOMMENDATIONS_FILE = os.getenv("RECOMMENDATIONS_FILE", "sindhu_food_recommendations.md")

TAG_COLORS = {
    "Enjoy": "teal",
    "Minimize": "yellow",
    "Avoid": "red",
    "Superfood": "lime",
}


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
            resp = self.session.request(method, self._url(path), **kwargs)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = base_delay * (2**attempt)
            else:
                delay = base_delay * (2**attempt)
            time.sleep(delay)
        resp.raise_for_status()
        return resp

    def list_spaces(self) -> List[dict]:
        resp = self._request("GET", "/v1/spaces")
        return resp.json().get("data", [])

    def list_types(self, space_id: str) -> List[dict]:
        resp = self._request("GET", f"/v1/spaces/{space_id}/types")
        return resp.json().get("data", [])

    def list_properties(self, space_id: str) -> List[dict]:
        resp = self._request("GET", f"/v1/spaces/{space_id}/properties")
        return resp.json().get("data", [])

    def list_tags(self, space_id: str, property_id: str) -> List[dict]:
        resp = self._request(
            "GET", f"/v1/spaces/{space_id}/properties/{property_id}/tags"
        )
        return resp.json().get("data", [])

    def create_tag(self, space_id: str, property_id: str, name: str, color: str) -> dict:
        payload = {"name": name, "color": color}
        resp = self._request(
            "POST",
            f"/v1/spaces/{space_id}/properties/{property_id}/tags",
            data=json.dumps(payload),
        )
        return resp.json()

    def search_objects(self, space_id: str, query: str, types: List[str]) -> List[dict]:
        payload = {"query": query, "types": types, "limit": 50}
        resp = self._request(
            "POST", f"/v1/spaces/{space_id}/search", data=json.dumps(payload)
        )
        return resp.json().get("data", [])

    def create_object(
        self,
        space_id: str,
        name: str,
        type_key: str,
        properties: List[dict],
    ) -> dict:
        payload = {"name": name, "type_key": type_key, "properties": properties}
        resp = self._request(
            "POST", f"/v1/spaces/{space_id}/objects", data=json.dumps(payload)
        )
        return resp.json()

    def update_object(self, space_id: str, object_id: str, properties: List[dict]) -> dict:
        payload = {"properties": properties}
        resp = self._request(
            "PATCH", f"/v1/spaces/{space_id}/objects/{object_id}", data=json.dumps(payload)
        )
        return resp.json()



def load_recommendations(path: str) -> List[Tuple[str, str]]:
    table_rows: List[Tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[0].lower() == "food":
                continue
            if re.match(r"^:?-+:?$", cells[0]) and re.match(r"^:?-+:?$", cells[1]):
                continue
            table_rows.append((cells[0], cells[1]))
    return table_rows


def find_space_id(spaces: Iterable[dict], space_name: str) -> Optional[str]:
    for space in spaces:
        if space.get("name") == space_name:
            return space.get("id")
    return None


def resolve_type_and_property(
    types: Iterable[dict],
    type_key: str,
    property_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    for type_info in types:
        if type_info.get("key") != type_key:
            continue
        for prop in type_info.get("properties", []):
            if prop.get("name") == property_name:
                return prop.get("key"), prop.get("id")
    return None, None


def ensure_tags(
    client: AnytypeClient,
    space_id: str,
    property_id: str,
    recommendations: Iterable[str],
) -> Dict[str, str]:
    tags = {tag.get("name"): tag.get("id") for tag in client.list_tags(space_id, property_id)}
    for rec in recommendations:
        if rec in tags:
            continue
        color = TAG_COLORS.get(rec, "grey")
        created = client.create_tag(space_id, property_id, rec, color)
        tag_data = created.get("data") if isinstance(created, dict) else None
        if isinstance(tag_data, dict):
            tags[tag_data.get("name")] = tag_data.get("id")
        else:
            tags[rec] = created.get("id") if isinstance(created, dict) else None
    return tags


def select_object_match(objects: Iterable[dict], name: str) -> Optional[dict]:
    for obj in objects:
        if obj.get("name") == name:
            return obj
    for obj in objects:
        if obj.get("name", "").lower() == name.lower():
            return obj
    return None


def main() -> int:
    if not API_KEY:
        print("Missing API key. Set ANYTYPE_API_KEY or ANTYPE_KEY.")
        return 1

    client = AnytypeClient(BASE_URL, API_KEY, API_VERSION)

    spaces = client.list_spaces()
    space_id = find_space_id(spaces, SPACE_NAME)
    if not space_id:
        print(f"Space '{SPACE_NAME}' not found.")
        return 1

    types = client.list_types(space_id)
    property_key, property_id = resolve_type_and_property(types, TYPE_KEY, PROPERTY_NAME)
    if not property_key or not property_id:
        print(f"Property '{PROPERTY_NAME}' not found on type '{TYPE_KEY}'.")
        return 1

    recommendations = load_recommendations(RECOMMENDATIONS_FILE)
    unique_recs = sorted({rec for _, rec in recommendations})
    tag_map = ensure_tags(client, space_id, property_id, unique_recs)

    # tag_priority = { 'Superfood': '4-Superfood',
    #                 'Enjoy': '3-Enjoy',
    #                 'Minimize': '2-Minimize',
    #                 'Avoid': '1-Avoid'}

    for food, recommendation in recommendations:
        tag_id = tag_map.get(recommendation)
        if not tag_id:
            print(f"Skipping {food}: no tag id for {recommendation}.")
            continue

        props_payload = [{"key": property_key, "select": tag_id}]
        results = client.search_objects(space_id, food, [TYPE_KEY])
        match = select_object_match(results, food)

        if match:
            client.update_object(space_id, match.get("id"), props_payload)
            print(f"Updated {food} -> {recommendation}")
        else:
            client.create_object(space_id, food, TYPE_KEY, props_payload)
            print(f"Created {food} -> {recommendation}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
