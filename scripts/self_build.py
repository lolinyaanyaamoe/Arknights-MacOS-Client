#!/usr/bin/env -S uv run --locked --no-dev
# SPDX-License-Identifier: MPL-2.0

"""Prepare pinned personal source builds without an upstream binary fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from lib.common import BUILD_DIR, PROJECT_DIR, run_main
from lib.extract_runtime import extract
from lib.licenses import stage_runtime_legal
from runtime_config import load_runtime_config, runtime_is_valid

RUNTIME_COMMIT = "d9f41d20117cf53c97c7097ce33e0db156174d67"
MOLTENVK_COMMIT = "db66022459ffb663aa2b50f6b018bc2e124f5edf"
SPARKLE_COMMIT = "ac2def288cbff5cfc7df3ffef6abdf45b72bcb0a"


def source_commit(directory: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(directory), "rev-parse", "HEAD"], text=True
    ).strip()


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError(f"pinned source changed; expected exactly one {before!r}")
    return source.replace(before, after, 1)


def patch_runtime(directory: Path, moltenvk: Path) -> None:
    configuration = json.loads((PROJECT_DIR / "runtime.json").read_text())
    if source_commit(directory) != RUNTIME_COMMIT:
        raise ValueError("runtime checkout does not match the reviewed source pin")
    if configuration["provenance"]["buildCommit"] != RUNTIME_COMMIT:
        raise ValueError("runtime.json no longer matches the reviewed source pin")
    if configuration["provenance"]["moltenvkCommit"] != MOLTENVK_COMMIT:
        raise ValueError("MoltenVK pin changed")
    if not moltenvk.is_file():
        raise ValueError("source-built MoltenVK library is missing")
    script = directory / "scripts/build-canary.sh"
    text = script.read_text()
    text = replace_once(
        text,
        'base_archive="$(run_python "$repository_root/scripts/runtime.py" fetch-base)"',
        "# Personal clean build: never fetch the upstream precompiled base archive.",
    )
    text = replace_once(
        text,
        'tar -xzf "$base_archive" -C "$stage_root/base"',
        '[[ "$build_mode" == "--clean-release" ]] || exit 1\n'
        'mkdir -p "$stage_root/base/Libraries/Wine/lib"\n'
        'cp "$SELF_BUILD_MOLTENVK_LIBRARY" '
        '"$stage_root/base/Libraries/Wine/lib/libMoltenVK.dylib"',
    )
    text = replace_once(
        text,
        "runtime.lock.json:baseArtifact (SHA-256-pinned third-party base archive; not built from source)",
        f"KhronosGroup/MoltenVK@{MOLTENVK_COMMIT} (built from source in this workflow)",
    )
    script.write_text(text)
    (directory / "personal-source-build.patch").write_text(
        subprocess.check_output(
            ["git", "-C", str(directory), "diff", "--", "scripts/build-canary.sh"],
            text=True,
        )
    )


def stage_runtime(archive: Path) -> None:
    configuration_path = PROJECT_DIR / "runtime.json"
    configuration = load_runtime_config(configuration_path)
    layout = configuration.layout
    libraries = extract(archive, BUILD_DIR / "self-build/runtime-extracted")
    destination = BUILD_DIR / "runtime"
    if destination.exists():
        raise ValueError("runtime staging must start from an empty directory")
    shutil.move(libraries / layout.archive_wine_directory, destination)
    shutil.move(
        libraries / layout.archive_dxmt_directory,
        destination / layout.dxmt.payload_directory,
    )
    shutil.copyfile(
        libraries / layout.capability_manifest_path,
        destination / layout.capability_manifest_path,
    )
    if not stage_runtime_legal(libraries.parent, destination):
        raise ValueError("source-built runtime lacks its license bundle")
    if not runtime_is_valid(destination, layout):
        raise ValueError("source-built runtime failed layout validation")
    metadata = json.loads(configuration_path.read_text())
    with archive.open("rb") as stream:
        metadata["runtime"]["sha256"] = hashlib.file_digest(
            stream, "sha256"
        ).hexdigest()
    metadata["runtime"]["name"] += " (personal source build)"
    metadata["selfBuild"] = {
        "repository": os.environ["GITHUB_REPOSITORY"],
        "runID": os.environ["GITHUB_RUN_ID"],
        "runtimeSourceCommit": RUNTIME_COMMIT,
        "moltenvkSourceCommit": MOLTENVK_COMMIT,
        "upstreamRuntimeURLIsReferenceOnly": True,
    }
    configuration_path.write_text(json.dumps(metadata, indent=2) + "\n")


def configure_app() -> None:
    plist = PROJECT_DIR / "Resources/Info.plist"
    with plist.open("rb") as stream:
        metadata = plistlib.load(stream)
    metadata["SelfBuildDisablesLauncherUpdates"] = True
    metadata["CFBundleVersion"] = os.environ["GITHUB_RUN_NUMBER"]
    for key in ("SUFeedURL", "LauncherAnnouncementsURL"):
        metadata.pop(key, None)
    with plist.open("wb") as stream:
        plistlib.dump(metadata, stream, sort_keys=False)


def configure_sparkle(directory: Path, framework: Path) -> None:
    if source_commit(directory) != SPARKLE_COMMIT:
        raise ValueError("Sparkle source pin changed")
    destination = BUILD_DIR / "self-build/Sparkle"
    destination.mkdir(parents=True, exist_ok=True)
    pins = json.loads((PROJECT_DIR / "Package.resolved").read_text())["pins"]
    pin = next(pin for pin in pins if pin["identity"] == "sparkle")["state"]
    if pin["revision"] != SPARKLE_COMMIT:
        raise ValueError("Package.resolved no longer matches the Sparkle source pin")
    with (framework / "Resources/Info.plist").open("rb") as stream:
        if plistlib.load(stream)["CFBundleShortVersionString"] != pin["version"]:
            raise ValueError("source-built Sparkle has the wrong version")
    (destination / "source-pin.json").write_text(json.dumps(pin, indent=2) + "\n")
    subprocess.run(
        [
            "xcodebuild",
            "-create-xcframework",
            "-framework",
            str(framework),
            "-output",
            str(destination / "Sparkle.xcframework"),
        ],
        check=True,
    )
    (destination / "Package.swift").write_text(
        "// swift-tools-version:5.3\nimport PackageDescription\n"
        'let package = Package(name: "Sparkle", platforms: [.macOS(.v10_13)], '
        'products: [.library(name: "Sparkle", targets: ["Sparkle"])], '
        'targets: [.binaryTarget(name: "Sparkle", path: "Sparkle.xcframework")])\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    patch = subparsers.add_parser("patch-runtime")
    patch.add_argument("directory", type=Path)
    patch.add_argument("moltenvk", type=Path)
    stage = subparsers.add_parser("stage-runtime")
    stage.add_argument("archive", type=Path)
    subparsers.add_parser("configure-app")
    sparkle = subparsers.add_parser("configure-sparkle")
    sparkle.add_argument("directory", type=Path)
    sparkle.add_argument("framework", type=Path)
    arguments = parser.parse_args()
    match arguments.command:
        case "patch-runtime":
            patch_runtime(arguments.directory, arguments.moltenvk)
        case "stage-runtime":
            stage_runtime(arguments.archive)
        case "configure-app":
            configure_app()
        case "configure-sparkle":
            configure_sparkle(arguments.directory, arguments.framework)


if __name__ == "__main__":
    run_main(main)
