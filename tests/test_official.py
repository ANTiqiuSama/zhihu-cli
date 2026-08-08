from __future__ import annotations

import hashlib
import json
import zipfile

import click
import pytest
from click.testing import CliRunner

from zhihu_cli import official as official_module
from zhihu_cli.commands import official as official_command
from zhihu_cli.commands.official import register_official
from zhihu_cli.official import OfficialCliError


def _build_cli() -> click.Group:
    @click.group()
    def root() -> None:
        pass

    register_official(root)
    return root


def test_official_command_forwards_unknown_options(monkeypatch, tmp_path):
    binary = tmp_path / "zhihu-cli.exe"
    binary.write_bytes(b"binary")
    captured = {}
    monkeypatch.setattr(official_command, "resolve_official_binary", lambda: binary)

    def fake_run(resolved, arguments):
        captured["binary"] = resolved
        captured["arguments"] = arguments
        return 0

    monkeypatch.setattr(official_command, "_run_official", fake_run)
    result = CliRunner().invoke(
        _build_cli(),
        ["official", "search", "zhihu", "--query", "科研自动化", "--count", "5", "--pretty"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "binary": binary,
        "arguments": ("search", "zhihu", "--query", "科研自动化", "--count", "5", "--pretty"),
    }


@pytest.mark.parametrize(
    "arguments",
    [
        ["official", "auth", "set", "zh-secret-value"],
        ["official", "auth", "set", "zh-secret-value", "--secret-stdin"],
        ["official", "init", "--secret", "zh-secret-value"],
        ["official", "init", "--secret=zh-secret-value"],
    ],
)
def test_official_command_refuses_secret_in_process_arguments(arguments):
    result = CliRunner().invoke(_build_cli(), arguments)

    assert result.exit_code == 2
    assert "Refusing to place an Access Secret" in result.output


def test_official_command_allows_secret_stdin_mode(monkeypatch, tmp_path):
    binary = tmp_path / "zhihu-cli.exe"
    binary.write_bytes(b"binary")
    captured = {}
    monkeypatch.setattr(official_command, "resolve_official_binary", lambda: binary)
    monkeypatch.setattr(
        official_command,
        "_run_official",
        lambda resolved, arguments: captured.update(binary=resolved, arguments=arguments) or 0,
    )

    result = CliRunner().invoke(_build_cli(), ["official", "auth", "set", "--secret-stdin"])

    assert result.exit_code == 0, result.output
    assert captured["arguments"] == ("auth", "set", "--secret-stdin")


def test_resolver_does_not_search_path(monkeypatch, tmp_path):
    monkeypatch.delenv("ZHIHU_OFFICIAL_CLI", raising=False)
    monkeypatch.setattr(official_module, "official_cli_home", lambda: tmp_path / "missing")
    monkeypatch.setattr(official_module, "official_platform_key", lambda: "windows-amd64")

    assert official_module.resolve_official_binary(required=False) is None
    with pytest.raises(OfficialCliError, match="official CLI is not installed"):
        official_module.resolve_official_binary()


def test_windows_home_ignores_store_python_localappdata_virtualization(monkeypatch, tmp_path):
    user_profile = tmp_path / "user"
    monkeypatch.delenv("ZHIHU_CLI_HOME", raising=False)
    monkeypatch.setenv("USERPROFILE", str(user_profile))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "package" / "LocalCache" / "Local"))
    monkeypatch.setattr(official_module.platform, "system", lambda: "Windows")

    assert official_module.official_cli_home() == user_profile / "AppData" / "Local" / "ZhihuCLI"


def test_artifact_rejects_non_official_host():
    manifest = {
        "cli": {
            "latest_version": "0.2.0",
            "artifacts": {
                "windows-amd64": {
                    "url": "https://example.com/zhihu-cli.zip",
                    "sha256": "a" * 64,
                    "size": 10,
                }
            },
        }
    }

    with pytest.raises(OfficialCliError, match="host differs"):
        official_module._artifact_for_platform(manifest, "windows-amd64")


