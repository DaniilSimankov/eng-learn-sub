#!/usr/bin/env python3
"""Локальный сервер SubLearn: статика + API для разбора страниц с плеером."""

from typing import Optional, Tuple
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

IFRAME_RE = re.compile(
    r'<iframe[^>]*class="[^"]*newdeaf-video[^"]*"[^>]*(?:src|data-src)=["\']([^"\']+)["\']',
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
    return ips


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
        "Разрешены только ссылки NewDeaf (*.newdeaf.co) или embed-плееры из белого списка"
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
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def fetch_binary(url: str, timeout: int = 30) -> Tuple[bytes, str]:
    validate_media_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type") or "application/octet-stream"
        return data, ctype


def embed_is_available(url: str) -> bool:
    try:
        validate_embed_url(url)
    except SecurityError:
        return False
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4, context=ctx) as resp:
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
    urls = IFRAME_RE.findall(page)
    seen = set()
    ordered = []
    for url in urls:
        url = html.unescape(url.strip())
        if url and url not in seen:
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

    ranked = sorted(cc_list, key=score, reverse=True)
    best = ranked[0]
    if score(best) < 60:
        return None

    for item in ranked:
        if score(item) < 60:
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
            "На странице не найден плеер. Вставьте ссылку на серию NewDeaf "
            "или прямую ссылку iframe из «Плеер 1/2/3»."
        )

    # Предпочитаем ylitron: id берём с NewDeaf, дальше ходим только туда
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
    path = ROOT / "ad-skip.js"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


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


OLLAMA_URL = os.environ.get("SUBLEARN_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# 3B хватает для коротких EN→RU переводов; 7B в Docker на Mac (без Metal) очень медленный
OLLAMA_MODEL = os.environ.get("SUBLEARN_OLLAMA_MODEL", "llama3.2:3b")


def _ollama_request(path: str, payload: Optional[dict] = None, timeout: int = 60):
    url = f"{OLLAMA_URL}{path}"
    data = None
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_status() -> dict:
    try:
        tags = _ollama_request("/api/tags", timeout=5)
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "ready": False,
            "model": OLLAMA_MODEL,
            "error": f"Ollama недоступна: {exc.reason}. Запустите ./start.sh",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "ready": False,
            "model": OLLAMA_MODEL,
            "error": str(exc),
        }

    names = []
    for item in tags.get("models") or []:
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(name)
    has_model = any(
        name == OLLAMA_MODEL
        or name.startswith(f"{OLLAMA_MODEL}-")
        or name.startswith(f"{OLLAMA_MODEL}:")
        for name in names
    ) or OLLAMA_MODEL in names

    return {
        "ok": True,
        "ready": has_model,
        "model": OLLAMA_MODEL,
        "models": names,
        "error": None if has_model else f"Модель {OLLAMA_MODEL} ещё не скачана (первый запуск контейнера)",
    }


def ollama_translate(text: str, *, word: Optional[str] = None, sentence: Optional[str] = None) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) > 800:
        raise ValueError("Слишком длинный текст (макс. 800 символов)")

    if word:
        target = word.strip()
        ctx = (sentence or cleaned).strip()
        system = (
            "You are an English learning assistant. Reply ONLY in Russian (Cyrillic). "
            "Never use Chinese, Japanese, Korean, or other non-Russian scripts. "
            "Format strictly:\n"
            "1) First line: short translation of the Phrase in context.\n"
            "2) Optional second line starting with 'Примечание:' — one short clarifying note.\n"
            "Use neighboring lines in Context when the Phrase is incomplete. "
            "No quotes, no preamble, no markdown."
        )
        user = f"Context: {ctx}\nPhrase: {target}"
        num_predict = 100
    else:
        system = (
            "You translate English subtitles to natural Russian. "
            "Reply with ONLY the Russian translation. "
            "Cyrillic only — no Chinese/Japanese/Korean, no quotes, no notes."
        )
        user = cleaned
        num_predict = 60

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.1,
            "num_predict": num_predict,
            "num_ctx": 512,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        data = _ollama_request("/api/chat", payload, timeout=90)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:200]}") from exc

    msg = (data.get("message") or {}).get("content") or ""
    result = msg.strip()
    if not result:
        raise RuntimeError("Пустой ответ модели")
    return result


class SubLearnHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

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
        if parsed.path == "/api/translate":
            params = parse_qs(parsed.query)
            text = (params.get("text") or [""])[0].strip()
            word = (params.get("word") or [""])[0].strip() or None
            sentence = (params.get("sentence") or [""])[0].strip() or None
            if not text and not word:
                self._json_response(400, {"error": "Параметр text или word обязателен"})
                return
            try:
                translation = ollama_translate(text or word or "", word=word, sentence=sentence)
                self._json_response(
                    200,
                    {
                        "translation": translation,
                        "provider": "ollama",
                        "model": OLLAMA_MODEL,
                    },
                )
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(
                    502,
                    {
                        "error": (
                            f"Ollama недоступна: {exc.reason}. "
                            "Запустите ./start.sh (Docker)"
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
    server = ThreadingHTTPServer((host, port), SubLearnHandler)
    print(f"SubLearn: http://127.0.0.1:{port}")
    print(f"AI: Ollama {OLLAMA_URL} model={OLLAMA_MODEL}")
    print("Остановка: Ctrl+C")
    server.serve_forever()


if __name__ == "__main__":
    main()
