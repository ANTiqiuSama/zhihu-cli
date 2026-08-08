"""Authentication and QR persistence tests."""

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from zhihu_cli.commands import auth as auth_commands
from zhihu_cli.commands.auth import register_auth
from zhihu_cli.content.handlers import auth_login
from zhihu_cli.content.handlers.auth_login import (
    EDGE_SEC_CH_UA,
    EDGE_USER_AGENT,
    _browser_identity,
    _desktop_headers,
    _detect_risk_control,
    _handle_risk_control,
    _is_login_success,
    _print_qr,
    _prompt_risk_control_verification,
    _resolve_browser,
    _resolve_qr_path,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "123"},
        {"userId": "123"},
        {"zC0": "cookie-value"},
        {"z_c0": "cookie-value"},
        {"access_token": "token"},
        {"success": True},
        {"logged_in": True},
        {"loginStatus": "CONFIRMED"},
        {"login_status": "login_success"},
    ],
)
def test_login_success_response_variants(payload):
    assert _is_login_success(payload)


def test_waiting_response_is_not_success():
    assert not _is_login_success({"status": 1})


def test_risk_control_40352_redirect():
    redirect = "https://www.zhihu.com/account/unhuman?example=1"
    payload = {"error": {"code": 40352, "need_login": True, "redirect": redirect}}
    assert _detect_risk_control(payload) == redirect


def test_qr_path_is_created(tmp_path: Path):
    output = _print_qr("https://example.com/login-token", tmp_path / "nested" / "login.png")
    assert output.exists()
    assert output.suffix == ".png"
    assert output.stat().st_size > 0


def test_default_qr_path_shape(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(auth_login, "DEFAULT_QR_PATH", tmp_path / ".zhihu-cli" / "login_qrcode.png")
    resolved = _resolve_qr_path(None)
    assert resolved == (tmp_path / ".zhihu-cli" / "login_qrcode.png").resolve()


def test_auto_browser_uses_windows_edge_default(monkeypatch):
    monkeypatch.setattr(auth_login, "get_user_agent", lambda: "")
    monkeypatch.setattr(auth_login, "_read_windows_https_progid", lambda: "MSEdgeHTM")

    assert _resolve_browser("auto") == "edge"


def test_auto_browser_uses_configured_edge_user_agent(monkeypatch):
    configured = EDGE_USER_AGENT.replace("145.0.0.0", "146.0.0.0")
    monkeypatch.setattr(auth_login, "get_user_agent", lambda: configured)
    monkeypatch.setattr(auth_login, "_read_windows_https_progid", lambda: "ChromeHTML")

    browser, user_agent, sec_ch_ua = _browser_identity("auto")

    assert browser == "edge"
    assert user_agent == configured
    assert sec_ch_ua == EDGE_SEC_CH_UA


def test_auto_browser_is_case_insensitive_for_library_callers(monkeypatch):
    monkeypatch.setattr(auth_login, "get_user_agent", lambda: EDGE_USER_AGENT)

    browser, user_agent, sec_ch_ua = _browser_identity("AUTO")

    assert browser == "edge"
    assert user_agent == EDGE_USER_AGENT
    assert sec_ch_ua == EDGE_SEC_CH_UA


def test_explicit_edge_identity_overrides_configured_chrome(monkeypatch):
    monkeypatch.setattr(auth_login, "get_user_agent", lambda: "Chrome/145.0.0.0")

    headers = _desktop_headers(browser="edge")

    assert "Edg/" in headers["User-Agent"]
    assert "Microsoft Edge" in headers["sec-ch-ua"]


def test_cookie_import_persists_explicit_edge_identity(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        auth_commands.cache_manager, "save_headers", lambda headers, profile_name=None: saved.update(headers)
    )
    monkeypatch.setattr(auth_commands.cache_manager, "get_active_profile", lambda: "test")
    monkeypatch.setattr(auth_commands, "reload_session", lambda: None)

    @click.group()
    def root():
        pass

    register_auth(root)
    result = CliRunner().invoke(
        root,
        ["auth", "cookie", "--cookie", "z_c0=test; d_c0=test", "--browser", "edge"],
    )

    assert result.exit_code == 0, result.output
    assert "Edg/" in saved["User-Agent"]


def test_noninteractive_risk_control_stops_before_opening_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(auth_login.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(auth_login, "_open_browser_url", lambda url, browser: opened.append(url))

    with pytest.raises(RuntimeError, match="user-visible terminal"):
        _prompt_risk_control_verification(object(), "https://www.zhihu.com/account/unhuman?session=test")

    assert opened == []


def test_second_risk_control_challenge_stops_without_prompt(monkeypatch):
    prompted = []
    monkeypatch.setattr(
        auth_login,
        "_prompt_risk_control_verification",
        lambda *args, **kwargs: prompted.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="after one human verification"):
        _handle_risk_control(
            object(),
            "https://www.zhihu.com/account/unhuman?session=test",
            2,
        )

    assert prompted == []