def test_artifact_rejects_nonstandard_https_port():
    manifest = {
        "cli": {
            "latest_version": "0.2.0",
            "artifacts": {
                "windows-amd64": {
                    "url": "https://developer-cdn.zhihu.com:444/zhihu-cli.zip",
                    "sha256": "a" * 64,
                    "size": 10,
                }
            },
        }
    }

    with pytest.raises(OfficialCliError, match="standard HTTPS port"):
        official_module._artifact_for_platform(manifest, "windows-amd64")


def test_extract_official_binary_rejects_duplicate_entries(tmp_path):
    archive_path = tmp_path / "zhihu-cli.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("zhihu-cli.exe", b"one")
        archive.writestr("nested/zhihu-cli.exe", b"two")

    with pytest.raises(OfficialCliError, match="exactly one"):
        official_module._extract_official_binary(
            archive_path,
            tmp_path / "out.exe",
            platform_key="windows-amd64",
        )


def test_extract_official_skill_rejects_unsafe_paths(tmp_path):
    archive_path = tmp_path / "zhihu-skill.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("zhihu/SKILL.md", "---\nname: zhihu\ndescription: test\n---\n")
        archive.writestr(
            "zhihu/manifest.json",
            json.dumps({"package": "zhihu-cli-skill", "skill": "zhihu", "version": "0.2.1"}),
        )
        archive.writestr("zhihu/scripts/run.ps1", "Write-Output ok\n")
        archive.writestr("zhihu/../outside.txt", "unsafe")

    with pytest.raises(OfficialCliError, match="unsafe path"):
        official_module._extract_official_skill(
            archive_path,
            tmp_path / "extract",
            expected_version="0.2.1",
        )


def test_install_official_cli_verifies_and_installs(monkeypatch, tmp_path):
    binary_bytes = b"verified official binary"
    archive_source = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_source, "w") as archive:
        archive.writestr("zhihu-cli.exe", binary_bytes)
    archive_bytes = archive_source.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "cli": {
            "latest_version": "0.2.0",
            "artifacts": {
                "windows-amd64": {
                    "url": "https://developer-cdn.zhihu.com/releases/zhihu-cli.zip",
                    "sha256": archive_hash,
                    "size": len(archive_bytes),
                }
            },
        },
    }
    home = tmp_path / "home"
    monkeypatch.setattr(official_module, "official_platform_key", lambda: "windows-amd64")
    monkeypatch.setattr(official_module, "official_cli_home", lambda: home)
    monkeypatch.setattr(official_module, "_fetch_manifest", lambda url: manifest)
    monkeypatch.setattr(
        official_module,
        "_download_bytes",
        lambda url, max_bytes: archive_bytes,
    )
    monkeypatch.setattr(official_module, "read_official_version", lambda binary: "0.2.0")

    def fake_install(staged_binary, install_home, version, platform_key):
        version_target = install_home / "versions" / version / "zhihu-cli.exe"
        current_target = install_home / "current" / "zhihu-cli.exe"
        version_target.parent.mkdir(parents=True)
        current_target.parent.mkdir(parents=True)
        version_target.write_bytes(staged_binary.read_bytes())
        current_target.write_bytes(staged_binary.read_bytes())
        return current_target

    monkeypatch.setattr(official_module, "_install_staged_binary", fake_install)

    result = official_module.install_official_cli()

    installed = home / "current" / "zhihu-cli.exe"
    assert result == {
        "ok": True,
        "installed": True,
        "reused_cli": False,
        "version": "0.2.0",
        "binary_path": str(installed.resolve()),
        "archive_sha256": archive_hash,
    }
    assert installed.read_bytes() == binary_bytes
    assert (home / "versions" / "0.2.0" / "zhihu-cli.exe").read_bytes() == binary_bytes


