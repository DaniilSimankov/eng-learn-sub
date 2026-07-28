#!/usr/bin/env python3
"""Локальный сервер SubLearn: статика + API для разбора страниц с плеером."""

from typing import Optional, Tuple
import html
import ipaddress
import json
import os
import re
import socket
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SUBLEARN_DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "vocab.db"
_db_lock = threading.RLock()
_dns_lock = threading.Lock()
_translate_cache_lock = threading.Lock()
_ollama_lock = threading.Lock()
_dns_cache: dict[str, tuple[float, list[str]]] = {}
_DNS_TTL_SEC = 600
_SSL_CONTEXT = ssl.create_default_context()
_ad_skip_script: Optional[str] = None
_TRANSLATE_CACHE_MAX = 512
_translate_cache: OrderedDict[str, str] = OrderedDict()
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

IFRAME_TAG_RE = re.compile(r"<iframe\b[^>]*>", re.IGNORECASE)
IFRAME_SRC_ATTR_RE = re.compile(
    r"""(?:src|data-src)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
YLITRON_ID_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?ylitron\.pro/(sie|tvb)/(\d+)',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
STREAM_RE = re.compile(
    r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)(?:[^\s"\'<>]*)?',
    re.IGNORECASE,
)
VTT_RE = re.compile(
    r'https?://[^\s"\'<>]+\.vtt(?:[^\s"\'<>]*)?',
    re.IGNORECASE,
)
VTT_EN_RE = re.compile(r"(?:^|[/_\-.])(en|eng|english)(?:[._\-.]|$)", re.IGNORECASE)
EMBED_HOSTS = (
    "cdnlbox.club",
    "ylitron.pro",
    "ortified.ws",
    "vak345.com",
    "interkh.com",
    "zombie-film.com",
)
ALLOWED_PAGE_SUFFIXES = (".newdeaf.co",)
MEDIA_CDN_SUFFIXES = (
    ".cloudfront.net",
    ".akamaized.net",
    ".amazonaws.com",
    ".b-cdn.net",
    ".fastly.net",
    ".edgecastcdn.net",
    ".kxcdn.com",
    ".jwpcdn.com",
    ".llnwi.net",
    ".bytefcdn.com",
)
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.goog",
    }
)
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "frame-src 'self' https: http:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    ),
)
IFRAME_SRC_RE = re.compile(r'(<iframe[^>]+src=)(["\'])([^"\']+)\2', re.IGNORECASE)
HEAD_RE = re.compile(r"(<head[^>]*>)", re.IGNORECASE)


class SecurityError(ValueError):
    pass


def _normalize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def _host_matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix[1:] or host.endswith(suffix) for suffix in suffixes)


def _host_matches_embed(host: str) -> bool:
    return any(token in host for token in EMBED_HOSTS)


def _resolve_public_ips(host: str) -> list[str]:
    now = time.monotonic()
    with _dns_lock:
        cached = _dns_cache.get(host)
        if cached and now - cached[0] < _DNS_TTL_SEC:
            return list(cached[1])

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SecurityError(f"Не удалось разрешить хост: {host}") from exc
    ips = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise SecurityError(f"Хост не найден: {host}")

    with _dns_lock:
        _dns_cache[host] = (now, ips)
        if len(_dns_cache) > 256:
            oldest = next(iter(_dns_cache))
            _dns_cache.pop(oldest, None)
    return list(ips)


def _assert_public_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError("Разрешены только http и https")
    if parsed.username or parsed.password:
        raise SecurityError("URL с логином/паролем запрещены")

    host = _normalize_host(parsed.hostname or "")
    if not host:
        raise SecurityError("Пустой хост в URL")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise SecurityError("Запрещённый хост")

    if host == "127.0.0.1" or host.startswith("127."):
        raise SecurityError("Локальные адреса запрещены")

    try:
        literal = ipaddress.ip_address(host)
        if literal.is_private or literal.is_loopback or literal.is_link_local or literal.is_reserved:
            raise SecurityError("Локальные и служебные IP запрещены")
        return
    except ValueError:
        pass

    for ip_str in _resolve_public_ips(host):
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SecurityError("Целевой IP недоступен (внутренняя сеть)")


def validate_page_url(url: str) -> str:
    url = url.strip()
    _assert_public_target(url)
    host = _normalize_host(urlparse(url).hostname or "")
    if _host_matches_embed(host) or _host_matches_suffix(host, ALLOWED_PAGE_SUFFIXES):
        return url
    raise SecurityError(
        "Разрешены только страницы с плеером Ylitron или embed из белого списка"
    )


def validate_embed_url(url: str) -> str:
    url = url.strip()
    _assert_public_target(url)
    host = _normalize_host(urlparse(url).hostname or "")
    if not _host_matches_embed(host):
        raise SecurityError("Embed-URL не из доверенного списка плееров")
    return url


def validate_media_url(url: str) -> str:
    url = url.strip()
    _assert_public_target(url)
    host = _normalize_host(urlparse(url).hostname or "")
    if _host_matches_embed(host) or _host_matches_suffix(host, MEDIA_CDN_SUFFIXES):
        return url
    raise SecurityError("URL медиа не из доверенного списка CDN")


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def fetch_binary(url: str, timeout: int = 30) -> Tuple[bytes, str]:
    validate_media_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type") or "application/octet-stream"
        return data, ctype


def embed_is_available(url: str) -> bool:
    try:
        validate_embed_url(url)
    except SecurityError:
        return False
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4, context=_SSL_CONTEXT) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 501):
            return True
        return exc.code < 400
    except urllib.error.URLError:
        return False


def clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(text).strip()


def extract_title(page: str) -> str:
    match = TITLE_RE.search(page)
    if match:
        return clean_text(match.group(1))
    match = OG_TITLE_RE.search(page)
    if match:
        return html.unescape(match.group(1)).strip()
    return "Без названия"


def extract_players(page: str) -> list[str]:
    """Достаёт src/data-src у iframe; оставляет только embed из белого списка."""
    seen = set()
    ordered = []
    for tag in IFRAME_TAG_RE.findall(page):
        match = IFRAME_SRC_ATTR_RE.search(tag)
        if not match:
            continue
        url = html.unescape(match.group(1).strip())
        if not url or url in seen:
            continue
        host = _normalize_host(urlparse(url).hostname or "")
        if not host or not _host_matches_embed(host):
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def parse_ylitron_ref(url: str) -> Optional[dict]:
    """Достаёт id сериала ylitron из embed-ссылки (/sie/463 или /tvb/1178445)."""
    match = YLITRON_ID_RE.search(html.unescape(url or ""))
    if not match:
        return None
    kind, ylitron_id = match.group(1).lower(), match.group(2)
    return {
        "ylitronId": ylitron_id,
        "ylitronKind": kind,
        "ylitronPath": f"/{kind}/{ylitron_id}",
    }


def find_ylitron_player(iframe_urls: list[str]) -> Optional[tuple[str, dict]]:
    for url in iframe_urls:
        ref = parse_ylitron_ref(url)
        if ref:
            return url, ref
    return None


def find_stream_in_html(content: str) -> Optional[str]:
    matches = STREAM_RE.findall(content)
    master = [u for u in matches if "master.m3u8" in u.lower()]
    if master:
        return master[0]
    for url in matches:
        if ".m3u8" in url.lower():
            return url
    return matches[0] if matches else None


def find_vtt_urls(content: str) -> list[str]:
    seen = set()
    ordered = []
    for url in VTT_RE.findall(content):
        url = html.unescape(url.strip())
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def score_vtt_url(url: str) -> int:
    lower = url.lower()
    score = 0
    if VTT_EN_RE.search(lower):
        score += 100
    if any(tag in lower for tag in ("forced", "sdh", "cc")):
        score -= 15
    if any(tag in lower for tag in ("/ru", "rus", "russian", ".ru.")):
        score -= 40
    score += min(len(url), 240) // 12
    return score


def pick_subtitle_url(vtt_urls: list[str]) -> Optional[str]:
    if not vtt_urls:
        return None
    valid = []
    for url in vtt_urls:
        try:
            validate_media_url(url)
            valid.append(url)
        except SecurityError:
            continue
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return max(valid, key=score_vtt_url)


def parse_season_episode(url: str) -> Tuple[int, int]:
    params = parse_qs(urlparse(url).query)
    try:
        season = int((params.get("season") or ["1"])[0])
    except ValueError:
        season = 1
    try:
        episode = int((params.get("episode") or ["1"])[0])
    except ValueError:
        episode = 1
    return season, episode


def extract_seasons_data(html: str) -> list:
    marker = "seasons:"
    idx = html.find(marker)
    if idx < 0:
        return []
    start = html.find("[", idx)
    if start < 0:
        return []
    depth = 0
    for i in range(start, min(len(html), start + 800000)):
        ch = html[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except json.JSONDecodeError:
                    return []
    return []


def find_episode_data(html: str, season: int, episode: int) -> Optional[dict]:
    for season_obj in extract_seasons_data(html):
        if season_obj.get("season") != season:
            continue
        for ep in season_obj.get("episodes") or []:
            if str(ep.get("episode")) == str(episode):
                return ep
    return None


def pick_cc_track(cc_list: list) -> Optional[str]:
    if not cc_list:
        return None

    def score(item: dict) -> int:
        name = (item.get("name") or "").lower()
        pts = 0
        if "eng" in name and "full" in name:
            pts += 100
        elif "eng" in name and "sdh" in name:
            pts += 85
        elif "eng" in name:
            pts += 70
        if "форс" in name or "forced" in name:
            pts -= 25
        if "рус" in name or "rus" in name:
            pts -= 40
        return pts

    ranked = sorted(((score(item), item) for item in cc_list), key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    if best_score < 60:
        return None

    for pts, item in ranked:
        if pts < 60:
            break
        url = item.get("url")
        if not url:
            continue
        try:
            validate_media_url(url)
            return url
        except SecurityError:
            continue
    return None


def extract_json_object(html: str, start: int) -> Optional[dict]:
    if start < 0 or start >= len(html) or html[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    quote = ""
    for i in range(start, min(len(html), start + 2_000_000)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


YLITRON_CC_LABELS = {
    "en": "Eng.",
    "ru": "Рус.",
    "ua": "Укр.",
}


def parse_ylitron_cc(cc: dict) -> Tuple[Optional[str], list]:
    tracks = []
    for lang, url in (cc or {}).items():
        if not url:
            continue
        tracks.append({"url": url, "name": YLITRON_CC_LABELS.get(lang, lang.upper())})

    subtitle_url = cc.get("en") if cc else None
    if subtitle_url:
        try:
            validate_media_url(subtitle_url)
        except SecurityError:
            subtitle_url = None

    if not subtitle_url:
        for track in tracks:
            if track["name"].startswith("Eng"):
                try:
                    validate_media_url(track["url"])
                    subtitle_url = track["url"]
                    break
                except SecurityError:
                    continue
    return subtitle_url, tracks


def parse_ylitron_assets(embed_html: str) -> Optional[dict]:
    idx = embed_html.find("window.playerData")
    if idx < 0:
        return None
    start = embed_html.find("{", idx)
    data = extract_json_object(embed_html, start)
    if not data:
        return None

    config = data.get("config") or {}
    stream = config.get("video")
    if not stream:
        return None
    try:
        validate_media_url(stream)
    except SecurityError:
        return None

    subtitle_url, subtitle_tracks = parse_ylitron_cc(config.get("cc") or {})
    valid_tracks = []
    for track in subtitle_tracks:
        try:
            validate_media_url(track["url"])
            valid_tracks.append(track)
        except SecurityError:
            continue

    return {
        "streamUrl": stream,
        "subtitleUrl": subtitle_url,
        "subtitleTracks": valid_tracks,
        "audioTrackNames": [],
    }


def parse_embed_assets(embed_html: str, iframe_url: str = "") -> dict:
    if "ylitron" in (iframe_url or "").lower():
        ylitron = parse_ylitron_assets(embed_html)
        if ylitron:
            return ylitron

    season, episode = parse_season_episode(iframe_url)
    ep_data = find_episode_data(embed_html, season, episode)
    if ep_data:
        cc = ep_data.get("cc") or []
        audio = ep_data.get("audio") or {}
        return {
            "streamUrl": ep_data.get("hls"),
            "subtitleUrl": pick_cc_track(cc),
            "subtitleTracks": [
                {"url": item.get("url"), "name": item.get("name")}
                for item in cc
                if item.get("url")
            ],
            "audioTrackNames": audio.get("names") or [],
        }
    return {
        "streamUrl": find_stream_in_html(embed_html),
        "subtitleUrl": pick_subtitle_url(find_vtt_urls(embed_html)),
        "subtitleTracks": [],
        "audioTrackNames": [],
    }


def build_player_entry(index: int, iframe_url: str) -> dict:
    available = embed_is_available(iframe_url)
    entry = {
        "index": index,
        "iframeUrl": iframe_url,
        "streamUrl": None,
        "subtitleUrl": None,
        "mode": "iframe",
        "available": available,
    }
    if not available:
        return entry
    try:
        validate_embed_url(iframe_url)
        embed_html = fetch_url(iframe_url)
        assets = parse_embed_assets(embed_html, iframe_url)
        entry["streamUrl"] = assets["streamUrl"]
        entry["subtitleUrl"] = assets["subtitleUrl"]
        entry["subtitleTracks"] = assets.get("subtitleTracks") or []
        entry["audioTrackNames"] = assets.get("audioTrackNames") or []
        if assets["streamUrl"]:
            entry["mode"] = "stream"
    except urllib.error.URLError:
        entry["available"] = False
    return entry


def resolve_page(url: str) -> dict:
    url = validate_page_url(url)
    parsed = urlparse(url)

    # Прямая ссылка на embed-плеер
    if any(host in parsed.netloc for host in EMBED_HOSTS):
        entry = build_player_entry(1, url)
        result = {
            "title": parsed.netloc,
            "sourceUrl": url,
            "players": [entry],
        }
        ref = parse_ylitron_ref(url)
        if ref:
            result.update(ref)
        return result

    page_html = fetch_url(url)
    iframe_urls = extract_players(page_html)
    if not iframe_urls:
        raise ValueError(
            "На странице не найден плеер. Вставьте ссылку на страницу "
            "с источником Ylitron или прямую ссылку iframe."
        )

    # Предпочитаем ylitron: id со страницы, дальше ходим только туда
    found = find_ylitron_player(iframe_urls)
    if found:
        ylitron_url, ref = found
        entry = build_player_entry(1, ylitron_url)
        entry["label"] = f"Ylitron {ref['ylitronPath']}"
        return {
            "title": extract_title(page_html),
            "sourceUrl": url,
            "players": [entry],
            **ref,
        }

    players = []
    with ThreadPoolExecutor(max_workers=min(3, len(iframe_urls))) as pool:
        futures = [
            pool.submit(build_player_entry, i, iframe_url)
            for i, iframe_url in enumerate(iframe_urls, start=1)
        ]
        players = [future.result() for future in futures]
    players.sort(key=lambda item: item["index"])

    return {
        "title": extract_title(page_html),
        "sourceUrl": url,
        "players": players,
    }


def load_ad_skip_script() -> str:
    global _ad_skip_script
    if _ad_skip_script is not None:
        return _ad_skip_script
    path = ROOT / "ad-skip.js"
    _ad_skip_script = path.read_text(encoding="utf-8") if path.exists() else ""
    return _ad_skip_script


def is_embed_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in EMBED_HOSTS)


def proxy_base_path() -> str:
    return "/api/embed"


def rewrite_nested_iframes(page: str, skip_ads: bool) -> str:
    def repl(match):
        prefix, quote_char, src = match.group(1), match.group(2), match.group(3)
        if not src.startswith("http") or not is_embed_url(src):
            return match.group(0)
        proxied = f"{proxy_base_path()}?url={quote(src, safe='')}"
        if skip_ads:
            proxied += "&skipAds=1"
        return f"{prefix}{quote_char}{proxied}{quote_char}"

    return IFRAME_SRC_RE.sub(repl, page)


def build_embed_proxy(url: str, skip_ads: bool) -> str:
    url = validate_embed_url(url)
    page = fetch_url(url)
    parsed = urlparse(url)
    base_href = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    if not base_href.endswith("/"):
        base_href = base_href.rsplit("/", 1)[0] + "/"

    inject = f'<base href="{html.escape(base_href)}">'
    if skip_ads:
        script = load_ad_skip_script()
        if script:
            inject += f"<script>{script}</script>"

    if HEAD_RE.search(page):
        page = HEAD_RE.sub(r"\1" + inject, page, count=1)
    else:
        page = inject + page

    if skip_ads:
        page = rewrite_nested_iframes(page, skip_ads=True)

    return page


def rewrite_m3u8(content: str, base_url: str) -> str:
    base_dir = base_url.rsplit("/", 1)[0] + "/"
    out = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if stripped.startswith("#"):
            if 'URI="' in stripped:
                def repl_uri(m):
                    raw = m.group(1)
                    abs_url = raw if raw.startswith("http") else urljoin(base_dir, raw)
                    return f'URI="/api/stream?url={quote(abs_url, safe="")}"'

                stripped = re.sub(r'URI="([^"]+)"', repl_uri, stripped)
            out.append(stripped)
            continue
        abs_url = stripped if stripped.startswith("http") else urljoin(base_dir, stripped)
        out.append(f"/api/stream?url={quote(abs_url, safe='')}")
    return "\n".join(out) + "\n"


def proxy_stream(url: str) -> Tuple[bytes, str]:
    url = validate_media_url(url)
    data, ctype = fetch_binary(url)
    if b"#EXTM3U" in data[:32] or url.lower().split("?")[0].endswith(".m3u8"):
        text = data.decode("utf-8", errors="replace")
        return rewrite_m3u8(text, url).encode("utf-8"), "application/vnd.apple.mpegurl"
    return data, ctype


OLLAMA_URL = os.environ.get("SUBLEARN_OLLAMA_URL", "http://ollama:11434").rstrip("/")
# Одна универсальная модель; «два агента» = разные промпты/num_ctx (слова vs фразы).
# Для qwen3 обязательно think:false в _chat_translate.
OLLAMA_MODEL = os.environ.get("SUBLEARN_OLLAMA_MODEL", "qwen3:4b")
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "3m")
try:
    OLLAMA_NUM_THREAD = max(1, int(os.environ.get("SUBLEARN_OLLAMA_NUM_THREAD", "2")))
except ValueError:
    OLLAMA_NUM_THREAD = 2
# google = быстрый путь; ai/ollama = локальная модель по кнопке «ИИ».
TRANSLATE_DEFAULT_ENGINE = os.environ.get("SUBLEARN_TRANSLATE_ENGINE", "google").strip().lower()
GOOGLE_TRANSLATE_ENABLED = os.environ.get("SUBLEARN_GOOGLE_TRANSLATE", "1").strip() not in (
    "0",
    "false",
    "no",
    "off",
)


def init_vocab_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vocabulary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT NOT NULL,
                    translation TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    saved_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vocab_word_ctx "
                "ON vocabulary(word COLLATE NOCASE, context)"
            )
            conn.commit()
        finally:
            conn.close()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_item(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "word": row["word"],
        "translation": row["translation"],
        "context": row["context"] or "",
        "savedAt": row["saved_at"],
    }


def vocab_list() -> list:
    with _db_lock:
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT id, word, translation, context, saved_at "
                "FROM vocabulary ORDER BY saved_at DESC, id DESC"
            ).fetchall()
            return [_row_to_item(r) for r in rows]
        finally:
            conn.close()


def vocab_add(
    word: str,
    translation: str,
    context: str = "",
    *,
    saved_at: Optional[int] = None,
) -> dict:
    word = (word or "").strip()
    translation = (translation or "").strip()
    context = (context or "").strip()
    if not word or not translation:
        raise ValueError("Нужны word и translation")
    ts = int(saved_at) if saved_at is not None else int(time.time() * 1000)
    with _db_lock:
        conn = _db()
        try:
            existing = conn.execute(
                "SELECT id FROM vocabulary "
                "WHERE lower(word)=lower(?) AND context=? LIMIT 1",
                (word, context),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE vocabulary SET translation=?, saved_at=? WHERE id=?",
                    (translation, ts, existing["id"]),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id, word, translation, context, saved_at "
                    "FROM vocabulary WHERE id=?",
                    (existing["id"],),
                ).fetchone()
                return _row_to_item(row)
            cur = conn.execute(
                "INSERT INTO vocabulary (word, translation, context, saved_at) "
                "VALUES (?, ?, ?, ?)",
                (word, translation, context, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, word, translation, context, saved_at "
                "FROM vocabulary WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
            return _row_to_item(row)
        finally:
            conn.close()


def vocab_import_many(items: list) -> int:
    prepared = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        word = str(raw.get("word") or "").strip()
        translation = str(raw.get("translation") or "").strip()
        if not word or not translation:
            continue
        context = str(raw.get("context") or "").strip()
        saved_at = raw.get("savedAt")
        ts = int(saved_at) if saved_at is not None else int(time.time() * 1000)
        prepared.append((word, translation, context, ts))
    if not prepared:
        return 0

    imported = 0
    with _db_lock:
        conn = _db()
        try:
            for word, translation, context, ts in prepared:
                existing = conn.execute(
                    "SELECT id FROM vocabulary "
                    "WHERE lower(word)=lower(?) AND context=? LIMIT 1",
                    (word, context),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE vocabulary SET translation=?, saved_at=? WHERE id=?",
                        (translation, ts, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO vocabulary (word, translation, context, saved_at) "
                        "VALUES (?, ?, ?, ?)",
                        (word, translation, context, ts),
                    )
                imported += 1
            conn.commit()
        finally:
            conn.close()
    return imported


def vocab_delete(item_id: int) -> bool:
    with _db_lock:
        conn = _db()
        try:
            cur = conn.execute("DELETE FROM vocabulary WHERE id=?", (item_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def vocab_clear() -> None:
    with _db_lock:
        conn = _db()
        try:
            conn.execute("DELETE FROM vocabulary")
            conn.commit()
        finally:
            conn.close()


def _ollama_request(path: str, payload: Optional[dict] = None, timeout: int = 60):
    url = f"{OLLAMA_URL}{path}"
    data = None
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _model_ready(names: list, model: str) -> bool:
    return any(
        name == model
        or name.startswith(f"{model}-")
        or name.startswith(f"{model}:")
        for name in names
    ) or model in names


def ollama_status() -> dict:
    try:
        tags = _ollama_request("/api/tags", timeout=5)
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "ready": False,
            "loaded": False,
            "model": OLLAMA_MODEL,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "error": f"Ollama недоступна: {exc.reason}. Запустите ./start.sh",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "ready": False,
            "loaded": False,
            "model": OLLAMA_MODEL,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "error": str(exc),
        }

    names = []
    for item in tags.get("models") or []:
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(name)
    ready = _model_ready(names, OLLAMA_MODEL)
    loaded = False
    if ready:
        try:
            ps = _ollama_request("/api/ps", timeout=5)
            running = []
            for item in ps.get("models") or []:
                name = item.get("name") or item.get("model") or ""
                if name:
                    running.append(name)
            loaded = _model_ready(running, OLLAMA_MODEL)
        except Exception:  # noqa: BLE001
            loaded = False

    return {
        "ok": True,
        "ready": ready,
        "loaded": loaded,
        "model": OLLAMA_MODEL,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "agents": ["word", "phrase"],
        "models": names,
        "error": None if ready else f"Модель ещё не скачана: {OLLAMA_MODEL}",
    }


def ollama_warm() -> dict:
    """Загрузить модель в RAM с keep_alive (без полноценного ответа)."""
    status = ollama_status()
    if not status.get("ok"):
        return {
            "ok": False,
            "loaded": False,
            "model": OLLAMA_MODEL,
            "error": status.get("error") or "Ollama недоступна",
        }
    if not status.get("ready"):
        return {
            "ok": False,
            "loaded": False,
            "model": OLLAMA_MODEL,
            "error": status.get("error") or f"Модель не скачана: {OLLAMA_MODEL}",
        }
    if status.get("loaded"):
        return {
            "ok": True,
            "loaded": True,
            "model": OLLAMA_MODEL,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "error": None,
        }

    payload = {
        "model": OLLAMA_MODEL,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "stream": False,
        "prompt": "",
        "options": {
            "num_predict": 0,
            "num_thread": OLLAMA_NUM_THREAD,
        },
    }
    try:
        with _ollama_lock:
            _ollama_request("/api/generate", payload, timeout=120)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:200]}") from exc

    return {
        "ok": True,
        "loaded": True,
        "model": OLLAMA_MODEL,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "error": None,
    }


# Частые маты/сленг: 3B-модель часто выдумывает «фуствать» вместо нормального перевода.
VULGAR_GLOSSARY = {
    "fuck": "ёбать; блять",
    "fucking": "ёбаный; (усиление) блять",
    "fucked": "в жопе; трахнутый",
    "fucker": "мудак; ублюдок",
    "fuckin": "ёбаный; (усиление) блять",
    "fuckin'": "ёбаный; (усиление) блять",
    "shit": "дерьмо; херня",
    "shitty": "дерьмовое; хреновое",
    "bullshit": "полная херня",
    "damn": "чёрт; проклятый",
    "damned": "проклятый",
    "bitch": "сука",
    "bitches": "суки",
    "ass": "жопа",
    "asses": "жопы",
    "asshole": "мудак; жопа",
    "bastard": "ублюдок",
    "hell": "ад; чёрт",
    "crap": "херня",
    "dick": "хуй",
    "cock": "хуй",
    "pussy": "пизда; тряпка",
    "piss": "ссать; бесить",
    "pissed": "в бешенстве; пьяный",
    "whore": "шлюха",
    "slut": "шлюха",
    "motherfucker": "мудак; сукин сын",
    "motherfucking": "ёбаный; (усиление) блять",
    "cunt": "пизда",
    "suck": "сосать; отстой",
    "sucks": "отстой",
    "goddamn": "чёртов; проклятый",
    "goddamned": "чёртов",
}

# Многословные идиомы — всегда раньше LLM (3B плохо их знает).
# Только мат/устойчивые ругательства — 4B их стабильно ломает.
# Обычные разговорные идиомы держим в промптах/few-shot, не раздувая словарь.
PHRASE_GLOSSARY = {
    "shut the fuck up": "заткнись нахуй",
    "shut the hell up": "заткнись уже",
    "shut up": "заткнись",
    "fuck off": "отъебись",
    "fuck you": "пошёл нахуй",
    "fuck me": "блядь; охуеть",
    "what the fuck": "что за хуйня",
    "what the hell": "какого чёрта",
    "the fuck": "(усиление) блять",
    "get the fuck out": "проваливай нахуй",
    "go fuck yourself": "иди нахуй",
    "are you fucking kidding me": "ты ёбанутый?",
    "no fucking way": "нихуя себе",
    "oh my fucking god": "ёбаный в рот",
}

# Односложные слова, которые 3B ломает рядом с матом / частые клики без LLM.
COMMON_WORD_GLOSSARY = {
    "shut": "закрыть; заткнуть",
    "look": "смотреть; выглядеть",
    "like": "как; нравиться; типа",
    "get": "получить; стать",
    "along": "вместе; вдоль",
    "with": "с",
    "would": "бы",
    "thinking": "думать; мысль",
    "myself": "себе; сам",
    "somebody": "кто-то",
    "someone": "кто-то",
    "normally": "обычно",
    "same": "тот же; такой же",
    "direction": "направление",
    "planet": "планета",
    "earth": "земля; Земля",
    "revolving": "вращающийся; вращаться",
    "point": "смысл; суть; точка",
    "ain't": "не (разг.)",
}

# Артикли: 3B в контексте мата часто отвечает «фUCK» вместо значения артикля.
FUNCTION_WORD_GLOSSARY = {
    "the": "определённый артикль the",
    "a": "неопределённый артикль a",
    "an": "неопределённый артикль an",
}


def _normalize_english_spacing(text: str) -> str:
    """Чинит «I 'm» / «who 's» от старой токенизации субтитров."""
    s = (text or "").strip()
    if not s:
        return ""
    s = re.sub(r"\b([A-Za-z]+)\s+('(?:[A-Za-z]+))\b", r"\1\2", s)
    s = re.sub(r"\b([A-Za-z]+)\s+(n't)\b", r"\1\2", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _is_long_phrase(target: str) -> bool:
    words = [w for w in _normalize_phrase_key(target).split() if w]
    return len(words) >= 4 or len((target or "").strip()) > 42


def _normalize_phrase_key(phrase: str) -> str:
    key = _normalize_english_spacing(phrase or "").lower()
    key = re.sub(r"[^a-zA-Z'\s]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def _glossary_lookup(phrase: str, sentence: Optional[str] = None) -> Optional[str]:
    key = _normalize_phrase_key(phrase)
    if not key:
        return None

    if key in PHRASE_GLOSSARY:
        return PHRASE_GLOSSARY[key]

    if " " not in key and key in FUNCTION_WORD_GLOSSARY:
        return FUNCTION_WORD_GLOSSARY[key]

    if " " not in key and key in COMMON_WORD_GLOSSARY:
        return COMMON_WORD_GLOSSARY[key]

    if " " not in key and key in VULGAR_GLOSSARY:
        ctx = _normalize_phrase_key(sentence or "")
        # В «shut the fuck up» / «the fuck» слово fuck — усилитель, не глагол.
        if key == "fuck" and ctx and re.search(
            r"\b(shut|what|where|who|how|get|get the|the)\b.*\bfuck\b|\bfuck\b.*\b(up|out|off)\b",
            ctx,
        ):
            return "(усиление) блять"
        return VULGAR_GLOSSARY[key]

    return None


def _normalize_word_gloss_case(text: str) -> str:
    """Убирает кривой регистр вроде «закрЫть» → «закрыть»."""
    if not text or re.search(r"[A-Za-z]", text):
        return text
    parts = []
    for chunk in re.split(r"(\s+)", text):
        if not chunk or chunk.isspace():
            parts.append(chunk)
            continue
        # Сохраняем скобочные пометки как есть после lower.
        parts.append(chunk.lower())
    return "".join(parts)


def _latin_tokens(text: str) -> list:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or "")


def _is_bad_word_translation(result: str, target: str) -> bool:
    """Отсекает галлюцинации в коротких словарных глоссах."""
    text = (result or "").strip()
    if not text:
        return True
    # Для длинных фраз допустимы имена собственные из оригинала.
    if _is_long_phrase(target):
        if len(text) > 220:
            return True
        src = {t.lower() for t in _latin_tokens(target)}
        for tok in _latin_tokens(text):
            if tok.lower() not in src and len(tok) > 1:
                return True
        return False

    if re.search(r"[A-Za-z]", text):
        # Имя собственное из оригинала (Rue, Earth) — ок.
        src = {t.lower() for t in _latin_tokens(target)}
        foreign = [t for t in _latin_tokens(text) if t.lower() not in src]
        if foreign:
            return True
    if len(text) > 64:
        return True
    if target and text.lower() == target.strip().lower():
        return True
    return False


def _translate_cache_key(text: str, word: Optional[str], sentence: Optional[str]) -> str:
    if word:
        return f"w:{word.strip().lower()}|{(sentence or '').strip().lower()}"
    return f"t:{(text or '').strip().lower()}"


def _translate_cache_get(key: str) -> Optional[str]:
    with _translate_cache_lock:
        value = _translate_cache.get(key)
        if value is None:
            return None
        _translate_cache.move_to_end(key)
        return value


def _translate_cache_put(key: str, value: str) -> None:
    with _translate_cache_lock:
        _translate_cache[key] = value
        _translate_cache.move_to_end(key)
        while len(_translate_cache) > _TRANSLATE_CACHE_MAX:
            _translate_cache.popitem(last=False)


def _colloquial_system_prompt(*, span: bool = False) -> str:
    """Общие правила разговорного EN→RU; паттерны вместо раздувания глоссария."""
    scope = (
        "Переведи ТОЛЬКО поле TARGET. CONTEXT — соседние реплики для смысла, "
        "его не переводи и не вплетай в ответ. "
        if span
        else "Переведи ТОЛЬКО данную реплику. "
    )
    return (
        "Ты переводчик разговорных субтитров EN→RU (сериал, сленг). "
        + scope
        + "Переводи смысл, как сказал бы носитель русского, а не слово в слово. "
        "Сначала ищи фразовый глагол/идиому целиком (snap out of, get over, come on), "
        "потом уже отдельные слова. "
        "Частые ловушки-кальки: "
        "snap out of (it/this) → очнись / выйди из этого (НЕ «разбейся/щёлкни»); "
        "the point / what's the point → суть/смысл (НЕ «точка»); "
        "things have been/are → всё стало/идёт (НЕ «вещи»); "
        "stack (cash/money) → копить/откладывать (НЕ «стекать/штабелировать»); "
        "hot as fuck → охуенно горячая/красивая (разг.); "
        "I mean → в смысле / ну; "
        "like (filler) → типа / как бы; "
        "ain't → разговорное отрицание. "
        "Мат-вставки (the fuck, fucking) — усиление, не отдельный «трахать». "
        "Без дописок и пояснений. Длина roughly как оригинал. "
        "Имена латиницей. Мат без цензуры. "
        + (
            'Строго JSON: {"ru":"перевод только TARGET"}.'
            if span
            else 'Строго JSON: {"ru":"перевод"}.'
        )
    )


def _line_translate_messages(cleaned: str) -> list:
    return [
        {"role": "system", "content": _colloquial_system_prompt(span=False)},
        # Few-shot: разные паттерны, не «заучивание» одной фразы.
        {"role": "user", "content": "you just snap the fuck out of this"},
        {"role": "assistant", "content": '{"ru":"ты просто очнись уже"}'},
        {"role": "user", "content": "I mean ain't that the point"},
        {"role": "assistant", "content": '{"ru":"в смысле, разве не в этом суть?"}'},
        {"role": "user", "content": "stack my cash"},
        {"role": "assistant", "content": '{"ru":"копить кэш"}'},
        {"role": "user", "content": "things have been like really good"},
        {"role": "assistant", "content": '{"ru":"всё стало типа реально хорошо"}'},
        {"role": "user", "content": "you're hot as fuck"},
        {"role": "assistant", "content": '{"ru":"ты охуенно горячая"}'},
        {"role": "user", "content": cleaned},
    ]


def _span_translate_messages(marked: str, target: str) -> list:
    """Перевод куска с соседним контекстом: контекст отдельно, чтобы не «прилипал»."""
    m = re.search(r"\[\[(.*?)\]\]", marked or "", re.DOTALL)
    frag = (m.group(1) if m else target).strip()
    before = ""
    after = ""
    if m:
        before = (marked[: m.start()] or "").strip()
        after = (marked[m.end() :] or "").strip()
    context_bits = " ".join(p for p in (before, after) if p).strip()

    return [
        {"role": "system", "content": _colloquial_system_prompt(span=True)},
        {
            "role": "user",
            "content": (
                "CONTEXT: I mean ever since I gave my life over to my lord and savior Jesus Christ\n"
                "TARGET: things have been like really good"
            ),
        },
        {"role": "assistant", "content": '{"ru":"всё стало типа реально хорошо"}'},
        {
            "role": "user",
            "content": (
                "CONTEXT: things have been like really good\n"
                "TARGET: I mean ain't that the point"
            ),
        },
        {"role": "assistant", "content": '{"ru":"в смысле, разве не в этом суть?"}'},
        {
            "role": "user",
            "content": (
                f"CONTEXT: {context_bits or '(нет)'}\n"
                f"TARGET: {frag}"
            ),
        },
    ]


def _word_translate_messages(marked: str, target: str) -> list:
    system = (
        "Словарь EN→RU. Переведи только [[...]]. Короткая глосса, без пояснений. "
        'Ответ строго JSON: {"ru":"перевод"}.'
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "[[know]]",
        },
        {"role": "assistant", "content": '{"ru":"знать"}'},
        {
            "role": "user",
            "content": marked if marked.strip().startswith("[[") else f"[[{target}]]",
        },
    ]


def _source_token_count(text: str) -> int:
    return len([w for w in _normalize_phrase_key(text).split() if w])


def _looks_like_elaboration(source: str, translation: str) -> bool:
    """Грубая эвристика: перевод сильно длиннее оригинала или типичная отсебятина."""
    src_n = _source_token_count(source)
    if src_n <= 0:
        return False
    # Считаем «слова» кириллицы/латиницы в переводе
    ru_words = re.findall(r"[A-Za-zА-Яа-яЁё]+", translation or "")
    ru_n = len(ru_words)
    if ru_n >= max(8, int(src_n * 1.85) + 2):
        return True
    # Типичные дописки модели
    if re.search(
        r"(?i)(даже не могу|не могу описать|и так далее|и т\.?\s*д\.?|"
        r"продолжает|в общем|короче говоря|настолько .+ что)",
        translation or "",
    ):
        return True
    if translation.strip().endswith(("...", "…")) and "..." not in source and "…" not in source:
        return True
    return False


def _is_bad_phrase_translation(source: str, translation: str) -> bool:
    """Ловит буквальщину и отсебятину во фразах субтитров."""
    if not (translation or "").strip():
        return True
    if _looks_like_elaboration(source, translation):
        return True
    src = _normalize_phrase_key(source)
    ru = (translation or "").lower()
    # Colloquial "things have been/are…" → не «вещи …»
    if re.search(r"^things\b.+\b(have been|has been|are|were|got|getting)\b", src):
        if re.search(r"\bвещ", ru):
            return True
    # Idiomatic "the point" (суть) → не геометрическая «точка»
    if re.search(r"\b(the point|what's the point|whats the point)\b", src):
        if re.search(r"\bточк", ru) and not re.search(r"\b(суть|смысл|дело)\b", ru):
            return True
    # slang stack cash/money → не «стекать/штабель»
    if re.search(r"\bstack\b.+\b(cash|money|dough|bread)\b", src):
        if re.search(r"стек|штабел|складывать стопк", ru):
            return True
    # snap out of → не «разбить/щёлкнуть»
    if re.search(r"\bsnap\b.+\bout\b", src):
        if re.search(r"разб|щёлка|щелка|лом(а|и)|треск", ru) and not re.search(
            r"очни|выйд|перестань|брось|хватит", ru
        ):
            return True
    return False


def _strict_retry_messages(target: str) -> list:
    return [
        {
            "role": "system",
            "content": (
                "EN→RU colloquial subtitles. Sense, not word-for-word. "
                "snap out of→очнись/выйди из этого (not разбейся). "
                "the point→суть/смысл (not точка). things→всё (not вещи). "
                "No extra words, no commentary. "
                'JSON only: {"ru":"..."}.'
            ),
        },
        {"role": "user", "content": "snap the fuck out of this"},
        {"role": "assistant", "content": '{"ru":"очнись уже"}'},
        {"role": "user", "content": "ain't that the point"},
        {"role": "assistant", "content": '{"ru":"разве не в этом суть?"}'},
        {"role": "user", "content": target},
    ]


def _extract_ru_payload(raw: str) -> str:
    """Достаёт перевод из JSON {\"ru\":...} или возвращает очищенный текст."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Срезать markdown-ограждения ```json ... ```
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("ru", "translation", "text", "gloss"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        if isinstance(data, str) and data.strip():
            return data.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    # Иногда модель клеит JSON в конец рассуждения.
    m = re.search(r'\{\s*"ru"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}', text)
    if m:
        try:
            return json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            return m.group(1).replace('\\"', '"')
    return _clean_translation(text)


def _extract_json_field(raw: str, *keys: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in keys:
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        if isinstance(data, str) and data.strip():
            return data.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    for key in keys:
        m = re.search(rf'\{{\s*"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}}', text)
        if m:
            try:
                return json.loads(f'"{m.group(1)}"')
            except json.JSONDecodeError:
                return m.group(1).replace('\\"', '"')
    return _clean_translation(text)


def _chat_json(
    messages: list,
    *,
    keys: Tuple[str, ...],
    num_predict: int,
    temperature: float,
    num_ctx: int,
    schema_props: dict,
) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "format": {
            "type": "object",
            "properties": schema_props,
            "required": list(keys),
        },
        "options": {
            "temperature": temperature,
            "top_p": 0.8,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
            "num_thread": OLLAMA_NUM_THREAD,
        },
        "messages": messages,
    }
    try:
        with _ollama_lock:
            data = _ollama_request("/api/chat", payload, timeout=90)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:200]}") from exc

    msg = data.get("message") or {}
    raw = (msg.get("content") or "").strip() or (msg.get("thinking") or "").strip()
    result = _extract_json_field(raw, *keys)
    if not result:
        raise RuntimeError("Пустой ответ модели")
    return result


def _tutor_system_prompt() -> str:
    """Отдельный промпт для чата-разбора: учитель, коротко и по делу."""
    return (
        "Ты учитель английского для русскоязычного зрителя сериала/фильма. "
        "Задача — объяснить выделенное слово или фразу в контексте реплики, "
        "чтобы зритель понял, зачем так сказано.\n"
        "\n"
        "Как отвечать:\n"
        "1) Сначала суть в 1 предложении (что это значит здесь).\n"
        "2) Затем 1–2 коротких уточнения: идиома/сленг, грамматика, тон или ловушка-калька — "
        "только то, что реально помогает.\n"
        "3) Если уместно — одна естественная русская калька смысла (не дословный перевод).\n"
        "\n"
        "Стиль: ясно, уверенно, без воды. 2–5 предложений, без списков и заголовков. "
        "Говори как хороший репетитор у экрана, не как учебник.\n"
        "\n"
        "Не делай: не пересказывай серию; не переводи всю реплику заново, если не просят; "
        "не сыпь правилами «на будущее»; не пиши «как носитель я бы сказал…»; "
        "не раздувай ответ примерами без нужды.\n"
        "\n"
        "Мат и сленг называй прямо. Если в выделении filler (like, I mean) — скажи, "
        "что это вставное слово, а не «как/я имею в виду» дословно.\n"
        'Строго JSON: {"answer":"текст ответа"}.'
    )


def ollama_explain(
    *,
    word: str,
    sentence: str = "",
    question: str = "",
    translation: str = "",
) -> str:
    """Короткий разбор слова/фразы: зачем так сказано, грамматика, идиома."""
    focus = _normalize_english_spacing(word or "")
    ctx = _normalize_english_spacing(sentence or "")
    q = (question or "").strip() or "Почему здесь так сказано? Кратко объясни."
    ru = (translation or "").strip()
    if not focus:
        raise ValueError("Нужно слово или фраза")
    if len(q) > 400:
        raise ValueError("Слишком длинный вопрос")

    user = (
        f"Выделение: {focus}\n"
        f"Реплика: {ctx or '(нет)'}\n"
        f"Перевод на экране: {ru or '(нет)'}\n"
        f"Вопрос: {q}"
    )
    return _chat_json(
        [
            {"role": "system", "content": _tutor_system_prompt()},
            {
                "role": "user",
                "content": (
                    "Выделение: snap the fuck out of this\n"
                    "Реплика: Maddy, you just snap the fuck out of this.\n"
                    "Перевод на экране: ты просто очнись уже\n"
                    "Вопрос: Почему так сказано?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    '{"answer":"Здесь snap out of this — идиома «очнись / выйди из этого '
                    "состояния», а не «разбей». The fuck усиливает злость и напор. "
                    'По смыслу: резко прекрати зацикливаться."}'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Выделение: like\n"
                    "Реплика: Don't you talk to me like that!\n"
                    "Перевод на экране: как; нравиться; типа\n"
                    "Вопрос: Это идиома или сленг? Как звучит по-русски естественно?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    '{"answer":"Здесь like — обычный предлог «как», не filler «типа» '
                    "и не «нравиться». Talk to me like that ≈ «говори со мной в таком тоне». "
                    'Естественно: «Не смей так со мной разговаривать!»"}'
                ),
            },
            {"role": "user", "content": user},
        ],
        keys=("answer",),
        num_predict=160,
        temperature=0.2,
        num_ctx=1024,
        schema_props={"answer": {"type": "string"}},
    )


def _chat_translate(
    messages: list,
    *,
    agent: str,
    num_predict: int,
    temperature: float,
    num_ctx: int,
) -> str:
    """agent: 'word' | 'phrase'. Одна модель; JSON-формат — чтобы qwen3 не уходил в болтовню."""
    return _chat_json(
        messages,
        keys=("ru", "translation", "text", "gloss"),
        num_predict=num_predict,
        temperature=temperature,
        num_ctx=num_ctx,
        schema_props={"ru": {"type": "string"}},
    )

def _has_broader_context(target: str, sentence: Optional[str]) -> bool:
    if not sentence or not target:
        return False
    sent = _normalize_english_spacing(sentence)
    tgt = _normalize_english_spacing(target)
    if not sent or not tgt:
        return False
    if _normalize_phrase_key(sent) == _normalize_phrase_key(tgt):
        return False
    return tgt.lower() in sent.lower() or _normalize_phrase_key(tgt) in _normalize_phrase_key(sent)


def _is_cue_join_span(target: str, sentence: str) -> bool:
    """Span только для склейки соседних cue (фраза в начале/конце), не для выделения из середины."""
    sent = _normalize_phrase_key(sentence)
    tgt = _normalize_phrase_key(target)
    if not sent or not tgt or sent == tgt:
        return False
    if tgt not in sent:
        return False
    # «prev… [[cue]]» или «[[cue]] next…»
    return sent.startswith(tgt + " ") or sent.endswith(" " + tgt)


def _looks_like_context_bleed(target: str, context: str, translation: str) -> bool:
    """Перевод заметно ближе по длине к CONTEXT, чем к TARGET."""
    tgt_n = _source_token_count(target)
    ctx_n = _source_token_count(context)
    ru_n = len(re.findall(r"[A-Za-zА-Яа-яЁё]+", translation or ""))
    if tgt_n <= 0 or ru_n <= 0 or ctx_n <= tgt_n + 1:
        return False
    if tgt_n <= 5 and ru_n >= tgt_n * 2 + 1:
        return True
    if ru_n >= tgt_n + 3 and ru_n >= int(0.55 * ctx_n):
        return True
    return False


def _phrase_num_predict(source: str) -> int:
    # Жёсткий потолок: меньше токенов → меньше места для отсебятины.
    n = _source_token_count(source)
    return min(72, max(28, 8 + n * 4))


def ollama_translate(text: str, *, word: Optional[str] = None, sentence: Optional[str] = None) -> str:
    cleaned = _normalize_english_spacing(text or "")
    if not cleaned:
        return ""
    if len(cleaned) > 800:
        raise ValueError("Слишком длинный текст (макс. 800 символов)")

    word_raw = _normalize_english_spacing(word) if word else None
    sentence = _normalize_english_spacing(sentence) if sentence else sentence

    # Фраза (2+ слова) с соседним cue-контекстом — переводим [[фрагмент]], не всю склейку.
    # Выделение из середины одной реплики («stack my cash») — без span, иначе модель
    # переводит всю строку.
    word_words = len(_normalize_phrase_key(word_raw or "").split()) if word_raw else 0
    span_mode = bool(
        word_raw
        and word_words >= 2
        and sentence
        and _has_broader_context(word_raw, sentence)
        and _is_cue_join_span(word_raw, sentence)
    )
    if word_raw and word_words >= 2 and not span_mode:
        cleaned = word_raw
        word_raw = None

    cache_key = _translate_cache_key(cleaned, word_raw, sentence)
    cached = _translate_cache_get(cache_key)
    if cached is not None:
        return cached

    source_for_check = word_raw or cleaned

    if span_mode:
        target = word_raw.strip()
        ctx = (sentence or "").strip()
        if len(ctx) > 420:
            ctx = ctx[:420].rsplit(" ", 1)[0]
        marked = _mark_phrase_in_context(ctx, target) if ctx else f"[[{target}]]"
        phrase_gloss = _glossary_lookup(target)
        if phrase_gloss and " " in _normalize_phrase_key(target):
            _translate_cache_put(cache_key, phrase_gloss)
            return phrase_gloss
        result = _chat_translate(
            _span_translate_messages(marked, target),
            agent="phrase",
            num_predict=_phrase_num_predict(target),
            temperature=0,
            num_ctx=1024,
        )
        # Контекст иногда ломает идиомы или «прилипает» целиком — только TARGET.
        if (
            _is_bad_phrase_translation(target, result)
            or _looks_like_context_bleed(target, ctx, result)
        ):
            result = _chat_translate(
                _line_translate_messages(target),
                agent="phrase",
                num_predict=_phrase_num_predict(target),
                temperature=0,
                num_ctx=1024,
            )
    elif word_raw:
        target = word_raw.strip()
        ctx = (sentence or "").strip()
        gloss = _glossary_lookup(target, ctx)
        if gloss:
            _translate_cache_put(cache_key, gloss)
            return gloss

        # Без длинного контекста: prefill на CPU дешевле, меньше «заражения» матом.
        marked = f"[[{target}]]"
        result = _chat_translate(
            _word_translate_messages(marked, target),
            agent="word",
            num_predict=24,
            temperature=0,
            num_ctx=256,
        )
        result = _normalize_word_gloss_case(result)
        if _is_bad_word_translation(result, word_raw):
            gloss = _glossary_lookup(word_raw, sentence)
            if gloss:
                _translate_cache_put(cache_key, gloss)
                return gloss
            retry = _chat_translate(
                _strict_retry_messages(target),
                agent="word",
                num_predict=20,
                temperature=0,
                num_ctx=256,
            )
            retry = _normalize_word_gloss_case(retry)
            if not _is_bad_word_translation(retry, word_raw):
                result = retry
            else:
                result = _chat_translate(
                    _line_translate_messages(word_raw),
                    agent="phrase",
                    num_predict=_phrase_num_predict(word_raw),
                    temperature=0,
                    num_ctx=1024,
                )
    else:
        phrase_gloss = _glossary_lookup(cleaned)
        if phrase_gloss and " " in _normalize_phrase_key(cleaned):
            _translate_cache_put(cache_key, phrase_gloss)
            return phrase_gloss

        result = _chat_translate(
            _line_translate_messages(cleaned),
            agent="phrase",
            num_predict=_phrase_num_predict(cleaned),
            temperature=0,
            num_ctx=1024,
        )

    if _is_bad_phrase_translation(source_for_check, result):
        result = _chat_translate(
            _strict_retry_messages(source_for_check),
            agent="phrase",
            num_predict=_phrase_num_predict(source_for_check),
            temperature=0,
            num_ctx=512,
        )

    _translate_cache_put(cache_key, result)
    return result


def google_translate(text: str) -> str:
    """Быстрый EN→RU через публичный endpoint Google Translate (client=gtx)."""
    cleaned = _normalize_english_spacing(text or "")
    if not cleaned:
        return ""
    if len(cleaned) > 800:
        raise ValueError("Слишком длинный текст (макс. 800 символов)")

    # Точные глоссы (мат и т.п.) — надёжнее Google.
    gloss = _glossary_lookup(cleaned)
    if gloss:
        return gloss

    cache_key = f"gtx:{cleaned.lower()}"
    cached = _translate_cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=en&tl=ru&dt=t&q={quote(cleaned)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Translate HTTP {exc.code}: {body[:160]}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Некорректный ответ Google Translate") from exc

    parts = []
    rows = data[0] if isinstance(data, list) and data else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, list) and row and isinstance(row[0], str) and row[0]:
                parts.append(row[0])
    result = "".join(parts).strip()
    if not result:
        raise RuntimeError("Пустой ответ Google Translate")
    result = _clean_translation(result)
    _translate_cache_put(cache_key, result)
    return result


def translate_text(
    text: str,
    *,
    word: Optional[str] = None,
    sentence: Optional[str] = None,
    engine: str = "google",
) -> Tuple[str, str, str]:
    """
    Возвращает (translation, provider, model).
    engine: google | ai/ollama
    """
    mode = (engine or TRANSLATE_DEFAULT_ENGINE or "google").strip().lower()
    if mode in ("ai", "ollama", "llm", "local"):
        return ollama_translate(text, word=word, sentence=sentence), "ollama", OLLAMA_MODEL

    # Google: переводим выделенное (word) или всю реплику (text), без «прилипания» контекста.
    focus = _normalize_english_spacing(word or text or "")
    if not focus:
        focus = _normalize_english_spacing(text or "")
    if not GOOGLE_TRANSLATE_ENABLED:
        return ollama_translate(text, word=word, sentence=sentence), "ollama", OLLAMA_MODEL

    try:
        return google_translate(focus), "google", "gtx"
    except Exception:
        # Сеть/лимиты Google — мягкий откат на локальную модель.
        return ollama_translate(text, word=word, sentence=sentence), "ollama", OLLAMA_MODEL


def _mark_phrase_in_context(context: str, phrase: str) -> str:
    """Оборачивает первое вхождение фразы в [[...]] (без учёта регистра)."""
    ctx = context or ""
    target = (phrase or "").strip()
    if not ctx or not target:
        return f"[[{target}]]" if target else ctx

    pattern = re.compile(re.escape(target), re.IGNORECASE)
    match = pattern.search(ctx)
    if not match:
        # Пробуем с нормализованными апострофами.
        ctx_n = _normalize_english_spacing(ctx)
        tgt_n = _normalize_english_spacing(target)
        match_n = re.compile(re.escape(tgt_n), re.IGNORECASE).search(ctx_n)
        if match_n:
            start, end = match_n.span()
            return f"{ctx_n[:start]}[[{ctx_n[start:end]}]]{ctx_n[end:]}"
        return f"{ctx}\n[[{target}]]"
    start, end = match.span()
    return f"{ctx[:start]}[[{ctx[start:end]}]]{ctx[end:]}"


def _clean_translation(raw: str) -> str:
    """Убирает типичные галлюцинации: примечания, кавычки, CJK, лишний текст."""
    text = (raw or "").strip()
    if not text:
        return ""

    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip().strip("\"'`«»")
        if not s:
            continue
        if re.match(r"(?i)^(примечание|note|context|phrase|перевод)\s*[:：]", s):
            if re.match(r"(?i)^перевод\s*[:：]", s):
                s = re.sub(r"(?i)^перевод\s*[:：]\s*", "", s).strip()
                if s:
                    lines.append(s)
            break
        s = re.sub(r"^\[\[|\]\]$", "", s).strip()
        lines.append(s)
        break

    result = lines[0] if lines else text.split("\n", 1)[0].strip().strip("\"'`«»")
    result = re.split(r"(?i)\s+примечание\s*[:：].*$", result, maxsplit=1)[0].strip()
    result = result.strip("\"'`«»[]")
    # Qwen иногда вставляет китайские иероглифы в RU-ответ.
    result = re.sub(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]+", "", result)
    # «curious - любопытный» / «[[know]] — знать»
    result = re.sub(r"^\[\[.*?\]\]\s*[-–—:]\s*", "", result).strip()
    result = re.sub(r"^[A-Za-z']+\s*[-–—:]\s*", "", result).strip()
    result = re.sub(r"\s{2,}", " ", result).strip(" ,;.")
    return result.strip()


class SubLearnHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        path = urlparse(self.path).path
        if path in ("/api/stream", "/api/subtitles"):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/embed":
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
        else:
            self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/resolve":
            params = parse_qs(parsed.query)
            url = (params.get("url") or [""])[0].strip()
            if not url:
                self._json_response(400, {"error": "Параметр url обязателен"})
                return
            try:
                data = resolve_page(url)
                self._json_response(200, data)
            except SecurityError as exc:
                self._json_response(403, {"error": str(exc)})
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(502, {"error": f"Не удалось загрузить страницу: {exc.reason}"})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        if parsed.path == "/api/embed":
            params = parse_qs(parsed.query)
            url = (params.get("url") or [""])[0].strip()
            skip_ads = (params.get("skipAds") or ["1"])[0] != "0"
            if not url:
                self._text_response(400, "url required", "text/plain")
                return
            try:
                body = build_embed_proxy(url, skip_ads).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except SecurityError as exc:
                self._text_response(403, str(exc), "text/plain")
            except urllib.error.HTTPError as exc:
                self._text_response(
                    502,
                    f"fetch error: {exc.reason} (HTTP {exc.code}). "
                    f"Плеер недоступен — выберите «Плеер 3» или нажмите «Загрузить» снова.",
                    "text/plain",
                )
            except urllib.error.URLError as exc:
                self._text_response(502, f"fetch error: {exc.reason}", "text/plain")
            except Exception as exc:  # noqa: BLE001
                self._text_response(500, str(exc), "text/plain")
            return
        if parsed.path == "/api/stream":
            params = parse_qs(parsed.query)
            url = (params.get("url") or [""])[0].strip()
            if not url:
                self._text_response(400, "invalid url", "text/plain")
                return
            try:
                body, ctype = proxy_stream(url)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except SecurityError as exc:
                self._text_response(403, str(exc), "text/plain")
            except urllib.error.URLError as exc:
                self._text_response(502, f"stream error: {exc.reason}", "text/plain")
            except Exception as exc:  # noqa: BLE001
                self._text_response(500, str(exc), "text/plain")
            return
        if parsed.path == "/api/subtitles":
            params = parse_qs(parsed.query)
            url = (params.get("url") or [""])[0].strip()
            if not url:
                self._text_response(400, "invalid url", "text/plain")
                return
            try:
                body, _ = fetch_binary(url)
                self.send_response(200)
                self.send_header("Content-Type", "text/vtt; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except SecurityError as exc:
                self._text_response(403, str(exc), "text/plain")
            except urllib.error.URLError as exc:
                self._text_response(502, f"subtitle error: {exc.reason}", "text/plain")
            except Exception as exc:  # noqa: BLE001
                self._text_response(500, str(exc), "text/plain")
            return
        if parsed.path == "/api/ai-status":
            self._json_response(200, ollama_status())
            return
        if parsed.path == "/api/vocab":
            try:
                self._json_response(200, {"items": vocab_list()})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        if parsed.path == "/api/translate":
            params = parse_qs(parsed.query)
            text = (params.get("text") or [""])[0].strip()
            word = (params.get("word") or [""])[0].strip() or None
            sentence = (params.get("sentence") or [""])[0].strip() or None
            engine = (params.get("engine") or [TRANSLATE_DEFAULT_ENGINE])[0].strip().lower()
            if not text and not word:
                self._json_response(400, {"error": "Параметр text или word обязателен"})
                return
            try:
                translation, provider, model = translate_text(
                    text or word or "",
                    word=word,
                    sentence=sentence,
                    engine=engine,
                )
                used_word = bool(word) and not _is_long_phrase(word)
                self._json_response(
                    200,
                    {
                        "translation": translation,
                        "provider": provider,
                        "model": model,
                        "engine": engine if engine in ("google", "ai", "ollama", "llm", "local") else "google",
                        "agent": "word" if used_word and provider == "ollama" else "phrase",
                        "canRefine": provider == "google",
                    },
                )
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(
                    502,
                    {
                        "error": (
                            f"Сервис перевода недоступен: {exc.reason}. "
                            "Проверьте сеть или Ollama (./start.sh)"
                        )
                    },
                )
            except RuntimeError as exc:
                self._json_response(502, {"error": str(exc)})
            except (json.JSONDecodeError, IndexError, TypeError) as exc:
                self._json_response(502, {"error": f"Не удалось разобрать ответ: {exc}"})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/vocab":
            try:
                payload = self._read_json_body()
                word = str(payload.get("word") or "").strip()
                translation = str(payload.get("translation") or "").strip()
                context = str(payload.get("context") or "").strip()
                saved_at = payload.get("savedAt")
                if not word or not translation:
                    self._json_response(400, {"error": "Нужны word и translation"})
                    return
                item = vocab_add(word, translation, context, saved_at=saved_at)
                self._json_response(200, {"item": item})
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        if parsed.path == "/api/vocab/import":
            try:
                payload = self._read_json_body()
                items = payload.get("items") or []
                if not isinstance(items, list):
                    self._json_response(400, {"error": "items должен быть массивом"})
                    return
                imported = vocab_import_many(items)
                self._json_response(200, {"imported": imported, "items": vocab_list()})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        if parsed.path == "/api/explain":
            try:
                payload = self._read_json_body()
                word = str(payload.get("word") or "").strip()
                sentence = str(payload.get("sentence") or "").strip()
                question = str(payload.get("question") or "").strip()
                translation = str(payload.get("translation") or "").strip()
                if not word:
                    self._json_response(400, {"error": "Нужен word"})
                    return
                answer = ollama_explain(
                    word=word,
                    sentence=sentence,
                    question=question,
                    translation=translation,
                )
                self._json_response(
                    200,
                    {
                        "answer": answer,
                        "provider": "ollama",
                        "model": OLLAMA_MODEL,
                    },
                )
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(
                    502,
                    {"error": f"Ollama недоступна: {exc.reason}"},
                )
            except RuntimeError as exc:
                self._json_response(502, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        if parsed.path == "/api/ai-warm":
            try:
                result = ollama_warm()
                code = 200 if result.get("ok") else 503
                self._json_response(code, result)
            except urllib.error.URLError as exc:
                self._json_response(
                    502,
                    {
                        "ok": False,
                        "loaded": False,
                        "model": OLLAMA_MODEL,
                        "error": f"Ollama недоступна: {exc.reason}",
                    },
                )
            except RuntimeError as exc:
                self._json_response(
                    502,
                    {
                        "ok": False,
                        "loaded": False,
                        "model": OLLAMA_MODEL,
                        "error": str(exc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json_response(
                    500,
                    {
                        "ok": False,
                        "loaded": False,
                        "model": OLLAMA_MODEL,
                        "error": str(exc),
                    },
                )
            return
        self._json_response(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/vocab":
            params = parse_qs(parsed.query)
            try:
                if "id" in params:
                    vid = int((params.get("id") or ["0"])[0])
                    ok = vocab_delete(vid)
                    if not ok:
                        self._json_response(404, {"error": "Не найдено"})
                        return
                    self._json_response(200, {"ok": True})
                    return
                # без id — очистить весь словарь
                vocab_clear()
                self._json_response(200, {"ok": True})
            except ValueError:
                self._json_response(400, {"error": "Некорректный id"})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
        self._json_response(404, {"error": "Not found"})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ValueError("Слишком большое тело запроса")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект")
        return data

    def _text_response(self, code: int, text: str, content_type: str):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    host = os.environ.get("SUBLEARN_HOST", "127.0.0.1")
    port = int(os.environ.get("SUBLEARN_PORT", "8765"))
    init_vocab_db()
    server = ThreadingHTTPServer((host, port), SubLearnHandler)
    print(f"SubLearn: http://127.0.0.1:{port}")
    print(
        f"Translate: default={TRANSLATE_DEFAULT_ENGINE} "
        f"google={'on' if GOOGLE_TRANSLATE_ENABLED else 'off'} "
        f"| AI Ollama {OLLAMA_URL} model={OLLAMA_MODEL}"
    )
    print(f"Vocab DB: {DB_PATH}")
    print("Остановка: Ctrl+C")
    server.serve_forever()


if __name__ == "__main__":
    main()
