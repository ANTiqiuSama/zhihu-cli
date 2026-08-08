"""Secure installation and invocation helpers for Zhihu's official CLI."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

OFFICIAL_MANIFEST_URL = "https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/manifest.json"
_OFFICIAL_CDN_HOST = "developer-cdn.zhihu.com"
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
_MAX_SKILL_BYTES = 16 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OfficialCliError(RuntimeError):
    """Raised when the official CLI cannot be resolved, verified, or installed."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so a verified CDN request cannot change authority."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def official_platform_key() -> str:
    """Return the official release-manifest key for this machine."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "windows-amd64"
    if system == "darwin" and machine in {"amd64", "x86_64"}:
        return "darwin-amd64"
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-arm64"
    raise OfficialCliError(f"Zhihu's official CLI does not publish a build for {system}/{machine}.")


def official_cli_home() -> Path:
    """Return the install root used by Zhihu's official Skill."""
    override = os.environ.get("ZHIHU_CLI_HOME")
    if override:
        return Path(override).expanduser()

    if platform.system().lower() == "windows":
        # Microsoft Store Python virtualizes LOCALAPPDATA into the package's
        # LocalCache. The official PowerShell Skill does not run in that
        # package context, so anchor to USERPROFILE/Path.home() to share its
        # real install location instead of maintaining two binary copies.
        user_profile = os.environ.get("USERPROFILE")
        user_home = Path(user_profile) if user_profile else Path.home()
        return user_home / "AppData" / "Local" / "ZhihuCLI"

    if platform.system().lower() == "darwin":
        return Path.home() / "Library" / "Application Support" / "zhihu-cli"

    return Path.home() / ".local" / "share" / "zhihu-cli"


def official_binary_name(platform_key: str | None = None) -> str:
    """Return the platform-specific official executable name."""
    key = platform_key or official_platform_key()
    return "zhihu-cli.exe" if key.startswith("windows-") else "zhihu-cli"


def codex_skills_home() -> Path:
    """Return the user-level Codex skills directory."""
    codex_home = os.environ.get("CODEX_HOME")
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return root / "skills"


def resolve_official_skill(*, required: bool = True) -> Path | None:
    """Return the installed official Zhihu Skill directory."""
    destination = codex_skills_home() / "zhihu"
    if destination.is_dir() and (destination / "SKILL.md").is_file():
        return destination.resolve()
    if required:
        raise OfficialCliError("Zhihu's official Codex Skill is not installed. Run `zhihu-cli official skill install`.")
    return None


def resolve_official_binary(*, required: bool = True) -> Path | None:
    """Resolve only explicit or official-Skill paths, never PATH.

    Searching PATH would find this community wrapper under the same executable
    name and could recursively execute itself.
    """
    explicit = os.environ.get("ZHIHU_OFFICIAL_CLI")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    try:
        candidates.append(official_cli_home() / "current" / official_binary_name())
    except OfficialCliError:
        pass

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    if required:
        raise OfficialCliError(
            "Zhihu's official CLI is not installed. Run `zhihu-cli official install`, "
            "or set ZHIHU_OFFICIAL_CLI to its absolute path."
        )
    return None


