# Publishing plugins

How a plugin goes from a commit to the Artwork Creator plugin manager. Short version:

```sh
# bump the version, commit, push
make check
make tag PLUGIN=halftone MSG="Line screen added"
git push origin halftone-0.2.0
# wait for the Release plugin workflow, then
# review and merge its "Index halftone-0.2.0" pull request, then
git pull                      # brings back the plugins.json commit
```

## How it fits together

```
tag halftone-0.2.0 ──► Release plugin workflow
                        ├─ resolve   tag matches plugins/halftone and its version?
                        ├─ build     libhalftone.so (Linux, glibc 2.28) + halftone.dll (Windows)
                        ├─ publish   GitHub Release "halftone-0.2.0" with the files,
                        │            downloaded back to check their SHA-256
                        └─ index     pull request adding the version to plugins.json;
                                     merged by hand into main
                                                  │
                       Pages workflow ◄───────────┘
                        └─ validates plugins.json, publishes it on GitHub Pages
                                                  │
Artwork Creator ◄── fetches plugins.json ─────────┘
                    downloads a file, checks its size and SHA-256
```

- **`plugins/<id>/`** holds a plugin: its code and a `plugin.json` manifest.
- **`plugins.json`** is the index the app reads. Only the Release workflow adds versions to it.
  The Pages workflow publishes it at
  `https://bzhmaddog.github.io/artwork-creator-plugins/plugins.json` each time it changes
  on `main`, where the app reads it. App versions up to 0.19.0 read it from `main`
  itself (`raw.githubusercontent.com`), so the file stays there too.
- **`site/`** is the rest of the Pages site: `index.html`, a page that lists the plugins
  and their versions, at `https://bzhmaddog.github.io/artwork-creator-plugins/`. It has no
  data of its own: its script, `index.js`, fetches the published `plugins.json` and builds a card per
  plugin, so it needs no change when a version is released.
- **Releases** hold the files. With release immutability on, a published release, its files
  and its tag can't change, so a URL in `plugins.json` always serves the bytes its hash
  describes.

[The Release workflow](release-workflow.md) details each job and where its data comes from.

## One-time setup

On GitHub, in the repository's settings:

1. *General > Releases*: turn on **release immutability**.
2. *Actions > General > Workflow permissions*: **Read and write permissions**, so the
   workflow can create releases and push its `index/<tag>` branch, and tick **Allow
   GitHub Actions to create and approve pull requests**, so it can open the pull request
   that adds the version to `plugins.json`. `main` itself can stay protected: the
   workflow never pushes to it. A ruleset must not cover `index/*` branches, or the
   workflow can't push them.
3. *Pages*: **Source** set to **GitHub Actions**, for the Pages workflow. It starts by
   itself when `plugins.json` or the workflow changes on `main`; if Pages was enabled
   after that, run it once by hand (*Actions > Pages > Run workflow*). Check that
   `https://bzhmaddog.github.io/artwork-creator-plugins/plugins.json` serves the index.

Locally: `cargo` and `python3` (3.11+). For `make windows`, the
`x86_64-pc-windows-gnu` target and MinGW. For `make linux-portable`, zig and
cargo-zigbuild. See the top of the `Makefile`.

## Adding a new plugin

1. Create `plugins/<id>/`. The folder name is the plugin's id and the first part of its
   release tags: lowercase letters, digits and dashes.
