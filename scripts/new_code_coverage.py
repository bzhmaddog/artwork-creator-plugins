#!/usr/bin/env python3
"""Coverage of new code, as the SonarQube Cloud quality gate measures it: the share of the
lines added or changed since the branch left main that the tests run.

Usage: new_code_coverage.py [--min PERCENT]

Reads the lcov reports coverage/python.lcov and coverage/rust.lcov (make coverage-python and
make coverage-rust write them; fixed paths, nothing read is named on the command line) and
the lines changed since the merge base of HEAD and origin/main (main without it; no branch
is taken from the command line, nor anything else handed to git):
committed, staged or not. A new file counts once git knows it (git add, as for a commit);
it isn't read by its name. Files Sonar leaves out (sonar.exclusions in sonar-project.properties: the
tests) are left out here too. Fails when fewer than PERCENT (80, the gate's threshold) of
the new lines that have code are covered. Run by make coverage and the pre-commit hook.

Standard library only (Python 3.11+).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ("coverage/python.lcov", "coverage/rust.lcov")
SOURCES = ("*.py", "*.rs")
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


class Error(Exception):
    pass


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


# The branches new code is measured against, the first that exists: fixed, never from outside.
BASES = ("origin/main", "main")
COMMIT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def base():
    """Where the branch left origin/main (or main when there's no origin/main): a commit hash,
    checked to be one before it's handed to git diff."""
    ref = next((b for b in BASES if subprocess.run(
        ["git", "rev-parse", "-q", "--verify", b], cwd=ROOT, capture_output=True, check=False
    ).returncode == 0), BASES[-1])  # fmt: skip
    since = git("merge-base", "HEAD", ref).strip()
    if not COMMIT_RE.fullmatch(since):
        raise Error(f"git merge-base gave {since!r}, not a commit hash")
    return since


def diff_lines(diff):
    """The lines a `git diff -U0` adds, by file: {path: {line, ...}}."""
    new: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif path and (hunk := HUNK_RE.match(line)):
            start, count = int(hunk[1]), int(hunk[2] if hunk[2] is not None else 1)
            new.setdefault(path, set()).update(range(start, start + count))
    return new


def new_lines(since):
    """The lines added since the commit `since`, by file (git diff, with the new files git
    knows)."""
    if not COMMIT_RE.fullmatch(since):
        raise Error(f"{since!r} is not a commit hash")
    return diff_lines(git("diff", "-U0", "--no-color", since, "--", *SOURCES))


def glob_re(pattern):
    """A regex matching what a Sonar glob does (** any folders, * and ? within a name)."""
    out = ""
    for part in re.split(r"(\*\*/|\*\*|\*|\?)", pattern):
        out += {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}.get(part, re.escape(part))
    return re.compile(out + "$")


def sonar_exclusions(properties):
    """The globs of sonar.exclusions and sonar.coverage.exclusions."""
    globs = []
    for line in properties.splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("sonar.exclusions", "sonar.coverage.exclusions"):
            globs += [g.strip() for g in value.split(",") if g.strip()]
    return [glob_re(g) for g in globs]


def read_lcov(text, root=None):
    """The hits of each line with code, by file relative to `root` (ROOT): {path: {line: hits}}."""
    root = ROOT if root is None else root
    found: dict[str, dict[int, int]] = {}
    lines: dict[int, int] = {}
    for line in text.splitlines():
        if line.startswith("SF:"):
            path = Path(line[3:])
            if path.is_absolute():
                path = path.relative_to(root) if path.is_relative_to(root) else path
            lines = found.setdefault(path.as_posix(), {})
        elif line.startswith("DA:"):
            number, hits = line[3:].split(",")[:2]
            lines[int(number)] = max(lines.get(int(number), 0), int(hits))
    return found


def measure(new, covered, excluded=()):
    """The new lines with code, the covered ones among them, and the uncovered ones by file."""
    total = hit = 0
    missed: dict[str, int] = {}
    for path, numbers in new.items():
        if any(r.match(path) for r in excluded):
            continue
        hits = covered.get(path, {})
        for n in numbers & hits.keys():
            total += 1
            if hits[n]:
                hit += 1
            else:
                missed[path] = missed.get(path, 0) + 1
    return total, hit, missed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Coverage of the code changed since main.")
    ap.add_argument("--min", type=float, default=80, help="the share to reach, in percent (80)")
    args = ap.parse_args(argv)
    covered: dict[str, dict[int, int]] = {}
    for report in REPORTS:
        path = ROOT / report
        if not path.is_file():
            raise Error(f"{report} is missing: run make coverage-python and make coverage-rust first")
        for file, hits in read_lcov(path.read_text(encoding="utf-8")).items():
            covered.setdefault(file, {}).update(hits)
    properties = ROOT / "sonar-project.properties"
    excluded = sonar_exclusions(properties.read_text(encoding="utf-8")) if properties.is_file() else []
    since = base()
    total, hit, missed = measure(new_lines(since), covered, excluded)
    if not total:
        print("coverage: no new lines to cover")
        return 0
    share = 100 * hit / total
    print(f"coverage: {share:.1f}% of new code covered ({hit} of {total} lines since {since[:12]}; gate {args.min:g}%)")
    if share >= args.min:
        return 0
    for path, n in sorted(missed.items()):
        print(f"  {n:4d} uncovered  {path}")
    print(f"coverage: below {args.min:g}%; add tests for the files above.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Error, subprocess.CalledProcessError) as e:
        print(f"coverage: {e}", file=sys.stderr)
        sys.exit(2)
