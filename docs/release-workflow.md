# The Release workflow

What `.github/workflows/release.yml` does when a release tag is pushed, job by job, and
where each piece of data comes from. To *release* a plugin, follow
[Publishing plugins](publishing.md); this page is for changing the workflow or
`scripts/plugin_index.py`, or understanding a failed run.

## Overview

```
git push origin halftone-0.2.0
        │
        ▼
┌─────────────┐  key=value outputs   ┌──────────────────┐
│ resolve     │ ───────────────────► │ build (library)  │  linux + windows
│ ubuntu      │                      │ matrix           │  artifacts asset-*
└─────────────┘                      └──────────────────┘
        │                                     │
        └──────────────┬──────────────────────┘
                       ▼
               ┌──────────────┐   draft release → upload → publish
               │ publish      │   verify downloads
               │ contents:    │   artifact index-entry (entry.json)
               │   write      │
               └──────────────┘
                       │
                       ▼
               ┌──────────────┐   merge entry.json into plugins.json
               │ index        │   validate, commit "Index <tag>", push to main
               │ contents:    │   (retried on a concurrent push)
               │   write      │
               └──────────────┘
```

## Trigger and settings

- **Trigger:** a pushed tag matching `*-[0-9]*.[0-9]*.[0-9]*`, such as `halftone-0.2.0`.
  Only someone with write access to the repository can push one.
- **Permissions:** `contents: read` by default; only `publish` and `index` get
  `contents: write` (to create the release and push `plugins.json`).
- **Concurrency:** one run per tag (`release-<tag>`, not cancelled), so a tag pushed twice
  doesn't release twice. Different tags run side by side.
- **`TAG`** (`github.ref_name`) is the only input; everything else is read from the
  repository at that tag.

## Jobs

### 1. resolve

Checks the tag and works out what to build.

1. `plugin_index.py resolve "$TAG"`:
   - splits the tag into `<folder>-<X.Y.Z>`, taking the longest folder of `plugins/` that
     matches (a folder name may itself end in `-<digits>`);
   - loads and checks that folder's `plugin.json` (and `Cargo.toml` for Rust);
   - fails if the version in the tag isn't the plugin's version, or if that version is
     already in `plugins.json`;
   - prints `dir`, `kind`, `version`, `name`, and `package` + `lib` (Rust) or
     `script` (Python) as `key=value` lines into `$GITHUB_OUTPUT`.
2. **Not published yet:** fails if a *published* (non-draft) release already exists for
   the tag. A draft left by a failed run is fine; `publish` replaces it.

`make tag` runs the same `resolve` locally before creating the tag.

### 2. build (Rust plugins only)

Skipped for `kind: python`. A matrix of two runners, `fail-fast`:

| Runner | Command | File |
|---|---|---|
| `ubuntu-latest` | `cargo zigbuild --release --locked` for `x86_64-unknown-linux-gnu.2.28` | `lib<lib>.so` |
| `windows-latest` | `cargo build --release --locked` | `<lib>.dll` |

- The Linux build links against glibc 2.28 like the app's Linux packages, with zig and
  cargo-zigbuild pinned to the app's versions; zig's download is checked against its SHA-256.
- `--locked` makes the build fail if `Cargo.lock` doesn't match the manifests.
- Each file is uploaded as an artifact `asset-linux` / `asset-windows` (kept 7 days).

### 3. publish

Runs when `resolve` succeeded and `build` succeeded or was skipped.

1. Fetches the tag again with its annotation (`actions/checkout` drops it); the tag's
   message becomes the version's `changes`.
2. Gathers the files into `dist/`: the `asset-*` artifacts (Rust), or a copy of
   `plugins/<dir>/<script>` (Python).
3. Installs the Rust toolchain for a Rust plugin: `prepare` reads the SDK's `ABI_VERSION`
   through `cargo metadata`.
4. **Index entry:** `plugin_index.py prepare` hashes each file in `dist/` (SHA-256 and size)
   and writes:
   - `entry.json`: the plugin's entry for `plugins.json`, with this one version and, for
     each platform, its URL under
     `https://github.com/<repo>/releases/download/<tag>/`;
   - `notes.md`: the release notes (the changes, and a table of files and SHA-256).
