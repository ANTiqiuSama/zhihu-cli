"""Safe, single-request reader for a user-specified public Zhihu answer."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit

from zhihu_cli.content.handlers.cache_manager import cache_manager
from zhihu_cli.content.utils.html2markdown import converter

ANSWER_PATH_RE = re.compile(r"^/question/(?P<question_id>\d+)/answer/(?P<answer_id>\d+)/?$")
ANSWER_DETAIL_INCLUDE = (
    "content,excerpt,author.name,question.title,created_time,updated_time,voteup_count,comment_count,favlists_count"
)
ANSWER_DETAIL_ENDPOINT = "https://www.zhihu.com/api/v4/answers/{answer_id}?include={include}"

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_BLOCKED = 3
EXIT_UNREADABLE = 4
EXIT_CLI_ERROR = 5


def canonicalize_answer_url(url: str) -> tuple[str, str, str]:
    """Return canonical URL, question ID, and answer ID for a public answer URL."""
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.zhihu.com":
        raise ValueError("URL must use https://www.zhihu.com")

    match = ANSWER_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValueError("URL must match /question/<question-id>/answer/<answer-id>")

    question_id = match.group("question_id")
    answer_id = match.group("answer_id")
    canonical_url = f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
    return canonical_url, question_id, answer_id


def invalid_url_result(url: str, reason: str) -> dict[str, Any]:
    """Build a stable structured result for invalid input."""
    return {
        "status": "cli_error",
        "reason": reason,
        "http_status": None,
        "input_url": url,
        "endpoint": "answer-detail",
    }


def _base_result(canonical_url: str, answer_id: str, active_profile: str | None) -> dict[str, Any]:
    return {
        "canonical_url": canonical_url,
        "answer_id": answer_id,
        "endpoint": "answer-detail",
        "authenticated_profile": bool(active_profile),
    }


def _error_details(payload: Any) -> tuple[Any, bool, str]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None, False, ""
    return error.get("code"), bool(error.get("need_login", False)), str(error.get("message") or "")


def _is_human_verification(error_code: Any, message: str) -> bool:
    return str(error_code) in {"40352", "40362"} or bool(
        re.search(r"captcha|verification|risk", message, re.IGNORECASE)
    )


def read_public_answer_api(
    url: str,
    *,
    metadata_only: bool = False,
    allow_anonymous: bool = False,
    http_session: Any | None = None,
    active_profile: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Read one public answer through the answer-detail API without retries.

    The caller must canonicalize or accept :class:`ValueError`. By default the
    function stops before creating an HTTP session when no active profile is
    available. ``allow_anonymous`` explicitly permits one compatibility probe.
    """
    canonical_url, _, answer_id = canonicalize_answer_url(url)
    if active_profile is None:
        active_profile = cache_manager.get_active_profile()

    base = _base_result(canonical_url, answer_id, active_profile)
    if not active_profile and not allow_anonymous:
        return {
            **base,
            "status": "blocked_auth",
            "reason": "No active zhihu-cli profile; network request was not sent",
            "http_status": None,
        }, EXIT_BLOCKED

    if http_session is None:
        from zhihu_cli.content.handlers import requests as requests_module

        http_session = requests_module.session

    endpoint = ANSWER_DETAIL_ENDPOINT.format(answer_id=answer_id, include=quote(ANSWER_DETAIL_INCLUDE, safe=""))
    previous_captcha_handler = getattr(http_session, "captcha_handler", None)
    try:
        if previous_captcha_handler is not None:
            http_session.captcha_handler = "ignore"
        response = http_session.get(endpoint, timeout=20, allow_redirects=False)
    except Exception as exc:
        return {
            **base,
            "status": "cli_error",
            "reason": f"Request failed: {type(exc).__name__}",
            "http_status": None,
        }, EXIT_CLI_ERROR
    finally:
        if previous_captcha_handler is not None:
            http_session.captcha_handler = previous_captcha_handler

    http_status = int(getattr(response, "status_code", 0) or 0)
    try:
        payload = response.json()
        valid_json = True
    except (TypeError, ValueError):
        payload = None
        valid_json = False

    error_code, need_login, error_message = _error_details(payload)
    if http_status in (401, 403) or (isinstance(payload, dict) and "error" in payload):
        human_verification = _is_human_verification(error_code, error_message)
        return {
            **base,
            "status": "blocked_human_verification" if human_verification else "blocked_auth",
            "reason": error_message or "Authentication or access verification is required",
            "http_status": http_status,
            "error_code": error_code,
            "need_login": need_login,
        }, EXIT_BLOCKED

    if http_status != 200:
        return {
            **base,
            "status": "unreadable",
            "reason": "Unexpected HTTP status",
            "http_status": http_status,
        }, EXIT_UNREADABLE

    if not valid_json or not isinstance(payload, dict):
        return {
            **base,
            "status": "unreadable",
            "reason": "HTTP 200 body was not valid JSON",
            "http_status": http_status,
        }, EXIT_UNREADABLE

    returned_id = str(payload.get("id", ""))
    content_html = str(payload.get("content") or "")
    if returned_id != answer_id or not content_html.strip():
        return {
            **base,
            "status": "unreadable",
            "reason": "HTTP 200 JSON did not contain the requested answer content",
            "http_status": http_status,
            "returned_answer_id": returned_id,
        }, EXIT_UNREADABLE

    content_md = converter.convert(content_html).strip()
    if not content_md:
        return {
            **base,
            "status": "unreadable",
            "reason": "Answer content was empty after conversion",
            "http_status": http_status,
            "returned_answer_id": returned_id,
        }, EXIT_UNREADABLE

    question = payload.get("question") if isinstance(payload.get("question"), dict) else {}
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    result: dict[str, Any] = {
        **base,
        "status": "ok",
        "http_status": http_status,
        "question_title": str(question.get("title") or ""),
        "author_name": str(author.get("name") or ""),
        "created_time": payload.get("created_time"),
        "updated_time": payload.get("updated_time"),
        "voteup_count": payload.get("voteup_count"),
        "comment_count": payload.get("comment_count"),
        "favlists_count": payload.get("favlists_count"),
        "content_chars": len(content_md),
        "completeness": {
            "valid_json": True,
            "matching_answer_id": True,
            "nonempty_content": True,
            "api_payload_complete": True,
        },
    }
    if not metadata_only:
        result["content_md"] = content_md
    return result, EXIT_OK
