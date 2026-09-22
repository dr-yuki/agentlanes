#!/usr/bin/env python3
"""Prove that init plans without writing, refuses rather than damages, and repeats.

Cases marked (audit) were found by an independent review of an earlier revision. In that
revision each of them returned exit 0, and three of them destroyed or overwrote bytes.

    <python> -I -B cli/test_init.py --git-executable <git>
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.stderr.write("test_init.py requires Python 3.10 or newer\n")
    raise SystemExit(2)
if sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1:
    sys.stderr.write("test_init.py must be invoked with Python -I -B\n")
    raise SystemExit(2)

import argparse
import json
import os
import shutil
import contextlib
import ctypes
import importlib.util
import io
import stat
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INIT = os.path.join(HERE, "agentlanes.py")
CHECK = os.path.join(HERE, "check.py")
# Exactly what `init --apply` reports under `stage`. Never `.agents`: that directory is shared
# with whatever else the project uses, and staging it wholesale commits another tool's files.
STAGE = ["AGENTS.md", "CLAUDE.md", ".gitattributes", ".agents/agentlanes",
         ".agents/agentlanes.lock.json", ".agents/multi-lane-wave-method.lock.json"]

OWN_INSTRUCTIONS = b"# My project\n\nBuild with `make`. Do not touch vendor/.\n"
OWN_ATTRIBUTES = b"*.png binary\n"
# How many rows a complete run records, before the row that checks this number. It is the same
# on every platform: a state a platform cannot build is recorded once per row as notApplicable,
# never as one row standing for several. Raise it when you add a case - that is the point. It
# went in because two platforms disagreed about it silently, 81 against 77, both green.
ROWS = 81


def force_writable(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: str) -> None:
    """Delete a temporary tree, making entries writable on the way. Cleanup decides no verdict.

    This used to be `shutil.rmtree(path, onexc=force_writable, ignore_errors=True)`. `onexc`
    exists only from Python 3.12, and this suite accepts 3.10, where that keyword is a TypeError
    and the report is never printed. Where it is accepted the handler never ran either:
    ignore_errors replaces it.
    """
    def retry(func, target, error):
        try:
            force_writable(func, target, error)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def run(script: str, repo: str, git_exe: str, *args: str) -> tuple[int, dict]:
    done = subprocess.run(
        [sys.executable, "-I", "-B", script, *args, "--repo", repo, "--git-executable", git_exe],
        capture_output=True, text=True, timeout=900, check=False,
    )
    try:
        return done.returncode, json.loads(done.stdout)
    except json.JSONDecodeError:
        return done.returncode, {"stdout": done.stdout[-800:], "stderr": done.stderr[-800:]}


def stage_and_commit(repo: str, git_exe: str) -> None:
    """Stage the exact paths, then commit them.

    A clone receives the committed tree. Stopping at `git add` measured a project nobody else
    could obtain, and check.py says so now rather than calling it clean.
    """
    subprocess.run([git_exe, "-C", repo, "add", "--", *STAGE],
                   capture_output=True, timeout=120, check=True)
    subprocess.run([git_exe, "-C", repo, "-c", "user.name=t", "-c",
                    "user.email=t@example.invalid", "commit", "-q", "-m", "adopt"],
                   capture_output=True, timeout=120, check=True)


def put(repo: str, rel: str, data: bytes) -> None:
    path = os.path.join(repo, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def tracked_and_hidden(root: str, git_exe: str, rel: str, hide: bool) -> str:
    """A project that commits its own `rel`, and with `hide` takes it off the disk.

    skip-worktree keeps a committed file in every clone and out of every directory listing
    here, which is what separates a check that asks git from one that asks the disk. The
    directories that held only that file go too, so the disk shows nothing at all.
    """
    repo = tempfile.mkdtemp(prefix="h", dir=root)

    def git(*args: str) -> None:
        subprocess.run([git_exe, "-C", repo, *args], capture_output=True, timeout=120,
                       check=True)

    git("init", "-q", "-b", "main")
    put(repo, rel, b"# the project's own file\n")
    git("add", "--", rel)
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "mine")
    if hide:
        git("update-index", "--skip-worktree", "--", rel)
        path = os.path.join(repo, *rel.split("/"))
        os.remove(path)
        parent = os.path.dirname(path)
        while parent != repo and not os.listdir(parent):
            os.rmdir(parent)
            parent = os.path.dirname(parent)
    return repo


def new_project(root: str, git_exe: str, own_files: bool = False) -> str:
    repo = tempfile.mkdtemp(prefix="p", dir=root)
    subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                   capture_output=True, timeout=120, check=True)
    if own_files:
        with open(os.path.join(repo, "AGENTS.md"), "wb") as handle:
            handle.write(OWN_INSTRUCTIONS)
        with open(os.path.join(repo, ".gitattributes"), "wb") as handle:
            handle.write(OWN_ATTRIBUTES)
    return repo


def snapshot(root: str) -> dict[str, bytes]:
    """Every byte under a directory, including .git, so a transient write is visible."""
    seen: dict[str, bytes] = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                with open(full, "rb") as handle:
                    seen[rel] = handle.read()
            except OSError:
                seen[rel] = b"<unreadable>"
    return seen


# A hook that records writes as they happen, rather than comparing directories before and
# after. `--plan` writing a file and deleting it again leaves both snapshots identical, and
# that is exactly what the before/after comparison could not see.
AUDIT_RUNNER = """
import json, os, runpy, sys

