#!/usr/bin/env python3
"""Put this package into a project, after a human has seen exactly what it would write.

    init --plan     reads, writes nothing, and prints the paths whose bytes would change
    init --apply    writes those paths and nothing else, and does not commit

`--apply` is deliberately not a committer. A human reads the diff and commits it, and that
commit is the only place in this flow where someone decides these bytes should exist.

Everything is composed and checked before anything is written, and every destination is proved
writable before the first write. That proof is a filter rather than a guarantee: a file can
answer "writable" and still refuse to be replaced, because on Windows an ordinary reader can
hold it open sharing read and write but not delete. So the original bytes are held as well, and
if any write fails every earlier one is put back - the run then reports that nothing was left
changed, and says so only when that is true. The temporary file each write goes through is
created exclusively with a random name in the destination directory: a predictable name in a
predictable place is one another process can create first, and if it creates it as a link, the
write lands wherever that link points.

Nothing here destroys project content. An existing AGENTS.md keeps everything outside the
generated region, byte for byte and blank lines included, and the region is placed first
because several products cap the instruction text they read and drop what is past the cap. An
existing .gitattributes keeps its own lines the same way, and the managed block is written last,
because the last matching line is the one in effect; one with project lines below it is refused.

`--plan` writes nothing anywhere: not in the project, and not in a temporary directory either.
Measuring the method bundle's digest reads the package's own copy rather than materialising
one.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.stderr.write("agentlanes.py requires Python 3.10 or newer\n")
    raise SystemExit(2)
if sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1:
    sys.stderr.write("agentlanes.py must be invoked with Python -I -B\n")
    raise SystemExit(2)

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_VERSION = "0.2.0"

VENDORED = ".agents/agentlanes"
PROJECT_LOCK = ".agents/agentlanes.lock.json"
METHOD_LOCK = ".agents/multi-lane-wave-method.lock.json"
GUARD = f"{VENDORED}/method/scripts/wave_guard.py"

BEGIN_LINE = re.compile(rb"^<!--\s*agentlanes:begin(?![\w-])[^\n]*-->\s*$")
END_LINE = re.compile(rb"^<!--\s*agentlanes:end\s*-->\s*$")
ATTR_BEGIN = re.compile(rb"^#\s*agentlanes:begin\s*$")
ATTR_END = re.compile(rb"^#\s*agentlanes:end\s*$")

BRIDGES = {"codex": [], "generic": [], "claude-code": ["CLAUDE.md"]}
ALL_BRIDGE_FILES = sorted({name for names in BRIDGES.values() for name in names})

QUESTIONS = [
    "Which agent products will work in this repository? (--agents, comma separated: "
    + ", ".join(sorted(BRIDGES)) + ")",
    "Will they take turns in this one checkout, or work at the same time in separate "
    "worktrees? At the same time in one directory is not an option.",
    "Which of them, if any, may create commits? Start with none and grant one at a time.",
    "May any of them send this code to a hosted service? Answer separately for each.",
    "If this repository already has instruction files, should they be kept as they are, "
    "folded into the project section, or removed by hand first?",
]


class Refused(Exception):
    """Stop rather than produce something half-written."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def is_reparse(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x0400)


def resolve_git(candidate: str) -> str:
    if not os.path.isabs(candidate):
        raise Refused("--git-executable must be an absolute path, not a command name")
    if is_reparse(candidate) or not os.path.isfile(candidate):
        raise Refused("--git-executable must be an absolute regular file")
    return candidate


# Names git already carries for this project - the index and HEAD, not just the disk.
#
# `assert_exact_case` used to list the working tree only. A project's own `agents.md`, committed
# and then taken off the disk with skip-worktree, is invisible to `os.listdir` and present in
# every clone, so `init --apply` wrote `AGENTS.md` beside it and produced a tree with two names
# that are one file on Windows and macOS. Filled once per run, because it costs two git calls
# and the answer cannot change while this program is the only writer.
TRACKED_NAMES: set[str] = set()