2. Add the code:
   - **Rust**: a crate with `crate-type = ["cdylib"]` and the SDK at an app release tag,
     `artwork-plugin-sdk = { git = "https://github.com/bzhmaddog/artwork-creator-app", tag = "v0.17.0" }`
     (the latest, unless the plugin must keep working with older apps). Add
     `"plugins/<id>"` to `members` in the top `Cargo.toml` (CI fails if you forget).
   - **Python**: one script. If it needs packages from PyPI, list them in a PEP 723 block
     at the top of the script; the release copies them into the index as the version's
     `dependencies`, for the app to install. See `plugins/film-grain/film_grain.py`:

     ```python
     # /// script
     # requires-python = ">=3.11"
     # dependencies = [
     #   "numpy>=1.26",
     # ]
     # ///
     ```

     Give a lower bound, not an exact pin, so the app can share one install between
     plugins. `python3 scripts/plugin_index.py dependencies` lists every plugin's;
     `make install` and CI install them, and the plugin's tests are skipped where they
     aren't installed. Add a new one to the `[mypy-…]` sections of `mypy.ini` too.

   A parameter's `role` tells the app what control to show: `seed` for an int that
   picks a random variation (the app picks it when the effect is added, and again with
   a button shown instead of a slider; declare it with `seed_param` / `Param::seed`),
   `angle` for a float in degrees (a dial), `size` for a float length in pixels (shown
   in mm on text and shape layers). See `Role` in the SDK, or `role=` of
   `int_param` / `float_param` in Python. Roles need SDK 0.4.0 (app 0.17.0). A Rust
   plugin using them still runs on older apps, which ignore them; a Python one doesn't,
   as `role=` is new in the SDK the app provides. Without a role, the app guesses it
   from an int's id `seed` and a float's unit `°` or `px`.

   A parameter's `group` puts it in a folding section of that name, with the other
   parameters of the same group, where the first of them is: `group=` of every
   `*_param` in Python, `Param::group` in Rust. Groups need SDK 0.5.0. A Rust plugin
   using them still runs on older apps, which show the parameters ungrouped; a Python
   one doesn't, as `group=` is new in the SDK the app provides.

   Its texts are in U.S. English, in the code; other languages are optional. The app asks a
   plugin for the texts of its language and shows those, the ones of the code where it has
   none. To translate them, give catalogs mapping texts of the code (names, descriptions,
   parameter labels, groups and choice labels; units are not translated) to a language's,
   for `en-GB` and `fr-FR` (the app's other languages), complete or not:
   - **Rust**: `plugins/<id>/locales/fr-FR.json` and the like, passed to
     `export_plugin!(..., translations: [("fr-FR", include_str!("../locales/fr-FR.json")),
     ...])`; a test that `artwork_plugin_sdk::untranslated(..)` of each is empty tells
     what one lacks (see `plugins/noise/src/tests.rs`), for a plugin that wants them
     complete.
   - **Python**: a `TRANSLATIONS = {"fr-FR": {...}, ...}` dict passed to
     `Plugin(..., translations=TRANSLATIONS)`; `plugin.untranslated("fr-FR")` tells what
     one lacks. A literal dict, there or as `TRANSLATIONS` at the top of the script:
     `make validate` reads it without running the script.

   Each catalog also translates the manifest's `name` and `description` (step 3); with
   the effects' and generators' names, a release copies these into its version's `texts`
   in `plugins.json` (those that differ from the English ones), so that the app shows
   them in its language in the plugin manager, and names a missing effect or generator in
   it before the plugin is installed. A text a catalog leaves out shows in English.

   Translations need plugin SDK 0.6.0: a Rust plugin built with it has ABI version 3,
   which only apps from that SDK on load; a Python plugin needs `"sdk": ">=0.6.0"` and
   the `app` that ships it.

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
     "engines": {"app": ">=0.17.0", "sdk": ">=0.4.0"},
     "effects": ["My effect"],
     "generators": ["My generator"]
   }
   ```

   `effects` and `generators` list the names the code exports (an Effect's or Generator's
   `name`), so the plugin manager can show them before the plugin is installed. Leave out a
   list that would be empty, and update them in the version that adds or removes one:
   `make validate` checks them against the code. It also checks that the `name` and
   (Python) `version` are the ones the code gives itself, in `Plugin("My effect", "1.0.0",
   ...)` or `export_plugin!`: the app shows those once the plugin is loaded.

   A Rust plugin has `"kind": "library"` and no `version`, `script` or `engines.sdk`: its version is
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
   - Python: `version` in `plugins/<id>/plugin.json`, and the version passed to
     `Plugin(...)` in the script, which the app shows once the plugin is loaded: they must
     match (`make validate` fails otherwise).

   Raise `engines.sdk` (Python) if the new version uses something a newer SDK added, such
   as `role=`, and set `engines.app` if it needs the app itself to behave differently (a
   fix it relies on). Use `>=`: an upper bound hides it from later apps that would run
   it. Apps up to 0.16 don't read `engines`, only the `min_app` the release writes from
   `engines.app`, so a Python plugin for an SDK newer than 0.3.0 also needs `engines.app`:
   at least the app release that ships that SDK (`make validate` fails without it).

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

   This runs the workflow's first checks locally (`make validate`, and that the version
   isn't released yet), then creates the annotated tag `halftone-0.2.0`. The workflow
   validates again at the tagged commit before it builds or publishes anything, so a tag
   whose manifest and code disagree (name, version, effects, generators) or whose details
   differ from `plugins.json` publishes nothing. Without make:
   `git tag -a halftone-0.2.0 -m "Line screen added"`.
5. **Push the tag**. This starts the release:

   ```sh
   git push origin halftone-0.2.0
   ```

6. **Watch** *Actions > Release plugin*. When it's done:
   - *Releases* has `halftone-0.2.0` with the files and their SHA-256 in its notes.
   - A pull request "Index halftone-0.2.0" adds the version to `plugins.json`. Merge it.
7. **Watch** *Actions > Pages*: the merge starts it. Once it has passed, the Pages URL
   serves the new version, and the app offers it. Until then, only app versions up to
   0.19.0, which read `plugins.json` on `main`, see it.
8. **`git pull`** to get the merge before your next change.

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
- Each plugin lists the working tree's version, then the versions already released (from
  this clone's `plugins.json`, downloaded from their GitHub Release), the same version
  number left out. So an app the working tree's version doesn't work with (an older one,
  say) is offered the latest released version that works, as from the published list.
  The app offers an update only to a higher version than the one installed, so bump the
  version to see a change as an update, or remove the plugin and install it again.
- The working tree's version is made from its manifest and build; a version has a
  `compatible_from` only when its manifest gives one, nothing is carried over from the
  previous version as a release would.
- A Rust plugin is built for Linux only by default (`SERVE_TARGETS`). For the app on
  Windows, reaching WSL's `localhost`, add the Windows build:
  `make serve SERVE_TARGETS="x86_64-unknown-linux-gnu x86_64-pc-windows-gnu"`. A file
  that hasn't been built is left out of the list.
- The server also serves the page of `site/` at `http://127.0.0.1:8765/`, to preview a
  change to the page before it's published. Served from here, the page has a select of
  the index to list: the working tree's (this server's list, the default), the
  `plugins.json` of this clone, or the published one. The published page doesn't have it.
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

