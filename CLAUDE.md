# Project notes

Plugin repository for Artwork Creator (the app is in `../artwork-creator-app`). README.md and
docs/publishing.md describe everything in detail; the rules that matter most:

- **`plugins.json`**: the index the app reads. Its `versions` are written only by the
  Release workflow; never edit them by hand.
- **A plugin** is a folder `plugins/<id>/` with a `plugin.json` manifest. `kind` is
  `library` (Rust cdylib) or `python` (one script). A Python plugin's `version` and
  `script` are in `plugin.json`; a Rust plugin's version is in its `Cargo.toml`.
- **A new Rust plugin** goes in `members` of the top `Cargo.toml` (no glob: CI checks
  none is missing) and takes the SDK from the app's repository at a release tag. Moving to
  a newer tag: change it, `cargo update -p artwork-plugin-sdk@<old version>`, `make check`.
- **`engines`**: Cargo-style requirements, prefer `>=` alone (no upper bound). `sdk` is
  required for Python plugins (the SDK that added the newest thing used); a Python plugin
  for an SDK newer than 0.3.0 also needs `app`. `make validate` checks this.
- **`compatible_from`**: set it to the new version only in a release that breaks saved
  settings or documents.
- **`effects` / `generators`** in the manifest must match the `name`s in the code; its
  `name` and `version` must match the code's `Plugin(name, version, ...)` (Python) or
  `export_plugin!` (Rust: `version: env!("CARGO_PKG_VERSION")`). Changing `name`,
  `description` or the other details copied into the index takes a version bump and a release.
- **Python plugins**: dependencies in the script's own PEP 723 block; tests next to the
  script (`plugins/<id>/test_*.py`), every Python plugin must have some. The tests in
  `tests/` use only the standard library.
- **Releasing**: bump the version, commit, push, then `make tag PLUGIN=<id> MSG="..."` (it
  runs `make validate` first, as the Release workflow does before building) and
  push the tag (ask before pushing). The workflow opens an "Index <id>-<version>" PR.
- **Trying before a release**: `make serve`, then add
  `http://127.0.0.1:8765/plugins.json` in the app's plugin manager.
- **U.S. English** in code, comments and docs, as in the app.

Before finishing, run `make check` (validate, lint with ruff and mypy, tests, clippy,
`cargo fmt --check`); `make fmt` formats Python and Rust.
