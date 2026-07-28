#!/usr/bin/env python3
"""Локальный сервер SubLearn: статика + API для разбора страниц с плеером."""

from datetime import date, datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
import html
import http.client
import http.cookiejar
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse
from backend.data.vocab_repo import (
    DB_PATH,
    init_vocab_db,
    vocab_add,
    vocab_clear,
    vocab_delete,
    vocab_import_many,
    vocab_list,
)
from backend.http.io import json_response, read_json_body, text_response

ROOT = Path(__file__).resolve().parent
_dns_lock = threading.Lock()
_translate_cache_lock = threading.Lock()
_ollama_lock = threading.Lock()
_dns_cache: dict[str, tuple[float, list[str]]] = {}
_DNS_TTL_SEC = 600
_SSL_CONTEXT = ssl.create_default_context()
_ad_skip_script: Optional[str] = None
_TRANSLATE_CACHE_MAX = 512
_translate_cache: OrderedDict[str, str] = OrderedDict()
_source_auth_lock = threading.Lock()
_fanseries_cookie_jar = http.cookiejar.CookieJar()
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

IFRAME_TAG_RE = re.compile(r"<iframe\b[^>]*>", re.IGNORECASE)
IFRAME_SRC_RE = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
IFRAME_DATA_SRC_RE = re.compile(r"""data-src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
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
LOMONT_CONFIG_RE = re.compile(r"""data-config=(['"])(.*?)\1""", re.IGNORECASE | re.DOTALL)
LOMONT_INPUT_DATA_RE = re.compile(
    r"""<div[^>]+id=(['"])inputData\1[^>]*>(.*?)</div>""",
    re.IGNORECASE | re.DOTALL,
)
LOMONT_SUBTITLE_ATTR_RE = re.compile(
    r"""data-([a-z]{2})_subtitle=(['"])(.*?)\2""",
    re.IGNORECASE,
)
EMBED_HOSTS = (
    "cdnlbox.club",
    "ylitron.pro",
    "lomont.site",
    "gencit.info",
    "ortified.ws",
    "vak345.com",
    "interkh.com",
    "zombie-film.com",
)
ALLOWED_PAGE_SUFFIXES = (
    ".newdeaf.co",
    ".1fanserials.org",
    ".1fanserials.online",
    ".1fanserials.com",
    ".fanserial.me",
)
NEWDEAF_TZ = ZoneInfo(os.environ.get("SUBLEARN_NEWDEAF_TZ", "Europe/Moscow"))
NEWDEAF_DNS_MODE = os.environ.get("SUBLEARN_NEWDEAF_DNS", "cloudflare").strip().lower()
DOH_GOOGLE_URL = "https://dns.google/resolve"
DOH_CLOUDFLARE_URL = "https://cloudflare-dns.com/dns-query"
NEWDEAF_MONTHS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)
FANSERIES_MIRROR_HOSTS = tuple(
    host
    for host in (
        item.strip().lower().rstrip(".")
        for item in os.environ.get(
            "SUBLEARN_FANSERIES_MIRRORS",
            "1fanserials.org,1fanserials.online,1fanserials.com,fanserial.me",
        ).split(",")
    )
    if host
)
NEWDEAF_CATEGORY_FROM_PATH = {
    "serial": "Сериал",
    "film": "Фильм",
    "multfilm": "Мультфильм",
    "anime": "Аниме",
}
SEARCH_CARD_RE = re.compile(
    r'<article class="card d-flex">(.*?)</article>',
    re.IGNORECASE | re.DOTALL,
)
SEARCH_TITLE_LINK_RE = re.compile(
    r'<h2 class="card__title">\s*<a href="([^"]+)">(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
SEARCH_TYPE_RE = re.compile(r"<span>Тип:</span>\s*([^<\n]+)", re.IGNORECASE)
SEARCH_POSTER_RE = re.compile(r'data-src="([^"]+)"', re.IGNORECASE)
SEARCH_TOTAL_RE = re.compile(r"найдено:\s*(\d+)", re.IGNORECASE)
FANSERIES_TYPE_FROM_PATH = {
    "series": "serial",
    "films": "film",
    "anime": "anime",
}
RELATED_SECTION_RE = re.compile(
    r'<section[^>]*class="[^"]*\bpmovie__related\b[^"]*"[^>]*>(.*?)</section>',
    re.IGNORECASE | re.DOTALL,
)
RELATED_LINK_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
RELATED_TITLE_RE = re.compile(
    r"<h3[^>]*>(.*?)</h3>|<div[^>]*class=\"line-clamp\"[^>]*>(.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
NEWDEAF_SERIAL_LIST_RE = re.compile(
    r'<table[^>]*class="[^"]*\bnewdeaf-serial_list\b[^"]*"[^>]*>(.*?)</table>',
    re.IGNORECASE | re.DOTALL,
)
NEWDEAF_SERIAL_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
NEWDEAF_SEASON_CELL_RE = re.compile(r"<th[^>]*>\s*(\d+)\s*сезон\s*</th>", re.IGNORECASE)
NEWDEAF_ROW_BUTTON_URL_RE = re.compile(
    r"location\.href\s*=\s*['\"](https?://[^'\"]+|/[^'\"]+)['\"]",
    re.IGNORECASE,
)
NEWDEAF_SEASON_EPISODE_COUNT_RE = re.compile(
    r"(\d+)\s*сезон\s+и\s+(\d+)\s*из\s*(\d+)\s*сери",
    re.IGNORECASE,
)
CDN_DATA_ITEM_RE = re.compile(
    r"window\.cdnData\[\d+\]\s*=\s*(\{.*?\});",
    re.IGNORECASE | re.DOTALL,
)
MEDIA_CDN_SUFFIXES = (
    ".ceramet.net",
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
CORS_ORIGIN = os.environ.get("SUBLEARN_CORS_ORIGIN", "").strip()
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
        "img-src 'self' data: blob: https:; "
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


def _newdeaf_dns_mode() -> str:
    mode = (NEWDEAF_DNS_MODE or "cloudflare").lower()
    if mode in ("off", "system", "direct", ""):
        return "system"
    if mode in ("google", "8.8.8.8", "8.8.4.4", "google-dns"):
        return "google"
    if mode in ("cloudflare", "1.1.1.1", "1.0.0.1"):
        return "cloudflare"
    return "cloudflare"


def _is_newdeaf_host(host: str) -> bool:
    host = _normalize_host(host)
    return host == "newdeaf.co" or host.endswith(".newdeaf.co")


def _resolve_host_via_doh(host: str, provider: str) -> list[str]:
    host = _normalize_host(host)
    query = urlencode({"name": host, "type": "A"})
    doh_url = f"{DOH_GOOGLE_URL}?{query}" if provider == "google" else f"{DOH_CLOUDFLARE_URL}?{query}"
    _assert_public_target(doh_url)
    req = urllib.request.Request(doh_url, headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=6, context=_SSL_CONTEXT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    ips: list[str] = []
    for item in payload.get("Answer") or []:
        if item.get("type") not in (1, "A"):
            continue
        ip_str = (item.get("data") or "").strip()
        if not ip_str:
            continue
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.version != 4 or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            continue
        if ip_str not in ips:
            ips.append(ip_str)
    if not ips:
        raise SecurityError(f"DoH: нет публичных A-записей для {host}")
    return ips


def _resolve_public_ips(host: str) -> list[str]:
    now = time.monotonic()
    with _dns_lock:
        cached = _dns_cache.get(host)
        if cached and now - cached[0] < _DNS_TTL_SEC:
            return list(cached[1])

    dns_mode = _newdeaf_dns_mode()
    if dns_mode != "system" and _is_newdeaf_host(host):
        try:
            ips = _resolve_host_via_doh(host, dns_mode)
            with _dns_lock:
                _dns_cache[host] = (now, ips)
            return list(ips)
        except (urllib.error.URLError, json.JSONDecodeError, SecurityError, OSError):
            pass

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
        "Разрешены только страницы с поддерживаемым плеером или embed из белого списка"
    )


def _assert_newdeaf_target(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError("Разрешены только http и https")
    if parsed.username or parsed.password:
        raise SecurityError("URL с логином/паролем запрещены")
    host = _normalize_host(parsed.hostname or "")
    if not host or not (host == "newdeaf.co" or host.endswith(".newdeaf.co")):
        raise SecurityError("URL не относится к поддерживаемому источнику")
    if not _host_matches_day_month_mirror(host):
        raise SecurityError("Недопустимый хост зеркала источника")
    return url


def _host_matches_day_month_mirror(host: str) -> bool:
    if host == "newdeaf.co":
        return True
    if not host.endswith(".newdeaf.co"):
        return False
    prefix = host[: -len(".newdeaf.co")]
    return bool(re.fullmatch(r"\d{1,2}(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", prefix))


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


def validate_image_url(url: str) -> str:
    url = url.strip()
    _assert_public_target(url)
    host = _normalize_host(urlparse(url).hostname or "")
    if (
        _host_matches_embed(host)
        or _host_matches_suffix(host, MEDIA_CDN_SUFFIXES)
        or _host_matches_suffix(host, ALLOWED_PAGE_SUFFIXES)
    ):
        return url
    raise SecurityError("URL изображения не из доверенного списка")


def _newdeaf_today() -> date:
    return datetime.now(NEWDEAF_TZ).date()


def _newdeaf_mirror_host(day: date) -> str:
    return f"{day.day}{NEWDEAF_MONTHS[day.month - 1]}.newdeaf.co"


def current_newdeaf_base(day: Optional[date] = None) -> str:
    day = day or _newdeaf_today()
    return f"https://{_newdeaf_mirror_host(day)}"


def is_newdeaf_url(url: str) -> bool:
    host = _normalize_host(urlparse(url).hostname or "")
    return host == "newdeaf.co" or host.endswith(".newdeaf.co")


def is_fanseries_url(url: str) -> bool:
    host = _normalize_host(urlparse(url).hostname or "")
    if not host:
        return False
    for mirror_host in FANSERIES_MIRROR_HOSTS:
        if host == mirror_host or host.endswith(f".{mirror_host}"):
            return True
    return False


def rewrite_newdeaf_mirror(url: str, day: Optional[date] = None) -> str:
    if not is_newdeaf_url(url):
        return url.strip()
    day = day or _newdeaf_today()
    parsed = urlparse(url.strip())
    host = _newdeaf_mirror_host(day)
    return urlunparse(
        (parsed.scheme or "https", host, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def normalize_newdeaf_href(url: str) -> str:
    url = html.unescape((url or "").strip())
    if is_newdeaf_url(url):
        return rewrite_newdeaf_mirror(url)
    return url


def _newdeaf_mirror_candidates() -> list[date]:
    today = _newdeaf_today()
    return [today, today - timedelta(days=1), today + timedelta(days=1)]


def _fanseries_mirror_candidates(url: str) -> list[str]:
    parsed = urlparse(url.strip())
    current_host = _normalize_host(parsed.hostname or "")
    candidates: list[str] = []
    ordered_hosts: list[str] = []
    if current_host:
        ordered_hosts.append(current_host)
    for host in FANSERIES_MIRROR_HOSTS:
        if host not in ordered_hosts:
            ordered_hosts.append(host)
    for host in ordered_hosts:
        candidate = urlunparse(
            (parsed.scheme or "https", host, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def current_fanseries_base() -> str:
    host = FANSERIES_MIRROR_HOSTS[0] if FANSERIES_MIRROR_HOSTS else "1fanserials.org"
    return f"https://{host}"


def fetch_url(
    url: str,
    timeout: int = 20,
    opener: Optional[urllib.request.OpenerDirector] = None,
) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if opener is not None:
        with opener.open(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _fanseries_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
        urllib.request.HTTPCookieProcessor(_fanseries_cookie_jar),
    )


def clear_fanseries_auth_session() -> None:
    with _source_auth_lock:
        _fanseries_cookie_jar.clear()


def login_fanseries_source(login: str, password: str, verify_url: str = "") -> dict:
    login = (login or "").strip()
    password = (password or "").strip()
    if not login or not password:
        raise ValueError("Нужны логин и пароль")

    base = current_fanseries_base().rstrip("/")
    login_page_url = f"{base}/index.php?do=login"
    with _source_auth_lock:
        opener = _fanseries_opener()
        login_page = fetch_url(login_page_url, timeout=20, opener=opener)

        form_match = re.search(
            r"<form[^>]*action=\"([^\"]*)\"[^>]*class=\"[^\"]*form-login[^\"]*\"[^>]*>(.*?)</form>",
            login_page,
            re.IGNORECASE | re.DOTALL,
        )
        if not form_match:
            raise ValueError("Не удалось найти форму входа на источнике")

        action = html.unescape((form_match.group(1) or "").strip()) or "/"
        form_html = form_match.group(2) or ""
        post_url = urljoin(base + "/", action.lstrip("/"))

        payload_data: dict[str, str] = {}
        for name, value in re.findall(
            r"<input[^>]+name=\"([^\"]+)\"[^>]*value=\"([^\"]*)\"[^>]*>",
            form_html,
            re.IGNORECASE | re.DOTALL,
        ):
            payload_data[name] = html.unescape(value or "")

        login_hash_match = re.search(
            r"var\s+dle_login_hash\s*=\s*'([^']+)'",
            login_page,
            re.IGNORECASE,
        )
        if login_hash_match and "login_hash" not in payload_data:
            payload_data["login_hash"] = login_hash_match.group(1)

        payload_data["login_name"] = login
        payload_data["login_password"] = password
        payload_data.setdefault("login", "submit")
        payload_data.setdefault("do", "login")

        payload = urlencode(payload_data).encode("utf-8")
        req = urllib.request.Request(
            post_url,
            data=payload,
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": base,
                "Referer": login_page_url,
            },
        )
        with opener.open(req, timeout=20):
            pass

    verify_target = (verify_url or "").strip()
    if verify_target:
        verify_target = validate_page_url(verify_target)
        if not is_fanseries_url(verify_target):
            raise ValueError("Для проверки нужен URL поддерживаемого источника")
    else:
        verify_target = f"{base}/69-euphoria.html"

    auth_required = True
    try:
        page = fetch_fanseries_page(verify_target, timeout=20)
        episode_candidates = extract_episode_page_candidates(page, verify_target, limit=5)
        path = (urlparse(verify_target).path or "").lower()
        is_episode_url = bool(
            re.search(r"/\d+-season/\d+-episode\.html$", path)
            or re.search(r"/\d+-sezon/\d+-seriya\.html$", path)
        )

        # Для карточки сериала считаем валидацию успешной только по страницам эпизодов.
        if not is_episode_url and episode_candidates:
            check_targets = episode_candidates
        else:
            check_targets = [verify_target]
            for episode_url in episode_candidates:
                if episode_url not in check_targets:
                    check_targets.append(episode_url)

        for target in check_targets:
            try:
                target_page = page if target == verify_target else fetch_fanseries_page(target, timeout=20)
            except (urllib.error.URLError, SecurityError):
                continue
            if not page_requires_auth(target_page):
                auth_required = False
                break
    except (urllib.error.URLError, SecurityError):
        auth_required = True

    return {
        "ok": not auth_required,
        "verified": not auth_required,
        "message": (
            "Авторизация выполнена, доступ к защищенной странице подтвержден."
            if not auth_required
            else "Авторизация не подтверждена. Проверьте логин/пароль или попробуйте другой URL."
        ),
    }


def _https_connect_via_ip(conn: http.client.HTTPSConnection, ip: str, host: str) -> None:
    conn.sock = socket.create_connection((ip, conn.port or 443), conn.timeout)
    conn.sock = conn._context.wrap_socket(conn.sock, server_hostname=host)


def _decode_http_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    if content_type:
        match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    return body.decode(charset, errors="replace")


def fetch_url_via_public_dns(url: str, provider: str, timeout: int = 20) -> str:
    url = _assert_newdeaf_target(url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https":
        raise SecurityError("Источник доступен только по https")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    last_error: Optional[Exception] = None
    for ip in _resolve_host_via_doh(host, provider):
        conn: Optional[http.client.HTTPSConnection] = None
        try:
            conn = http.client.HTTPSConnection(host, timeout=timeout, context=_SSL_CONTEXT)
            ip_addr = ip
            conn.connect = lambda c=conn, addr=ip_addr, h=host: _https_connect_via_ip(c, addr, h)
            conn.request(
                "GET",
                path,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Host": host,
                },
            )
            resp = conn.getresponse()
            body = resp.read()
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, body)
            return _decode_http_body(body, resp.getheader("Content-Type", ""))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            if conn is not None:
                conn.close()
    if last_error:
        raise last_error
    raise urllib.error.URLError("Не удалось загрузить страницу источника через публичный DNS")


def _fetch_newdeaf_candidate(candidate_url: str, timeout: int = 20) -> str:
    _assert_newdeaf_target(candidate_url)
    dns_mode = _newdeaf_dns_mode()
    if dns_mode != "system":
        try:
            return fetch_url_via_public_dns(candidate_url, dns_mode, timeout=timeout)
        except (urllib.error.URLError, SecurityError, OSError, http.client.HTTPException):
            pass
    return fetch_url(validate_page_url(candidate_url), timeout=timeout)


def fetch_newdeaf_page(url: str, timeout: int = 20) -> str:
    if not is_newdeaf_url(url):
        return fetch_url(url, timeout=timeout)

    last_error: Optional[Exception] = None
    for day in _newdeaf_mirror_candidates():
        candidate = rewrite_newdeaf_mirror(url, day)
        try:
            return _fetch_newdeaf_candidate(candidate, timeout=timeout)
        except (urllib.error.URLError, SecurityError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise urllib.error.URLError("Не удалось загрузить страницу источника")


def fetch_fanseries_page(url: str, timeout: int = 20) -> str:
    if not is_fanseries_url(url):
        return fetch_url(url, timeout=timeout)
    last_error: Optional[Exception] = None
    for candidate in _fanseries_mirror_candidates(url):
        try:
            validated = validate_page_url(candidate)
            with _source_auth_lock:
                opener = _fanseries_opener()
                return fetch_url(validated, timeout=timeout, opener=opener)
        except (urllib.error.URLError, SecurityError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise urllib.error.URLError("Не удалось загрузить страницу источника")


def _category_from_fanseries_url(url: str) -> Optional[str]:
    path = (urlparse(url).path or "").strip("/").lower()
    if not path:
        return None
    first = path.split("/", 1)[0]
    return FANSERIES_TYPE_FROM_PATH.get(first)


def _category_from_newdeaf_url(url: str) -> Optional[str]:
    path = urlparse(url).path.strip("/").lower()
    if not path:
        return None
    segment = path.split("/", 1)[0]
    return segment if segment in NEWDEAF_CATEGORY_FROM_PATH else None


def parse_search_results(page_html: str, mirror_base: str) -> Tuple[int, list]:
    total_match = SEARCH_TOTAL_RE.search(page_html)
    total = int(total_match.group(1)) if total_match else 0
    results = []
    seen_urls = set()

    for block in SEARCH_CARD_RE.findall(page_html):
        title_match = SEARCH_TITLE_LINK_RE.search(block)
        if not title_match:
            continue
        href = html.unescape(title_match.group(1).strip())
        title = clean_text(title_match.group(2))
        if not href or not title:
            continue

        if href.startswith("/"):
            href = urljoin(mirror_base + "/", href.lstrip("/"))
        elif href.startswith("//"):
            href = f"https:{href}"
        href = normalize_newdeaf_href(href)

        if href in seen_urls:
            continue
        seen_urls.add(href)

        type_match = SEARCH_TYPE_RE.search(block)
        kind_label = clean_text(type_match.group(1)) if type_match else ""
        category = _category_from_newdeaf_url(href) or ""

        poster_match = SEARCH_POSTER_RE.search(block)
        poster = html.unescape(poster_match.group(1).strip()) if poster_match else None

        results.append(
            {
                "title": title,
                "url": href,
                "type": kind_label,
                "category": category,
                "poster": poster,
            }
        )

    return total, results


def extract_related_series(page_html: str, current_url: str) -> list[dict]:
    section_match = RELATED_SECTION_RE.search(page_html or "")
    if not section_match:
        return []
    section_html = section_match.group(1)
    current_norm = normalize_newdeaf_href(current_url or "")
    seen = {current_norm} if current_norm else set()
    items: list[dict] = []

    for href, inner_html in RELATED_LINK_RE.findall(section_html):
        url = normalize_newdeaf_href(href)
        if url.startswith("/"):
            base = current_newdeaf_base()
            url = urljoin(base + "/", url.lstrip("/"))
            url = normalize_newdeaf_href(url)
        elif url.startswith("//"):
            url = normalize_newdeaf_href(f"https:{url}")
        if not url or url in seen:
            continue
        try:
            validate_page_url(url)
        except SecurityError:
            continue
        title_match = RELATED_TITLE_RE.search(inner_html or "")
        raw_title = (title_match.group(1) or title_match.group(2) or "").strip() if title_match else ""
        title = clean_text(raw_title) if raw_title else ""
        season_match = re.search(r"-(\d+)-(?:sezon|season)\b", (urlparse(url).path or "").lower())
        if season_match and "сезон" not in title.lower():
            title = f"{title} ({season_match.group(1)} сезон)"
        if not title:
            continue
        seen.add(url)
        items.append({"title": title, "url": url})

    return items


def _series_slug_key(url: str) -> str:
    path = (urlparse(url).path or "").strip("/").lower()
    match = re.search(r"/?serial/\d+-([a-z0-9-]+?)-(?:\d+-(?:sezon|season).*)$", path)
    if not match:
        match = re.search(r"/?serial/\d+-([a-z0-9-]+?)(?:-(?:\d+-(?:sezon|season).*)?)?$", path)
    return (match.group(1) if match else "").strip("-")


def extract_same_series_options(page_html: str, current_url: str, page_title: str) -> list[dict]:
    slug_key = _series_slug_key(current_url)
    if not slug_key:
        return []
    seen = set()
    items: list[dict] = []
    for raw in HREF_RE.findall(page_html or ""):
        href = normalize_newdeaf_href(raw)
        if href.startswith("/"):
            href = normalize_newdeaf_href(urljoin(current_newdeaf_base() + "/", href.lstrip("/")))
        elif href.startswith("//"):
            href = normalize_newdeaf_href(f"https:{href}")
        if not href or href in seen:
            continue
        if f"-{slug_key}-" not in (urlparse(href).path or "").lower():
            continue
        try:
            validate_page_url(href)
        except SecurityError:
            continue
        season_match = re.search(r"-(\d+)-(?:sezon|season)\b", (urlparse(href).path or "").lower())
        if href == current_url:
            title = page_title or "Текущая серия"
        elif season_match:
            title = f"{page_title} ({season_match.group(1)} сезон)"
        else:
            title = page_title
        items.append({"title": title, "url": href})
        seen.add(href)

    return items


def extract_newdeaf_serial_list_options(page_html: str, current_url: str, page_title: str) -> list[dict]:
    table_match = NEWDEAF_SERIAL_LIST_RE.search(page_html or "")
    if not table_match:
        return []
    table_html = table_match.group(1)
    seen = set()
    items: list[dict] = []
    for row_html in NEWDEAF_SERIAL_ROW_RE.findall(table_html):
        url_match = NEWDEAF_ROW_BUTTON_URL_RE.search(row_html)
        if not url_match:
            continue
        raw_url = html.unescape((url_match.group(1) or "").strip())
        if raw_url.startswith("/"):
            raw_url = urljoin(current_newdeaf_base() + "/", raw_url.lstrip("/"))
        elif raw_url.startswith("//"):
            raw_url = f"https:{raw_url}"
        url = normalize_newdeaf_href(raw_url)
        if not url or url in seen:
            continue
        try:
            validate_page_url(url)
        except SecurityError:
            continue
        season_match = NEWDEAF_SEASON_CELL_RE.search(row_html)
        if season_match:
            title = f"{page_title} ({season_match.group(1)} сезон)"
        else:
            title = page_title or url
        seen.add(url)
        items.append({"title": title, "url": url})
    return items


def extract_newdeaf_episode_options(page_html: str, iframe_url: str) -> list[dict]:
    if not iframe_url:
        return []
    match = NEWDEAF_SEASON_EPISODE_COUNT_RE.search(page_html or "")
    if not match:
        return []
    try:
        season = int(match.group(1))
        current_episode = int(match.group(2))
        total_episodes = int(match.group(3))
    except (TypeError, ValueError):
        return []
    if season < 1 or total_episodes < 1:
        return []
    total = max(current_episode, total_episodes)
    total = min(total, 300)
    parsed = urlparse(iframe_url)
    params = parse_qs(parsed.query)
    options: list[dict] = []
    for ep in range(1, total + 1):
        query = dict(params)
        query["season"] = [str(season)]
        query["episode"] = [str(ep)]
        new_query = urlencode(query, doseq=True)
        option_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        options.append(
            {
                "title": f"{season} сезон · {ep} серия",
                "url": option_url,
            }
        )
    return options


def search_newdeaf(
    query: str,
    content_type: str = "",
    limit: int = 15,
) -> dict:
    query = (query or "").strip()
    if len(query) < 2:
        raise ValueError("Запрос должен быть не короче 2 символов")
    if len(query) > 30:
        query = query[:30]

    limit = max(1, min(int(limit), 30))
    content_type = (content_type or "").strip().lower()
    if content_type and content_type not in NEWDEAF_CATEGORY_FROM_PATH:
        raise ValueError("type должен быть serial, film, multfilm или anime")

    search_query = urlencode(
        {"do": "search", "subaction": "search", "story": query},
        quote_via=quote,
    )
    last_error: Optional[Exception] = None
    for day in _newdeaf_mirror_candidates():
        mirror_base = current_newdeaf_base(day)
        search_url = f"{mirror_base}/?{search_query}"
        try:
            page_html = _fetch_newdeaf_candidate(search_url)
            break
        except (urllib.error.URLError, SecurityError) as exc:
            last_error = exc
            page_html = ""
    else:
        if last_error:
            raise last_error
        raise urllib.error.URLError("Не удалось выполнить поиск по каталогу")

    total, results = parse_search_results(page_html, mirror_base)
    if content_type:
        results = [item for item in results if item.get("category") == content_type]

    return {
        "query": query,
        "mirror": mirror_base,
        "dns": _newdeaf_dns_mode(),
        "total": total,
        "results": results[:limit],
    }


def search_fanseries(
    query: str,
    content_type: str = "",
    limit: int = 15,
) -> dict:
    query = (query or "").strip()
    if len(query) < 2:
        raise ValueError("Запрос должен быть не короче 2 символов")
    if len(query) > 30:
        query = query[:30]
    limit = max(1, min(int(limit), 30))
    content_type = (content_type or "").strip().lower()
    if content_type and content_type not in NEWDEAF_CATEGORY_FROM_PATH:
        raise ValueError("type должен быть serial, film, multfilm или anime")

    def _normalize_text(value: str) -> str:
        value = clean_text(value or "").lower()
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    last_error: Optional[Exception] = None
    mirror_base = ""
    page_html = ""
    base_template = f"{current_fanseries_base()}/"
    for candidate_base in _fanseries_mirror_candidates(base_template):
        mirror_base = f"{urlparse(candidate_base).scheme}://{urlparse(candidate_base).netloc}"
        try:
            page_html = fetch_fanseries_page(candidate_base, timeout=15)
            if "newscatalog-main" in page_html and "newscatalog-list" in page_html:
                break
            raise ValueError("Каталог не найден в разметке источника")
        except (urllib.error.URLError, SecurityError, ValueError) as exc:
            last_error = exc
            page_html = ""
            continue
    else:
        if last_error:
            raise urllib.error.URLError(str(last_error))
        raise urllib.error.URLError("Не удалось выполнить поиск по каталогу")

    query_norm = _normalize_text(query)
    results: list[dict] = []
    seen = set()
    item_re = re.compile(
        r"<li[^>]*class=\"literal__item[^\"]*\"[^>]*>(.*?)</li>",
        re.IGNORECASE | re.DOTALL,
    )
    link_re = re.compile(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    poster_re = re.compile(r"<img[^>]+src=\"([^\"]+)\"", re.IGNORECASE)

    for block in item_re.findall(page_html):
        link_match = link_re.search(block)
        if not link_match:
            continue

        raw_url = html.unescape(link_match.group(1)).strip()
        title = clean_text(link_match.group(2) or "").strip()
        if not raw_url or not title:
            continue

        title_norm = _normalize_text(title)
        if query_norm and query_norm not in title_norm:
            continue

        if raw_url.startswith("//"):
            raw_url = f"https:{raw_url}"
        elif raw_url.startswith("/"):
            raw_url = urljoin(mirror_base + "/", raw_url.lstrip("/"))
        try:
            url = validate_page_url(raw_url)
        except SecurityError:
            continue
        if url in seen:
            continue
        seen.add(url)

        category = _category_from_fanseries_url(url) or ""
        if content_type and category and category != content_type:
            continue

        poster = ""
        poster_match = poster_re.search(block)
        if poster_match:
            poster = html.unescape(poster_match.group(1) or "").strip()
            if poster.startswith("//"):
                poster = f"https:{poster}"
            elif poster.startswith("/"):
                poster = urljoin(mirror_base + "/", poster.lstrip("/"))
            elif not poster.startswith("http"):
                poster = urljoin(mirror_base + "/", poster)

        results.append(
            {
                "title": title,
                "url": url,
                "category": category,
                "poster": poster,
                "source": "catalog_b",
            }
        )

    return {
        "query": query,
        "mirror": mirror_base,
        "total": len(results),
        "results": results[:limit],
    }


def search_catalog(query: str, content_type: str = "", limit: int = 15) -> dict:
    query = (query or "").strip()
    limit = max(1, min(int(limit), 30))
    sources = {}
    combined = []
    seen_urls = set()
    errors = []

    try:
        a = search_newdeaf(query, content_type, limit)
        sources["catalog_a"] = {"ok": True, "mirror": a.get("mirror", ""), "total": a.get("total", 0)}
        for item in a.get("results", []):
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            item = dict(item)
            item["source"] = "catalog_a"
            combined.append(item)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
        sources["catalog_a"] = {"ok": False, "error": str(exc)}

    try:
        b = search_fanseries(query, content_type, limit)
        sources["catalog_b"] = {"ok": True, "mirror": b.get("mirror", ""), "total": b.get("total", 0)}
        for item in b.get("results", []):
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            combined.append(item)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
        sources["catalog_b"] = {"ok": False, "error": str(exc)}

    if not combined and errors:
        raise urllib.error.URLError("Оба каталога недоступны")

    return {
        "query": query,
        "total": len(combined),
        "results": combined[:limit],
        "sources": sources,
    }


def fetch_binary(url: str, timeout: int = 30) -> Tuple[bytes, str]:
    validate_media_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type") or "application/octet-stream"
        return data, ctype


def fetch_image_binary(url: str, timeout: int = 20) -> Tuple[bytes, str]:
    url = validate_image_url(url)
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
    """Достаёт iframe src/data-src; предпочитает src, затем data-src."""
    seen = set()
    ordered = []
    for tag in IFRAME_TAG_RE.findall(page):
        candidates = []
        src_match = IFRAME_SRC_RE.search(tag)
        data_src_match = IFRAME_DATA_SRC_RE.search(tag)
        if src_match:
            candidates.append(src_match.group(1))
        if data_src_match:
            candidates.append(data_src_match.group(1))

        for raw_url in candidates:
            url = html.unescape((raw_url or "").strip())
            if not url or url in seen:
                continue
            host = _normalize_host(urlparse(url).hostname or "")
            if not host or not _host_matches_embed(host):
                continue
            seen.add(url)
            ordered.append(url)
            break
    return ordered


def merge_player_urls(iframe_urls: list[str], cdn_players: list[dict]) -> list[str]:
    merged_urls: list[str] = []
    seen_urls = set()
    # Сначала источники с субтитрами, затем остальные, затем iframe из HTML.
    for item in sorted(cdn_players or [], key=lambda p: (not p.get("isSubtitles"), p.get("label") or "")):
        u = item.get("url") or ""
        if u and u not in seen_urls:
            seen_urls.add(u)
            merged_urls.append(u)
    for u in iframe_urls or []:
        if u and u not in seen_urls:
            seen_urls.add(u)
            merged_urls.append(u)
    return merged_urls


def extract_episode_page_candidates(page: str, page_url: str, limit: int = 10) -> list[str]:
    candidates: list[str] = []
    seen = set()
    for raw in HREF_RE.findall(page or ""):
        href = html.unescape((raw or "").strip())
        if not href:
            continue
        if href.startswith("//"):
            href = f"https:{href}"
        elif href.startswith("/"):
            href = urljoin(page_url, href)
        elif not href.startswith("http"):
            href = urljoin(page_url, href)
        try:
            href = validate_page_url(href)
        except SecurityError:
            continue
        path = (urlparse(href).path or "").lower().rstrip("/")
        is_episode = re.search(r"/\d+-season/\d+-episode\.html$", path) or re.search(
            r"/\d+-sezon/\d+-seriya\.html$",
            path,
        )
        if not is_episode:
            continue
        if href in seen:
            continue
        seen.add(href)
        candidates.append(href)
        if len(candidates) >= max(1, limit):
            break
    return candidates


def page_requires_auth(page: str) -> bool:
    haystack = (page or "").lower()
    return (
        "требуется вход в систему" in haystack
        or "для доступа к видеоконтенту необходимо иметь учётную запись" in haystack
        or "для доступа к видеоконтенту необходимо иметь учетную запись" in haystack
    )


def extract_cdn_players(page: str, page_url: str) -> list[dict]:
    """Достаёт плееры из window.cdnData (если есть на странице)."""
    if not page:
        return []
    result: list[dict] = []
    seen = set()
    for match in CDN_DATA_ITEM_RE.finditer(page):
        raw = (match.group(1) or "").strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        player = html.unescape(str(item.get("player") or "")).strip()
        if not player:
            continue
        if player.startswith("//"):
            player = f"https:{player}"
        elif player.startswith("/"):
            player = urljoin(page_url, player)
        host = _normalize_host(urlparse(player).hostname or "")
        if not host or not _host_matches_embed(host):
            continue
        if player in seen:
            continue
        seen.add(player)
        name = clean_text(str(item.get("name") or "")).strip()
        is_subtitles = "субтит" in name.lower() or "subtitle" in name.lower()
        result.append(
            {
                "url": player,
                "label": name or "Источник",
                "isSubtitles": is_subtitles,
            }
        )
    return result


def parse_ylitron_ref(url: str) -> Optional[dict]:
    """Достаёт id сериала из embed-ссылки (/sie/463 или /tvb/1178445)."""
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


def parse_ylitron_episode_options(embed_html: str) -> list[dict]:
    match = re.search(r"window\.playerData\s*=\s*(\{.*?\});", embed_html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    request_full = ((data.get("config") or {}).get("request_full") or "").replace("\\/", "/")
    if not request_full:
        return []
    parsed = urlparse(request_full)
    base_path = parsed.path
    params = parse_qs(parsed.query)
    voice = (params.get("voice") or [""])[0]

    serial = (data.get("playlist") or {}).get("serial") or {}
    seasons = serial.get("list") or []
    options: list[dict] = []

    for season_idx, season_episodes in enumerate(seasons, start=1):
        if not isinstance(season_episodes, list):
            continue
        for ep in season_episodes:
            if not isinstance(ep, dict):
                continue
            ep_num = ep.get("num")
            if ep_num is None:
                continue
            ep_int = int(ep_num)
            spec = ep.get("spec_ep") if isinstance(ep.get("spec_ep"), dict) else None
            if ep_int > 0:
                label = f"{season_idx} сезон · {ep_int} серия"
            else:
                label = f"{season_idx} сезон · {spec.get('custom_name') or 'спецвыпуск'}"
            query = {"season": str(season_idx), "episode": str(ep_int)}
            if voice:
                query["voice"] = voice
            url = urlunparse(("https", "ylitron.pro", base_path, "", urlencode(query), ""))
            options.append({"title": label, "url": url})

    # Удаляем дубликаты ссылок, сохраняя порядок.
    uniq: list[dict] = []
    seen = set()
    for item in options:
        u = item.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(item)
    return uniq


def parse_ylitron_embed_meta(embed_html: str) -> dict:
    match = re.search(r"window\.playerData\s*=\s*(\{.*?\});", embed_html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    current = ((data.get("playlist") or {}).get("serial") or {}).get("current") or {}
    serial_name = (((data.get("playlist") or {}).get("current") or {}).get("serialName") or "").strip()
    season = current.get("season")
    episode = current.get("episode")
    title = serial_name
    if title and season and episode is not None:
        try:
            ep_num = int(episode)
            if ep_num > 0:
                title = f"{title} · {int(season)} сезон {ep_num} серия"
        except (TypeError, ValueError):
            pass
    return {
        "title": title,
        "season": season,
        "episode": episode,
    }


def parse_embed_assets(embed_html: str, iframe_url: str = "") -> dict:
    generic_player_data = parse_ylitron_assets(embed_html)
    if generic_player_data:
        return generic_player_data

    if "lomont.site" in (iframe_url or "").lower():
        lomont = parse_lomont_assets(embed_html, iframe_url)
        if lomont:
            return lomont

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


def _safe_media_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        validate_media_url(url)
        return url
    except SecurityError:
        return None


def _parse_lomont_data_config(embed_html: str) -> Optional[str]:
    match = LOMONT_CONFIG_RE.search(embed_html)
    if not match:
        return None
    raw = html.unescape(match.group(2) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _safe_media_url(data.get("hls") or "")


def _parse_lomont_subtitle_attrs(embed_html: str) -> list[dict]:
    tracks = []
    seen = set()
    labels = {"en": "Eng. subtitle", "ru": "Рус. subtitle"}
    for lang, _, raw_url in LOMONT_SUBTITLE_ATTR_RE.findall(embed_html):
        url = _safe_media_url(html.unescape((raw_url or "").strip()))
        if not url or url in seen:
            continue
        seen.add(url)
        lang = (lang or "").lower()
        tracks.append({"url": url, "name": labels.get(lang, f"{lang.upper()} subtitle")})
    return tracks


def _parse_lomont_input_data(embed_html: str, season: int, episode: int) -> list[dict]:
    match = LOMONT_INPUT_DATA_RE.search(embed_html)
    if not match:
        return []
    raw = html.unescape((match.group(2) or "").strip())
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    season_obj = data.get(str(season)) if isinstance(data, dict) else None
    episode_list = season_obj.get(str(episode)) if isinstance(season_obj, dict) else None
    if not isinstance(episode_list, list):
        return []

    tracks = []
    seen = set()
    for item in episode_list:
        if not isinstance(item, dict):
            continue
        voice_name = str(item.get("voice_name") or "")
        if int(item.get("voice_id") or 0) != 2 and "субтит" not in voice_name.lower():
            continue
        video_id = item.get("video_id")
        if not video_id:
            continue
        for lang, label in (("en", "Eng. subtitle"), ("ru", "Рус. subtitle")):
            url = _safe_media_url(f"https://lomont.site/player/subtitle/{lang}_{video_id}.vtt")
            if not url or url in seen:
                continue
            seen.add(url)
            tracks.append({"url": url, "name": label})
    return tracks


def parse_lomont_assets(embed_html: str, iframe_url: str = "") -> Optional[dict]:
    stream_url = _parse_lomont_data_config(embed_html) or find_stream_in_html(embed_html)
    stream_url = _safe_media_url(stream_url or "")
    if not stream_url:
        return None

    season, episode = parse_season_episode(iframe_url)
    tracks = _parse_lomont_subtitle_attrs(embed_html)
    fallback_tracks = _parse_lomont_input_data(embed_html, season, episode)
    seen = {track["url"] for track in tracks}
    for track in fallback_tracks:
        if track["url"] not in seen:
            seen.add(track["url"])
            tracks.append(track)

    if not tracks:
        tracks = [{"url": url, "name": "Subtitle"} for url in find_vtt_urls(embed_html) if _safe_media_url(url)]

    subtitle_url = None
    for track in tracks:
        if track["name"].lower().startswith("eng"):
            subtitle_url = track["url"]
            break
    if not subtitle_url and tracks:
        subtitle_url = tracks[0]["url"]

    return {
        "streamUrl": stream_url,
        "subtitleUrl": subtitle_url,
        "subtitleTracks": tracks,
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
    url = url.strip()
    is_newdeaf = is_newdeaf_url(url)
    is_fanseries = is_fanseries_url(url)
    if is_newdeaf:
        url = rewrite_newdeaf_mirror(url)
        _assert_newdeaf_target(url)
    else:
        url = validate_page_url(url)
    parsed = urlparse(url)
    if is_newdeaf:
        fetch_page = fetch_newdeaf_page
    elif is_fanseries:
        fetch_page = fetch_fanseries_page
    else:
        fetch_page = fetch_url

    page_title = ""
    series_options: list[dict] = []

    # Прямая ссылка на embed-плеер
    if any(host in parsed.netloc for host in EMBED_HOSTS):
        entry = build_player_entry(1, url)
        episode_options: list[dict] = []
        title = parsed.netloc
        try:
            embed_html = fetch_url(url)
            meta = parse_ylitron_embed_meta(embed_html)
            episode_options = parse_ylitron_episode_options(embed_html)
            if meta.get("title"):
                title = str(meta["title"])
        except Exception:  # noqa: BLE001
            pass
        result = {
            "title": title,
            "sourceUrl": url,
            "players": [entry],
            "episodeOptions": episode_options,
            "seriesOptions": [],
        }
        ref = parse_ylitron_ref(url)
        if ref:
            result.update(ref)
        return result

    page_html = fetch_page(url)
    page_title = extract_title(page_html)
    series_options = extract_same_series_options(page_html, url, page_title)
    if is_newdeaf:
        serial_list_options = extract_newdeaf_serial_list_options(page_html, url, page_title)
        if serial_list_options:
            known = {item.get("url") for item in series_options}
            for item in serial_list_options:
                item_url = item.get("url")
                if item_url and item_url not in known:
                    known.add(item_url)
                    series_options.append(item)
    if len(series_options) < 2:
        series_options = extract_related_series(page_html, url)
    if page_title:
        current_item = {"title": page_title, "url": url}
        if not any(item.get("url") == url for item in series_options):
            series_options.insert(0, current_item)
    iframe_urls = extract_players(page_html)
    cdn_players = extract_cdn_players(page_html, url)
    iframe_urls = merge_player_urls(iframe_urls, cdn_players)

    # Для карточек сериалов некоторых каталогов плеер может быть только на странице эпизода.
    auth_required_detected = page_requires_auth(page_html)
    if not iframe_urls and is_fanseries:
        for episode_url in extract_episode_page_candidates(page_html, url, limit=10):
            try:
                episode_html = fetch_page(episode_url)
            except urllib.error.URLError:
                continue
            if page_requires_auth(episode_html):
                auth_required_detected = True
            episode_iframes = extract_players(episode_html)
            episode_cdn = extract_cdn_players(episode_html, episode_url)
            merged_episode_urls = merge_player_urls(episode_iframes, episode_cdn)
            if not merged_episode_urls:
                continue
            url = episode_url
            page_html = episode_html
            page_title = extract_title(episode_html) or page_title
            iframe_urls = merged_episode_urls
            break
    if not iframe_urls:
        if auth_required_detected:
            raise ValueError(
                "Источник требует авторизацию для доступа к плееру. "
                "Выполните вход и повторите попытку или вставьте прямую ссылку на поток."
            )
        raise ValueError(
            "На странице не найден плеер. Вставьте ссылку на страницу "
            "с поддерживаемым источником или прямую ссылку iframe."
        )

    players = []
    with ThreadPoolExecutor(max_workers=min(3, len(iframe_urls))) as pool:
        futures = [
            pool.submit(build_player_entry, i, iframe_url)
            for i, iframe_url in enumerate(iframe_urls, start=1)
        ]
        players = [future.result() for future in futures]
    players.sort(key=lambda item: item["index"])

    # Явно подписываем источники последовательно, чтобы в UI было
    # "Источник 1", "Источник 2", ... и можно было пробовать разные.
    for idx, player in enumerate(players, start=1):
        player["label"] = f"Источник {idx}"

    # Метаданные источника и опции эпизодов берём из первого подходящего
    # iframe с id, но не ограничиваемся только им.
    ref: dict = {}
    episode_options: list[dict] = []
    found = find_ylitron_player([p.get("iframeUrl", "") for p in players if p.get("iframeUrl")])
    if found:
        ylitron_url, ref = found
        try:
            embed_html = fetch_url(ylitron_url)
            episode_options = parse_ylitron_episode_options(embed_html)
        except Exception:  # noqa: BLE001
            episode_options = []
    if not episode_options and is_newdeaf:
        first_iframe = next((p.get("iframeUrl", "") for p in players if p.get("iframeUrl")), "")
        episode_options = extract_newdeaf_episode_options(page_html, first_iframe)

    result = {
        "title": page_title,
        "sourceUrl": url,
        "players": players,
        "seriesOptions": series_options,
        "episodeOptions": episode_options,
    }
    if ref:
        result.update(ref)
    return result


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
# Две модели: лёгкая по кнопке «ИИ», тяжёлая — эскалация если ответ плохой.
# В RAM одновременно только одна (keep_alive + unload перед эскалацией).
# Для qwen3 обязательно think:false в _chat_translate.
OLLAMA_MODEL_HEAVY = os.environ.get("SUBLEARN_OLLAMA_MODEL", "qwen3:4b")
OLLAMA_MODEL_LIGHT = os.environ.get("SUBLEARN_OLLAMA_MODEL_LIGHT", "qwen3:1.7b")
OLLAMA_MODEL = OLLAMA_MODEL_HEAVY  # обратная совместимость
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "3m")
try:
    OLLAMA_NUM_THREAD = max(1, int(os.environ.get("SUBLEARN_OLLAMA_NUM_THREAD", "2")))
except ValueError:
    OLLAMA_NUM_THREAD = 2
CTX_WORD = 384
CTX_PHRASE = 1280
CTX_PHRASE_STRICT = 640
CTX_EXPLAIN = 1280
# google = быстрый путь; ai/ollama = локальная модель по кнопке «ИИ».
TRANSLATE_DEFAULT_ENGINE = os.environ.get("SUBLEARN_TRANSLATE_ENGINE", "google").strip().lower()
GOOGLE_TRANSLATE_ENABLED = os.environ.get("SUBLEARN_GOOGLE_TRANSLATE", "1").strip() not in (
    "0",
    "false",
    "no",
    "off",
)


def ollama_unload(model: str) -> None:
    """Выгрузить модель из RAM (важно при эскалации light→heavy в пределах ~3 ГБ)."""
    if not model:
        return
    try:
        with _ollama_lock:
            _ollama_request(
                "/api/generate",
                {
                    "model": model,
                    "keep_alive": 0,
                    "stream": False,
                    "prompt": "",
                    "options": {"num_predict": 0},
                },
                timeout=30,
            )
    except Exception:  # noqa: BLE001
        pass


def _ollama_running_names() -> list:
    try:
        ps = _ollama_request("/api/ps", timeout=5)
    except Exception:  # noqa: BLE001
        return []
    names = []
    for item in ps.get("models") or []:
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(name)
    return names


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
    base = {
        "model": OLLAMA_MODEL_LIGHT,
        "model_light": OLLAMA_MODEL_LIGHT,
        "model_heavy": OLLAMA_MODEL_HEAVY,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    try:
        tags = _ollama_request("/api/tags", timeout=5)
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "ready": False,
            "loaded": False,
            "loaded_light": False,
            "loaded_heavy": False,
            "error": f"Ollama недоступна: {exc.reason}. Запустите ./start.sh",
            **base,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "ready": False,
            "loaded": False,
            "loaded_light": False,
            "loaded_heavy": False,
            "error": str(exc),
            **base,
        }

    names = []
    for item in tags.get("models") or []:
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(name)
    ready_light = _model_ready(names, OLLAMA_MODEL_LIGHT)
    ready_heavy = _model_ready(names, OLLAMA_MODEL_HEAVY)
    ready = ready_light and ready_heavy
    running = _ollama_running_names()
    loaded_light = _model_ready(running, OLLAMA_MODEL_LIGHT)
    loaded_heavy = _model_ready(running, OLLAMA_MODEL_HEAVY)
    loaded = loaded_light or loaded_heavy

    error = None
    if not ready_light:
        error = f"Лёгкая модель не скачана: {OLLAMA_MODEL_LIGHT}"
    elif not ready_heavy:
        error = f"Тяжёлая модель не скачана: {OLLAMA_MODEL_HEAVY}"

    return {
        "ok": True,
        "ready": ready,
        "ready_light": ready_light,
        "ready_heavy": ready_heavy,
        "loaded": loaded,
        "loaded_light": loaded_light,
        "loaded_heavy": loaded_heavy,
        "agents": ["word", "phrase"],
        "models": names,
        "error": error,
        **base,
    }


def ollama_warm() -> dict:
    """Загрузить лёгкую модель в RAM (кнопки «ИИ»); тяжёлая — только при эскалации."""
    return _ollama_warm_model(OLLAMA_MODEL_LIGHT)


def _ollama_warm_model(model: str) -> dict:
    """Загрузить модель в RAM с keep_alive (без полноценного ответа)."""
    status = ollama_status()
    if not status.get("ok"):
        return {
            "ok": False,
            "loaded": False,
            "model": model,
            "tier": "light" if model == OLLAMA_MODEL_LIGHT else "heavy",
            "error": status.get("error") or "Ollama недоступна",
        }
    ready = (
        status.get("ready_light")
        if model == OLLAMA_MODEL_LIGHT
        else status.get("ready_heavy")
    )
    if not ready:
        label = "лёгкая" if model == OLLAMA_MODEL_LIGHT else "тяжёлая"
        return {
            "ok": False,
            "loaded": False,
            "model": model,
            "tier": "light" if model == OLLAMA_MODEL_LIGHT else "heavy",
            "error": status.get("error") or f"{label} модель не скачана: {model}",
        }
    loaded = (
        status.get("loaded_light")
        if model == OLLAMA_MODEL_LIGHT
        else status.get("loaded_heavy")
    )
    if loaded:
        return {
            "ok": True,
            "loaded": True,
            "model": model,
            "tier": "light" if model == OLLAMA_MODEL_LIGHT else "heavy",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "error": None,
        }

    if model == OLLAMA_MODEL_LIGHT:
        ollama_unload(OLLAMA_MODEL_HEAVY)

    payload = {
        "model": model,
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
        "model": model,
        "tier": "light" if model == OLLAMA_MODEL_LIGHT else "heavy",
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
    model: str,
) -> str:
    payload = {
        "model": model,
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


def _is_bad_explain_answer(answer: str) -> bool:
    text = (answer or "").strip()
    if len(text) < 20:
        return True
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]+", text):
        return True
    latin = len(re.findall(r"[A-Za-z]", text))
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    if latin > cyr * 2 and latin > 40:
        return True
    if re.search(
        r"(?i)(cannot help|can't help|i'm sorry|as an ai|"
        r"как языковая модель|не могу помочь|извините, но)",
        text,
    ):
        return True
    return False


def _translate_needs_heavy(source: str, result: str, word_raw: Optional[str]) -> bool:
    if word_raw and len(_normalize_phrase_key(word_raw).split()) <= 1:
        return _is_bad_word_translation(result, word_raw)
    return _is_bad_phrase_translation(source, result)


def _ollama_explain_with_model(
    *,
    word: str,
    sentence: str = "",
    question: str = "",
    translation: str = "",
    model: str,
) -> str:
    focus = _normalize_english_spacing(word or "")
    ctx = _normalize_english_spacing(sentence or "")
    q = (question or "").strip() or "Почему здесь так сказано? Кратко объясни."
    ru = (translation or "").strip()
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
        num_ctx=CTX_EXPLAIN,
        schema_props={"answer": {"type": "string"}},
        model=model,
    )


def ollama_explain(
    *,
    word: str,
    sentence: str = "",
    question: str = "",
    translation: str = "",
    tier: str = "auto",
) -> Tuple[str, str]:
    """Короткий разбор: tier=auto (light→heavy), light, heavy (ручной)."""
    focus = _normalize_english_spacing(word or "")
    if not focus:
        raise ValueError("Нужно слово или фраза")
    if len((question or "").strip()) > 400:
        raise ValueError("Слишком длинный вопрос")

    mode = _normalize_tier(tier)
    kwargs = {
        "word": word,
        "sentence": sentence,
        "question": question,
        "translation": translation,
    }
    if mode == "heavy":
        ollama_unload(OLLAMA_MODEL_LIGHT)
        answer = _ollama_explain_with_model(**kwargs, model=OLLAMA_MODEL_HEAVY)
        ollama_unload(OLLAMA_MODEL_HEAVY)
        return answer, OLLAMA_MODEL_HEAVY
    if mode == "light":
        ollama_unload(OLLAMA_MODEL_HEAVY)
        answer = _ollama_explain_with_model(**kwargs, model=OLLAMA_MODEL_LIGHT)
        return answer, OLLAMA_MODEL_LIGHT

    ollama_unload(OLLAMA_MODEL_HEAVY)
    try:
        answer = _ollama_explain_with_model(**kwargs, model=OLLAMA_MODEL_LIGHT)
        if not _is_bad_explain_answer(answer):
            return answer, OLLAMA_MODEL_LIGHT
    except Exception:
        answer = None
    ollama_unload(OLLAMA_MODEL_LIGHT)
    answer = _ollama_explain_with_model(**kwargs, model=OLLAMA_MODEL_HEAVY)
    ollama_unload(OLLAMA_MODEL_HEAVY)
    return answer, OLLAMA_MODEL_HEAVY


def _chat_translate(
    messages: list,
    *,
    agent: str,
    num_predict: int,
    temperature: float,
    num_ctx: int,
    model: str,
) -> str:
    """agent: 'word' | 'phrase'. Одна модель; JSON-формат — чтобы qwen3 не уходил в болтовню."""
    return _chat_json(
        messages,
        keys=("ru", "translation", "text", "gloss"),
        num_predict=num_predict,
        temperature=temperature,
        num_ctx=num_ctx,
        schema_props={"ru": {"type": "string"}},
        model=model,
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


def _ollama_translate_with_model(
    text: str,
    *,
    word: Optional[str] = None,
    sentence: Optional[str] = None,
    model: str,
) -> Tuple[str, str, Optional[str]]:
    """Перевод через указанную модель. Возвращает (result, source_for_check, word_raw)."""
    cleaned = _normalize_english_spacing(text or "")
    if not cleaned:
        return "", cleaned, None
    if len(cleaned) > 800:
        raise ValueError("Слишком длинный текст (макс. 800 символов)")

    word_raw = _normalize_english_spacing(word) if word else None
    sentence = _normalize_english_spacing(sentence) if sentence else sentence

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

    source_for_check = word_raw or cleaned

    if span_mode:
        target = word_raw.strip()
        ctx = (sentence or "").strip()
        if len(ctx) > 420:
            ctx = ctx[:420].rsplit(" ", 1)[0]
        marked = _mark_phrase_in_context(ctx, target) if ctx else f"[[{target}]]"
        phrase_gloss = _glossary_lookup(target)
        if phrase_gloss and " " in _normalize_phrase_key(target):
            return phrase_gloss, source_for_check, word_raw
        result = _chat_translate(
            _span_translate_messages(marked, target),
            agent="phrase",
            num_predict=_phrase_num_predict(target),
            temperature=0,
            num_ctx=CTX_PHRASE,
            model=model,
        )
        if (
            _is_bad_phrase_translation(target, result)
            or _looks_like_context_bleed(target, ctx, result)
        ):
            result = _chat_translate(
                _line_translate_messages(target),
                agent="phrase",
                num_predict=_phrase_num_predict(target),
                temperature=0,
                num_ctx=CTX_PHRASE,
                model=model,
            )
    elif word_raw:
        target = word_raw.strip()
        ctx = (sentence or "").strip()
        gloss = _glossary_lookup(target, ctx)
        if gloss:
            return gloss, source_for_check, word_raw

        marked = f"[[{target}]]"
        result = _chat_translate(
            _word_translate_messages(marked, target),
            agent="word",
            num_predict=24,
            temperature=0,
            num_ctx=CTX_WORD,
            model=model,
        )
        result = _normalize_word_gloss_case(result)
        if _is_bad_word_translation(result, word_raw):
            gloss = _glossary_lookup(word_raw, sentence)
            if gloss:
                return gloss, source_for_check, word_raw
            retry = _chat_translate(
                _strict_retry_messages(target),
                agent="word",
                num_predict=20,
                temperature=0,
                num_ctx=CTX_WORD,
                model=model,
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
                    num_ctx=CTX_PHRASE,
                    model=model,
                )
    else:
        phrase_gloss = _glossary_lookup(cleaned)
        if phrase_gloss and " " in _normalize_phrase_key(cleaned):
            return phrase_gloss, source_for_check, word_raw

        result = _chat_translate(
            _line_translate_messages(cleaned),
            agent="phrase",
            num_predict=_phrase_num_predict(cleaned),
            temperature=0,
            num_ctx=CTX_PHRASE,
            model=model,
        )

    if _is_bad_phrase_translation(source_for_check, result):
        result = _chat_translate(
            _strict_retry_messages(source_for_check),
            agent="phrase",
            num_predict=_phrase_num_predict(source_for_check),
            temperature=0,
            num_ctx=CTX_PHRASE_STRICT,
            model=model,
        )

    return result, source_for_check, word_raw


def ollama_translate(
    text: str,
    *,
    word: Optional[str] = None,
    sentence: Optional[str] = None,
    tier: str = "auto",
) -> Tuple[str, str]:
    """tier=auto: light→heavy при плохом ответе; heavy/light — ручной режим."""
    mode = _normalize_tier(tier)
    cleaned = _normalize_english_spacing(text or "")
    word_raw = _normalize_english_spacing(word) if word else None
    sentence_norm = _normalize_english_spacing(sentence) if sentence else sentence
    word_words = len(_normalize_phrase_key(word_raw or "").split()) if word_raw else 0
    span_mode = bool(
        word_raw
        and word_words >= 2
        and sentence_norm
        and _has_broader_context(word_raw, sentence_norm)
        and _is_cue_join_span(word_raw, sentence_norm)
    )
    cache_word = word_raw
    cache_cleaned = cleaned
    if word_raw and word_words >= 2 and not span_mode:
        cache_cleaned = word_raw
        cache_word = None
    cache_key = _translate_cache_key(cache_cleaned, cache_word, sentence_norm)
    if mode != "auto":
        cache_key = f"{cache_key}|tier:{mode}"
    cached = _translate_cache_get(cache_key)
    if cached is not None:
        model_cached = OLLAMA_MODEL_HEAVY if mode == "heavy" else OLLAMA_MODEL_LIGHT
        return cached, model_cached

    if mode == "heavy":
        ollama_unload(OLLAMA_MODEL_LIGHT)
        result, _, _ = _ollama_translate_with_model(
            text,
            word=word,
            sentence=sentence,
            model=OLLAMA_MODEL_HEAVY,
        )
        ollama_unload(OLLAMA_MODEL_HEAVY)
        _translate_cache_put(cache_key, result)
        return result, OLLAMA_MODEL_HEAVY

    if mode == "light":
        ollama_unload(OLLAMA_MODEL_HEAVY)
        result, _, _ = _ollama_translate_with_model(
            text,
            word=word,
            sentence=sentence,
            model=OLLAMA_MODEL_LIGHT,
        )
        _translate_cache_put(cache_key, result)
        return result, OLLAMA_MODEL_LIGHT

    ollama_unload(OLLAMA_MODEL_HEAVY)
    result, source_for_check, check_word = _ollama_translate_with_model(
        text,
        word=word,
        sentence=sentence,
        model=OLLAMA_MODEL_LIGHT,
    )
    if _translate_needs_heavy(source_for_check, result, check_word):
        ollama_unload(OLLAMA_MODEL_LIGHT)
        result, _, _ = _ollama_translate_with_model(
            text,
            word=word,
            sentence=sentence,
            model=OLLAMA_MODEL_HEAVY,
        )
        ollama_unload(OLLAMA_MODEL_HEAVY)
        model_used = OLLAMA_MODEL_HEAVY
    else:
        model_used = OLLAMA_MODEL_LIGHT

    _translate_cache_put(cache_key, result)
    return result, model_used


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


def _normalize_tier(tier: Optional[str]) -> str:
    t = (tier or "auto").strip().lower()
    if t in ("heavy", "strong", "max", "4b", "manual"):
        return "heavy"
    if t in ("light", "fast", "1.7b", "min"):
        return "light"
    return "auto"


def _model_tier(model: str) -> str:
    return "heavy" if model == OLLAMA_MODEL_HEAVY else "light"


def translate_text(
    text: str,
    *,
    word: Optional[str] = None,
    sentence: Optional[str] = None,
    engine: str = "google",
    tier: str = "auto",
) -> Tuple[str, str, str]:
    """
    Возвращает (translation, provider, model).
    engine: google | ai/ollama
    tier: auto | light | heavy (только для ai)
    """
    mode = (engine or TRANSLATE_DEFAULT_ENGINE or "google").strip().lower()
    if mode in ("ai", "ollama", "llm", "local"):
        translation, model = ollama_translate(
            text, word=word, sentence=sentence, tier=tier
        )
        return translation, "ollama", model

    # Google: переводим выделенное (word) или всю реплику (text), без «прилипания» контекста.
    focus = _normalize_english_spacing(word or text or "")
    if not focus:
        focus = _normalize_english_spacing(text or "")
    if not GOOGLE_TRANSLATE_ENABLED:
        translation, model = ollama_translate(
            text, word=word, sentence=sentence, tier=tier
        )
        return translation, "ollama", model

    try:
        return google_translate(focus), "google", "gtx"
    except Exception:
        # Сеть/лимиты Google — мягкий откат на локальную модель.
        translation, model = ollama_translate(
            text, word=word, sentence=sentence, tier=tier
        )
        return translation, "ollama", model


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
        if parsed.path.startswith("/api/") and CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/") or not CORS_ORIGIN:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

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
        if parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            query = (params.get("q") or params.get("query") or [""])[0].strip()
            content_type = (params.get("type") or [""])[0].strip().lower()
            try:
                limit = int((params.get("limit") or ["15"])[0])
            except ValueError:
                limit = 15
            if not query:
                self._json_response(400, {"error": "Параметр q обязателен"})
                return
            try:
                data = search_catalog(query, content_type, limit)
                self._json_response(200, data)
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(502, {"error": f"Не удалось выполнить поиск: {exc.reason}"})
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
        if parsed.path == "/api/image":
            params = parse_qs(parsed.query)
            url = (params.get("url") or [""])[0].strip()
            if not url:
                self._text_response(400, "invalid url", "text/plain")
                return
            try:
                body, ctype = fetch_image_binary(url)
                if not ctype.lower().startswith("image/"):
                    self._text_response(415, "unsupported media type", "text/plain")
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
            except SecurityError as exc:
                self._text_response(403, str(exc), "text/plain")
            except urllib.error.URLError as exc:
                self._text_response(502, f"image error: {exc.reason}", "text/plain")
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
            tier = (params.get("tier") or ["auto"])[0].strip().lower()
            if not text and not word:
                self._json_response(400, {"error": "Параметр text или word обязателен"})
                return
            try:
                translation, provider, model = translate_text(
                    text or word or "",
                    word=word,
                    sentence=sentence,
                    engine=engine,
                    tier=tier,
                )
                used_word = bool(word) and not _is_long_phrase(word)
                self._json_response(
                    200,
                    {
                        "translation": translation,
                        "provider": provider,
                        "model": model,
                        "tier": _model_tier(model) if provider == "ollama" else None,
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
        if parsed.path == "/api/source-auth":
            try:
                payload = self._read_json_body()
                source = str(payload.get("source") or "").strip().lower()
                login = str(payload.get("login") or "").strip()
                password = str(payload.get("password") or "").strip()
                verify_url = str(payload.get("verifyUrl") or "").strip()
                if source not in ("catalog_b", "source_b", "source2", "2"):
                    self._json_response(400, {"error": "Неизвестный ID источника"})
                    return
                data = login_fanseries_source(login, password, verify_url=verify_url)
                self._json_response(200, data)
            except ValueError as exc:
                self._json_response(400, {"error": str(exc)})
            except SecurityError as exc:
                self._json_response(403, {"error": str(exc)})
            except urllib.error.URLError as exc:
                self._json_response(502, {"error": f"Ошибка авторизации: {exc.reason}"})
            except Exception as exc:  # noqa: BLE001
                self._json_response(500, {"error": str(exc)})
            return
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
                tier = str(payload.get("tier") or "auto").strip().lower()
                if not word:
                    self._json_response(400, {"error": "Нужен word"})
                    return
                answer, model = ollama_explain(
                    word=word,
                    sentence=sentence,
                    question=question,
                    translation=translation,
                    tier=tier,
                )
                self._json_response(
                    200,
                    {
                        "answer": answer,
                        "provider": "ollama",
                        "model": model,
                        "tier": _model_tier(model),
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
                        "model": OLLAMA_MODEL_LIGHT,
                        "tier": "light",
                        "error": f"Ollama недоступна: {exc.reason}",
                    },
                )
            except RuntimeError as exc:
                self._json_response(
                    502,
                    {
                        "ok": False,
                        "loaded": False,
                        "model": OLLAMA_MODEL_LIGHT,
                        "tier": "light",
                        "error": str(exc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json_response(
                    500,
                    {
                        "ok": False,
                        "loaded": False,
                        "model": OLLAMA_MODEL_LIGHT,
                        "tier": "light",
                        "error": str(exc),
                    },
                )
            return
        self._json_response(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/source-auth":
            clear_fanseries_auth_session()
            self._json_response(200, {"ok": True})
            return
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
        return read_json_body(self)

    def _text_response(self, code: int, text: str, content_type: str):
        text_response(self, code, text, content_type)

    def _json_response(self, code: int, payload: dict):
        json_response(self, code, payload)


def main():
    host = os.environ.get("SUBLEARN_HOST", "127.0.0.1")
    port = int(os.environ.get("SUBLEARN_PORT") or os.environ.get("PORT", "8765"))
    init_vocab_db()
    server = ThreadingHTTPServer((host, port), SubLearnHandler)
    print(f"SubLearn: http://127.0.0.1:{port}")
    print(
        f"Translate: default={TRANSLATE_DEFAULT_ENGINE} "
        f"google={'on' if GOOGLE_TRANSLATE_ENABLED else 'off'} "
        f"| AI Ollama {OLLAMA_URL} light={OLLAMA_MODEL_LIGHT} heavy={OLLAMA_MODEL_HEAVY}"
    )
    print(f"Vocab DB: {DB_PATH}")
    print("Остановка: Ctrl+C")
    server.serve_forever()


if __name__ == "__main__":
    main()
