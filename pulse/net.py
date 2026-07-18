"""HTTP utilities: retry wrapper for resilient outbound requests, JSON parsing helper."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def safe_parse_json(data: Any) -> dict:
    """Parse JSON string to dict, returning {} on failure."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return {}
    return data if isinstance(data, dict) else {}


def http_request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_retries: int = 2,
    backoff: float = 1.5,
) -> tuple[int, list[str]]:
    """HTTP request with exponential backoff retry."""
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt < max_retries:
                wait = backoff ** attempt
                logger.debug("http_request retry %d/%d in %.1fs: %s", attempt + 1, max_retries, wait, e)
                time.sleep(wait)
            else:
                raise urllib.error.URLError(f"all {max_retries + 1} attempts failed") from e
    raise urllib.error.URLError(f"all {max_retries + 1} attempts failed")