def _validated_https_url(url: str, *, expected_host: str | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise OfficialCliError("Official release URLs must use credential-free HTTPS.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise OfficialCliError("Official release URL has an invalid port.") from exc
    if port not in {None, 443}:
        raise OfficialCliError("Official release URLs must use the standard HTTPS port.")
    if expected_host and parsed.hostname.lower() != expected_host.lower():
        raise OfficialCliError("Official artifact host differs from the trusted manifest host.")
    return url


def _download_bytes(url: str, *, max_bytes: int) -> bytes:
    _validated_https_url(url, expected_host=_OFFICIAL_CDN_HOST)
    request = Request(url, headers={"User-Agent": "zhihu-cli-community-official-provider/0.3"})
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise OfficialCliError("Official release response exceeds the allowed size.")
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        raise OfficialCliError(f"Official release download failed with HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise OfficialCliError(f"Official release download failed: {exc}") from exc
    if len(data) > max_bytes:
        raise OfficialCliError("Official release response exceeds the allowed size.")
    return data


def _fetch_manifest(url: str) -> dict[str, Any]:
    raw = _download_bytes(url, max_bytes=_MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialCliError("Official release manifest is invalid JSON.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise OfficialCliError("Official release manifest schema is unsupported.")
    return manifest


def _artifact_for_platform(manifest: dict[str, Any], platform_key: str) -> tuple[str, str, int, str]:
    try:
        version = str(manifest["cli"]["latest_version"])
        artifact = manifest["cli"]["artifacts"][platform_key]
        url = str(artifact["url"])
        sha256 = str(artifact["sha256"]).lower()
        size = int(artifact["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OfficialCliError(f"Official release manifest lacks a valid {platform_key} artifact.") from exc

    _validated_https_url(url, expected_host=_OFFICIAL_CDN_HOST)
    if not _SHA256_RE.fullmatch(sha256) or not 0 < size <= _MAX_ARTIFACT_BYTES:
        raise OfficialCliError("Official artifact integrity fields are invalid.")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise OfficialCliError("Official CLI version is invalid.")
    return version, url, size, sha256


def _skill_artifact(manifest: dict[str, Any]) -> tuple[str, str, int, str]:
    try:
        skill = manifest["skill"]
        version = str(skill["latest_version"])
        url = str(skill["url"])
        sha256 = str(skill["sha256"]).lower()
        size = int(skill["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OfficialCliError("Official release manifest lacks a valid Skill artifact.") from exc

    _validated_https_url(url, expected_host=_OFFICIAL_CDN_HOST)
    if not url.lower().endswith(".zip"):
        raise OfficialCliError("Official Skill artifact must be a ZIP archive.")
    if not _SHA256_RE.fullmatch(sha256) or not 0 < size <= _MAX_SKILL_BYTES:
        raise OfficialCliError("Official Skill integrity fields are invalid.")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise OfficialCliError("Official Skill version is invalid.")
    return version, url, size, sha256


def _write_verified_artifact(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int = _MAX_ARTIFACT_BYTES,
) -> None:
    data = _download_bytes(url, max_bytes=max_bytes)
    if len(data) != expected_size:
        raise OfficialCliError("Official artifact size does not match the release manifest.")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise OfficialCliError("Official artifact SHA-256 does not match the release manifest.")
    destination.write_bytes(data)


def _extract_official_skill(archive_path: Path, destination_root: Path, *, expected_version: str) -> Path:
    """Extract one verified `zhihu/` Skill tree without trusting ZIP paths."""
    seen: set[str] = set()
    total_size = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if not entries:
            raise OfficialCliError("Official Skill archive is empty.")
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "zhihu":
                raise OfficialCliError("Official Skill archive contains an unsafe path.")
            normalized = path.as_posix().rstrip("/")
            if normalized in seen:
                raise OfficialCliError("Official Skill archive contains duplicate paths.")
            seen.add(normalized)
            mode = entry.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise OfficialCliError("Official Skill archive must not contain symbolic links.")
            if entry.file_size < 0 or entry.file_size > _MAX_SKILL_BYTES:
                raise OfficialCliError("Official Skill archive entry is too large.")
            total_size += entry.file_size
            if total_size > _MAX_SKILL_BYTES:
                raise OfficialCliError("Official Skill archive expands beyond the allowed size.")

        required = {"zhihu/SKILL.md", "zhihu/manifest.json", "zhihu/scripts/run.ps1"}
        if not required.issubset(seen):
            raise OfficialCliError("Official Skill archive is missing required files.")

        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            target = destination_root.joinpath(*path.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    skill_dir = destination_root / "zhihu"
    try:
        package_manifest = json.loads((skill_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialCliError("Official Skill package manifest is invalid.") from exc
    if (
        package_manifest.get("package") != "zhihu-cli-skill"
        or package_manifest.get("skill") != "zhihu"
        or str(package_manifest.get("version")) != expected_version
    ):
        raise OfficialCliError("Official Skill package identity does not match the release manifest.")
    return skill_dir


def _add_utf8_bom_to_powershell_scripts(skill_dir: Path) -> bool:
    """Make UTF-8 scripts readable by Windows PowerShell 5.1 without changing text."""
    changed = False
    for script in (skill_dir / "scripts").glob("*.ps1"):
        raw = script.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OfficialCliError(f"Official Skill script is not valid UTF-8: {script.name}") from exc
        script.write_bytes(b"\xef\xbb\xbf" + raw)
        changed = True
    return changed


def _installed_skill_version(destination: Path) -> str | None:
    try:
        package_manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if package_manifest.get("package") != "zhihu-cli-skill" or package_manifest.get("skill") != "zhihu":
        return None
    version = str(package_manifest.get("version", ""))
    return version if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version) else None


def _replace_skill_directory(staged_skill: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise OfficialCliError("Refusing to replace a symbolic-link Skill destination.")

    with tempfile.TemporaryDirectory(prefix=".zhihu-skill-backup-", dir=destination.parent) as backup_dir:
        backup = Path(backup_dir) / "zhihu"
        had_existing = destination.exists()
        if had_existing:
            os.replace(destination, backup)
        try:
            os.replace(staged_skill, destination)
        except OSError:
            if had_existing and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise


def install_official_skill(
    *,
    force: bool = False,
    manifest_url: str = OFFICIAL_MANIFEST_URL,
) -> dict[str, Any]:
    """Install the verified official Zhihu Skill into the user-level Codex directory."""
    _validated_https_url(manifest_url, expected_host=_OFFICIAL_CDN_HOST)
    destination = codex_skills_home() / "zhihu"
    existing_version = _installed_skill_version(destination)
    if existing_version and not force:
        return {
            "ok": True,
            "installed": False,
            "reused_skill": True,
            "version": existing_version,
            "skill_path": str(destination.resolve()),
        }
    if destination.exists() and not force:
        raise OfficialCliError(
            "A non-official or invalid `zhihu` Skill already exists. "
            "Review it before using `zhihu-cli official skill install --force`."
        )

    manifest = _fetch_manifest(manifest_url)
    version, artifact_url, expected_size, expected_sha256 = _skill_artifact(manifest)
    skills_home = codex_skills_home()
    skills_home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zhihu-skill-install-", dir=skills_home) as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / "zhihu-cli-skill.zip"
        extraction_root = temp_root / "extracted"
        extraction_root.mkdir()
        _write_verified_artifact(
            artifact_url,
            archive_path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            max_bytes=_MAX_SKILL_BYTES,
        )
        staged_skill = _extract_official_skill(archive_path, extraction_root, expected_version=version)
        powershell_compatibility = False
        if platform.system().lower() == "windows":
            powershell_compatibility = _add_utf8_bom_to_powershell_scripts(staged_skill)
        _replace_skill_directory(staged_skill, destination)

    return {
        "ok": True,
        "installed": True,
        "reused_skill": False,
        "version": version,
        "skill_path": str(destination.resolve()),
        "archive_sha256": expected_sha256,
        "windows_powershell_utf8_compatible": powershell_compatibility,
    }


def _safe_archive_member(name: str, binary_name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and path.name == binary_name


def _extract_official_binary(archive_path: Path, destination: Path, *, platform_key: str) -> None:
    binary_name = official_binary_name(platform_key)
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                entry
                for entry in archive.infolist()
                if not entry.is_dir() and _safe_archive_member(entry.filename, binary_name)
            ]
            if len(matches) != 1 or matches[0].file_size > _MAX_ARTIFACT_BYTES:
                raise OfficialCliError(f"Official archive must contain exactly one valid {binary_name}.")
            with archive.open(matches[0]) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    elif archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, mode="r:gz") as archive:
            matches = [
                member
                for member in archive.getmembers()
                if member.isfile() and _safe_archive_member(member.name, binary_name)
            ]
            if len(matches) != 1 or matches[0].size > _MAX_ARTIFACT_BYTES:
                raise OfficialCliError(f"Official archive must contain exactly one valid {binary_name}.")
            source = archive.extractfile(matches[0])
            if source is None:
                raise OfficialCliError(f"Unable to extract {binary_name} from the official archive.")
            with source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    else:
        raise OfficialCliError("Official artifact archive type is unsupported.")

    if not platform_key.startswith("windows-"):
        destination.chmod(0o755)


def read_official_version(binary: Path) -> str:
    """Run the official binary's self-reporting version command."""
    try:
        result = subprocess.run(
            [str(binary), "version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfficialCliError(f"Downloaded official CLI cannot run: {exc}") from exc
    if result.returncode != 0:
        raise OfficialCliError("Downloaded official CLI failed its version self-check.")
    try:
        payload = json.loads(result.stdout)
        version = str(payload["version"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise OfficialCliError("Downloaded official CLI returned invalid version JSON.") from exc
    return version


def _install_staged_binary(staged_binary: Path, home: Path, version: str, *, platform_key: str) -> Path:
    binary_name = official_binary_name(platform_key)
    version_dir = home / "versions" / version
    current_dir = home / "current"
    version_target = version_dir / binary_name
    current = current_dir / binary_name

    if platform_key.startswith("windows-"):
        # Store-packaged Python virtualizes writes to LocalAppData. Run the
        # final copy in PowerShell so this bridge and Zhihu's official Skill
        # share the real %USERPROFILE%\AppData\Local\ZhihuCLI location.
        script = (
            "$ErrorActionPreference='Stop'; "
            "$source=$env:ZHIHU_OFFICIAL_INSTALL_SOURCE; "
            "$versionDir=$env:ZHIHU_OFFICIAL_INSTALL_VERSION_DIR; "
            "$currentDir=$env:ZHIHU_OFFICIAL_INSTALL_CURRENT_DIR; "
            "$name=$env:ZHIHU_OFFICIAL_INSTALL_BINARY_NAME; "
            "New-Item -ItemType Directory -Force -Path $versionDir,$currentDir | Out-Null; "
            "Copy-Item -LiteralPath $source -Destination (Join-Path $versionDir $name) -Force; "
            "Copy-Item -LiteralPath (Join-Path $versionDir $name) "
            "-Destination (Join-Path $currentDir $name) -Force"
        )
        install_env = os.environ.copy()
        install_env.update(
            {
                "ZHIHU_OFFICIAL_INSTALL_SOURCE": str(staged_binary.resolve()),
                "ZHIHU_OFFICIAL_INSTALL_VERSION_DIR": str(version_dir),
                "ZHIHU_OFFICIAL_INSTALL_CURRENT_DIR": str(current_dir),
                "ZHIHU_OFFICIAL_INSTALL_BINARY_NAME": binary_name,
            }
        )
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=install_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficialCliError(f"Unable to install the official CLI with PowerShell: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "PowerShell copy failed"
            raise OfficialCliError(f"Unable to install the official CLI: {detail}")
        return current

    version_dir.mkdir(parents=True, exist_ok=True)
    current_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged_binary, version_target)
    version_target.chmod(0o755)
    staged_current = current_dir / f".{binary_name}.tmp"
    shutil.copy2(version_target, staged_current)
    staged_current.chmod(0o755)
    os.replace(staged_current, current)
    return current


def install_official_cli(*, force: bool = False, manifest_url: str = OFFICIAL_MANIFEST_URL) -> dict[str, Any]:
    """Install the latest official binary using its signed-by-transport manifest contract."""
    _validated_https_url(manifest_url, expected_host=_OFFICIAL_CDN_HOST)
    platform_key = official_platform_key()
    binary_name = official_binary_name(platform_key)
    home = official_cli_home()
    current = home / "current" / binary_name

    if current.is_file() and not force:
        try:
            current_version = read_official_version(current)
        except OfficialCliError:
            current_version = None
        if current_version:
            return {
                "ok": True,
                "installed": False,
                "reused_cli": True,
                "version": current_version,
                "binary_path": str(current.resolve()),
            }

    manifest = _fetch_manifest(manifest_url)
    version, artifact_url, expected_size, expected_sha256 = _artifact_for_platform(manifest, platform_key)
    with tempfile.TemporaryDirectory(prefix="zhihu-cli-official-") as temp_dir:
        temp_root = Path(temp_dir)
        archive_name = "zhihu-cli.zip" if artifact_url.endswith(".zip") else "zhihu-cli.tar.gz"
        archive_path = temp_root / archive_name
        staged_binary = temp_root / binary_name
        _write_verified_artifact(
            artifact_url,
            archive_path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        _extract_official_binary(archive_path, staged_binary, platform_key=platform_key)
        staged_version = read_official_version(staged_binary)
        if staged_version != version:
            raise OfficialCliError("Downloaded official CLI version does not match the release manifest.")

        current = _install_staged_binary(staged_binary, home, version, platform_key=platform_key)

    return {
        "ok": True,
        "installed": True,
        "reused_cli": False,
        "version": version,
        "binary_path": str(current.resolve()),
        "archive_sha256": expected_sha256,
    }
