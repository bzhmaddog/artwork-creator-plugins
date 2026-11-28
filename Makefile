# Builds and checks the plugins. Release builds of the Rust plugins go to target/<target>/release,
# like the app's Makefile. The Release workflow (.github/workflows/release.yml) builds a plugin's
# Linux file with make install-zig install-zigbuild and make linux-portable PACKAGE=<package>.
#
# Prerequisites: docs/publishing.md#prerequisites (rustup, python3 3.11+, Node.js 18+, MinGW);
# make install adds the rest.
#
# Common targets:
#   make install      install the tools to build, test, lint and serve: the Rust targets and
#                     components, cargo-zigbuild and cargo-llvm-cov, zig in .tools/, a .venv
#                     with requirements-dev.txt and the Python plugins' dependencies, jscpd
#                     (in npx's cache), the git hooks, and the local app's SDK when there is one (sdk-local)
#   make              build every Rust plugin for Linux and Windows (all)
#   make linux        build for Linux, against this machine's glibc
#   make linux-portable  build for Linux against glibc GLIBC, like the released files (one
#                     plugin with PACKAGE=<its Cargo package>, as the Release workflow does)
#   make windows      build for Windows (cross-compiled with MinGW)
#   make dist         the files a release publishes, for every plugin, in dist/
#   make serve        serve the working tree's plugins as a repository at
#                     http://127.0.0.1:8765/plugins.json, rebuilt on every fetch, to try
#                     them in the app before a release (SERVE_TARGETS, SERVE_PORT)
#   make check        everything CI checks (tests included), plus rustfmt and clippy
#   make test         run every test: the Rust plugins' and the Python ones (scripts and
#                     plugins, in tests/)
#   make coverage     the tests' coverage, as reports in coverage/: Python (coverage.py,
#                     requirements-dev.txt; fails under fail_under in .coveragerc) and
#                     Rust (cargo-llvm-cov: cargo install cargo-llvm-cov), then fails when
#                     less than MIN % (80) of the code changed since main is covered, as
#                     SonarQube Cloud's gate (make coverage-new, on the reports alone)
#   make lint         lint and type-check the Python code (ruff, ruff format --check, mypy;
#                     requirements-dev.txt)
#   make duplication  fail when more than 3 % of a plugin's code is copied within that
#                     plugin (jscpd, one plugin at a time: plugins share code on purpose)
#   make fmt          format the Rust and the Python code
#   make lock         regenerate requirements-dev.txt (hash-locked) from requirements-dev.in
#   make hooks        install the git hook of .pre-commit-config.yaml (pre-commit; again
#                     after moving the clone, as the hook names the .venv's Python)
#   make pre-commit   run the commit hooks on every file, not only the staged ones
#   make sdk-local    build against the plugin SDK of a local app checkout (SDK_PATH,
#                     ../artwork-creator-app/plugin-sdk) instead of GitHub's, for this
#                     clone only (.cargo/config.toml); CI always takes GitHub's
#   make sdk-github   back to the SDK from GitHub
#   make tag PLUGIN=halftone MSG="Line screen added"
#                     tag the plugin's current version for release (pushing it releases)
#   make release PLUGIN=halftone MSG="Line screen added"
#                     make tag, then push the tag: releases it
#   make clean        remove build outputs

CARGO   ?= cargo
# .venv's Python when there is one (make install makes it), which has the tools of lint,
# coverage and the hooks.
PYTHON  ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
LINUX   := x86_64-unknown-linux-gnu
WINDOWS := x86_64-pc-windows-gnu
INDEX   := $(PYTHON) scripts/plugin_index.py
DIST    := dist
COVERAGE ?= $(PYTHON) -m coverage
RUFF    ?= $(PYTHON) -m ruff
MYPY    ?= $(PYTHON) -m mypy

# Oldest glibc the released Linux files run on; the same as the app (GLIBC in its Makefile)
# and as the Release workflow.
GLIBC   := 2.28

