"""Tests for macOS startup scripts, installer workflows, and runtime definitions."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from blab.solvers.beat_engine_runtime import (
    BEAT_ENGINE_CPU_BACKEND,
    BEAT_ENGINE_METAL_BACKEND,
    DEFAULT_BEAT_ENGINE_METAL_PROJECT,
    normalize_beat_engine_backend,
)
from blab.ui.diagnostics import _system_ram_text
from repo_paths import REPO_ROOT


def test_macos_scripts_exist_and_are_executable():
    scripts = [
        REPO_ROOT / "01_install_update_boundary-lab.sh",
        REPO_ROOT / "01_install_update_boundary-lab.command",
        REPO_ROOT / "02_start_boundary_lab.sh",
        REPO_ROOT / "02_start_boundary_lab.command",
    ]
    for script in scripts:
        assert script.is_file(), f"Missing script: {script}"
        assert os.access(script, os.X_OK), f"Script not executable: {script}"


def test_macos_scripts_bash_syntax():
    scripts = [
        str(REPO_ROOT / "01_install_update_boundary-lab.sh"),
        str(REPO_ROOT / "01_install_update_boundary-lab.command"),
        str(REPO_ROOT / "02_start_boundary_lab.sh"),
        str(REPO_ROOT / "02_start_boundary_lab.command"),
    ]
    result = subprocess.run(["bash", "-n", *scripts], capture_output=True, text=True)
    assert result.returncode == 0, f"Bash syntax check failed:\n{result.stderr}"


def test_macos_metal_runtime_definitions():
    assert DEFAULT_BEAT_ENGINE_METAL_PROJECT.name == "julia_metal"
    assert normalize_beat_engine_backend("metal") == BEAT_ENGINE_METAL_BACKEND
    assert normalize_beat_engine_backend("beat_metal") == BEAT_ENGINE_METAL_BACKEND
    assert normalize_beat_engine_backend("apple_metal") == BEAT_ENGINE_METAL_BACKEND


def test_macos_backend_default_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert normalize_beat_engine_backend(None) == BEAT_ENGINE_CPU_BACKEND
    assert normalize_beat_engine_backend("") == BEAT_ENGINE_CPU_BACKEND


def test_system_ram_text_on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    text = _system_ram_text()
    assert text != "unknown"
    assert "GiB" in text


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture
def fake_git_checkout(tmp_path: Path):
    remote = tmp_path / "remote_repo"
    remote.mkdir()
    git(remote, "init", "-b", "main")
    git(remote, "config", "user.name", "Test User")
    git(remote, "config", "user.email", "test@example.com")
    (remote / "pyproject.toml").write_text("[project]\nname='test'\n")
    (remote / "src" / "blab").mkdir(parents=True)
    (remote / "src" / "blab" / "__init__.py").write_text("")
    (remote / "version.txt").write_text("v1.0.0")
    git(remote, "add", ".")
    git(remote, "commit", "-m", "v1.0.0 commit")
    git(remote, "tag", "v1.0.0")
    v1_hash = git(remote, "rev-parse", "HEAD")

    (remote / "version.txt").write_text("v1.1.0-dev")
    git(remote, "commit", "-am", "dev commit")

    local = tmp_path / "user_checkout"
    subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)
    git(local, "config", "user.name", "Test User")
    git(local, "config", "user.email", "test@example.com")

    return local, v1_hash, str(remote)


def test_launcher_checks_for_venv(tmp_path: Path):
    import shutil

    launcher = REPO_ROOT / "02_start_boundary_lab.sh"
    # Run launcher pointing to empty folder without .venv
    dummy_repo = tmp_path / "empty_repo"
    dummy_repo.mkdir()
    (dummy_repo / "pyproject.toml").write_text("[project]\nname='test'\n")
    (dummy_repo / "src" / "blab").mkdir(parents=True)
    dummy_launcher = dummy_repo / launcher.name
    shutil.copy(launcher, dummy_launcher)
    dummy_launcher.chmod(0o755)

    result = subprocess.run([str(dummy_launcher)], cwd=dummy_repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ERROR: Boundary Lab is not installed in this checkout" in result.stdout or "ERROR" in result.stderr


def test_launcher_missing_project(tmp_path: Path):
    import shutil

    launcher = REPO_ROOT / "02_start_boundary_lab.sh"
    dummy_dir = tmp_path / "standalone_dir"
    dummy_dir.mkdir()
    dummy_launcher = dummy_dir / launcher.name
    shutil.copy(launcher, dummy_launcher)
    dummy_launcher.chmod(0o755)

    result = subprocess.run([str(dummy_launcher)], cwd=dummy_dir, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ERROR: Could not find the Boundary Lab project folder" in result.stdout or "ERROR" in result.stderr


def test_installer_folder_collision(tmp_path: Path):
    import shutil

    installer = REPO_ROOT / "01_install_update_boundary-lab.sh"
    dummy_dir = tmp_path / "standalone_install"
    dummy_dir.mkdir()
    # Create an invalid boundary-lab directory (not a checkout)
    (dummy_dir / "boundary-lab").mkdir()
    dummy_installer = dummy_dir / installer.name
    shutil.copy(installer, dummy_installer)
    dummy_installer.chmod(0o755)

    result = subprocess.run([str(dummy_installer)], cwd=dummy_dir, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ERROR: The folder exists but is not a Boundary Lab checkout" in result.stdout or "ERROR" in result.stderr


def test_show_native_error_box_on_macos(monkeypatch):
    from blab.gui import _show_native_error_box

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)

    _show_native_error_box("Test Title", "Test Message\nSecond Line")
    assert len(calls) == 1
    cmd = calls[0][0]
    assert cmd[0] == "osascript"
    assert "Test Title" in cmd
    assert "Test Message\nSecond Line" in cmd


def test_desktop_runtime_macos_error_logging(tmp_path: Path, monkeypatch):
    from blab import desktop_runtime

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "stderr", None)

    # Calling main when _main raises will write to ~/Library/Logs/Boundary Lab/launcher.log
    def fake_main_raise():
        raise RuntimeError("Simulated startup explosion")

    monkeypatch.setattr(desktop_runtime, "_main", fake_main_raise)

    # Intercept osascript call
    osascript_called = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: osascript_called.append(cmd))

    with pytest.raises(SystemExit):
        desktop_runtime.main()

    log_file = fake_home / "Library/Logs/Boundary Lab/launcher.log"
    assert log_file.is_file(), f"Expected log file {log_file} to exist"
    log_content = log_file.read_text()
    assert "Simulated startup explosion" in log_content
    assert len(osascript_called) == 1
    assert "Boundary Lab could not start" in osascript_called[0][-1]


def test_startup_log_path_on_macos(monkeypatch, tmp_path):
    from blab.gui import _startup_log_path

    fake_home = tmp_path / "fake_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "platform", "darwin")

    log_path = _startup_log_path()
    assert log_path.parent == fake_home / "Library/Logs/Boundary Lab"
    assert log_path.name.startswith("startup-")
    assert log_path.suffix == ".log"


def test_check_metal_runs_and_displays_dialog(tmp_path: Path, monkeypatch):
    from blab import desktop_runtime

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "platform", "darwin")

    osascript_calls = []

    def fake_run(cmd, **kwargs):
        if cmd[0] == "osascript":
            osascript_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        # Pretend julia succeeded
        return subprocess.CompletedProcess(cmd, 0, stdout="Apple Metal 3.0", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    dummy_root = tmp_path / "dummy_root"
    dummy_root.mkdir()
    success = desktop_runtime.check_metal(dummy_root)
    assert success is True

    metal_log = fake_home / "Library/Logs/Boundary Lab/metal-check.log"
    assert metal_log.is_file()
    assert "Apple Metal 3.0" in metal_log.read_text()
    assert len(osascript_calls) == 1
    assert "Apple Metal is ready" in osascript_calls[0][-1]


def test_git_update_flow_checks_dirty_and_dev_branches(fake_git_checkout: tuple[Path, str, str], tmp_path: Path):
    local, _v1_hash, remote = fake_git_checkout

    # Test dev branch protection
    git(local, "checkout", "-b", "feature-branch")
    installer = REPO_ROOT / "01_install_update_boundary-lab.sh"
    dummy_installer = local / installer.name
    import shutil

    shutil.copy(installer, dummy_installer)
    dummy_installer.chmod(0o755)

    test_env = dict(
        os.environ,
        BLAB_INTERNAL_RUN="1",
        BLAB_ORIGINAL_DIR=str(local),
        BLAB_REPO_URL=str(remote),
        BLAB_SKIP_PYTHON_SETUP="1",
    )

    # Answer 'y' to prompt
    result = subprocess.run(
        [str(dummy_installer)],
        input="y\n",
        cwd=local,
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert "Development branches must be managed manually" in result.stdout

    # Test dirty checkout protection
    git(local, "checkout", "main")
    (local / "version.txt").write_text("dirty edit")
    result = subprocess.run(
        [str(dummy_installer)],
        input="y\n",
        cwd=local,
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert "Tracked files contain local changes" in result.stdout

    # Test clean checkout update to stable release tag
    git(local, "checkout", "--", "version.txt")
    result = subprocess.run(
        [str(dummy_installer)],
        input="y\n",
        cwd=local,
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert "Checking out stable release v1.0.0" in result.stdout
    assert git(local, "describe", "--tags", "HEAD") == "v1.0.0"


def test_cross_platform_path_resolution():
    from blab.project.io import _is_absolute_path, _resolve_path_fields

    assert _is_absolute_path("C:/meshes/enclosure.msh") is True
    assert _is_absolute_path("D:\\meshes\\enclosure.msh") is True
    assert _is_absolute_path("/Users/user/mesh.msh") is True
    assert _is_absolute_path("meshes/enclosure.msh") is False

    payload = {"source_file": "C:/meshes/enclosure.msh"}
    _resolve_path_fields(payload, Path("/some/base/dir"), ("source_file",))
    assert payload["source_file"] == "C:/meshes/enclosure.msh"



