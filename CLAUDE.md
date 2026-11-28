# Project notes

Plugin repository for Artwork Creator (the app is in `../artwork-creator-app`). README.md and
docs/publishing.md describe everything in detail; the rules that matter most:

- **`plugins.json`**: the index the app reads, from GitHub Pages (the Pages workflow
  publishes it when it changes on `main`). Its `versions` are written only by the
  Release workflow; never edit them by hand.
- **A plugin** is a folder `plugins/<id>/` with a `plugin.json` manifest. `kind` is
  `library` (Rust cdylib) or `python` (one script). A Python plugin's `version` and
  `script` are in `plugin.json`; a Rust plugin's version is in its `Cargo.toml`.
- **A new Rust plugin** goes in `members` of the top `Cargo.toml` (no glob: CI checks
  none is missing) and takes the SDK from the app's repository at a release tag. Moving to
  a newer tag: change it, `cargo update -p artwork-plugin-sdk@<old version>`, `make check`.
  Never a `path` dependency (CI has only this repository): `make sdk-local` builds against
  the local app's SDK for this clone only (a `paths` override: `Cargo.lock` keeps the SDK
  from GitHub), `make sdk-github` goes back.
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
- **Translations**: every official plugin gives all its texts in `en-US`, `en-GB` and
  `fr-FR`, each a complete catalog of the code's texts (Rust: `plugins/<id>/locales/<code>.json`
  in `export_plugin!`'s `translations`; Python: a `TRANSLATIONS` dict passed to
  `Plugin(..., translations=...)`). Tests check that none is missing (a Rust plugin's own
  `untranslated` test, `tests/test_plugins.py` for Python). Needs plugin SDK 0.6.0.
- **U.S. English** in code, comments and docs, as in the app.

Before finishing, run `make check` (validate, lint with ruff and mypy, duplication within
each plugin with jscpd, tests, clippy, `cargo fmt --check`); `make fmt` formats Python and Rust.
