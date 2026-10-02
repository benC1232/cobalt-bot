"""Minimal client for a self-hosted cobalt api (see docs/api.md)."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

API_URL = os.environ.get("COBALT_API_URL", "http://localhost:9000/")
REQUEST_OPTIONS = {
    # always download through cobalt's tunnel instead of being redirected to the
    # service's CDN: some services return broken redirect urls (e.g. streamable)
    "alwaysProxy": True,
    **json.loads(os.environ.get("COBALT_OPTIONS") or "{}"),
}
CHUNK_SIZE = 64 * 1024


class CobaltError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TooLargeError(Exception):
    pass


@dataclass
class MediaItem:
    url: str
    filename: str


async def resolve(session: aiohttp.ClientSession, url: str) -> list[MediaItem]:
    """Asks cobalt to process a url and returns the files to download."""
    async with session.post(
        API_URL,
        json={**REQUEST_OPTIONS, "url": url},
        headers={"Accept": "application/json"},
    ) as res:
        data = await res.json(content_type=None)

    status = data.get("status")
    if status in ("tunnel", "redirect"):
        return [MediaItem(data["url"], data["filename"])]

    if status == "picker":
        items = [
            MediaItem(item["url"], _filename_from_url(item["url"], f"{item['type']}_{i}"))
            for i, item in enumerate(data["picker"], start=1)
        ]
        if data.get("audio"):
            items.append(MediaItem(data["audio"], data["audioFilename"]))
        return items

    if status == "error":
        raise CobaltError(data["error"]["code"])
    raise CobaltError(f"unexpected status: {status}")


async def download(session: aiohttp.ClientSession, item: MediaItem, directory: Path, max_bytes: int) -> Path:
    """Streams a file into directory, giving up once it grows past max_bytes."""
    path = directory / _sanitize(item.filename)
    received = 0

    try:
        async with session.get(item.url) as res:
            if res.status != 200:
                raise CobaltError(f"download failed: HTTP {res.status}")
            if (res.content_length or 0) > max_bytes:
                raise TooLargeError()

            with path.open("wb") as f:
                async for chunk in res.content.iter_chunked(CHUNK_SIZE):
                    received += len(chunk)
                    if received > max_bytes:
                        raise TooLargeError()
                    f.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    # cobalt tunnels end with an empty body when the upstream fetch fails
    if received == 0:
        path.unlink(missing_ok=True)
        raise CobaltError("download failed: empty file")
    return path


def _filename_from_url(url: str, fallback: str) -> str:
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    return name if re.search(r"\.[a-z0-9]{2,5}$", name, re.I) else fallback


def _sanitize(name: str) -> str:
    return re.sub(r'[/\\?%*:|"<>\x00-\x1f]', "_", name or "file")[:200]
