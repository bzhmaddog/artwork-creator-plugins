# artwork-creator-plugins
A plugin repository for [Artwork Creator](https://github.com/bzhmaddog/artwork-creator).

`plugins.json` is the index the app reads: each plugin, its versions, and for each version
the files to download (per platform), with their SHA-256 and size. Every URL points to an
asset of an immutable GitHub Release, never to `main`, so a file always matches its hash.
The index is written by the Release workflow; don't edit the `versions` by hand.

## Layout

Each plugin is a folder of `plugins/` named after its id, with a `plugin.json` manifest:

| Field | |
|---|---|
| `id`, `name`, `description`, `author`, `homepage`, `license` | shown in the plugin manager |
| `kind` | `library` (a Rust crate, built as `.so` and `.dll`) or `python` (a script) |
| `min_app` | oldest Artwork Creator version the plugin runs on |
| `version` | Python only (a Rust plugin's version is the one in its `Cargo.toml`) |
| `script` | Python only: the file to publish |
| `sdk` | Python only: the Python SDK version it was written for |

A Rust plugin is also listed in the `members` of the workspace in the top `Cargo.toml`, which takes the
plugin SDK from the Artwork Creator repository at a release tag. Its ABI version is read
from that SDK at release time. A Python plugin's dependencies stay in its own PEP 723
block; the release copies them into the index as `dependencies`, so there's nothing to
keep in step.

## Releasing a plugin

Bump the plugin's version (`Cargo.toml` or `plugin.json`), commit and push, then tag and
push the tag:

```sh
make tag PLUGIN=halftone MSG="Line screen added"
git push origin halftone-0.2.0
```

The **Release plugin** workflow builds the files, publishes them on the GitHub Release for
that tag, checks their hashes, and commits the new version to `plugins.json` on `main`.
The whole process, adding a new plugin, and what to do when a release fails:
[docs/publishing.md](docs/publishing.md).

**CI** checks every push and pull request: the manifests and `plugins.json`, and that
everything builds (`make check` runs the same checks locally).

### Repository settings

- *Settings > General > Releases*: turn on **release immutability**, so a published
  release, its files and its tag can't be changed or moved.
- *Settings > Actions > General > Workflow permissions*: the workflow pushes
  `plugins.json` to `main` with `GITHUB_TOKEN`; if `main` is protected, let GitHub
  Actions bypass the rule.