def load_tracked_names(repo: str, git_exe: str) -> None:
    """Read the index and HEAD once. Silence here would be a hole, so failure is refusal."""
    global TRACKED_NAMES
    names: set[str] = set()
    for args in (("ls-files", "-z"), ("ls-tree", "-r", "-z", "--name-only", "HEAD")):
        done = subprocess.run(
            [git_exe, "-c", f"safe.directory={repo}", "-c", "core.quotePath=false",
             "-C", repo, *args],
            capture_output=True, timeout=600, check=False,
        )
        if done.returncode != 0:
            if args[0] == "ls-tree":
                continue      # a project with no commit yet has no HEAD, which is not an error
            raise Refused("git could not list this project's tracked files")
        names |= {p.decode("utf-8", "surrogateescape")
                  for p in done.stdout.split(b"\0") if p}
    TRACKED_NAMES = names


def assert_inside(repo: str, rel: str) -> str:
    """Resolve a project-relative path and prove every step of it stays in the project."""
    if os.path.isabs(rel) or "\\" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
        raise Refused(f"{rel} is not a normalised project-relative path")
    target = os.path.join(repo, *rel.split("/"))
    walked = repo
    for part in rel.split("/"):
        walked = os.path.join(walked, part)
        if os.path.lexists(walked) and is_reparse(walked):
            raise Refused(f"{rel} passes through a link or junction; refusing to write through it")
    resolved_parent = os.path.realpath(os.path.dirname(target))
    if os.path.commonpath([resolved_parent, repo]) != repo:
        raise Refused(f"{rel} resolves outside the project")
    assert_exact_case(repo, rel)
    return target


def assert_exact_case(repo: str, rel: str) -> None:
    """Refuse a destination that collides with a name this project has or tracks.

    A name differing only in case, a file where a directory is needed, or the reverse.

    On a case-insensitive filesystem `os.replace` renames it: a project's own `agents.md`
    became `AGENTS.md` on disk while git went on tracking `agents.md` and called it modified.
    The content survived, so nothing looked wrong - and a clone onto a case-sensitive
    filesystem then gets `agents.md`, which is not the file this package's checker looks for or
    the file most products read. Renaming somebody's tracked file is theirs to do.
    """
    # Names git carries for this path's directory, whether or not they are on the disk. A
    # committed file marked skip-worktree is in every clone and in no listing here.
    #
    # Compared component by component, not as whole strings. A tracked FILE `.AGENTS` sits where
    # this program needs a DIRECTORY `.agents/`, and a tracked directory `agents.md/` - or
    # `AGENTS.md/` with the very same spelling - sits where it would write a FILE. No whole path
    # is equal in either case, so a whole-path comparison let init write 21 paths in both.
    # Measured on Windows, neither stops anything, which is the trouble: spelled the same, the
    # index cannot hold both and `git add` makes room by staging the project's own entry for
    # deletion without a word; differing only in case, a clone exits 0 with one of the two
    # missing and `git status` there reporting it deleted.
    want = rel.lower().split("/")
    for tracked in TRACKED_NAMES:
        have = tracked.lower().split("/")
        if have == want:
            if tracked != rel:
                raise Refused(
                    f"this project already tracks {tracked!r} where {rel!r} would be written. "
                    "Those two names are one file on a case-insensitive filesystem (Windows, "
                    "and macOS by default): a clone there gets one file on the disk for both, "
                    "with only a warning, and git status reports the other modified. Rename it "
                    f"first (git mv {tracked} {rel}), then run this again."
                )
        elif len(have) < len(want) and want[:len(have)] == have:
            raise Refused(
                f"this project tracks {tracked!r}, and {rel!r} needs a directory by that name. "
                f"Spelled the same, staging this program's files takes {tracked!r} out of the "
                "index without a word and the next commit deletes it; differing only in case, "
                "a clone onto a case-insensitive filesystem gets one of the two and reports "
                "the other deleted. Move it first (git mv), then run this again."
            )
        elif len(want) < len(have) and have[:len(want)] == want:
            below = "/".join(tracked.split("/")[:len(want)])
            raise Refused(
                f"this project tracks {tracked!r}, so {below!r} is a directory in this project, "
                f"and this program would write the file {rel!r} there. Spelled the same, "
                f"staging that file takes {tracked!r} out of the index without a word and the "
                "next commit deletes it; differing only in case, a clone onto a "
                "case-insensitive filesystem gets one of the two and reports the other "
                "deleted. Move the directory first (git mv), then run this again."
            )

    walked = repo
    for part in rel.split("/"):
        parent, walked = walked, os.path.join(walked, part)
        try:
            siblings = os.listdir(parent)
        except OSError:
            return
        # Asked of the tree, not of this machine's idea of the tree. This used to begin with
        # `if not os.path.exists(walked): return`, which is false on a case-sensitive
        # filesystem exactly when the collision is real - so on Linux the check returned
        # before looking and a project's own `agents.md` gained an `AGENTS.md` beside it.
        # Two names that are one file elsewhere: a clone of that repository onto Windows exits
        # 0 with a warning, one file on the disk stands for both, and git status reports the
        # other modified.
        actual = next((name for name in siblings
                       if name != part and name.lower() == part.lower()), None)
        if actual is not None:
            raise Refused(
                f"this project already has {actual!r} where {part!r} would be written. Those "
                "two names are one file on a case-insensitive filesystem (Windows, and macOS by "
                "default), so writing here either renames the project's own file or, where the "
                "two can coexist, produces a repository whose clones on those systems get one "
                f"file for both. Rename it first (git mv {actual} {part}), then run this again."
            )
        if part not in siblings:
            return          # nothing below this exists yet, so nothing below can collide