5. **Release:** deletes a draft left by an earlier failed run, creates a *draft* release
   for the tag (`--verify-tag`, not marked latest), uploads the files, then publishes it.
   Files go on a draft first because, with release immutability on, a published release
   takes no more files.
6. **Verify downloads:** `plugin_index.py verify` downloads every URL in `entry.json`
   (6 attempts, waiting longer each time) and checks its size and SHA-256.
7. Uploads `entry.json` as the artifact `index-entry` (kept 30 days), for `index` and for
   a merge by hand.

### 4. index

Adds the version to `plugins.json` on the default branch. Runs when `publish` succeeded
(an explicit condition: otherwise a skipped `build` would skip it too).

It has no concurrency group, because GitHub would cancel all but one pending run of a
group and drop releases tagged together. Instead it retries up to 5 times:

1. fetch the default branch and reset to it;
2. `plugin_index.py merge entry.json`: adds the version to its plugin (creating the
   plugin if it's new), fills in `compatible_from` from the previous version when the
   manifest has none, keeps the versions newest first, updates `latest` and the plugin's
   details, and sorts the plugins by id; fails if the version is already there;
3. `plugin_index.py validate`: the same checks as CI, on every manifest and the whole
   index;
4. commit `Index <tag>` as `github-actions[bot]` and push. If another release pushed
   first, wait and start over from the new `main`.

After 5 failed pushes the job fails, and the entry can be merged by hand (see
[When something goes wrong](publishing.md#when-something-goes-wrong)).

## Where the data comes from

Every input of the workflow comes from the repository or from an earlier job of the same
run; nothing comes from outside users.

| Data | Comes from | Who can change it |
|---|---|---|
| `TAG` | the pushed tag | anyone with write access |
| `plugin.json`, `Cargo.toml`, scripts, sources | the repository at the tag | anyone with write access |
| `plugins.json` read by `merge` | the default branch | anyone with write access, and this workflow |
| built files (`asset-*`) | the `build` job of this run | the workflow |
| `entry.json`, `notes.md` | `prepare` in the `publish` job of this run | the workflow |
| downloaded files (`verify`) | the GitHub Release this run just published | the workflow (immutable once published) |

Each file the workflow writes has a fixed name: `plugins.json` at the repository root,
`entry.json` and `notes.md` in `$RUNNER_TEMP`. No name or path written to is built from
file contents.

### About SonarCloud's path traversal finding

SonarCloud reports `pythonsecurity:S2083` (*Path Traversal via file content*) on
`cmd_merge`: it follows the content of `plugins.json` from where it's read to where it's
written back. Its taint analysis treats any file's content as coming from an attacker, and
flags the write because the data reaches a file API.

Here that is a false positive:

- the path written is the constant `ROOT / "plugins.json"`; the data read only becomes
  the file's *content*, never its name or location;
- the data comes from the repository and from this workflow (see the table above), which
  only people with write access can change, and they could change the script itself.

What the content *does* control is what the app downloads: a URL and an id in
`plugins.json`. Those are checked by `validate`, which `index` runs before committing,
and by CI on every push: every URL must be a release asset of `<id>-<version>` of this
repository, every SHA-256 64 hex digits, every size a positive integer.

## Commands of `scripts/plugin_index.py`

| Command | Used by | Does |
|---|---|---|
| `resolve TAG` | `resolve` job, `make tag` | check the tag, print what to build |
| `prepare TAG --assets --base-url --out [--notes]` | `publish` job | hash the files, write the entry and notes |
| `verify ENTRY` | `publish` job | download each file of an entry, check size and SHA-256 |
| `merge ENTRY` | `index` job, by hand | add an entry's version to `plugins.json` |
| `validate` | `index` job, CI, `make validate` | check every manifest and `plugins.json` |
| `version PLUGIN` | `make tag` | print a plugin's version |
| `dependencies` | CI, `make install-python` | print the Python plugins' dependencies, for `pip install` |

Errors are printed as `::error::<message>` so they show up as annotations on the run.
