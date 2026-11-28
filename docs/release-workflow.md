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
               ┌──────────────┐   merge entry.json into plugins.json, validate,
               │ index        │   commit "Index <tag>" on index/<tag>, push it,
               │ contents:    │   open a pull request to main
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
2. **Validate:** `plugin_index.py validate`, the same checks as CI, at the tagged commit:
   a manifest that disagrees with its code (name, version, effects, generators) or with
   `plugins.json` stops the release before anything is built or published.
3. **Not published yet:** `plugin_index.py unpublished "$TAG"` fails if a *published*
   (non-draft) release already exists for the tag. A draft left by a failed run is fine;
   `publish` replaces it.

`make tag` (and `make release`, which then pushes the tag) runs the same `validate` and
`resolve` locally before creating the tag.

### 2. build (Rust plugins only)

Skipped for `kind: python`. A matrix of two runners, `fail-fast`:

| Runner | Command | File |
|---|---|---|
| `ubuntu-latest` | `make install-zig install-zigbuild`, then `make linux-portable PACKAGE=<package>` (`cargo zigbuild --release --locked` for `x86_64-unknown-linux-gnu.2.28`) | `lib<lib>.so` |
| `windows-latest` | `cargo build --release --locked` | `<lib>.dll` |

- The Linux build links against glibc 2.28 like the app's Linux packages, with zig and
  cargo-zigbuild at the app's versions, pinned once in the `Makefile` (`GLIBC`,
  `ZIG_VERSION`, `ZIG_SHA256`, `CARGO_ZIGBUILD_VERSION`), which `make dist` uses too;
  zig's download is checked against its SHA-256.
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
5. **Release:** `plugin_index.py publish` deletes a draft left by an earlier failed run,
   creates a *draft* release for the tag (`--verify-tag`, not marked latest), uploads the
   files, then publishes it.
   Files go on a draft first because, with release immutability on, a published release
   takes no more files.
6. **Verify downloads:** `plugin_index.py verify` downloads every URL in `entry.json`
   (6 attempts, waiting longer each time) and checks its size and SHA-256.
7. Uploads `entry.json` as the artifact `index-entry` (kept 30 days), for `index` and for
   a merge by hand.

### 4. index

Opens a pull request adding the version to `plugins.json`, to be merged by hand: the
default branch is protected, and the workflow never pushes to it. Runs when `publish`
succeeded (an explicit condition: otherwise a skipped `build` would skip it too). It checks
out the default branch, then `plugin_index.py pull-request` does the rest:

1. create the branch `index/<tag>` from it;
2. `plugin_index.py merge entry.json`: adds the version to its plugin (creating the
   plugin if it's new), fills in `compatible_from` from the previous version when the
   manifest has none, keeps the versions newest first, updates `latest` and the plugin's
   details, and sorts the plugins by id; fails if the version is already there;
3. `plugin_index.py validate`: the same checks as CI, on every manifest and the whole
   index;
4. commit `Index <tag>` as `github-actions[bot]` and force-push `index/<tag>`, so a
   re-run replaces the branch an earlier run left;
5. open a pull request `Index <tag>` from it to the default branch, with `entry.json` in
   its description, unless one is already open for that branch.

Each release gets its own branch, so releases tagged together don't race. Their pull
requests all edit `plugins.json`, though: after merging one, the next may need a rebase
(re-running its `index` job rebuilds it from the new `main`).

Pull requests opened with the workflow's `GITHUB_TOKEN` don't start other workflows, so
CI doesn't run on them by itself. If the ruleset requires status checks, close and reopen
the pull request to start CI, or merge as an admin bypassing the checks (see
[When something goes wrong](publishing.md#when-something-goes-wrong)).

## After the merge: the Pages workflow

The app doesn't read `plugins.json` on the default branch (only versions up to 0.19.0
do), but its copy on GitHub Pages. `.github/workflows/pages.yml` publishes it: on each
push to `main` that changes `plugins.json`, `site/` or the workflow, and by hand. Its `build`
job runs `plugin_index.py validate` (the whole repository, as CI does) and uploads
`plugins.json` and `site/` (the page that lists the plugins) as the site; its `deploy` job, the only one with `pages: write` and
`id-token: write`, deploys it. If `validate` fails, nothing is deployed and the site keeps
the previous index. So a merged Index pull request reaches the app only once that workflow
has passed.

## Where the data comes from

Every input of the workflow comes from the repository or from an earlier job of the same
run; nothing comes from outside users.

| Data | Comes from | Who can change it |
|---|---|---|
| `TAG` | the pushed tag | anyone with write access |
| `plugin.json`, `Cargo.toml`, scripts, sources | the repository at the tag | anyone with write access |
| `plugins.json` read by `merge` | the default branch | anyone with write access, through a reviewed pull request |
| built files (`asset-*`) | the `build` job of this run | the workflow |
| `entry.json`, `notes.md` | `prepare` in the `publish` job of this run | the workflow |
| downloaded files (`verify`) | the GitHub Release this run just published | the workflow (immutable once published) |
| `plugins.json` the app reads | GitHub Pages, deployed by the Pages workflow from the default branch | anyone with write access, through a reviewed pull request or a run by hand |

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
| `unpublished TAG` | `resolve` job | fail if the tag's release is already published |
| `publish TAG --notes --title FILE...` | `publish` job | draft release, upload the files, publish it (`gh`) |
| `merge ENTRY` | `pull-request`, by hand | add an entry's version to `plugins.json` |
| `pull-request TAG ENTRY --base --branch --repo` | `index` job | merge, validate, commit on its branch, push, open the pull request (`git`, `gh`) |
| `validate` | `resolve` and `index` jobs, CI, `make validate`, `make tag` | check every manifest and `plugins.json` |
| `version PLUGIN` | `make tag` | print a plugin's version |
| `dependencies` | CI, `make install-python` | print the Python plugins' dependencies, for `pip install` |

Errors are printed as `::error::<message>` so they show up as annotations on the run.