def assert_writable(repo: str, rel: str) -> None:
    """Prove the destination can be replaced, before any of the run's writes happen.

    Without this, a single read-only file part way through the list left nineteen files
    written and the twentieth raising - a project half converted, from an ordinary condition
    that needs no race to produce.
    """
    target = os.path.join(repo, *rel.split("/"))
    if os.path.exists(target):
        if not os.path.isfile(target):
            raise Refused(f"{rel} exists and is not a regular file")
        if not os.access(target, os.W_OK):
            raise Refused(f"{rel} is not writable; nothing has been written")
        return
    directory = os.path.dirname(target) or repo
    probe = directory
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not os.path.isdir(probe) or not os.access(probe, os.W_OK):
        raise Refused(f"{rel} cannot be created: {os.path.relpath(probe, repo)} is not writable")


def write_bytes(path: str, data: bytes) -> None:
    """Write through an exclusively created temporary file in the destination directory."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".agentlanes-", dir=directory)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def as_text(data: bytes, rel: str) -> None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Refused(
            f"{rel} is not UTF-8, and composing it as text would corrupt it. Convert or move it "
            "first."
        ) from error
    if data.startswith(b"\xef\xbb\xbf") and not rel.endswith(".gitattributes"):
        # Only where the reason is true. In an instruction file the generated region goes
        # first, so a mark that was at the start of the project's own text ends up three bytes
        # into the middle of it, which is no longer a mark and is nobody's idea of an
        # improvement. Refusing is right there.
        #
        # In `.gitattributes` the region is appended at the end and the mark does not move at
        # all. This used to refuse anyway, saying git reads the mark as part of the first
        # pattern so that line matches nothing - **which is false**. Measured on git 2.54, with
        # the reader's own attributes file switched off:
        #
        #     no mark      first.md: text: set   first.md: eol: lf
        #     with a mark  first.md: text: set   first.md: eol: lf
        #
        # That sentence was reasoning about how a parser might work, shipped as a fact in a
        # message a person is asked to act on. Refusing on a false reason is worse than not
        # refusing: it blocks a project for something that does not happen.
        raise Refused(
            f"{rel} starts with a byte-order mark. The generated region has to be first, so the "
            "mark would be moved into the middle of your text. Remove it first."
        )


def package_files() -> dict[str, str]:
    planned: dict[str, str] = {}
    for sub, target in (("core/method", "method"), ("core/policy", "policy")):
        root = os.path.join(PACKAGE, sub.replace("/", os.sep))
        if not os.path.isdir(root):
            raise Refused(f"the package is incomplete: {sub} is missing")
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                full = os.path.join(base, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                planned[f"{VENDORED}/{target}/{rel}"] = full
    for name in ("AGENTS.md", "CLAUDE.md", "gitattributes"):
        planned[f"{VENDORED}/templates/{name}"] = os.path.join(PACKAGE, "templates", name)
    planned[f"{VENDORED}/cli/check.py"] = os.path.join(PACKAGE, "cli", "check.py")
    # MIT asks that its notice go with every copy of a substantial portion, and each file
    # above is one. One LICENSE beside them covers the vendored tree.
    planned[f"{VENDORED}/LICENSE"] = os.path.join(PACKAGE, "LICENSE")
    return planned


def marked_span(lines: list[bytes], begin, end, label: str) -> tuple[int, int] | None:
    """Indices of one marked region, or None. Tolerant of trailing carriage returns."""
    starts = [i for i, l in enumerate(lines) if begin.match(l.rstrip(b"\r"))]
    stops = [i for i, l in enumerate(lines) if end.match(l.rstrip(b"\r"))]
    if not starts and not stops:
        return None
    if len(starts) != 1 or len(stops) != 1 or stops[0] <= starts[0]:
        raise Refused(
            f"{label} has {len(starts)} begin and {len(stops)} end marker lines. Exactly one "
            "pair, in that order, is required; resolve it by hand rather than letting this guess."
        )
    return starts[0], stops[0]


def without_region(data: bytes, begin, end, label: str, where: str) -> bytes:
    """The project's own bytes: everything outside the marked region, exactly as it was.

    Byte offsets rather than splitting into lines and joining them back. A split-and-join loses
    the project's blank lines at the two edges of the region and quietly gains one every time it
    runs, and blank lines somebody wrote are theirs.

    A region is only ever recognised where this program puts one: first in an instruction file,
    last in an attributes file. Anywhere else it belongs to the project - a repository that
    documents this package writes those two marker lines in its own prose - and treating that
    as the generated region deleted everything between them, silently, on a run that exited 0.
    """
    lines = data.split(b"\n")
    span = marked_span(lines, begin, end, label)
    if span is None:
        return data
    first, last = span
    tail = [i for i, l in enumerate(lines) if l.strip()]
    misplaced = first != 0 if where == "first" else (not tail or last != tail[-1])
    if misplaced:
        raise Refused(
            f"{label} has a marker pair that is not where this program writes one (it writes "
            f"the region {where}). Those two lines are the project's own text - quoted, "
            "documented, or left by something else - and rewriting round them would delete "
            "what is between them. Move or rename them, or remove the pair by hand."
        )
    start = sum(len(l) + 1 for l in lines[:first])
    stop = start + sum(len(l) + 1 for l in lines[first : last + 1])
    return data[:start] + data[min(stop, len(data)):]


def template_block(name: str) -> bytes:
    data = read_bytes(os.path.join(PACKAGE, "templates", name))
    lines = data.split(b"\n")
    span = marked_span(lines, BEGIN_LINE, END_LINE, f"templates/{name}")
    if span is None:
        raise Refused(f"templates/{name} has no generated region")
    start, stop = span
    return b"\n".join(lines[start : stop + 1]) + b"\n"


def compose_agents_md(existing: bytes | None) -> bytes:
    """Keep whatever the project wrote, and put the generated region first."""
    block = template_block("AGENTS.md")
    if existing is None:
        return read_bytes(os.path.join(PACKAGE, "templates", "AGENTS.md"))
    as_text(existing, "AGENTS.md")
    rest = without_region(existing, BEGIN_LINE, END_LINE, "AGENTS.md", "first")
    if not rest:
        return block
    # A separator is added only when the project's own bytes do not already begin with one.
    # Adding a blank line is a formatting choice; removing the ones somebody wrote is a loss.
    return block + (b"" if rest.startswith((b"\n", b"\r\n")) else b"\n") + rest


def compose_gitattributes(existing: bytes | None) -> bytes:
    """Write the managed block last and leave every other line exactly as it was.

    The block is found by its own marker lines rather than by matching its content, so a copy
    written with different line endings is recognised and replaced instead of being appended a
    second time. Everything outside it - including blank lines the project chose - is preserved
    byte for byte.
    """
    block = read_bytes(os.path.join(PACKAGE, "templates", "gitattributes"))
    if existing is None:
        return block
    as_text(existing, ".gitattributes")
    body = without_region(existing, ATTR_BEGIN, ATTR_END, ".gitattributes", "last")
    if not body:
        return block
    return body + (b"" if body.endswith(b"\n") else b"\n") + block


def method_lock_bytes() -> bytes:
    """Measure the bundle's digest with the bundle's own guard, from the package's own copy.

    Reading the package rather than materialising a copy is what lets `--plan` write nothing
    anywhere, rather than nothing inside the project. The bytes are the same either way: the
    bundle is vendored verbatim.
    """
    guard = os.path.join(PACKAGE, "core", "method", "scripts", "wave_guard.py")
    done = subprocess.run(
        [sys.executable, "-I", "-B", guard, "method-digest"],
        capture_output=True, text=True, timeout=600, check=False,
    )
    if done.returncode != 0:
        raise Refused(f"the guard could not measure the bundle: {done.stderr.strip()[:200]}")
    measured = json.loads(done.stdout)
    lock = {
        "schemaVersion": 2,
        "methodId": measured["methodId"],
        "methodVersion": measured["methodVersion"],
        "digestAlgorithm": measured["digestAlgorithm"],
        "canonicalDigest": measured["canonicalDigest"],
        "provenanceStatus": "UNVERIFIED_LOCAL",
        "sourceRevision": None,
        "provenanceAuthority": None,
        "recoverySource": f"{VENDORED}/method",
        "recoveryDigest": measured["canonicalDigest"],
    }
    return json.dumps(lock, indent=2).encode("utf-8") + b"\n"


def project_lock_bytes(staged: dict[str, bytes], agents: list[str]) -> bytes:
    def digest_of(rel: str) -> str:
        return sha256_bytes(staged[rel])

    lines = staged["AGENTS.md"].split(b"\n")
    start, stop = marked_span(lines, BEGIN_LINE, END_LINE, "AGENTS.md")
    generated = [{
        "path": "AGENTS.md",
        "source": f"{VENDORED}/templates/AGENTS.md",
        "mode": "block",
        # The digest covers the generated region only. Hashing the whole file would make an
        # ordinary edit to the project's own section read as drift, which the template
        # explicitly promises it is not.
        "sha256": sha256_bytes(b"\n".join(lines[start : stop + 1]) + b"\n"),
    }]
    for name in sorted({n for agent in agents for n in BRIDGES[agent]}):
        generated.append({
            "path": name, "source": f"{VENDORED}/templates/{name}",
            "mode": "whole", "sha256": digest_of(name),
        })
    lock = {
        "schemaVersion": 1,
        "packageVersion": PACKAGE_VERSION,
        "methodLock": METHOD_LOCK,
        "vendored": VENDORED,
        "policy": {"path": f"{VENDORED}/policy/REPOSITORY_POLICY.md",
                   "sha256": digest_of(f"{VENDORED}/policy/REPOSITORY_POLICY.md")},
        "checker": {"path": f"{VENDORED}/cli/check.py",
                    "sha256": digest_of(f"{VENDORED}/cli/check.py")},
        # The bundle's identity is the guard's answer and the guard lives in the bundle. Pinning
        # it here is what stops a two-line script that prints `lockVerified: true` from standing
        # in for the whole of question 1.
        "guard": {"path": GUARD,
                  "sha256": digest_of(GUARD)},
        # Pinned like the policy. An unpinned file in the vendored tree is refused by the
        # checker, and a notice nobody pins can be edited with nothing to say so.
        "license": {"path": f"{VENDORED}/LICENSE",
                    "sha256": digest_of(f"{VENDORED}/LICENSE")},
        "templates": [{"path": f"{VENDORED}/templates/{n}",
                       "sha256": digest_of(f"{VENDORED}/templates/{n}")}
                      for n in ("AGENTS.md", "CLAUDE.md", "gitattributes")],
        "generated": generated,
    }
    return json.dumps(lock, indent=2).encode("utf-8") + b"\n"


def stage(repo: str, agents: list[str], replace_bridges: bool) -> dict[str, bytes]:
    """Compose every byte this run would write, and refuse before writing any of it."""
    staged: dict[str, bytes] = {}
    for project_path, source in sorted(package_files().items()):
        assert_inside(repo, project_path)
        staged[project_path] = read_bytes(source)

    assert_inside(repo, "AGENTS.md")
    agents_md = os.path.join(repo, "AGENTS.md")
    staged["AGENTS.md"] = compose_agents_md(
        read_bytes(agents_md) if os.path.isfile(agents_md) else None)

    selected = {name for agent in agents for name in BRIDGES[agent]}
    for name in ALL_BRIDGE_FILES:
        path = assert_inside(repo, name)
        template = read_bytes(os.path.join(PACKAGE, "templates", name))
        if name in selected:
            if os.path.isfile(path) and read_bytes(path) != template and not replace_bridges:
                raise Refused(
                    f"{name} exists and differs from the bridge this would write. The whole file "
                    "is generated, so applying would discard it. Move it aside, fold it into "
                    "AGENTS.md, or pass --replace-bridges to say the loss is intended."
                )
            staged[name] = template
        elif os.path.isfile(path):
            raise Refused(
                f"{name} exists but no selected agent uses it, so it would be left behind and "
                "unverified. Include the agent that needs it in --agents, or delete the file."
            )

    attributes = assert_inside(repo, ".gitattributes")
    staged[".gitattributes"] = compose_gitattributes(
        read_bytes(attributes) if os.path.isfile(attributes) else None)

    method_lock = assert_inside(repo, METHOD_LOCK)
    assert_inside(repo, PROJECT_LOCK)
    staged[METHOD_LOCK] = method_lock_bytes()
    # The whole file is generated, exactly as a bridge is, so an existing one that differs is
    # discarded by applying. Refusing a CLAUDE.md in that state and overwriting this one was
    # the same decision made two different ways.
    if os.path.isfile(method_lock) and read_bytes(method_lock) != staged[METHOD_LOCK] \
            and not replace_bridges:
        raise Refused(
            f"{METHOD_LOCK} exists and differs from the one this would write. The whole file is "
            "generated, so applying would discard it - including a provenance or recovery source "
            "somebody set deliberately. Move it aside, or pass --replace-bridges to say the loss "
            "is intended."
        )
    staged[PROJECT_LOCK] = project_lock_bytes(staged, agents)
    return staged


def stage_paths(agents: list[str]) -> list[str]:
    """Exactly what this run owns, for `git add --`.

    `.agents` is not on this list and must not be. It is a directory products share, and a
    project can keep another tool's state in it; staging it wholesale puts somebody else's file
    into the commit that adopts this package. `.agents/agentlanes` is different - every file
    under it belongs to this package, and check.py refuses an unmanaged one.
    """
    names = ["AGENTS.md", ".gitattributes", VENDORED, PROJECT_LOCK, METHOD_LOCK]
    names += sorted({name for agent in agents for name in BRIDGES[agent]})
    return sorted(names)


def differences(repo: str, staged: dict[str, bytes]) -> list[dict[str, str]]:
    changes = []
    for rel, data in sorted(staged.items()):
        path = os.path.join(repo, *rel.split("/"))
        if not os.path.exists(path):
            changes.append({"path": rel, "how": "create"})
        elif read_bytes(path) != data:
            changes.append({"path": rel, "how": "rewrite"})
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Install this package into a project.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    mode = init.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="read-only: print what would change")
    mode.add_argument("--apply", action="store_true", help="write those paths; do not commit")
    init.add_argument("--repo", default=".")
    init.add_argument("--git-executable", required=True)
    init.add_argument("--agents", default="codex,claude-code",
                      help="comma separated: " + ", ".join(sorted(BRIDGES)))
    init.add_argument("--replace-bridges", action="store_true",
                      help="allow an existing whole-file bridge or method lock to be overwritten")
    args = parser.parse_args()

    try:
        repo = os.path.realpath(os.path.abspath(args.repo))
        if not os.path.isdir(repo):
            raise Refused("--repo is not a directory")
        git_exe = resolve_git(args.git_executable)
        load_tracked_names(repo, git_exe)
        # Duplicates would produce a lock with the same bridge recorded twice, which this
        # program's own checker then refuses. An initializer must not exit 0 having written
        # something it will be told is wrong.
        agents = sorted(dict.fromkeys(a.strip() for a in args.agents.split(",") if a.strip()))
        unknown = [a for a in agents if a not in BRIDGES]
        if unknown:
            raise Refused(
                f"no adapter for {', '.join(unknown)}. Known: {', '.join(sorted(BRIDGES))}. "
                "Use 'generic' for a product that reads AGENTS.md, and do not invent an adapter."
            )
        if not agents:
            raise Refused("--agents named no product")

        staged = stage(repo, agents, args.replace_bridges)
        changes = differences(repo, staged)

        if args.plan:
            print(json.dumps({
                "mode": "plan", "wrote": [], "answerFirst": QUESTIONS,
                "wouldChange": changes, "stage": stage_paths(agents),
                "next": "Show this to a human. Nothing has been written.",
            }, indent=2))
            return 0

        for change in changes:
            assert_writable(repo, change["path"])
        # `assert_writable` is a filter, not a proof. On Windows a file opened by an ordinary
        # reader that shares read and write but not delete answers os.access(W_OK) with true and
        # then refuses to be replaced - no race required. So the original bytes of everything
        # about to change are held, and a failure puts every one of them back. That is what
        # makes "nothing has been written" a statement about the whole project, not only about the
        # files the run had not reached yet.
        before: dict[str, bytes | None] = {}
        for change in changes:
            path = os.path.join(repo, *change["path"].split("/"))
            before[change["path"]] = read_bytes(path) if change["how"] == "rewrite" else None
        written: list[str] = []
        try:
            for change in changes:
                write_bytes(os.path.join(repo, *change["path"].split("/")),
                            staged[change["path"]])
                written.append(change["path"])
        except OSError as error:
            restored, stuck = [], []
            for rel in reversed(written):
                path = os.path.join(repo, *rel.split("/"))
                try:
                    if before[rel] is None:
                        os.remove(path)
                    else:
                        write_bytes(path, before[rel])
                    restored.append(rel)
                except OSError:
                    stuck.append(rel)
            if stuck:
                print(json.dumps({
                    "ok": None, "measured": False,
                    "reason": f"writing stopped at {len(written) + 1} of {len(changes)} paths "
                              f"({type(error).__name__}) and {len(stuck)} could not be put back",
                    "notRestored": sorted(stuck),
                    "next": "The project is part converted. Restore these paths by hand - "
                            "`git checkout --` if they were committed - and rerun.",
                }, indent=2))
                return 2
            print(json.dumps({
                "ok": None, "measured": False,
                "reason": f"{changes[len(written)]['path']} could not be written "
                          f"({type(error).__name__}); the {len(restored)} paths already written "
                          "were put back and nothing was left changed",
                "wrote": [],
                "next": "Close whatever is holding that file open, or move it aside, and rerun.",
            }, indent=2))
            return 2
        print(json.dumps({
            "mode": "apply", "wrote": written, "unchanged": not written,
            "stage": stage_paths(agents),
            "next": "Review the diff, stage exactly the paths under `stage`, commit, "
                    "then run check.py. It verifies the committed tree, because that is "
                    "what a clone receives. This command did not commit.",
        }, indent=2))
        return 0
    except Refused as error:
        print(json.dumps({"ok": None, "refused": str(error)}, indent=2))
        return 2
    except Exception as error:  # noqa: BLE001 - a crash must not look like a verdict
        print(json.dumps({"ok": None, "refused": f"unexpected {type(error).__name__}: {error}"},
                         indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
