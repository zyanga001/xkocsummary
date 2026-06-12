#!/usr/bin/env python3
"""Fetch profile and engagement data from fxtwitter API.

- profile: per-author lookup → name, followers, following, tweets count
- engagement: per-tweet lookup → views, likes, retweets, replies
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from typing import Any


def _fetch_json(url: str, timeout: int = 10) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "KOC-DailyBrief/2.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_profile(username: str) -> dict[str, Any]:
    """Fetch display name and follower count for a user."""
    try:
        data = _fetch_json(f"https://api.fxtwitter.com/{username.lstrip('@')}")
        user = data.get("user", {}) if isinstance(data, dict) else {}
        return {
            "username": username.lstrip("@"),
            "name": user.get("name", "") or username,
            "screen_name": user.get("screen_name", "") or username,
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "tweets_count": user.get("tweets", 0),
            "avatar_url": user.get("avatar_url", ""),
        }
    except Exception:
        return {
            "username": username.lstrip("@"),
            "name": username,
            "screen_name": username,
            "followers": 0,
            "following": 0,
            "tweets_count": 0,
            "avatar_url": "",
            "error": True,
        }


def fetch_tweet_engagement(url: str) -> dict[str, Any]:
    """Fetch engagement metrics for a tweet URL."""
    try:
        # Extract username/status_id from URL
        parts = url.rstrip("/").split("/")
        status_id = parts[-1]
        username = parts[-3] if len(parts) >= 3 else ""
        data = _fetch_json(f"https://api.fxtwitter.com/{username}/status/{status_id}")
        tweet = data.get("tweet", {}) if isinstance(data, dict) else {}
        return {
            "views": tweet.get("views", 0) or 0,
            "likes": tweet.get("likes", 0) or 0,
            "retweets": tweet.get("retweets", 0) or 0,
            "replies": tweet.get("replies", 0) or 0,
            "quotes": tweet.get("quotes", 0) or 0,
            "created_at": tweet.get("created_at", ""),
        }
    except Exception:
        return {"views": 0, "likes": 0, "retweets": 0, "replies": 0, "quotes": 0, "error": True}


def enrich_all(items: list[dict], max_workers: int = 8) -> list[dict]:
    """Enrich all items with profile and engagement data.

    Args:
        items: list of dicts with 'username' and 'url' keys
        max_workers: concurrent threads for API calls

    Returns:
        same items with added profile and engagement fields
    """
    # Collect unique usernames
    usernames = list(set(item.get("username") or item.get("用户名", "") for item in items))
    usernames = [u for u in usernames if u]

    # Fetch profiles in parallel
    profiles: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(usernames))) as pool:
        futures = {pool.submit(fetch_profile, u): u for u in usernames}
        for future in as_completed(futures):
            u = futures[future]
            try:
                profiles[u] = future.result()
            except Exception:
                profiles[u] = {"username": u, "name": u, "followers": 0}

    # Fetch tweet engagements in parallel
    engagements: dict[str, dict] = {}
    urls = [item.get("url") or item.get("推文链接", "") for item in items if item.get("url") or item.get("推文链接")]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
        futures = {pool.submit(fetch_tweet_engagement, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                engagements[url] = future.result()
            except Exception:
                engagements[url] = {}

    # Attach to items
    for item in items:
        username = item.get("username") or item.get("用户名", "")
        url = item.get("url") or item.get("推文链接", "")
        profile = profiles.get(username, {})
        eng = engagements.get(url, {})

        item["display_name"] = profile.get("name", username) or username
        item["followers"] = profile.get("followers", 0)
        item["following"] = profile.get("following", 0)
        item["avatar_url"] = profile.get("avatar_url", "")
        item["views"] = eng.get("views", 0)
        item["likes"] = eng.get("likes", 0)
        item["retweets"] = eng.get("retweets", 0)
        item["replies"] = eng.get("replies", 0)
        item["has_engagement"] = bool(eng and not eng.get("error"))

    return items


def format_meta(item: dict) -> str:
    """Format engagement line like '113.0K 粉丝 · 852.6K 阅 · 600 赞 · 79 转'"""
    parts = []
    followers = item.get("followers", 0) or 0
    views = item.get("views", 0) or 0
    likes = item.get("likes", 0) or 0
    retweets = item.get("retweets", 0) or 0

    if followers:
        parts.append(f"{_compact(followers)} 粉丝")
    if views:
        parts.append(f"{_compact(views)} 阅")
    if likes:
        parts.append(f"{_compact(likes)} 赞")
    if retweets:
        parts.append(f"{_compact(retweets)} 转")

    return " · ".join(parts) if parts else ""


def _compact(n: int) -> str:
    """Format large numbers for display. Public via import by v2_report."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