# Tool versions make install sets up. The Release workflow takes zig and cargo-zigbuild from
# here too (make install-zig install-zigbuild); cargo-llvm-cov is the CI's: raise them together.
ZIG_VERSION            := 0.14.1
ZIG_SHA256             := 24aeeec8af16c381934a6cd7d95c807a8cb2cf7df9fa40d359aa884195c4716c
ZIG_DIR                := .tools/zig-x86_64-linux-$(ZIG_VERSION)
CARGO_ZIGBUILD_VERSION := 0.24.1
CARGO_LLVM_COV_VERSION := 0.9.2
# The Python that makes .venv.
BOOTSTRAP_PYTHON       ?= python3

# The Python plugins' scripts; a plugin's tests (test_*.py next to it) aren't part of it.
PY_PLUGIN_TESTS := $(wildcard plugins/*/test_*.py)
PY_PLUGINS := $(filter-out $(PY_PLUGIN_TESTS),$(wildcard plugins/*/*.py))
PY_TESTS   := tests/*.py $(PY_PLUGIN_TESTS)

.PHONY: sdk-local sdk-github
.PHONY: all install install-rust install-zig install-zigbuild install-python install-jscpd lock linux linux-portable windows dist serve check validate test test-rust test-python coverage coverage-python coverage-rust coverage-new lint duplication hooks pre-commit fmt clippy tag release clean

all: linux windows

# Safe to run again: each step skips or updates what's already there.
install: install-rust install-zig install-python install-jscpd
	@if [ -d .git ]; then .venv/bin/python -m pre_commit install; fi
	@# The local app's SDK when there is one (and none was chosen yet): see sdk-local.
	@if [ -f $(SDK_PATH)/Cargo.toml ] && [ ! -f .cargo/config.toml ]; then $(MAKE) --no-print-directory sdk-local; \
	  elif [ ! -f .cargo/config.toml ]; then echo "note: no app checkout in $(SDK_PATH): building against the SDK from GitHub"; fi
	@command -v x86_64-w64-mingw32-gcc >/dev/null || \
	  echo "note: MinGW not found; the Windows build (make windows, dist) needs it: sudo apt install gcc-mingw-w64-x86-64"

install-rust: install-zigbuild
	@command -v rustup >/dev/null || { echo "rustup is needed first: https://rustup.rs"; exit 1; }
	rustup component add rustfmt clippy llvm-tools-preview
	rustup target add $(LINUX) $(WINDOWS)
	$(CARGO) install --locked cargo-llvm-cov@$(CARGO_LLVM_COV_VERSION)

install-zigbuild:
	$(CARGO) install --locked cargo-zigbuild@$(CARGO_ZIGBUILD_VERSION)

# zig for make linux-portable, checked against its SHA-256 like in the Release workflow.
install-zig:
	@if [ -x $(ZIG_DIR)/zig ]; then echo "zig $(ZIG_VERSION) is in $(ZIG_DIR)"; else \
	  mkdir -p .tools && \
	  curl --proto '=https' --tlsv1.2 -fsSL -o .tools/zig.tar.xz \
	    https://ziglang.org/download/$(ZIG_VERSION)/zig-x86_64-linux-$(ZIG_VERSION).tar.xz && \
	  echo "$(ZIG_SHA256)  .tools/zig.tar.xz" | sha256sum -c - && \
	  tar -xJf .tools/zig.tar.xz -C .tools && rm .tools/zig.tar.xz; fi

# jscpd for make duplication, fetched once into npx's cache (Node.js 18+ is needed first).
# Only make duplication needs Node.js: without it, a note, and make install goes on.
install-jscpd:
	@if node -e 'process.exit(parseInt(process.versions.node) < 18 ? 1 : 0)' 2>/dev/null; then $(JSCPD) --version; \
	  else echo "note: Node.js 18+ not found; make duplication (and make check) needs it: https://nodejs.org"; fi

install-python:
	@$(BOOTSTRAP_PYTHON) -c 'import sys; sys.exit(sys.version_info < (3, 11))' || \
	  { echo "Python 3.11+ is needed ($(BOOTSTRAP_PYTHON) is older)"; exit 1; }
	test -x .venv/bin/python || $(BOOTSTRAP_PYTHON) -m venv .venv
	.venv/bin/python -m pip install -q --require-hashes --only-binary ':all:' -r requirements-dev.txt
	deps="$$(.venv/bin/python scripts/plugin_index.py dependencies)" && \
	  if [ -n "$$deps" ]; then .venv/bin/python -m pip install -q $$deps; fi

# requirements-dev.txt from requirements-dev.in: every dependency pinned, with its hashes
# (pip-tools, in its own venv in .tools/).
lock:
	test -x .tools/pip-tools/bin/pip-compile || \
	  { $(BOOTSTRAP_PYTHON) -m venv .tools/pip-tools && .tools/pip-tools/bin/pip install -q pip-tools; }
	CUSTOM_COMPILE_COMMAND="make lock" .tools/pip-tools/bin/pip-compile -q --generate-hashes \
	  --allow-unsafe --strip-extras -o requirements-dev.txt requirements-dev.in

linux:
	$(CARGO) build --release --locked --workspace --target $(LINUX)

# With the zig of make install, when it's there. Every plugin, or the Cargo package PACKAGE.
linux-portable:
	PATH="$(CURDIR)/$(ZIG_DIR):$$PATH" $(CARGO) zigbuild --release --locked \
	  $(if $(PACKAGE),-p $(PACKAGE),--workspace) --target $(LINUX).$(GLIBC)

windows:
	$(CARGO) build --release --locked --workspace --target $(WINDOWS)

# The .so and .dll at the top of each release folder are the plugins (cdylibs only).
dist: linux-portable windows
	mkdir -p $(DIST)
	cp target/$(LINUX)/release/*.so target/$(WINDOWS)/release/*.dll $(DIST)/
	cp $(PY_PLUGINS) $(DIST)/

# The Rust targets make serve rebuilds on every fetch of the list; add $(WINDOWS) to serve
# the .dll too, e.g. to a Windows app reaching WSL's localhost.
SERVE_TARGETS ?= $(LINUX)
SERVE_PORT    ?= 8765

serve:
	$(PYTHON) scripts/serve.py --port $(SERVE_PORT) $(foreach t,$(SERVE_TARGETS),--build $(t))

check: validate lint duplication test clippy
	$(CARGO) fmt --all --check

# What CI checks besides the builds: the manifests, plugins.json and the Python scripts.
validate:
	$(INDEX) validate
	$(PYTHON) -m py_compile scripts/*.py $(PY_PLUGINS) $(PY_TESTS)

test: test-rust test-python

test-rust:
	$(CARGO) test --locked --workspace

# The scripts' tests (tests/) and the Python plugins' (plugins/*/test_*.py, which
# tests/test_plugins.py collects). A plugin's tests are skipped when its dependencies
# aren't installed (make install-python installs them in .venv).
test-python:
	$(PYTHON) -m unittest discover -s tests -t .

