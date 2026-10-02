"""Decides locally whether cobalt supports a url, so unsupported links never hit the api.

Python port of cobalt's own matching logic:
  - api/src/processing/service-config.js  (SERVICES)
  - api/src/processing/url.js             (alias_url, clean_url, get_host, extract)
When merging upstream cobalt, check those files for new services or patterns
and run `python -m unittest` from bot/ (tests/ replays cobalt's own test urls through this module).
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

SERVICES = {
    "bilibili": {
        "patterns": [
            "video/:comId",
            "video/:comId?p=:partId",
            "_shortLink/:comShortLink",
            "_tv/:lang/video/:tvId",
            "_tv/video/:tvId",
        ],
        "subdomains": ["m"],
    },
    "bsky": {
        "patterns": ["profile/:user/post/:post"],
        "tld": "app",
    },
    "dailymotion": {
        "patterns": ["video/:id"],
    },
    "facebook": {
        "patterns": [
            "_shortLink/:shortLink",
            ":username/videos/:caption/:id",
            ":username/videos/:id",
            "reel/:id",
            "share/:shareType/:id",
        ],
        "subdomains": ["web", "m"],
        "altDomains": ["fb.watch"],
    },
    "instagram": {
        "patterns": [
            "p/:postId",
            "tv/:postId",
            "reel/:postId",
            "reels/:postId",
            "stories/:username/:storyId",
            "share/:shareId",
            "share/p/:shareId",
            "share/reel/:shareId",
            ":username/p/:postId",
            ":username/reel/:postId",
        ],
        "altDomains": ["ddinstagram.com"],
    },
    "loom": {
        "patterns": ["share/:id", "embed/:id"],
    },
    "ok": {
        "patterns": ["video/:id", "videoembed/:id"],
        "tld": "ru",
    },
    "pinterest": {
        "patterns": ["pin/:id", "pin/:id/:garbage", "url_shortener/:shortLink"],
    },
    "newgrounds": {
        "patterns": ["portal/view/:id", "audio/listen/:audioId"],
    },
    "reddit": {
        "patterns": [
            "comments/:id",
            "r/:sub/comments/:id",
            "r/:sub/comments/:id/:title",
            "r/:sub/comments/:id/comment/:commentId",
            "user/:user/comments/:id",
            "user/:user/comments/:id/:title",
            "user/:user/comments/:id/comment/:commentId",
            "r/u_:user/comments/:id",
            "r/u_:user/comments/:id/:title",
            "r/u_:user/comments/:id/comment/:commentId",
            "r/:sub/s/:shareId",
            "video/:shortId",
        ],
        "subdomains": "*",
    },
    "rutube": {
        "patterns": [
            "video/:id",
            "play/embed/:id",
            "shorts/:id",
            "yappy/:yappyId",
            "video/private/:id?p=:key",
            "video/private/:id",
        ],
        "tld": "ru",
    },
    "snapchat": {
        "patterns": [
            ":shortLink",
            "spotlight/:spotlightId",
            "add/:username/:storyId",
            "u/:username/:storyId",
            "add/:username",
            "u/:username",
            "t/:shortLink",
            "o/:spotlightId",
        ],
        "subdomains": ["t", "story"],
    },
    "soundcloud": {
        "patterns": [":author/:song/s-:accessKey", ":author/:song", ":shortLink"],
        "subdomains": ["on", "m"],
    },
    "streamable": {
        "patterns": [":id", "o/:id", "e/:id", "s/:id"],
    },
    "tiktok": {
        "patterns": [
            ":user/video/:postId",
            "i18n/share/video/:postId",
            ":shortLink",
            "t/:shortLink",
            ":user/photo/:postId",
            "v/:postId.html",
        ],
        "subdomains": ["vt", "vm", "m", "t", "pro"],
    },
    "tumblr": {
        "patterns": ["post/:id", "blog/view/:user/:id", ":user/:id", ":user/:id/:trackingId"],
        "subdomains": "*",
    },
    "twitch": {
        "patterns": [":channel/clip/:clip"],
        "tld": "tv",
        "subdomains": ["clips", "www", "m"],
    },
    "twitter": {
        "patterns": [
            ":user/status/:id",
            ":user/status/:id/video/:index",
            ":user/status/:id/photo/:index",
            ":user/status/:id/mediaviewer",
            ":user/status/:id/mediaViewer",
            "i/bookmarks?post_id=:id",
        ],
        "subdomains": ["mobile"],
        "altDomains": ["x.com", "vxtwitter.com", "fixvx.com"],
    },
    "vimeo": {
        "patterns": [
            ":id",
            "video/:id",
            ":id/:password",
            "/channels/:user/:id",
            "groups/:groupId/videos/:id",
        ],
        "subdomains": ["player"],
    },
    "vk": {
        "patterns": [
            "video:ownerId_:videoId",
            "clip:ownerId_:videoId",
            "video:ownerId_:videoId_:accessKey",
            "clip:ownerId_:videoId_:accessKey",
            "clips:duplicateId",
            "videos:duplicateId",
            "search/video",
        ],
        "subdomains": ["m"],
        "altDomains": ["vkvideo.ru", "vk.ru"],
    },
    "youtube": {
        "patterns": ["watch?v=:id", "embed/:id", "watch/:id", "v/:id"],
        "subdomains": ["music", "m"],
    },
}

# url-pattern's default segment charset, plus the '@.:' cobalt adds
_SEGMENT = r"([a-zA-Z0-9\-_~ %@.:]+)"


def _compile(pattern: str) -> re.Pattern:
    """Translates a url-pattern (npm) pattern into an anchored regex."""
    regex = re.sub(
        r":[a-zA-Z0-9]+|[^:]+",
        lambda m: _SEGMENT if m[0].startswith(":") else re.escape(m[0]),
        pattern,
    )
    return re.compile(f"^{regex}$")


_PATTERNS = {name: [_compile(p) for p in s["patterns"]] for name, s in SERVICES.items()}


@dataclass
class _Url:
    hostname: str
    path: str
    query: list[tuple[str, str]]

    @classmethod
    def parse(cls, url: str) -> "_Url":
        parts = urlsplit(url)
        # percent-encode the path the way js' URL does (non-ascii, spaces, quotes, ...)
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~[]^|\\")
        return cls(parts.hostname or "", path, parse_qsl(parts.query, keep_blank_values=True))

    def param(self, key: str) -> str | None:
        return next((v for k, v in self.query if k == key), None)

    @property
    def search(self) -> str:
        return f"?{urlencode(self.query, quote_via=quote)}" if self.query else ""


@dataclass
class _Host:
    subdomain: str | None
    sld: str
    tld: str

    @property
    def domain(self) -> str:
        return f"{self.sld}.{self.tld}"


def _parse_host(hostname: str) -> _Host | None:
    # stand-in for the psl package: every tld cobalt cares about is a single label
    labels = hostname.split(".")
    if len(labels) < 2 or not all(labels):
        return None
    return _Host(".".join(labels[:-2]) or None, labels[-2], labels[-1])


def _encode(value: str) -> str:
    # same as js encodeURIComponent
    return quote(value, safe="-_.!~*'()")


def _alias_url(url: _Url) -> _Url:
    host = _parse_host(url.hostname)
    if not host:
        return url
    parts = url.path.split("/")
    sld = host.sld

    if sld == "youtube":
        if url.path.startswith("/live/") or url.path.startswith("/shorts/"):
            url.path = "/watch"
            url.query = [("v", parts[2])]
    elif sld == "youtu":
        if url.hostname == "youtu.be" and len(parts) >= 2:
            url = _Url.parse(f"https://youtube.com/watch?v={_encode(parts[1])}")
    elif sld == "pin":
        if url.hostname == "pin.it" and len(parts) == 2:
            url = _Url.parse(f"https://pinterest.com/url_shortener/{_encode(parts[1])}")
    elif sld in ("vxtwitter", "fixvx", "x"):
        if url.hostname in SERVICES["twitter"]["altDomains"]:
            url.hostname = "twitter.com"
    elif sld == "twitch":
        if url.hostname == "clips.twitch.tv" and len(parts) >= 2:
            url = _Url.parse(f"https://twitch.tv/_/clip/{parts[1]}")
    elif sld == "bilibili":
        if host.tld == "tv":
            url = _Url.parse(f"https://bilibili.com/_tv{url.path}")
    elif sld == "b23":
        if url.hostname == "b23.tv" and len(parts) == 2:
            url = _Url.parse(f"https://bilibili.com/_shortLink/{parts[1]}")
    elif sld == "dai":
        if url.hostname == "dai.ly" and len(parts) == 2:
            url = _Url.parse(f"https://dailymotion.com/video/{parts[1]}")
    elif sld in ("facebook", "fb"):
        if url.param("v"):
            url = _Url.parse(f"https://web.facebook.com/user/videos/{url.param('v')}")
        if url.hostname == "fb.watch":
            url = _Url.parse(f"https://web.facebook.com/_shortLink/{parts[1]}")
    elif sld == "ddinstagram":
        if host.domain in SERVICES["instagram"]["altDomains"] and host.subdomain in (None, "d", "g"):
            url.hostname = "instagram.com"
    elif sld in ("vk", "vkvideo"):
        if url.hostname in SERVICES["vk"]["altDomains"]:
            url.hostname = "vk.com"
        if url.param("z"):
            url = _Url.parse(f"https://vk.com/{url.param('z')}")
    elif sld == "loom":
        id_part = parts[-1]
        if len(id_part) > 32:
            url.path = f"/share/{id_part[-32:]}"
    elif sld == "redd":
        if url.hostname == "v.redd.it" and len(parts) == 2:
            url = _Url.parse(f"https://www.reddit.com/video/{parts[1]}")

    return url


def _clean_url(url: _Url) -> _Url:
    host = _parse_host(url.hostname)
    sld = host.sld if host else None
    kept = None

    if sld == "pinterest":
        url.hostname = "pinterest.com"
    elif sld == "vk":
        if "/clip" in url.path and url.param("z"):
            kept = "z"
    elif sld == "youtube":
        if url.param("v"):
            kept = "v"
    elif sld in ("bilibili", "rutube"):
        if url.param("p"):
            kept = "p"
    elif sld == "twitter":
        if url.param("post_id"):
            kept = "post_id"

    url.query = [(kept, url.param(kept))] if kept else []
    if url.path.endswith("/"):
        url.path = url.path[:-1]
    return url


def _get_service(url: _Url) -> str | None:
    host = _parse_host(url.hostname)
    if not host:
        return None
    service = SERVICES.get(host.sld)
    if not service:
        return None
    if service.get("tld", "com") != host.tld:
        return None

    subdomains = service.get("subdomains", [])
    if subdomains != "*" and host.subdomain not in (None, "www", *subdomains):
        return None
    return host.sld


def match_service(url: str) -> str | None:
    """Returns the cobalt service name for a supported url, or None."""
    try:
        parsed = _clean_url(_alias_url(_Url.parse(url)))
    except ValueError:
        return None

    service = _get_service(parsed)
    if not service:
        return None

    target = parsed.path[1:] + parsed.search
    if any(p.match(target) for p in _PATTERNS[service]):
        return service
    return None
