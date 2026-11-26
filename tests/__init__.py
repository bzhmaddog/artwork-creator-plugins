"""The tests of the scripts and plugins.

Run inside a git hook (the pre-commit one), git sets variables naming this repository and the
index the commit is being made from (GIT_INDEX_FILE, GIT_DIR...). The tests run git in
repositories of their own, and so does the code they test: with those variables, it would
write into that index, the commit then made from it. They are removed before any test runs
(the list of `git rev-parse --local-env-vars`).

The scripts are imported as top-level modules, so scripts/ goes on the path here too.
"""

import os
import sys
from pathlib import Path

GIT_LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)
for _name in GIT_LOCAL_ENV_VARS:
    os.environ.pop(_name, None)

_SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
