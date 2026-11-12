# Personal source build

Run **Actions → Personal source build → Run workflow** in this fork. The workflow builds the launcher, its compatibility shims, WineCX, DXMT, MoltenVK and its shader dependencies, and Sparkle. It uses fixed source commits. It keeps the upstream compatibility patches.

Download the `Arknights-Client-personal-source-build` artifact after all jobs pass. It contains a DMG, checksums, source identifiers, and build-time changes. Artifacts expire after three days. Intermediate runtime and framework artifacts include checksums. A failed source build stops the workflow. It never falls back to the launcher's precompiled runtime or Sparkle release archive.

The app disables launcher updates before Sparkle starts. It removes the upstream update and announcement URLs. Rebuild the app in this fork to update it. Official game downloads and game updates still use the publisher's services. The package is ad-hoc signed, not Apple-notarized. The workflow does not need a personal access token or signing secret. It creates no release and deploys no website.

## Source and trust boundaries

- Launcher: the workflow's exact commit in this fork.
- Runtime build recipe: `LuMiSxh/Arknights-MacOS-Runtime@d9f41d20117cf53c97c7097ce33e0db156174d67`.
- WineCX and DXMT: the commits and patches in that recipe's `runtime.lock.json`.
- MoltenVK: `KhronosGroup/MoltenVK@db66022459ffb663aa2b50f6b018bc2e124f5edf`. Its own revision files select its shader dependencies. The runtime's precompiled base-archive download is removed.
- Sparkle: `sparkle-project/Sparkle@ac2def288cbff5cfc7df3ffef6abdf45b72bcb0a`. A local Swift package links the framework compiled in this workflow.
- YouTubePlayerKit: compiled by SwiftPM from `Package.resolved`.

GitHub runners, Apple SDKs, compilers, Python packages, Homebrew tools, and Nix library caches remain external binary inputs. The runtime component inventory records Nix libraries. This workflow does not claim a bootstrap from source for every transitive dependency. Building reviewed source also does not prove that the source is safe.

The clean build changes the MoltenVK binary, so it needs manual game compatibility testing. Automated checks validate source, runtime layout, native unit and integration tests, signatures, and the DMG. They do not sign into an account or launch the game. Logs and source archives can be large; retain them only as long as needed.
