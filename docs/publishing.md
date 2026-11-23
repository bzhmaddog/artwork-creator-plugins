# Publishing plugins

How a plugin goes from a commit to the Artwork Creator plugin manager. Short version:

```sh
# bump the version, commit, push
make check
make tag PLUGIN=halftone MSG="Line screen added"
git push origin halftone-0.2.0
# wait for the Release plugin workflow, then
git pull                      # brings back the plugins.json commit it made
```

## How it fits together

```
tag halftone-0.2.0 ──► Release plugin workflow
                        ├─ resolve   tag matches plugins/halftone and its version?
                        ├─ build     libhalftone.so (Linux, glibc 2.28) + halftone.dll (Windows)
                        ├─ publish   GitHub Release "halftone-0.2.0" with the files,
                        │            downloaded back to check their SHA-256
                        └─ index     plugins.json on main gets the new version
                                                  │
Artwork Creator ◄── fetches plugins.json ─────────┘
                    downloads a file, checks its size and SHA-256
```

- **`plugins/<id>/`** holds a plugin: its code and a `plugin.json` manifest.
- **`plugins.json`** is the index the app reads. Only the Release workflow adds versions to it.
- **Releases** hold the files. With release immutability on, a published release, its files
  and its tag can't change, so a URL in `plugins.json` always serves the bytes its hash
  describes.

## One-time setup

On GitHub, in the repository's settings:

1. *General > Releases*: turn on **release immutability**.
2. *Actions > General > Workflow permissions*: **Read and write permissions**, so the
   workflow can create releases and push `plugins.json`. If `main` has a branch
   protection rule or ruleset, let GitHub Actions bypass it.

Locally: `cargo` and `python3` (3.11+). For `make windows`, the
`x86_64-pc-windows-gnu` target and MinGW. For `make linux-portable`, zig and
cargo-zigbuild. See the top of the `Makefile`.

## Adding a new plugin

1. Create `plugins/<id>/`. The folder name is the plugin's id and the first part of its
   release tags: lowercase letters, digits and dashes.
2. Add the code:
   - **Rust**: a crate with `crate-type = ["cdylib"]` and
     `artwork-plugin-sdk = { workspace = true }`. Add `"plugins/<id>"` to `members` in
     the top `Cargo.toml` (CI fails if you forget).
   - **Python**: one script. If it needs packages, list them in a PEP 723 block at the
     top of the script; the release copies them into the index.
3. Add `plugins/<id>/plugin.json`. Copy one from another plugin of the same kind and
   change it:

   ```json
   {
     "id": "my-effect",
     "name": "My effect",
     "description": "What it does, in one line",
     "author": "bzhmaddog",
     "homepage": "https://github.com/bzhmaddog/artwork-creator-plugins/tree/main/plugins/my-effect",
     "license": "MIT",
     "kind": "python",
     "version": "1.0.0",
     "script": "my_effect.py",
     "min_app": "0.16.0",
     "sdk": "0.3.0",
     "effects": ["My effect"],
     "generators": ["My generator"]
   }
   ```

   `effects` and `generators` list the names the code exports (an Effect's or Generator's
   `name`), so the plugin manager can show them before the plugin is installed. Leave out a
   list that would be empty, and update them in the version that adds or removes one:
   `make validate` checks them against the code.

   A Rust plugin has `"kind": "library"` and no `version`, `script` or `sdk`: its version is
   the one in its `Cargo.toml`, and its ABI version is read from the SDK when it's released.
4. Try it in the app: install it from the plugin manager with `make serve` (see
   [Trying plugins before a release](#trying-plugins-before-a-release)).
5. Add tests: a Rust plugin's go in its crate (`#[cfg(test)]`), a Python plugin's in a
   `test_<plugin>.py` next to its script (`tests/plugin_testing.py` has the helpers; the
   release ships the script only).
6. `make check`, then commit and push or open a pull request. CI runs the same checks
   and tests, and builds on Linux and Windows.
7. Release it as below. The plugin shows up in `plugins.json` with its first release.

## Releasing a version

1. **Pull first.** Every release commits to `plugins.json` on `main`, so your copy may be
   behind: `git pull`.
2. **Bump the version**:
   - Rust: `version` in `plugins/<id>/Cargo.toml`, then `cargo update -p <id>` to update
     `Cargo.lock` (the builds and checks use `--locked` and fail until it matches).
   - Python: `version` in `plugins/<id>/plugin.json`. You can also update the version
     passed to `Plugin(...)` in the script to match.

   Raise `min_app` (and `sdk` for Python) if the new version needs a newer app. Use
   semantic versions, `X.Y.Z`.

   If the new version can't read what earlier versions saved (an effect's settings renamed
   or changed meaning, a generator removed), set `"compatible_from"` in `plugin.json` to the
   new version. It goes into the index with the version, and the app can warn before an
   update from anything older. Without it, the release carries over the previous
   version's `compatible_from` (a first release gets its own version), so every version
   in the index has one. Leaving it in `plugin.json` for the following versions does the
   same; raise it only at the next break: `make validate` fails if a version's `compatible_from` is older
   than an earlier version's.
3. **Check and push**: `make check`, commit, and push to `main`. Wait for CI to pass.
4. **Tag** the commit. The tag's message becomes the version's `changes`, shown in the
   plugin manager, so write it for users:

   ```sh
   make tag PLUGIN=halftone MSG="Line screen added"
   ```

   This runs the workflow's first check locally (the version isn't released yet), then
   creates the annotated tag `halftone-0.2.0`. Without make:
   `git tag -a halftone-0.2.0 -m "Line screen added"`.