coverage: coverage-python coverage-rust coverage-new

# Settings in .coveragerc. The report comes last, so the reports are written even when
# it fails on fail_under.
coverage-python:
	$(COVERAGE) erase
	$(COVERAGE) run -m unittest discover -s tests -t .
	$(COVERAGE) combine -q
	$(COVERAGE) html
	$(COVERAGE) xml
	$(COVERAGE) lcov -q -o coverage/python.lcov
	$(COVERAGE) report

# coverage/rust.lcov for tools, coverage/html for people.
coverage-rust:
	mkdir -p coverage
	$(CARGO) llvm-cov clean --workspace
	$(CARGO) llvm-cov --no-report --locked --workspace
	$(CARGO) llvm-cov report --lcov --output-path coverage/rust.lcov
	$(CARGO) llvm-cov report --html --output-dir coverage
	$(CARGO) llvm-cov report --summary-only

# The SonarQube Cloud gate on the reports of coverage-python and coverage-rust: at least MIN %
# (80) of the lines changed since the branch left main covered (scripts/new_code_coverage.py).
MIN ?= 80
coverage-new:
	$(PYTHON) scripts/new_code_coverage.py --min $(MIN)

# Copy-paste in a plugin's own code (not its tests), each plugin on its own: they stand
# alone, so what they have in common is copied on purpose, and SonarQube Cloud leaves
# plugins/ out of its duplication check (sonar.cpd.exclusions), which spans the whole
# repository. The 3 % is SonarQube Cloud's gate on new code.
JSCPD_VERSION := 5.4.3
JSCPD ?= npx --yes jscpd@$(JSCPD_VERSION)

