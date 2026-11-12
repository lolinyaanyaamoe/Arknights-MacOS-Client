# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import hashlib
import json
import plistlib
from pathlib import Path

import pytest
import self_build
from runtime_config import load_runtime_config
from test_download_runtime import write_runtime_archive


def test_personal_package_has_no_upstream_update_or_announcement_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resources = tmp_path / "Resources"
    resources.mkdir()
    plist = resources / "Info.plist"
    plist.write_bytes(
        plistlib.dumps(
            {
                "SUFeedURL": "https://example.com/update.xml",
                "LauncherAnnouncementsURL": "https://example.com/announcements.json",
                "SUPublicEDKey": "retained but unused",
            }
        )
    )
    monkeypatch.setattr(self_build, "PROJECT_DIR", tmp_path)
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "42")
    self_build.configure_app()
    metadata = plistlib.loads(plist.read_bytes())
    assert metadata["SelfBuildDisablesLauncherUpdates"] is True
    assert metadata["CFBundleVersion"] == "42"
    assert "SUFeedURL" not in metadata
    assert "LauncherAnnouncementsURL" not in metadata


@pytest.mark.parametrize("commit", [self_build.RUNTIME_COMMIT, "unreviewed"])
def test_runtime_patch_removes_binary_download_and_rejects_unknown_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit: str
) -> None:
    runtime = tmp_path / "runtime"
    scripts = runtime / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "build-canary.sh"
    original = (
        'base_archive="$(run_python "$repository_root/scripts/runtime.py" fetch-base)"\n'
        'tar -xzf "$base_archive" -C "$stage_root/base"\n'
        "runtime.lock.json:baseArtifact (SHA-256-pinned third-party base archive; not built from source)\n"
    )
    script.write_text(original)
    moltenvk = tmp_path / "libMoltenVK.dylib"
    moltenvk.touch()
    monkeypatch.setattr(self_build, "source_commit", lambda _: commit)
    monkeypatch.setattr(self_build.subprocess, "check_output", lambda *a, **kw: "diff")
    if commit != self_build.RUNTIME_COMMIT:
        with pytest.raises(ValueError, match="reviewed source pin"):
            self_build.patch_runtime(runtime, moltenvk)
        assert script.read_text() == original
    else:
        self_build.patch_runtime(runtime, moltenvk)
        assert "fetch-base" not in script.read_text()
        assert "SELF_BUILD_MOLTENVK_LIBRARY" in script.read_text()
        assert self_build.MOLTENVK_COMMIT in script.read_text()


def test_local_runtime_hash_and_provenance_follow_the_built_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_config = self_build.PROJECT_DIR / "runtime.json"
    layout = load_runtime_config(original_config).layout
    (tmp_path / "runtime.json").write_bytes(original_config.read_bytes())
    build = tmp_path / ".build"
    build.mkdir()
    archive = tmp_path / "runtime.tar.gz"
    write_runtime_archive(
        archive, tmp_path / "input", layout, manifest=b'{"schemaVersion":2}'
    )
    monkeypatch.setattr(self_build, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(self_build, "BUILD_DIR", build)
    monkeypatch.setattr(self_build, "stage_runtime_legal", lambda *a: True)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repository")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    self_build.stage_runtime(archive)
    metadata = json.loads((tmp_path / "runtime.json").read_text())
    assert (
        metadata["runtime"]["sha256"]
        == hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    assert metadata["selfBuild"]["repository"] == "owner/repository"
    assert metadata["selfBuild"]["runtimeSourceCommit"] == self_build.RUNTIME_COMMIT
    assert (build / "runtime/bin/wine64").is_file()
