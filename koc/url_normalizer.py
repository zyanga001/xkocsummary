from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


SUPPORTED_HOSTS = {
    "x.com",
    "twitter.com",
    "mobile.twitter.com",
    "xcancel.com",
    "nitter.net",
}


@dataclass(frozen=True)
class NormalizedTweetUrl:
    raw_url: str
    username: str
    tweet_id: str
    canonical_url: str


def normalize_tweet_url(raw_url: str) -> NormalizedTweetUrl:
    parsed = urlparse(raw_url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in SUPPORTED_HOSTS:
        raise ValueError(f"unsupported tweet URL host: {parsed.netloc or '(missing)'}")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[1] not in {"status", "statuses"}:
        raise ValueError("tweet URL must look like /<username>/status/<tweet_id>")
    username = parts[0].lstrip("@")
    tweet_id = parts[2]
    if not username or not re.fullmatch(r"\d+", tweet_id):
        raise ValueError("tweet URL must include username and numeric tweet id")

    return NormalizedTweetUrl(
        raw_url=raw_url,
        username=username,
        tweet_id=tweet_id,
        canonical_url=f"https://x.com/{username}/status/{tweet_id}",
    )


def canonical_tweet_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username.lstrip('@')}/status/{tweet_id}"