**The release was published but no pull request was opened** (the *Index pull request*
job failed, for example because the workflow may not create pull requests). Fix the cause
and *Re-run failed jobs*; a re-run replaces the `index/<tag>` branch and reuses an open
pull request.
Or add the entry by hand: download the run's `index-entry` artifact (`entry.json`), then:

```sh
python3 scripts/plugin_index.py merge entry.json
python3 scripts/plugin_index.py validate
git commit -am "Index halftone-0.2.0" && git push
```

**The index was merged but the app doesn't offer the new version.** Look at
*Actions > Pages*. If no run started (Pages wasn't enabled yet, say), run it by hand. If
it failed at `validate`, the repository on `main` doesn't pass `make validate`, maybe
because of another plugin: fix that on `main`, then run the workflow by hand. The site
keeps the last index that passed meanwhile.

**A published version is broken.** You can't replace its files or reuse its version.
Release a fix as the next version (`0.2.1`). To stop the app offering the broken one,
remove its entry from `versions` in `plugins.json`, set the plugin's `latest` to the
newest version left (`make validate` checks it), and commit that. This is the one
change to `plugins.json` made by hand. The release itself stays, so anyone who already
has the file can still check it.

## Moving to a newer app or SDK

Each Rust plugin builds against the SDK at the app tag in its own `Cargo.toml`, so
plugins move to a newer SDK one at a time: one whose code a new SDK breaks stays on its
tag until it's ported, and one that must keep working with older apps can stay on an
older SDK. `Cargo.lock` holds each SDK the workspace uses, and the release reads the ABI
version of the plugin's own SDK. To move a plugin:

1. Change the tag in its `Cargo.toml`, then run
   `cargo update -p artwork-plugin-sdk@<old version>` (just `-p artwork-plugin-sdk` when
   the workspace has one SDK) and `make check`.
2. Bump its version and release it. A new SDK can raise the ABI version, which the
   release records as `abi`. The app loads a library only for an ABI version it knows
   (`OLDEST_ABI_VERSION` to `ABI_VERSION` in the SDK), so a Rust plugin needs no
   `engines` for that; but apps that don't know the new ABI won't be offered it.

### Working with an SDK that isn't released yet

To change the SDK and a plugin together, build against the SDK of a local app checkout:

```sh
make sdk-local     # SDK_PATH=../artwork-creator-app/plugin-sdk by default
make sdk-github    # back to the SDK from GitHub
```

`make install` runs `make sdk-local` when it finds the app checkout there (and
`make sdk-github` wasn't chosen since: it leaves an existing `.cargo/config.toml` alone).
`make sdk-local` writes a `paths` override in `.cargo/config.toml`, which git ignores, so
it is for this clone only: the `Cargo.toml` files keep their git dependency (`make validate`
refuses a `path` one, which CI couldn't build, as it checks out this repository alone).
Every build, test and `make serve` then uses the local SDK, while `Cargo.lock` keeps the
SDK from GitHub at the plugins' tags, as CI builds it: it can be committed as it is. The
local SDK may have another version than the tag's, but no dependency the tag's SDK hasn't
(Cargo refuses the override then). The commit hook still checks that the staged
`Cargo.lock` takes the SDK from GitHub.

Until the app releases the SDK, CI needs it from GitHub too: point the plugin at a pushed
commit of the app, `rev = "<commit>"` in place of `tag`, and move it to the release
tag before releasing the plugin.

A Python plugin runs with the SDK of the app it's installed in, the only one there. It
moves by raising its `engines.sdk` (and `engines.app`, see
[Releasing a version](#releasing-a-version)). An SDK release that removes or changes
something Python plugins use raises `OLDEST_VERSION` in the SDK: apps from then on don't
offer versions whose `engines.sdk` starts before it, and skip installed ones, with a
message saying so. Release a ported version of each such plugin, with the new
`engines.sdk`, before or with that app.

The Linux build tools (glibc 2.28, zig, cargo-zigbuild) are pinned in
`.github/workflows/release.yml` to the same versions as the app's release workflow. Keep
them in step when the app raises them.
