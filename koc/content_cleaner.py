from __future__ import annotations

from dataclasses import dataclass
import re


NOISE_LINES = {
    "view replies",
    "show more",
    "read more",
    "log in",
    "sign up",
    "open in app",
}


@dataclass(frozen=True)
class CleanedContent:
    text: str
    quality: str
    preview: str
    length: int


def clean_jina_markdown(markdown: str | None) -> CleanedContent:
    body = _extract_markdown_body(markdown or "")
    if _looks_like_blocker(body):
        return CleanedContent(text="", quality="empty", preview="", length=0)
    lines = [_clean_line(line) for line in body.splitlines()]
    kept = [line for line in lines if _keep_line(line)]
    kept = _extract_x_tweet_lines(kept)
    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    quality = _quality(text)
    return CleanedContent(
        text=text,
        quality=quality,
        preview=_preview(text),
        length=len(text),
    )


def _extract_markdown_body(markdown: str) -> str:
    marker = "Markdown Content:"
    if marker in markdown:
        return markdown.split(marker, 1)[1].strip()
    return markdown.strip()


def _clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\s*([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    return line.strip()


def _keep_line(line: str) -> bool:
    if not line:
        return False
    lower = line.lower()
    if lower in NOISE_LINES:
        return False
    if lower in {"don’t miss what’s happening", "don't miss what's happening", "people on x are the first to know.", "post", "conversation"}:
        return False
    if lower.startswith(("title:", "url source:", "published time:")):
        return False
    return True


def _extract_x_tweet_lines(lines: list[str]) -> list[str]:
    handle_index = None
    for index, line in enumerate(lines):
        if re.fullmatch(r"@\w{1,20}", line):
            handle_index = index
            break
    if handle_index is None:
        return lines

    body: list[str] = []
    for line in lines[handle_index + 1 :]:
        lower = line.lower()
        if _is_x_page_tail(line, lower):
            break
        body.append(line)
    return body or lines


def _is_x_page_tail(line: str, lower: str) -> bool:
    if re.search(r"\d{1,2}:\d{2}\s+[AP]M\s+·\s+\w+\s+\d{1,2},\s+\d{4}", line):
        return True
    if re.search(r"\bviews?$", lower):
        return True
    return lower in {
        "new to x?",
        "trending now",
        "what’s happening",
        "what's happening",
        "terms of service",
        "privacy policy",
    }


def _quality(text: str) -> str:
    if not text:
        return "empty"
    if len(text) < 20:
        return "low"
    return "high"


def _looks_like_blocker(text: str) -> bool:
    lower = text.lower()
    markers = [
        "sorry this pages exist in order to keep the service usable",
        "if you can't pass the test",
        "please whitelist your extensions",
        "enable javascript",
        "checking your browser",
    ]
    return any(marker in lower for marker in markers)


def _preview(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"
