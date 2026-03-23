"""URL normalization and validation utilities for job ingestion."""

from __future__ import annotations

from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

import requests

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {
    "ref",
    "ref_src",
    "source",
    "src",
    "trk",
    "tracking",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Normalize a URL by resolving relatives, stripping spaces, and de-slashing.

    Args:
        url: Input URL which may be relative or absolute.
        base_url: Optional base URL used to resolve relative URLs.

    Returns:
        A normalized absolute-like URL string when possible.
    """

    raw = str(url or "").strip()
    if not raw:
        return ""

    resolved = urljoin(base_url, raw) if base_url else raw
    parsed = urlparse(resolved)

    # Remove trailing slash for non-root paths only.
    path = parsed.path.rstrip("/") if parsed.path not in {"", "/"} else parsed.path
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    ).strip()


def clean_url(url: str) -> str:
    """Remove tracking noise and reduce URL to its stable base path.

    This intentionally strips all query parameters and fragments to maximize
    URL stability across fetches.
    """

    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""

    # Parse once so we can optionally preserve non-tracking params in future.
    _ = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith(_TRACKING_PARAM_PREFIXES) and k.lower() not in _TRACKING_PARAMS
    ]

    cleaned = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") if parsed.path not in {"", "/"} else parsed.path,
            "",
            "",
            "",
        )
    )
    return cleaned.strip()


def is_valid_url(url: str) -> bool:
    """Return True only when URL is reachable with HTTP 200 via HEAD request."""

    try:
        response = requests.head(str(url or "").strip(), allow_redirects=True, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def extract_platform(url: str) -> str:
    """Infer source platform name from URL domain."""

    host = urlparse(str(url or "").strip().lower()).netloc
    if "linkedin.com" in host:
        return "LINKEDIN"
    if "naukri.com" in host:
        return "NAUKRI"
    return "UNKNOWN"
