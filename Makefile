# Builds and checks the plugins. Release builds of the Rust plugins go to target/<target>/release,
# like the app's Makefile; the Release workflow (.github/workflows/release.yml) does its own builds.
#
# Needs: cargo, python3 (3.11+); for windows the x86_64-pc-windows-gnu target and MinGW
#   (rustup target add x86_64-pc-windows-gnu; apt install gcc-mingw-w64-x86-64);
#   for linux-portable zig and cargo-zigbuild.
#
# Common targets:
#   make              build every Rust plugin for Linux and Windows (all)
#   make linux        build for Linux, against this machine's glibc
#   make linux-portable  build for Linux against glibc GLIBC, like the released files
#   make windows      build for Windows (cross-compiled with MinGW)
#   make dist         the files a release publishes, for every plugin, in dist/
#   make install      copy the plugins into the app's plugins folder (APP_PLUGINS), where
#                     a debug build run from the app's repository (make run) finds them
#   make check        everything CI checks, plus rustfmt and clippy
#   make test         run the Rust plugins' tests
#   make fmt          format the Rust code
#   make tag PLUGIN=halftone MSG="Line screen added"
#                     tag the plugin's current version for release (pushing it releases)
#   make clean        remove build outputs

CARGO   ?= cargo
PYTHON  ?= python3
LINUX   := x86_64-unknown-linux-gnu
WINDOWS := x86_64-pc-windows-gnu
INDEX   := $(PYTHON) .github/scripts/plugin_index.py
DIST    := dist

# Oldest glibc the released Linux files run on; the same as the app (GLIBC in its Makefile)
# and as the Release workflow.
GLIBC   := 2.28

# The app's repository next to this one; make install copies the plugins into its plugins/.
APP_PLUGINS ?= ../artwork-creator/plugins

PY_PLUGINS := $(wildcard plugins/*/*.py)

.PHONY: all linux linux-portable windows dist install check validate test fmt clippy tag clean

all: linux windows

linux:
	$(CARGO) build --release --locked --workspace --target $(LINUX)

linux-portable:
	$(CARGO) zigbuild --release --locked --workspace --target $(LINUX).$(GLIBC)

windows:
	$(CARGO) build --release --locked --workspace --target $(WINDOWS)

# The .so and .dll at the top of each release folder are the plugins (cdylibs only).
dist: linux-portable windows
	mkdir -p $(DIST)
	cp target/$(LINUX)/release/*.so target/$(WINDOWS)/release/*.dll $(DIST)/
	cp $(PY_PLUGINS) $(DIST)/

install: linux windows
	mkdir -p $(APP_PLUGINS)
	cp target/$(LINUX)/release/*.so target/$(WINDOWS)/release/*.dll $(APP_PLUGINS)/
	cp $(PY_PLUGINS) $(APP_PLUGINS)/

check: validate clippy
	$(CARGO) fmt --all --check

# What CI checks besides the builds: the manifests, plugins.json and the Python scripts.
validate:
	$(INDEX) validate
	$(PYTHON) -m py_compile .github/scripts/plugin_index.py $(PY_PLUGINS)

test:
	$(CARGO) test --locked --workspace

fmt:
	$(CARGO) fmt --all

clippy:
	$(CARGO) clippy --locked --workspace --all-targets -- -D warnings

# An annotated tag <plugin>-<version>; its message becomes the version's "changes" in plugins.json.
tag:
	@test -n "$(PLUGIN)" || { echo 'usage: make tag PLUGIN=<folder in plugins/> MSG="<changes>"'; exit 1; }
	@test -n "$(MSG)" || { echo 'MSG="<changes>" is needed: it becomes the version'"'"'s changes'; exit 1; }
	@version=$$($(INDEX) version $(PLUGIN)) && tag="$(PLUGIN)-$$version" && \
	  $(INDEX) resolve "$$tag" >/dev/null && \
	  git tag -a "$$tag" -m "$(MSG)" && \
	  echo "Tagged $$tag. Release it with: git push origin $$tag"

clean:
	$(CARGO) clean
	rm -rf $(DIST)
