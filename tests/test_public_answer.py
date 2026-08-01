import json

import click
import pytest
from click.testing import CliRunner

from zhihu_cli.commands import browse as browse_commands
from zhihu_cli.commands.browse import register_browse
from zhihu_cli.commands.compat import register_compat
from zhihu_cli.content.handlers import public_answer
from zhihu_cli.content.handlers.public_answer import (
    EXIT_BLOCKED,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    EXIT_UNREADABLE,
    canonicalize_answer_url,
    read_public_answer_api,
)
from zhihu_cli.output import set_json_mode

ANSWER_URL = "https://www.zhihu.com/question/2066595452238160814/answer/2066720705471836838"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.captcha_handler = "auto"
        self.calls = []
        self.handler_values = []

    def __setattr__(self, name, value):
        if name == "captcha_handler" and "handler_values" in self.__dict__:
            self.handler_values.append(value)
        super().__setattr__(name, value)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _success_payload():
    return {
        "id": "2066720705471836838",
        "content": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "question": {"title": "Test question"},
        "author": {"name": "Test author"},
        "created_time": 1,
        "updated_time": 2,
        "voteup_count": 3,
        "comment_count": 4,
        "favlists_count": 5,
    }


def _build_cli():
    @click.group()
    def root():
        pass

    register_browse(root)
    register_compat(root)
    return root


def test_canonicalize_answer_url_strips_tracking_query():
    canonical, question_id, answer_id = canonicalize_answer_url(ANSWER_URL + "?share_code=x&utm_source=y")

    assert canonical == ANSWER_URL
    assert question_id == "2066595452238160814"
    assert answer_id == "2066720705471836838"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.zhihu.com/question/1/answer/2",
        "https://zhihu.com/question/1/answer/2",
        "https://www.zhihu.com/question/1",
        "https://www.zhihu.com.evil.example/question/1/answer/2",
    ],
)
def test_canonicalize_answer_url_rejects_noncanonical_input(url):
    with pytest.raises(ValueError):
        canonicalize_answer_url(url)


def test_no_profile_stops_before_network(monkeypatch):
    session = FakeSession(FakeResponse(200, _success_payload()))
    monkeypatch.setattr(public_answer.cache_manager, "get_active_profile", lambda: None)

    result, exit_code = read_public_answer_api(ANSWER_URL, http_session=session)

    assert exit_code == EXIT_BLOCKED
    assert result["status"] == "blocked_auth"
    assert result["http_status"] is None
    assert session.calls == []


def test_http_200_requires_matching_nonempty_content_and_restores_handler():
    session = FakeSession(FakeResponse(200, _success_payload()))

    result, exit_code = read_public_answer_api(ANSWER_URL, http_session=session, active_profile="research")

    assert exit_code == EXIT_OK
    assert result["status"] == "ok"
    assert result["http_status"] == 200
    assert result["content_md"] == "First paragraph.\n\nSecond paragraph."
    assert result["completeness"] == {
        "valid_json": True,
        "matching_answer_id": True,
        "nonempty_content": True,
        "api_payload_complete": True,
    }
    assert len(session.calls) == 1
    _, kwargs = session.calls[0]
    assert kwargs == {"timeout": 20, "allow_redirects": False}
    assert session.handler_values == ["ignore", "auto"]
    assert session.captcha_handler == "auto"


def test_metadata_only_omits_content():
    session = FakeSession(FakeResponse(200, _success_payload()))

    result, exit_code = read_public_answer_api(
        ANSWER_URL,
        metadata_only=True,
        http_session=session,
        active_profile="research",
    )

    assert exit_code == EXIT_OK
    assert "content_md" not in result
    assert result["content_chars"] > 0


def test_risk_control_is_a_hard_stop_without_retry():
    session = FakeSession(FakeResponse(403, {"error": {"code": 40352, "message": "verification required"}}))

    result, exit_code = read_public_answer_api(ANSWER_URL, http_session=session, active_profile="research")

    assert exit_code == EXIT_BLOCKED
    assert result["status"] == "blocked_human_verification"
    assert result["error_code"] == 40352
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("payload", "reason_fragment"),
    [
        ({"id": "wrong", "content": "<p>text</p>"}, "requested answer content"),
        ({"id": "2066720705471836838", "content": ""}, "requested answer content"),
        (ValueError("invalid json"), "not valid JSON"),
    ],
)
def test_http_200_incomplete_payload_is_unreadable(payload, reason_fragment):
    session = FakeSession(FakeResponse(200, payload))

    result, exit_code = read_public_answer_api(ANSWER_URL, http_session=session, active_profile="research")

    assert exit_code == EXIT_UNREADABLE
    assert result["status"] == "unreadable"
    assert reason_fragment in result["reason"]
    assert len(session.calls) == 1


def test_top_level_answer_alias_exposes_api_json(monkeypatch):
    expected = {
        "status": "ok",
        "http_status": 200,
        "canonical_url": ANSWER_URL,
        "answer_id": "2066720705471836838",
        "endpoint": "answer-detail",
        "authenticated_profile": True,
        "content_chars": 42,
        "completeness": {
            "valid_json": True,
            "matching_answer_id": True,
            "nonempty_content": True,
            "api_payload_complete": True,
        },
    }
    monkeypatch.setattr(browse_commands, "read_public_answer_api", lambda *args, **kwargs: (expected, EXIT_OK))

    try:
        result = CliRunner().invoke(_build_cli(), ["answer", ANSWER_URL, "--api", "--json", "--metadata-only"])
    finally:
        set_json_mode(False)

    assert result.exit_code == EXIT_OK, result.output
    assert json.loads(result.output) == expected


def test_api_json_invalid_url_has_stable_exit_code():
    try:
        result = CliRunner().invoke(
            _build_cli(),
            ["answer", "https://example.com/question/1/answer/2", "--api", "--json"],
        )
    finally:
        set_json_mode(False)

    assert result.exit_code == EXIT_INVALID_INPUT
    assert json.loads(result.output)["status"] == "cli_error"
