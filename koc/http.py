from __future__ import annotations

import time as _time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch_text(url: str, timeout: int = 12, max_retries: int = 2, backoff_base: float = 1.5) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml,application/xml,text/html,text/plain,*/*",
        },
    )

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            delay = backoff_base * (2 ** (attempt - 1))
            _time.sleep(delay)

        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            code = exc.code
            msg = f"HTTP {code} while fetching {url}"
            if code in (429, 502, 503, 504):
                if attempt < max_retries:
                    continue
            if code == 404:
                raise RuntimeError(msg) from exc
            if attempt < max_retries and code >= 500:
                continue
            raise RuntimeError(msg) from exc
        except URLError as exc:
            msg = f"Network error while fetching {url}: {exc.reason}"
            if attempt < max_retries:
                last_error = RuntimeError(msg)
                continue
            raise RuntimeError(msg) from exc

    raise last_error or RuntimeError(f"Failed after {max_retries + 1} attempts: {url}")