duplication:
	@for d in plugins/*/; do \
	  out="$$($(JSCPD) --format rust,python --min-tokens 50 --threshold 3 \
	    --ignore '**/tests.rs,**/test_*.py' --reporters console "$$d" 2>&1)" \
	    || { printf '%s\n' "$$out"; echo "duplication in $$d"; exit 1; }; \
	done; echo "no duplication within a plugin"

# Settings in ruff.toml and mypy.ini.
lint:
	$(RUFF) check .
	$(RUFF) format --check .
	$(MYPY)

# The plugin SDK of a local app checkout in place of the one from GitHub, through a paths
# override in .cargo/config.toml, which git ignores: the Cargo.toml files keep their git
# dependency for CI, and unlike a [patch], it leaves Cargo.lock alone, so the lock keeps the
# SDK from GitHub and can be committed. The local SDK may have another version than the
# tag's, but not dependencies the tag's hasn't (Cargo then refuses the override).
# Running cargo metadata also repairs a lock that an older make sdk-local (a [patch]) wrote.
SDK_PATH ?= ../artwork-creator-app/plugin-sdk

sdk-local:
	@test -f $(SDK_PATH)/Cargo.toml || { echo "no plugin SDK in $(SDK_PATH): set SDK_PATH"; exit 1; }
	@mkdir -p .cargo
	@printf '# Written by make sdk-local, removed by make sdk-github.\npaths = ["%s"]\n' \
	  "$$(cd $(SDK_PATH) && pwd)" > .cargo/config.toml
	$(CARGO) metadata --format-version 1 > /dev/null
	@echo "Building against $$(cd $(SDK_PATH) && pwd); make sdk-github to go back."

sdk-github:
	rm -f .cargo/config.toml
	$(CARGO) metadata --format-version 1 > /dev/null
	@echo "Building against the SDK from GitHub, as CI does."

hooks:
	$(PYTHON) -m pre_commit install

STAGE ?= pre-commit

pre-commit:
	$(PYTHON) -m pre_commit run --all-files --hook-stage $(STAGE)

fmt:
	$(CARGO) fmt --all
	$(RUFF) format .

clippy:
	$(CARGO) clippy --locked --workspace --all-targets -- -D warnings

# An annotated tag <plugin>-<version>; its message becomes the version's "changes" in plugins.json.
tag:
	@test -n "$(PLUGIN)" || { echo 'usage: make tag PLUGIN=<folder in plugins/> MSG="<changes>"'; exit 1; }
	@test -n "$(MSG)" || { echo 'MSG="<changes>" is needed: it becomes the version'"'"'s changes'; exit 1; }
	@$(INDEX) validate
	@version=$$($(INDEX) version $(PLUGIN)) && tag="$(PLUGIN)-$$version" && \
	  $(INDEX) resolve "$$tag" >/dev/null && \
	  git tag -a "$$tag" -m "$(MSG)" && \
	  echo "Tagged $$tag. Release it with: git push origin $$tag"

# make tag, then push that tag on its own, which starts the Release workflow. One tag per
# push: GitHub starts no workflow for a push of more than three tags.
release: tag
	git push origin "$(PLUGIN)-$$($(INDEX) version $(PLUGIN))"

clean:
	$(CARGO) clean
	rm -rf $(DIST) coverage