def test_install_reuses_valid_local_binary_without_network(monkeypatch, tmp_path):
    current = tmp_path / "home" / "current" / "zhihu-cli.exe"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"existing")
    monkeypatch.setattr(official_module, "official_platform_key", lambda: "windows-amd64")
    monkeypatch.setattr(official_module, "official_cli_home", lambda: tmp_path / "home")
    monkeypatch.setattr(official_module, "read_official_version", lambda binary: "0.2.0")

    def fail_fetch(url):
        raise AssertionError("network should not be used for a valid existing install")

    monkeypatch.setattr(official_module, "_fetch_manifest", fail_fetch)

    assert official_module.install_official_cli() == {
        "ok": True,
        "installed": False,
        "reused_cli": True,
        "version": "0.2.0",
        "binary_path": str(current.resolve()),
    }


def test_install_official_skill_verifies_installs_and_adds_windows_bom(monkeypatch, tmp_path):
    archive_source = tmp_path / "skill-source.zip"
    package_manifest = {"package": "zhihu-cli-skill", "skill": "zhihu", "version": "0.2.1"}
    with zipfile.ZipFile(archive_source, "w") as archive:
        archive.writestr("zhihu/SKILL.md", "---\nname: zhihu\ndescription: official test skill\n---\n")
        archive.writestr("zhihu/manifest.json", json.dumps(package_manifest))
        archive.writestr("zhihu/scripts/run.ps1", "# 中文注释\nWrite-Output ok\n")
        archive.writestr("zhihu/scripts/setup.ps1", "# 安装\nWrite-Output setup\n")
    archive_bytes = archive_source.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    release_manifest = {
        "schema_version": 1,
        "skill": {
            "latest_version": "0.2.1",
            "url": "https://developer-cdn.zhihu.com/releases/zhihu-cli-skill.zip",
            "sha256": archive_hash,
            "size": len(archive_bytes),
        },
    }
    skills_home = tmp_path / ".codex" / "skills"
    monkeypatch.setattr(official_module, "codex_skills_home", lambda: skills_home)
    monkeypatch.setattr(official_module, "_fetch_manifest", lambda url: release_manifest)
    monkeypatch.setattr(official_module, "_download_bytes", lambda url, max_bytes: archive_bytes)
    monkeypatch.setattr(official_module.platform, "system", lambda: "Windows")

    result = official_module.install_official_skill()

    installed = skills_home / "zhihu"
    assert result == {
        "ok": True,
        "installed": True,
        "reused_skill": False,
        "version": "0.2.1",
        "skill_path": str(installed.resolve()),
        "archive_sha256": archive_hash,
        "windows_powershell_utf8_compatible": True,
    }
    assert (installed / "SKILL.md").is_file()
    assert (installed / "scripts" / "run.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (installed / "scripts" / "setup.ps1").read_bytes().startswith(b"\xef\xbb\xbf")


def test_install_official_skill_reuses_valid_package_without_network(monkeypatch, tmp_path):
    installed = tmp_path / "skills" / "zhihu"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("---\nname: zhihu\ndescription: test\n---\n", encoding="utf-8")
    (installed / "manifest.json").write_text(
        json.dumps({"package": "zhihu-cli-skill", "skill": "zhihu", "version": "0.2.1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(official_module, "codex_skills_home", lambda: tmp_path / "skills")
    monkeypatch.setattr(
        official_module,
        "_fetch_manifest",
        lambda url: (_ for _ in ()).throw(AssertionError("network should not be used")),
    )

    assert official_module.install_official_skill() == {
        "ok": True,
        "installed": False,
        "reused_skill": True,
        "version": "0.2.1",
        "skill_path": str(installed.resolve()),
    }


def test_install_command_emits_json(monkeypatch):
    payload = {"ok": True, "installed": False, "version": "0.2.0"}
    monkeypatch.setattr(official_command, "install_official_cli", lambda force=False: payload)

    result = CliRunner().invoke(_build_cli(), ["official", "install"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload


def test_skill_install_command_emits_json(monkeypatch):
    payload = {"ok": True, "installed": True, "version": "0.2.1"}
    monkeypatch.setattr(official_command, "install_official_skill", lambda force=False: payload)

    result = CliRunner().invoke(_build_cli(), ["official", "skill", "install", "--force"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload
