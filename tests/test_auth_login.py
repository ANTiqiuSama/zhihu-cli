"""Authentication and QR persistence tests."""

from pathlib import Path

import pytest

from zhihu_cli.content.handlers import auth_login
from zhihu_cli.content.handlers.auth_login import (
    _detect_risk_control,
    _is_login_success,
    _print_qr,
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
