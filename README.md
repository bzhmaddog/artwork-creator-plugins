# artwork-creator-plugins
A plugin repository for [Artwork Creator](https://github.com/bzhmaddog/artwork-creator-app).

`plugins.json` is the index the app reads: each plugin, its `latest` version, its versions, and for each version
the files to download (per platform), with their SHA-256 and size. Every URL points to an
asset of an immutable GitHub Release, never to `main`, so a file always matches its hash.
The index is written by the Release workflow; don't edit the `versions` by hand.

## Layout

Each plugin is a folder of `plugins/` named after its id, with a `plugin.json` manifest:

| Field | |
|---|---|
| `id`, `name`, `description`, `author`, `homepage`, `license` | shown in the plugin manager, copied into the index by each release. `name` is also the one the code gives (`Plugin(name, ...)` or `export_plugin!`'s `name`), which the app shows once the plugin is loaded: checked to match. Changing one of these takes a new version, as the index only gets them with a release (`make validate` fails when they differ from the index at the released version) |
| `kind` | `library` (a Rust crate, built as `.so` and `.dll`) or `python` (a script) |
| `engines` | what the plugin needs of the app, as version requirements in Cargo's syntax, as npm's and VS Code's `engines`: `{"app": ">=0.17.0", "sdk": ">=0.4.0"}`. Operators `>=`, `>`, `<=`, `<`, `=`, joined by commas. `sdk`: Python only, required, at least the SDK that added the newest thing it uses (a library's is its ABI version). `app`: optional, for a plugin that relies on the app's own behavior (a fix it needs); a Python plugin for an SDK newer than 0.3.0 needs it too, from the app release that ships that SDK, as apps up to 0.16 don't read `engines` but only the `min_app` the release writes from it (`make validate` says so). Prefer `>=` alone: an upper bound hides the plugin from later apps that would run it |
| `compatible_from` | optional: oldest version of this plugin whose saved settings and documents this version still reads, so the app can warn before an update that breaks them. Every version in the index has it: left out of the manifest, it's carried over from the previous release (a first release gets its own version). Set it to the new version in a release that breaks with the past |
| `effects`, `generators` | display names of what it provides (the `name` each one has in the code), copied into each version in the index; at least one of the two, and checked against the code |
| `version` | Python only, and the same as the one passed to `Plugin(name, version, ...)` in the script (checked). A Rust plugin's version is the one in its `Cargo.toml`, which `export_plugin!` takes with `env!("CARGO_PKG_VERSION")` |
| `script` | Python only: the file to publish |

A Rust plugin is also listed in the `members` of the workspace in the top `Cargo.toml`, and takes the
plugin SDK in its own `Cargo.toml` from the Artwork Creator repository at a release tag, so each
plugin moves to a newer SDK on its own. Its ABI version is read from its SDK at release time. A Python plugin's dependencies stay in its own PEP 723
block; the release copies them into the index as `dependencies`, so there's nothing to
keep in step. `plugins/film-grain` is an example (numpy).

## Releasing a plugin

Bump the plugin's version (`Cargo.toml` or `plugin.json`), commit and push, then tag and
push the tag:

```sh
make tag PLUGIN=halftone MSG="Line screen added"
git push origin halftone-0.2.0
```

The **Release plugin** workflow builds the files, publishes them on the GitHub Release for
that tag, checks their hashes, and commits the new version to `plugins.json` on `main`.
The **Pages** workflow then publishes `plugins.json` on GitHub Pages, at
`https://bzhmaddog.github.io/artwork-creator-plugins/plugins.json`, where the app reads it.
The whole process, adding a new plugin, and what to do when a release fails:
[docs/publishing.md](docs/publishing.md).

To try plugins in the app before releasing them, `make serve` serves the working tree
as a local repository: see [Trying plugins before a release](docs/publishing.md#trying-plugins-before-a-release).

**CI** checks every push and pull request: the manifests and `plugins.json`, the tests,
and that everything builds (`make check` runs the same checks locally).

**Tests**: `make test` runs them all. The Rust plugins' tests are in their crates
(`make test-rust`, i.e. `cargo test`). A Python plugin's are next to its script
(`plugins/<plugin>/test_*.py`), run against a small stand-in for `artwork_plugin_sdk` when the
real SDK isn't installed; the release ships the script only. `tests/` holds the tests of
`scripts/`, run against a throwaway repository, the helpers the plugins' tests share, and
`test_plugins.py`, which brings the plugins' tests into `make test-python` and checks that
every Python plugin has some. They need only the standard library, plus each Python
plugin's own dependencies for its tests, which are skipped when those aren't installed
(`make install` puts them in `.venv`; CI installs them). pytest runs them too
(`pytest tests plugins`).

**Coverage**: `make coverage` writes reports to `coverage/`. The Python report is
`coverage/python-html/index.html` (and `coverage/python.xml`); it needs coverage.py from
`requirements-dev.txt` and fails below `fail_under` in `.coveragerc`. The Rust report is
`coverage/html/index.html` (and `coverage/rust.lcov`); it needs `cargo install cargo-llvm-cov`.
CI runs it too, with the totals in the run's summary and the reports as an artifact.

**Lint**: `make lint` runs ruff (lint rules and format check, `ruff.toml`) and mypy
(`mypy.ini`) on the scripts, the tests and the Python plugins; `make fmt` formats the
Python code with ruff as well as the Rust code. CI runs it too.

**Git hooks** (pre-commit, `.pre-commit-config.yaml`): `make install` installs them (or
`make hooks` alone). Each commit then checks whitespace and line endings, JSON/TOML/YAML syntax, ruff
(fixing what it can) and ruff format, mypy, `cargo fmt`, the manifests and
`plugins.json` (`plugin_index.py validate`), and runs the Python and Rust tests under
coverage (`make coverage`) when Python or Rust files changed: it fails under `fail_under`
in `.coveragerc`, or when less than 80% of the code changed since `main` is covered, the
SonarQube Cloud gate (`scripts/new_code_coverage.py`, which counts files git doesn't track
yet too). A hook that fixes files stops the
commit: look at the changes, `git add` them and commit again. `make pre-commit` runs the
hooks on every file; `git commit --no-verify` skips them. Run `make hooks` again after
moving the clone: the hook names the `.venv`'s Python by its path.

**Setup**: with [rustup](https://rustup.rs) and Python 3.11+ installed, `make install` adds
everything else to build, test, lint and serve: the Rust targets (Linux, Windows) and
components (rustfmt, clippy, llvm-tools), cargo-zigbuild and cargo-llvm-cov, zig in `.tools/`,
a `.venv` with `requirements-dev.txt` and the Python plugins' dependencies (which make then
uses), and the git hooks. With the app checked out next to this repository
(`../artwork-creator-app`), it also makes the Rust plugins build against that app's plugin SDK
instead of the one from GitHub, for this clone only (`make sdk-local`, see
[Working with an SDK that isn't released yet](docs/publishing.md#working-with-an-sdk-that-isnt-released-yet)).
`requirements-dev.txt` is generated and hash-locked: edit the tool versions in
`requirements-dev.in`, then run `make lock` to regenerate it. Running it
again only updates what's missing. The one thing it doesn't install is MinGW, the linker of
the Windows build, a system package: `sudo apt install gcc-mingw-w64-x86-64` (make install
says so when it's missing).

### Repository settings

- *Settings > General > Releases*: turn on **release immutability**, so a published
  release, its files and its tag can't be changed or moved.
- *Settings > Actions > General > Workflow permissions*: the workflow pushes
  `plugins.json` to `main` with `GITHUB_TOKEN`; if `main` is protected, let GitHub
  Actions bypass the rule.
- *Settings > Pages*: **Source** set to **GitHub Actions**, for the Pages workflow.