WRITES = []
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def hook(event, args):
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wxa+")) or (
            isinstance(flags, int) and bool(flags & WRITE_FLAGS))
        if writing:
            WRITES.append("open " + repr(path))
    elif event in ("os.rename", "os.replace", "os.remove", "os.unlink", "os.mkdir",
                   "os.rmdir", "os.truncate", "shutil.copyfile", "shutil.move"):
        WRITES.append(event + " " + repr(args))


sys.addaudithook(hook)
script = sys.argv.pop(1)
sys.argv[0] = script
try:
    runpy.run_path(script, run_name="__main__")
    code = 0
except SystemExit as stop:
    code = stop.code or 0
sys.stderr.write("AUDIT " + json.dumps({"writes": WRITES, "exit": code}) + "\\n")
"""


def plan_under_audit(workspace: str, repo: str, git_exe: str) -> tuple[int, list[str]]:
    runner = os.path.join(workspace, "audit_runner.py")
    with open(runner, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(AUDIT_RUNNER)
    done = subprocess.run(
        [sys.executable, "-I", "-B", runner, INIT, "init", "--plan",
         "--repo", repo, "--git-executable", git_exe],
        capture_output=True, text=True, timeout=900, check=False,
    )
    line = [l for l in done.stderr.splitlines() if l.startswith("AUDIT ")]
    if not line:
        return done.returncode, ["<the audit runner produced nothing: " + done.stderr[-160:] + ">"]
    payload = json.loads(line[-1][len("AUDIT "):])
    # The guard runs as a separate process and this hook cannot see into it. It is measured
    # not to write, and the byte-for-byte snapshot above covers the project directory anyway.
    return payload["exit"], payload["writes"]


def hold_undeletable(path: str):
    """A handle that shares read and write but not delete - an ordinary reader on Windows.

    os.access answers "writable" for a file held like this and os.replace then refuses, which
    is how a run that reported writing nothing came to have written every path before the one
    it stopped at. The count moves with the number a fresh install writes - it was nineteen of
    twenty-one when this was written, and the rows below report twenty of twenty-two now that
    the LICENSE is a role. The figures in `agentlanes.py` are from the earlier size too.

    **This state does not exist on POSIX.** There, os.replace needs write permission on the
    directory and ignores the file's own mode, and a file this program cannot write answers
    os.access(W_OK) with no - so the pre-flight refuses before the branch under test is
    reached. The two states built on this are marked not applicable rather than skipped: a
    thing that cannot happen here is different from a thing that was not tried, and different
    again from a pass. Two states, but six rows, and it is the rows that are counted - each
    one is recorded, so the run is the same size on every platform.
    """
    if os.name != "nt":
        return None, None
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p]
    handle = kernel32.CreateFileW(path, 0x80000000, 0x00000001 | 0x00000002, None, 3, 0x80, None)
    if handle in (None, 0, 2 ** 64 - 1, -1):
        # The state exists here and was not built. That is a failure to measure, not a
        # platform without the state, so the callers report it red, not as not applicable.
        return kernel32, None
    return kernel32, handle


def apply_with_a_failing_write(workspace: str, git_exe: str, failing: str,
                               unrestorable: str) -> tuple[int, dict]:
    """Run `init --apply` in-process with one write failing and one restore failing.

    The restore branch needs a write to succeed and then refuse to be undone, and nothing
    outside the run can arrange that on a real filesystem - the file does not exist until the
    run creates it. An earlier version of this raced a thread for the handle and sometimes lost,
    which made the whole suite non-deterministic. Importing the module and failing a named write
    reaches the same branch every time.
    """
    spec = importlib.util.spec_from_file_location("agentlanes_under_test", INIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    repo = tempfile.mkdtemp(prefix="stuck", dir=workspace)
    subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                   capture_output=True, timeout=120, check=True)
    put(repo, unrestorable, OWN_ATTRIBUTES)          # exists, so restoring it is a write
    put(repo, failing, b"# not the bridge\n")

    real_write = module.write_bytes
    state = {"failed": False}

    # The exact path, not its basename: the vendored templates/CLAUDE.md shares a basename
    # with the bridge and is written first, so a basename match fired on the wrong file.
    fail_at = os.path.join(repo, *failing.split("/"))
    keep_at = os.path.join(repo, *unrestorable.split("/"))

    def failing_write(path: str, data: bytes) -> None:
        if not state["failed"] and os.path.abspath(path) == os.path.abspath(fail_at):
            state["failed"] = True
            raise OSError(13, "injected: this write cannot happen")
        if state["failed"] and os.path.abspath(path) == os.path.abspath(keep_at):
            raise OSError(13, "injected: this restore cannot happen")
        real_write(path, data)

    module.write_bytes = failing_write
    argv, out = sys.argv, io.StringIO()
    sys.argv = ["agentlanes.py", "init", "--apply", "--replace-bridges",
                "--repo", repo, "--git-executable", git_exe]
    try:
        with contextlib.redirect_stdout(out):
            code = module.main()
    finally:
        sys.argv = argv
    try:
        return code, json.loads(out.getvalue())
    except json.JSONDecodeError:
        return code, {"stdout": out.getvalue()[-300:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-executable", required=True)
    args = parser.parse_args()
    git_exe = args.git_executable
    results: list[dict] = []

    def record(name: str, passed: bool, detail: object = "") -> None:
        results.append({"case": name, "pass": bool(passed), "detail": detail})

    def not_applicable(name: str, why: str) -> None:
        """A state this platform cannot construct. Not a pass, and not a failure either.

        Recording it as a pass would be a green that means nothing; recording it as a failure
        would make the suite red on every platform but one. The row carries "pass": true so the
        run is not red, and "notApplicable" with the reason, which is what a reader counting
        passes has to leave out.
        """
        results.append({"case": name, "pass": True, "notApplicable": why})

    # Resolved for the same reason as in test_check.py: the installer resolves its --repo,
    # and a workspace reached through a symlink or spelled as an 8.3 short name is a different
    # string from the one it reports back.
    workspace = os.path.realpath(tempfile.mkdtemp(prefix="agentlanes-init-"))
    try:
        # --- plan writes nothing, measured over every byte rather than a file list
        repo = new_project(workspace, git_exe, own_files=True)
        before = snapshot(repo)
        code, payload = run(INIT, repo, git_exe, "init", "--plan")
        record("plan exits 0", code == 0, code)
        record("plan changes no byte anywhere, .git included", snapshot(repo) == before)
        record("plan reports no writes", payload.get("wrote") == [], payload.get("wrote"))
        record("plan asks before it acts", len(payload.get("answerFirst", [])) >= 5)

        # --- apply keeps what the project wrote
        code, _ = run(INIT, repo, git_exe, "init", "--apply")
        record("apply exits 0", code == 0, code)
        agents_md = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        record("the project's own instructions survive", OWN_INSTRUCTIONS.strip() in agents_md)
        record("the generated region is first", agents_md.startswith(b"<!-- agentlanes:begin"),
               agents_md[:36].decode("utf-8", "replace"))
        attributes = open(os.path.join(repo, ".gitattributes"), "rb").read()
        record("the project's own attributes survive", OWN_ATTRIBUTES.strip() in attributes)
        record("the managed pins are last, so they are in effect",
               attributes.rstrip().endswith(b"# agentlanes:end")
               and attributes.find(b"CLAUDE.md text eol=lf")
               > attributes.find(OWN_ATTRIBUTES.strip()) >= 0,
               attributes.rstrip()[-40:].decode("utf-8", "replace"))
        stage_and_commit(repo, git_exe)
        code, _ = run(CHECK, repo, git_exe)
        record("check exits 0 on what apply produced", code == 0, code)
        vendored = os.path.join(repo, ".agents", "agentlanes", "cli", "check.py")
        record("the checker is vendored into the project", os.path.isfile(vendored))
        code, _ = run(vendored, repo, git_exe)
        record("the project can run its own vendored checker", code == 0, code)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("applying twice writes nothing", payload.get("wrote") == [], payload.get("wrote"))
        code, payload = run(INIT, repo, git_exe, "init", "--plan")
        record("(audit) plan on a current install reports no change",
               payload.get("wouldChange") == [], payload.get("wouldChange"))

        # --- (audit) an ambiguous marker line must not be read as a marker
        repo = new_project(workspace, git_exe)
        ambiguous = (b"<!-- agentlanes:beginning of my own notes -->\nKEEP-THIS\n"
                     b"<!-- agentlanes:end -->\ntail\n")
        with open(os.path.join(repo, "AGENTS.md"), "wb") as handle:
            handle.write(ambiguous)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        after = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        record("(audit) an unpaired end marker is refused rather than guessed",
               code == 2 and "marker line" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        # Every byte, not two words from it: a refusal that had put a region above them, or
        # rewritten the lines around them, would still contain both.
        record("(audit) the project's bytes are untouched by that refusal", after == ambiguous,
               repr(after[:60]))

        # --- (audit) a predictable temporary name must not be usable as a link target
        repo = new_project(workspace, git_exe)
        victim = os.path.join(workspace, "victim.txt")
        with open(victim, "wb") as handle:
            handle.write(b"ORIGINAL VICTIM CONTENT\n")
        link = os.path.join(repo, "AGENTS.md.agentlanes-tmp")
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/H", link, victim],
                                  capture_output=True, timeout=120, check=False)
            linked = made.returncode == 0
        else:
            try:
                os.link(victim, link)
                linked = True
            except OSError:
                linked = False
        if linked:
            run(INIT, repo, git_exe, "init", "--apply")
            record("(audit) a file outside the project is not overwritten",
                   open(victim, "rb").read() == b"ORIGINAL VICTIM CONTENT\n")
        else:
            record("(audit) hardlink case skipped: could not create a link here", False,
                   "SKIPPED - this is not a pass; rerun where hard links can be made")

        # --- (audit) a link in the path must stop the run before the first write
        repo = new_project(workspace, git_exe)
        outside = os.path.join(workspace, "elsewhere")
        os.makedirs(outside, exist_ok=True)
        # A junction on Windows and a directory symlink elsewhere: one state, two names for
        # it, and one refusal - `is_reparse` tests S_ISLNK before the Windows attribute.
        if os.name == "nt":
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", os.path.join(repo, ".agents"), outside],
                capture_output=True, timeout=120, check=False)
            made_link = junction.returncode == 0
        else:
            try:
                os.symlink(outside, os.path.join(repo, ".agents"), target_is_directory=True)
                made_link = True
            except OSError:
                made_link = False
        # The third place with the shape audit 3 and audit 4 were fixed for: one branch decides
        # two rows and the other stood for both with one, so a machine that cannot make a
        # directory link recorded 80 rows and named only one of the two questions it skipped.
        refused, nothing_through = ("(audit) a junction on the write path is refused",
                                    "(audit) nothing was written through the junction")
        if made_link:
            code, payload = run(INIT, repo, git_exe, "init", "--apply")
            record(refused, code == 2 and "junction" in payload.get("refused", ""),
                   payload.get("refused", "")[:90])
            record(nothing_through, not os.listdir(outside), os.listdir(outside)[:4])
        else:
            # Not `notApplicable`: every platform can make one of the two kinds of link, so a
            # failure here is a failure to build a state that exists, not a state that cannot.
            for name in (refused, nothing_through):
                record(name, False,
                       "SKIPPED - this is not a pass; rerun where a directory link can be made")

        # --- (audit) text that is not UTF-8 is refused rather than composed
        repo = new_project(workspace, git_exe)
        with open(os.path.join(repo, "AGENTS.md"), "wb") as handle:
            handle.write("# 見出し\n".encode("utf-16"))
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit) a non-UTF-8 instruction file is refused",
               code == 2 and "UTF-8" in payload.get("refused", ""), payload.get("refused", "")[:90])

        # --- (audit) pins already present but overridden later must be moved to the end
        repo = new_project(workspace, git_exe)
        with open(os.path.join(repo, ".gitattributes"), "wb") as handle:
            handle.write(b".agents/agentlanes/** text eol=lf\n"
                         b".agents/multi-lane-wave-method.lock.json text eol=lf\n"
                         b".agents/agentlanes.lock.json text eol=lf\n"
                         b"AGENTS.md text eol=lf\nCLAUDE.md text eol=lf\n"
                         b"* -text\n")
        run(INIT, repo, git_exe, "init", "--apply")
        stage_and_commit(repo, git_exe)
        code, payload = run(CHECK, repo, git_exe)
        record("(audit) a later conflicting rule does not survive as the effective one",
               code == 0, str(payload.get("findings", payload.get("reason")))[:110])

        # --- (audit) a differing whole-file bridge is not silently replaced
        repo = new_project(workspace, git_exe)
        with open(os.path.join(repo, "CLAUDE.md"), "wb") as handle:
            handle.write(b"# our own CLAUDE instructions\n")
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit) an existing differing bridge is refused without consent",
               code == 2 and "--replace-bridges" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        record("(audit) that bridge still holds its own bytes",
               open(os.path.join(repo, "CLAUDE.md"), "rb").read() == b"# our own CLAUDE instructions\n")
        code, _ = run(INIT, repo, git_exe, "init", "--apply", "--replace-bridges")
        record("consent lets it through", code == 0, code)

        # --- (audit) deselecting an agent must not leave its bridge unverified
        repo = new_project(workspace, git_exe)
        run(INIT, repo, git_exe, "init", "--apply")
        code, payload = run(INIT, repo, git_exe, "init", "--apply", "--agents", "codex")
        record("(audit) dropping an agent whose bridge exists is refused",
               code == 2 and "no selected agent uses it" in payload.get("refused", ""),
               payload.get("refused", "")[:90])


        # --- (audit) a destination that cannot be written stops the run before the first write
        repo = new_project(workspace, git_exe)
        agents = os.path.join(repo, "AGENTS.md")
        with open(agents, "wb") as handle:
            handle.write(OWN_INSTRUCTIONS)
        # Remembered rather than reconstructed: S_IWRITE clears the read-only flag on Windows
        # and means "owner may write, nobody may read" on POSIX, so restoring with it made the
        # file unreadable and the check below raised instead of measuring.
        was = os.stat(agents).st_mode
        os.chmod(agents, stat.S_IREAD)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit) a read-only destination is refused, with a reason, not a traceback",
               code == 2 and "not writable" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        left = sorted(rel for rel in snapshot(repo) if not rel.startswith(".git/"))
        record("(audit) the refusal left the project as it was", left == ["AGENTS.md"], left[:6])
        os.chmod(agents, was)
        record("(audit) the file it could not write still holds its own bytes",
               open(agents, "rb").read() == OWN_INSTRUCTIONS)

        # --- (audit) the same agent named twice is one agent
        repo = new_project(workspace, git_exe)
        code, payload = run(INIT, repo, git_exe, "init", "--apply",
                            "--agents", "codex,claude-code,codex")
        record("(audit) a repeated --agents entry is accepted once", code == 0,
               payload.get("refused", code))
        stage_and_commit(repo, git_exe)
        code, payload = run(CHECK, repo, git_exe)
        record("(audit) and what it installed still checks clean", code == 0,
               str(payload.get("findings", payload.get("reason", "")))[:110])

        # --- (audit) plan writes nothing into the temporary directory either
        repo = new_project(workspace, git_exe)
        observed = tempfile.mkdtemp(prefix="tmp-observed-", dir=workspace)
        env = dict(os.environ, TMPDIR=observed, TEMP=observed, TMP=observed)
        done = subprocess.run(
            [sys.executable, "-I", "-B", INIT, "init", "--plan", "--repo", repo,
             "--git-executable", git_exe],
            capture_output=True, text=True, timeout=900, check=False, env=env,
        )
        record("(audit) plan leaves the temporary directory empty as well",
               done.returncode == 0 and os.listdir(observed) == [],
               os.listdir(observed)[:4] or done.returncode)

        # --- a project written with CRLF keeps its own line endings and gains one block, once
        repo = new_project(workspace, git_exe)
        with open(os.path.join(repo, "AGENTS.md"), "wb") as handle:
            handle.write(b"# My project\r\n\r\n\r\nBuild with `make`.\r\n")
        run(INIT, repo, git_exe, "init", "--apply")
        first = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        record("a CRLF project keeps its own blank lines", b"\r\n\r\n\r\nBuild with" in first,
               first[-60:].decode("utf-8", "replace"))
        run(INIT, repo, git_exe, "init", "--apply")
        second = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        record("re-applying to a CRLF file adds no second block",
               first == second and second.count(b"agentlanes:begin") == 1,
               second.count(b"agentlanes:begin"))

        # --- (audit 3) the stage list is what a person is told to run, so it is checked
        repo = new_project(workspace, git_exe)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        listed = payload.get("stage", [])
        record("(audit 3) the stage list never names the shared .agents directory",
               ".agents" not in listed and ".agents/agentlanes" in listed, listed)
        record("(audit 3) it names both locks by their exact paths",
               ".agents/agentlanes.lock.json" in listed
               and ".agents/multi-lane-wave-method.lock.json" in listed, listed)
        wrote = set(payload.get("wrote", []))
        covered = {w for w in wrote
                   if any(w == name or w.startswith(name + "/") for name in listed)}
        record("(audit 3) every path it wrote is under something on that list",
               covered == wrote, sorted(wrote - covered)[:4])

        # --- (license) the MIT notice travels with the vendored files, and the lock pins it
        import hashlib
        shipped = open(os.path.join(os.path.dirname(HERE), "LICENSE"), "rb").read()
        carried = os.path.join(repo, ".agents", "agentlanes", "LICENSE")
        carried_bytes = open(carried, "rb").read() if os.path.isfile(carried) else b""
        record("(license) the install carries the package's LICENSE, byte for byte",
               carried_bytes == shipped and shipped.startswith(b"MIT License"),
               len(carried_bytes))
        pinned = json.loads(open(os.path.join(repo, ".agents", "agentlanes.lock.json"),
                                 encoding="utf-8").read()).get("license", {})
        record("(license) and the project lock pins it by digest",
               pinned.get("path") == ".agents/agentlanes/LICENSE"
               and pinned.get("sha256") == "sha256:" + hashlib.sha256(shipped).hexdigest(),
               pinned)

        # --- (audit 3) plan writes nothing, measured as it runs rather than after
        repo = new_project(workspace, git_exe)
        code, writes = plan_under_audit(workspace, repo, git_exe)
        record("(audit 3) plan opens nothing for writing anywhere", code == 0 and writes == [],
               writes[:3] or code)

        # --- (audit 3) a failed apply puts back everything it had written
        repo = new_project(workspace, git_exe, own_files=True)
        edit_target = os.path.join(repo, "AGENTS.md")
        original = open(edit_target, "rb").read()
        subprocess.run([git_exe, "-C", repo, "checkout", "-q", "--", "."],
                       capture_output=True, timeout=120, check=False)
        fresh = new_project(workspace, git_exe)
        target = os.path.join(fresh, "AGENTS.md")
        before = snapshot(fresh)
        put(fresh, "AGENTS.md", OWN_INSTRUCTIONS)      # make one path need rewriting
        before = snapshot(fresh)
        kernel32, held = hold_undeletable(target)
        # One name per row in every branch, so the three answers exist on every platform.
        # They did not: where the state cannot be built, one notApplicable row used to stand
        # for all three, and the same in audit 4. POSIX runs therefore reported 77 rows and
        # Windows 81, both green, with nothing in either saying which four were missing.
        stops, says_so, bytes_kept = (
            "(audit 3) a write that cannot happen stops the run",
            "(audit 3) and it says nothing was left changed",
            "(audit 3) and nothing was: every byte is as it was")
        if kernel32 is None:
            for name in (stops, says_so, bytes_kept):
                not_applicable(name,
                               "a share-mode handle is a Windows state; os.replace on POSIX "
                               "ignores the file's mode and the pre-flight refuses first")
        elif held is None:
            for name in (stops, says_so, bytes_kept):
                record(name, False,
                       "the share-mode handle could not be opened, so nothing was measured")
        else:
            try:
                code, payload = run(INIT, fresh, git_exe, "init", "--apply")
                record(stops, code == 2,
                       payload.get("reason", payload.get("refused", ""))[:90])
                record(says_so,
                       "nothing was left changed" in payload.get("reason", ""),
                       payload.get("reason", "")[:90])
                record(bytes_kept,
                       snapshot(fresh) == before,
                       sorted(set(snapshot(fresh)) ^ set(before))[:4])
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(held))

        # --- (audit 3) the project's own blank lines at both edges of the region
        repo = new_project(workspace, git_exe)
        subprocess.run([git_exe, "-C", repo, "rm", "-rq", "--cached", "."],
                       capture_output=True, timeout=120, check=False)
        repo = tempfile.mkdtemp(prefix="blank", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, "AGENTS.md", b"\n\n# My project\n")
        put(repo, ".gitattributes", b"*.png binary\n\n\n")
        run(INIT, repo, git_exe, "init", "--apply")
        agents_md = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        attributes = open(os.path.join(repo, ".gitattributes"), "rb").read()
        record("(audit 3) leading blank lines the project wrote are still there",
               agents_md.endswith(b"\n\n\n# My project\n"), repr(agents_md[-30:]))
        record("(audit 3) trailing blank lines the project wrote are still there",
               attributes.startswith(b"*.png binary\n\n\n"), repr(attributes[:30]))
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 3) and applying again changes nothing",
               payload.get("wrote") == [], payload.get("wrote"))

        # --- (audit 3) a marker pair in the project's own prose is not this program's region
        repo = tempfile.mkdtemp(prefix="prose", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        own = (b"# My project\n\nWe document the convention here:\n\n"
               b"<!-- agentlanes:begin -->\nKEEP-THIS\n<!-- agentlanes:end -->\n\nTAIL\n")
        put(repo, "AGENTS.md", own)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 3) a marker pair that is not first is refused, not rewritten round",
               code == 2 and "not where this program writes one" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        record("(audit 3) and the paragraph between those markers is still there",
               open(os.path.join(repo, "AGENTS.md"), "rb").read() == own)

        # --- (audit 3) a byte-order mark cannot be moved into the middle of somebody's text
        repo = tempfile.mkdtemp(prefix="bom", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, "AGENTS.md", b"\xef\xbb\xbf# My project\n")
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 3) a byte-order mark is refused rather than relocated",
               code == 2 and "moved into the middle of your text" in payload.get("refused", ""),
               payload.get("refused", "")[:90])

        # --- (sweep) the same mark in the other destination, where the reason is different
        # The region is written LAST in .gitattributes, so it would not move at all. Refusing
        # is still right - git reads the mark as part of the first pattern line - but the
        # reason given was the instruction file's, and a reader who checks finds it false.
        repo = tempfile.mkdtemp(prefix="bomattrs", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, ".gitattributes", b"\xef\xbb\xbf*.png binary\n")
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        # (audit 7) This used to be refused, and the reason given was false: measured on git
        # 2.54, a .gitattributes beginning with a mark still applies its first pattern. The
        # region is appended at the end of this file, so the mark does not move either. What
        # is asserted now is what was measured.
        after = open(os.path.join(repo, ".gitattributes"), "rb").read()
        record("(audit 7) a mark in .gitattributes does not stop the install",
               code == 0, payload.get("refused", code))
        record("(audit 7) and the mark is still where the project put it",
               after.startswith(b"\xef\xbb\xbf"), repr(after[:12]))
        record("(audit 7) and the project's own line survives",
               b"*.png binary" in after, repr(after[:40]))
        record("(audit 7) and the managed region is last, so nothing moved the mark",
               after.rstrip().endswith(b"# agentlanes:end"), repr(after[-30:]))

        # --- (audit 3) a generated lock is treated like a generated bridge
        repo = tempfile.mkdtemp(prefix="lock", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, ".agents/multi-lane-wave-method.lock.json", b'{"mine": true}\n')
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 3) an existing method lock is refused without consent",
               code == 2 and "--replace-bridges" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        record("(audit 3) and it still holds its own bytes",
               open(os.path.join(repo, ".agents", "multi-lane-wave-method.lock.json"),
                    "rb").read() == b'{"mine": true}\n')
        code, _ = run(INIT, repo, git_exe, "init", "--apply", "--replace-bridges")
        record("(audit 3) consent lets that through too", code == 0, code)

        # --- (sweep) a project file whose name differs only by case is not renamed
        repo = tempfile.mkdtemp(prefix="case", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        # Left untracked on purpose. A committed one is caught by the tracked-names refusal
        # before this branch is reached, so tracking it here would move the case to the other
        # check and leave the working-tree listing with no counterexample at all.
        put(repo, "agents.md", b"# my own lowercase file\n")
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        names = sorted(n for n in os.listdir(repo) if n.lower() == "agents.md")
        record("(sweep) a name differing only by case is refused, not renamed",
               code == 2 and "already has" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        record("(sweep) and the project's file still has the name it had",
               names == ["agents.md"], names)

        # --- (audit 7) the same collision, tracked and not on the disk
        # A committed file marked skip-worktree is in every clone and in no listing here, so
        # os.listdir saw an empty directory and the run wrote AGENTS.md beside it. The two
        # branches are kept apart on purpose: this project tracks the name and does not have
        # it, the one above has it and does not track it, and each is the only counterexample
        # for its own half.
        repo = tempfile.mkdtemp(prefix="skipped", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, "agents.md", b"# my own notes\n")
        subprocess.run([git_exe, "-C", repo, "add", "--", "agents.md"],
                       capture_output=True, timeout=120, check=True)
        subprocess.run([git_exe, "-C", repo, "-c", "user.name=t",
                        "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "mine"],
                       capture_output=True, timeout=120, check=True)
        subprocess.run([git_exe, "-C", repo, "update-index", "--skip-worktree", "--",
                        "agents.md"], capture_output=True, timeout=120, check=True)
        os.remove(os.path.join(repo, "agents.md"))
        before = snapshot(repo)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 7) a tracked name that is not on the disk still collides",
               code == 2 and "already tracks" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        # The disk, not the payload: a refusal carries no "wrote" at all, so asking the payload
        # answered yes on every refused run, whatever had been written.
        record("(audit 7) and nothing was written beside it", snapshot(repo) == before,
               sorted(set(snapshot(repo)) ^ set(before))[:4])

        # --- (audit 8) a tracked name where this program needs the other kind of thing
        # The comparison above was whole-path only. A tracked FILE `.AGENTS` is not the name of
        # anything this program writes, and on Windows and macOS it is `.agents/`, the directory
        # it needs. Measured in the other direction as well: a tracked directory `agents.md/`,
        # and `AGENTS.md/` spelled exactly as this program spells it, where it writes a file.
        # Hidden by skip-worktree, each was in every clone and in no listing here, and each run
        # wrote 21 paths.
        baseline = sorted(run(INIT, new_project(workspace, git_exe), git_exe,
                              "init", "--apply")[1].get("wrote", []))
        for rel, words in ((".AGENTS", "needs a directory by that name"),
                           ("agents.md/notes.txt", "is a directory in this project"),
                           ("AGENTS.md/notes.txt", "is a directory in this project")):
            repo = tracked_and_hidden(workspace, git_exe, rel, hide=True)
            before = snapshot(repo)
            code, payload = run(INIT, repo, git_exe, "init", "--apply")
            record(f"(audit 8) a hidden tracked {rel} is refused",
                   code == 2 and words in payload.get("refused", ""),
                   payload.get("refused", "")[:90])
            record(f"(audit 8) and nothing was written around {rel}", snapshot(repo) == before,
                   sorted(set(snapshot(repo)) ^ set(before))[:4])
        # The controls. Another tool's files under `.agents/` share a first component with this
        # program's and collide with nothing; a comparison that stopped short of the last
        # component would refuse every project that has them.
        for hide in (False, True):
            repo = tracked_and_hidden(workspace, git_exe, ".agents/skills/foo/SKILL.md", hide)
            code, payload = run(INIT, repo, git_exe, "init", "--apply")
            state = "hidden" if hide else "on the disk"
            record(f"(audit 8) another tool's .agents/skills file {state} is left alone",
                   code == 0 and bool(baseline)
                   and sorted(payload.get("wrote", [])) == baseline,
                   (code, len(payload.get("wrote", [])), payload.get("refused", "")[:90]))

        # --- (audit 4) the rollback restores bytes, not only removes files it created
        # The previous rollback case only ever created files, so the branch that writes an
        # existing file's bytes back was never reached and deleting it changed nothing. Sorted
        # order puts ".gitattributes" before "AGENTS.md", so a project with its own attributes
        # file has one rewritten before the unwritable one is reached.
        repo = tempfile.mkdtemp(prefix="restore", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        put(repo, ".gitattributes", OWN_ATTRIBUTES)
        put(repo, "AGENTS.md", OWN_INSTRUCTIONS)
        before = snapshot(repo)
        kernel32, held = hold_undeletable(os.path.join(repo, "AGENTS.md"))
        # The same three-in-every-branch as audit 3. The notApplicable row here also carried a
        # fourth name - "put back", where the measured row says "put back byte for byte" - so
        # the two platforms did not even agree on the name of the row they shared.
        put_back, project_kept, says_two = (
            "(audit 4) a file rewritten before the failure is put back byte for byte",
            "(audit 4) and the whole project is as it was",
            "(audit 4) the run says so, and exits 2")
        if kernel32 is None:
            for name in (put_back, project_kept, says_two):
                not_applicable(name, "same Windows state as above")
        elif held is None:
            for name in (put_back, project_kept, says_two):
                record(name, False,
                       "the share-mode handle could not be opened, so nothing was measured")
        else:
            try:
                code, payload = run(INIT, repo, git_exe, "init", "--apply")
                after = snapshot(repo)
                rewritten = open(os.path.join(repo, ".gitattributes"), "rb").read()
                record(put_back, rewritten == OWN_ATTRIBUTES, repr(rewritten[:60]))
                record(project_kept, after == before,
                       sorted(set(after) ^ set(before))[:4])
                record(says_two, code == 2
                       and "nothing was left changed" in payload.get("reason", ""),
                       payload.get("reason", "")[:80])
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(held))

        # --- (audit 4) the managed attributes block has to be last, or it is inert
        repo = tempfile.mkdtemp(prefix="notlast", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        own = (b"# agentlanes:begin\nAGENTS.md text eol=lf\n# agentlanes:end\n"
               b"*.dat binary\n")
        put(repo, ".gitattributes", own)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 4) a managed block that is not last is refused",
               code == 2 and "not where this program writes one" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        record("(audit 4) and the project's own rule below it survives",
               open(os.path.join(repo, ".gitattributes"), "rb").read() == own)

        # --- (audit 4) the stage list is exactly what this package owns, no more
        repo = new_project(workspace, git_exe)
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 4) the stage list is exactly the six paths, not a superset",
               sorted(payload.get("stage", [])) == sorted(STAGE), payload.get("stage"))

        # --- (audit 5) the preserved bytes are the project's, to the last byte
        # The earlier case used a body whose stripped form was identical, so a mutation adding
        # rstrip to it changed nothing and 59 cases stayed green.
        repo = tempfile.mkdtemp(prefix="exact", dir=workspace)
        subprocess.run([git_exe, "-C", repo, "init", "-q", "-b", "main"],
                       capture_output=True, timeout=120, check=True)
        own = b"# My project   \r\n\r\ntrailing spaces and a blank line above   \r\n\r\n"
        put(repo, "AGENTS.md", own)
        run(INIT, repo, git_exe, "init", "--apply")
        after = open(os.path.join(repo, "AGENTS.md"), "rb").read()
        record("(audit 5) the project's own bytes survive exactly, trailing space included",
               after.endswith(own), repr(after[-40:]))

        # --- (audit 5) a run that says it changed nothing has to have exited 0
        repo = new_project(workspace, git_exe)
        run(INIT, repo, git_exe, "init", "--apply")           # install it first
        code, payload = run(INIT, repo, git_exe, "init", "--apply")
        record("(audit 5) applying to a current install writes nothing AND exits 0",
               code == 0 and payload.get("wrote") == [], (code, payload.get("wrote")))
        code, payload = run(INIT, repo, git_exe, "init", "--plan")
        record("(audit 5) planning a current install reports no change AND exits 0",
               code == 0 and payload.get("wouldChange") == [], (code, payload.get("wouldChange")))

        # --- (audit 5) when the restore itself fails, the run must not claim otherwise
        code, payload = apply_with_a_failing_write(workspace, git_exe,
                                                   failing="CLAUDE.md",
                                                   unrestorable=".gitattributes")
        record("(audit 5) a restore that fails is reported, not swallowed",
               code == 2 and payload.get("notRestored") == [".gitattributes"],
               payload.get("notRestored", payload.get("stdout", ""))[:90])
        record("(audit 5) and the run does not claim nothing was left changed",
               "nothing was left changed" not in payload.get("reason", ""),
               payload.get("reason", "")[:90])
        record("(audit 5) and it names how far it got",
               "could not be put back" in payload.get("reason", ""),
               payload.get("reason", "")[:90])

        # --- refusing is a feature
        repo = new_project(workspace, git_exe)
        code, payload = run(INIT, repo, git_exe, "init", "--plan", "--agents", "some-new-agent")
        record("an unknown agent is refused, not guessed at",
               code == 2 and "do not invent an adapter" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
        code, payload = run(INIT, repo, "git", "init", "--plan")
        record("a bare git command name is refused",
               code == 2 and "absolute" in payload.get("refused", ""),
               payload.get("refused", "")[:90])
    finally:
        remove_tree(workspace)

    # The run's own population. Everything above answers a question about the installer; this
    # answers one about the run: were all of the questions asked. A platform that cannot build
    # a state still records its rows, so the count does not move, and a green run that is
    # quietly smaller than another green run is red here instead.
    names = [row["case"] for row in results]
    record(f"all {ROWS} rows were recorded, each name once",
           len(names) == ROWS and len(set(names)) == ROWS,
           {"recorded": len(names), "distinct": len(set(names)), "expected": ROWS,
            "twice": sorted({n for n in names if names.count(n) > 1})})

    failed = [r for r in results if not r["pass"]]
    print(json.dumps({"ok": not failed, "checked": results}, indent=2, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