5. **Push the tag**. This starts the release:

   ```sh
   git push origin halftone-0.2.0
   ```

6. **Watch** *Actions > Release plugin*. When it's done:
   - *Releases* has `halftone-0.2.0` with the files and their SHA-256 in its notes.
   - `main` has a commit "Index halftone-0.2.0" that adds the version to `plugins.json`.
7. **`git pull`** to get that commit before your next change.

Several plugins can be released at once. Each tag runs its own workflow, and their
`plugins.json` commits go in one after another.

## Trying plugins before a release

`make serve` runs a plugin repository on this machine, made from the working tree: the
same list the Release workflow would write, but with every file served by the local
server instead of a GitHub Release. Nothing needs to be committed, tagged or pushed.

```sh
make serve        # http://127.0.0.1:8765/plugins.json, Ctrl+C to stop
```

In the app's plugin manager, *Repositories* tab, add `http://127.0.0.1:8765/plugins.json`
(the app takes an `http://` address only for this machine), then install or update from
the *Plugins* tab.

- Every fetch of the list reads the manifests, rebuilds the Rust plugins (`cargo build`, a
  no-op when nothing changed) and hashes the files again, so an edit or a version bump shows
  up the next time the app reads the list, without restarting the server. A version bumped
  in a `Cargo.toml` is written into `Cargo.lock` on that fetch. A build error comes back as
  the error of the list, and in the server's output.
- Only the working tree's version of each plugin is listed. The app offers an update only
  to a higher version than the one installed, so bump the version to see a change as an
  update, or remove the plugin and install it again.
- The list is made from the manifests and builds only; the committed `plugins.json` isn't
  read. So a version has a `compatible_from` only when its manifest gives one; nothing is
  carried over from the previous version as a release would.
- A Rust plugin is built for Linux only by default (`SERVE_TARGETS`). For the app on
  Windows, reaching WSL's `localhost`, add the Windows build:
  `make serve SERVE_TARGETS="x86_64-unknown-linux-gnu x86_64-pc-windows-gnu"`. A file
  that hasn't been built is left out of the list.
- Another port: `make serve SERVE_PORT=9000`.

## When something goes wrong

**The workflow failed before publishing** (wrong version, build error). Nothing is
public: the files are at most on a draft release. Delete the tag, fix the problem, and tag
again:

```sh
git push --delete origin halftone-0.2.0
git tag -d halftone-0.2.0
# fix, commit, push, then make tag ... and git push origin halftone-0.2.0 again
```

A leftover draft is replaced on the next run. For a passing hiccup (a download timed
out), *Re-run failed jobs* on the run is enough.

**The release was published but `plugins.json` wasn't updated** (the *Update plugins.json*
job failed, for example on a protected `main`). Fix the cause and *Re-run failed jobs*.
Or add the entry by hand: download the run's `index-entry` artifact (`entry.json`), then:

```sh
python3 scripts/plugin_index.py merge entry.json
python3 scripts/plugin_index.py validate
git commit -am "Index halftone-0.2.0" && git push
```

**A published version is broken.** You can't replace its files or reuse its version.
Release a fix as the next version (`0.2.1`). To stop the app offering the broken one,
remove its entry from `versions` in `plugins.json`, set the plugin's `latest` to the
newest version left (`make validate` checks it), and commit that. This is the one
change to `plugins.json` made by hand. The release itself stays, so anyone who already
has the file can still check it.

## Moving to a newer app or SDK

Rust plugins build against the SDK at the app tag set in the top `Cargo.toml`
(`tag = "v0.16.0"`). To use a newer SDK:

1. Change the tag, then run `cargo update -p artwork-plugin-sdk` and `make check`.
2. Bump the version and `min_app` of each plugin that should move to it, and release them.
   A new SDK can raise the ABI version, which the release records as `abi`, next to
   `min_app`. The app uses both to tell which versions it can load.

The Linux build tools (glibc 2.28, zig, cargo-zigbuild) are pinned in
`.github/workflows/release.yml` to the same versions as the app's release workflow. Keep
them in step when the app raises them.
