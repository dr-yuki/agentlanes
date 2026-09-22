#!/usr/bin/env python3
"""Deterministic guards for the multi-lane-wave-engineering method.

The tool never runs fetch, checkout, reset, stash, rebase, commit, push, or merge.
It emits metadata and hashes, never repository file contents.
"""

from __future__ import annotations

import sys

# Refuse an unsafe interpreter before importing any module that PYTHONPATH or the script directory
# could shadow. The trusted caller must still resolve the Python executable itself.
if sys.version_info < (3, 10):
    sys.stderr.write("wave_guard.py requires Python 3.10 or newer\n")
    raise SystemExit(1)
if sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1:
    sys.stderr.write("wave_guard.py must be invoked with Python -I -B\n")
    raise SystemExit(1)

# Keep the script directory out of sys.path even under a runtime whose isolated-mode behavior is
# different. The flag check above runs before any shadowable standard-library import.
_SCRIPT_DIRECTORY = __file__.replace("\\", "/").rsplit("/", 1)[0].rstrip("/").casefold()
sys.path[:] = [
    entry
    for entry in sys.path
    if entry
    and entry.replace("\\", "/").rstrip("/").casefold() != _SCRIPT_DIRECTORY
]

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


METHOD_ID = "multi-lane-wave-engineering"
METHOD_VERSION = "2.0.0"
SCHEMA_VERSION = 2
METHOD_LOCK_FIELDS = {
    "schemaVersion",
    "methodId",
    "methodVersion",
    "digestAlgorithm",
    "canonicalDigest",
    "provenanceStatus",
    "sourceRevision",
    "provenanceAuthority",
    "recoverySource",
    "recoveryDigest",
}
HEX_OBJECT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
UNRESOLVED_TEMPLATE_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9])REPLACE(?![A-Z0-9])", re.IGNORECASE
)
RAW_HEADER_RE = re.compile(
    rb"^:([0-7]{6}) ([0-7]{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z][0-9]*)$"
)
FORBIDDEN_PATH_CHARS = set('*?[]\\<>:"|')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_METHOD_ENTRIES = 128
MAX_METHOD_PATH_DEPTH = 16
GIT_TIMEOUT_SECONDS = 120
MAX_CHARTER_CELLS = 64
MAX_WORKTREES = 64
MAX_OWNED_PATHS = 512
MAX_HANDOFFS = 64
MAX_EVIDENCE_REQUIREMENTS = 64
MAX_CHECK_IDS = 64
MAX_ARTIFACTS = 64
MAX_ARTIFACT_STATUS_IDS = 64
MAX_OWNER_LOCAL_CHECKS = 64
MAX_SNAPSHOT_COMMITS = 256
MAX_SNAPSHOT_PATH_ENTRIES = 2048
MAX_SNAPSHOT_BLOB_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_TOTAL_BLOB_BYTES = 256 * 1024 * 1024
MAX_SNAPSHOT_DIFF_BYTES = 64 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_GIT_CALLS_PER_OPERATION = 4096
MAX_OPERATION_SECONDS = 600
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_GIT_EXECUTABLE: Path | None = None
_OPERATION_DEADLINE: float | None = None
_OPERATION_GIT_CALLS = 0
_OPERATION_BLOB_CACHE: dict[str, str] = {}
_OPERATION_BLOB_BYTES = 0


class GuardError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise GuardError(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def reject_unpaired_surrogates(value: Any, label: str) -> None:
    """Reject JSON strings Python cannot encode as canonical UTF-8."""

    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            fail(f"{label} contains an unpaired Unicode surrogate")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_unpaired_surrogates(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            reject_unpaired_surrogates(key, f"{label} object key")
            reject_unpaired_surrogates(item, f"{label}.{key}")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def physical_identity_digest(path: Path) -> str:
    identity = os.path.normcase(os.path.realpath(path)).replace("\\", "/")
    return sha256_bytes(identity.encode("utf-8", "surrogateescape"))


def reject_unresolved_template_tokens(value: Any, label: str) -> None:
    """Reject canonical distributed-template sentinels anywhere in a proof document."""
    if isinstance(value, str):
        if UNRESOLVED_TEMPLATE_TOKEN_RE.search(value):
            fail(f"{label} contains unresolved distributed-template token REPLACE")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_unresolved_template_tokens(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            reject_unresolved_template_tokens(key, f"{label} key")
            reject_unresolved_template_tokens(item, f"{label}.{key}")


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    )


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    left_identity = (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
    )
    right_identity = (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
    )
    # Windows exposes different creation/change timestamp semantics through a file handle and a
    # path stat.  Device + file-index + mode + size + mtime still bind the opened object there.
    if os.name != "nt":
        left_identity += (
            getattr(left, "st_ctime_ns", int(left.st_ctime * 1_000_000_000)),
        )
        right_identity += (
            getattr(right, "st_ctime_ns", int(right.st_ctime * 1_000_000_000)),
        )
    return left_identity == right_identity


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    # Directory size/mtime legitimately changes when unrelated siblings are created.  Device,
    # inode/file-index and mode bind the traversed parent without that false-positive surface.
    return (left.st_dev, left.st_ino, left.st_mode) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
    )


def _validated_path_chain(path: Path, label: str) -> tuple[Path, list[tuple[Path, os.stat_result]]]:
    absolute = path.absolute()
    parts = absolute.parts
    if not parts:
        fail(f"{label} has no absolute path")
    current = Path(parts[0])
    chain: list[tuple[Path, os.stat_result]] = []
    for part in parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            fail(f"{label} does not exist: {path}")
        if _is_link_or_reparse(info):
            fail(f"{label} cannot traverse a symlink or reparse point: {path}")
        chain.append((current, info))
    return absolute, chain


def validate_no_reparse_chain(path: Path, label: str) -> Path:
    absolute, _chain = _validated_path_chain(path, label)
    return absolute


def read_regular_bytes(path: Path, label: str, *, maximum: int = MAX_JSON_BYTES) -> bytes:
    safe_path, parent_chain_before = _validated_path_chain(path, label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(safe_path, flags)
    except (FileNotFoundError, OSError) as error:
        fail(f"{label} could not be opened safely: {error}")
    try:
        before = os.fstat(descriptor)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            fail(f"{label} must be a regular, non-link file: {path}")
        if before.st_size > maximum:
            fail(f"{label} exceeds the {maximum}-byte metadata limit: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    safe_path_after, parent_chain_after = _validated_path_chain(safe_path, label)
    if safe_path_after != safe_path or len(parent_chain_after) != len(parent_chain_before):
        fail(f"{label} path changed while it was being read: {path}")
    for index, ((before_path, before_info), (after_path, after_info)) in enumerate(
        zip(parent_chain_before, parent_chain_after)
    ):
        identity_matches = (
            _same_file_identity(before_info, after_info)
            if index == len(parent_chain_before) - 1
            else _same_directory_identity(before_info, after_info)
        )
        if before_path != after_path or not identity_matches:
            fail(f"{label} parent path changed while it was being read: {path}")
    current = parent_chain_after[-1][1] if parent_chain_after else safe_path.lstat()
    if not _same_file_identity(before, after) or not _same_file_identity(after, current):
        fail(f"{label} changed while it was being read: {path}")
    if len(data) != before.st_size:
        fail(f"{label} size changed while it was being read: {path}")
    return data


def load_json_file(path: Path, label: str) -> Any:
    try:
        raw = read_regular_bytes(path, label)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_object)
        reject_unpaired_surrogates(value, label)
        return value
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"{label} is not valid UTF-8 JSON: {error}")


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def require_list(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{label} must be an array")
    if nonempty and not value:
        fail(f"{label} must not be empty")
    return value


def bounded_list(
    value: Any,
    label: str,
    *,
    limit: int,
    nonempty: bool = False,
) -> list[Any]:
    result = require_list(value, label, nonempty=nonempty)
    if len(result) > limit:
        fail(f"{label} cannot exceed {limit} entries")
    return result


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        fail(f"{label} must be a nonempty string without surrounding whitespace")
    return value


def require_integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        fail(f"{label} must be an integer, not a boolean or other JSON value")
    if minimum is not None and value < minimum:
        fail(f"{label} must be at least {minimum}")
    return value


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        fail(f"{label} fields do not match schema; missing={missing}, extra={extra}")


def resolve_regular_json(base: Path, value: str, label: str) -> Path:
    validate_repo_path(value, label)
    root = validate_no_reparse_chain(base, f"{label} proof root")
    if not root.is_dir():
        fail(f"{label} proof root must be a directory")
    unresolved = root
    for part in PurePosixPath(value).parts:
        unresolved = unresolved / part
        try:
            info = unresolved.lstat()
        except FileNotFoundError:
            fail(f"{label} does not exist: {value}")
        if _is_link_or_reparse(info):
            fail(f"{label} cannot traverse a symlink or reparse point: {value}")
    path = unresolved.absolute()
    try:
        path.relative_to(root)
    except ValueError:
        fail(f"{label} must remain below the handoff directory: {value}")
    return path


def git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def configure_git_executable(value: str | os.PathLike[str]) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        fail("Git executable must be supplied as an absolute trusted path")
    executable = validate_no_reparse_chain(candidate, "Git executable")
    try:
        info = executable.lstat()
    except OSError as error:
        fail(f"Git executable is unavailable: {error}")
    if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        fail("Git executable must be a regular non-reparse file")
    global _GIT_EXECUTABLE
    _GIT_EXECUTABLE = executable
    return executable


def start_operation_budget() -> None:
    global _OPERATION_DEADLINE, _OPERATION_GIT_CALLS
    global _OPERATION_BLOB_CACHE, _OPERATION_BLOB_BYTES
    _OPERATION_DEADLINE = time.monotonic() + MAX_OPERATION_SECONDS
    _OPERATION_GIT_CALLS = 0
    _OPERATION_BLOB_CACHE = {}
    _OPERATION_BLOB_BYTES = 0


def _consume_git_budget(label: str) -> float:
    global _OPERATION_DEADLINE, _OPERATION_GIT_CALLS
    if _OPERATION_DEADLINE is None:
        start_operation_budget()
    assert _OPERATION_DEADLINE is not None
    _OPERATION_GIT_CALLS += 1
    if _OPERATION_GIT_CALLS > MAX_GIT_CALLS_PER_OPERATION:
        fail(f"{label} exceeds the {MAX_GIT_CALLS_PER_OPERATION}-call Git operation ceiling")
    remaining = _OPERATION_DEADLINE - time.monotonic()
    if remaining <= 0:
        fail(f"{label} exceeds the {MAX_OPERATION_SECONDS}-second top-level operation ceiling")
    return remaining


def git_command(repo: Path, args: Iterable[str]) -> list[str]:
    if _GIT_EXECUTABLE is None:
        fail("Git executable is not configured; pass --git-executable with a trusted absolute path")
    safe_repo = validate_no_reparse_chain(Path(repo), "Git repository")
    return [
        str(_GIT_EXECUTABLE),
        "-C",
        str(safe_repo),
        "-c",
        f"safe.directory={safe_repo}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.commitGraph=false",
        "-c",
        "diff.ignoreSubmodules=none",
        *args,
    ]


def _assert_no_executable_git_config(repo: Path) -> None:
    returncode, stdout, stderr = _run_process_bounded(
        git_command(
            repo,
            ["config", "--includes", "--name-only", "--list"],
        ),
        label="Git executable-config inspection",
        stdout_limit=MAX_JSON_BYTES,
    )
    if returncode != 0:
        fail(f"Git executable-config inspection failed: {stderr.decode('utf-8', 'replace').strip()}")
    names = stdout.decode("utf-8", "replace").splitlines()
    forbidden = [
        name
        for name in names
        if re.fullmatch(
            r"(?:filter\..*\.(?:clean|smudge|process)|"
            r"diff\..*\.(?:command|textconv)|diff\.external|"
            r"core\.worktree|"
            r"extensions\.partialclone|remote\..*\.(?:promisor|partialclonefilter))",
            name.casefold(),
        )
    ]
    if forbidden:
        fail(
            "repository Git config contains executable filter/diff drivers or lazy-fetch settings: "
            f"{sorted(forbidden)}"
        )


def _assert_no_graph_overrides(repo: Path) -> None:
    """Reject repository-local graph replacement mechanisms that can forge ancestry."""

    common = common_git_directory(repo)
    for relative, label in ((Path("info") / "grafts", "grafts"), (Path("shallow"), "shallow history")):
        path = common / relative
        if os.path.lexists(path):
            validate_no_reparse_chain(path, f"Git {label} path")
            fail(f"repository uses unsupported {label}: {path}")
        validate_no_reparse_chain(path.parent, f"Git {label} parent")


def _run_process_bounded(
    command: list[str],
    *,
    label: str,
    stdout_limit: int,
    stdout_file: Any | None = None,
    stdin_file: Any | None = None,
) -> tuple[int, bytes, bytes]:
    operation_remaining = _consume_git_budget(label)
    timed_out = threading.Event()
    overflowed = False
    captured: list[bytes] = []
    with tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL if stdin_file is None else stdin_file,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            env=git_environment(),
        )
        assert process.stdout is not None

        def terminate_for_timeout() -> None:
            timed_out.set()
            try:
                process.kill()
            except OSError:
                pass

        process_timeout = min(GIT_TIMEOUT_SECONDS, operation_remaining)
        watchdog = threading.Timer(process_timeout, terminate_for_timeout)
        watchdog.daemon = True
        watchdog.start()
        total = 0
        try:
            while True:
                remaining = stdout_limit + 1 - total
                chunk = process.stdout.read(min(1024 * 1024, max(1, remaining)))
                if not chunk:
                    break
                total += len(chunk)
                if total > stdout_limit:
                    overflowed = True
                    try:
                        process.kill()
                    except OSError:
                        pass
                    break
                if stdout_file is None:
                    captured.append(chunk)
                else:
                    stdout_file.write(chunk)
        finally:
            process.stdout.close()
            returncode = process.wait()
            watchdog.cancel()
        stderr_file.seek(0)
        stderr = stderr_file.read(MAX_JSON_BYTES + 1)
    if timed_out.is_set():
        fail(f"{label} exceeded its {process_timeout:.3f}-second guard timeout")
    if overflowed:
        fail(f"{label} exceeds the {stdout_limit}-byte output ceiling")
    return returncode, b"".join(captured), stderr


def run_git(
    repo: Path,
    args: Iterable[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> bytes:
    if input_bytes is not None:
        fail("guard Git commands do not accept caller-supplied stdin")
    command = git_command(repo, args)
    _assert_no_executable_git_config(repo)
    _assert_no_graph_overrides(repo)
    label = f"git {' '.join(args)}"
    returncode, stdout, stderr = _run_process_bounded(
        command,
        label=label,
        stdout_limit=MAX_GIT_OUTPUT_BYTES,
    )
    if check and returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        fail(f"git {' '.join(args)} failed: {message}")
    return stdout


def validate_worktree_admin_path(worktree: Path) -> Path:
    """Resolve a worktree's .git marker without letting Git follow an unchecked pointer."""

    worktree = validate_no_reparse_chain(worktree, "worktree path")
    marker = worktree / ".git"
    if not os.path.lexists(marker):
        fail(f"worktree is missing its .git administrative marker: {worktree}")
    marker = validate_no_reparse_chain(marker, "worktree .git marker")
    info = marker.lstat()
    if stat.S_ISDIR(info.st_mode):
        return marker
    if not stat.S_ISREG(info.st_mode):
        fail("worktree .git marker must be a directory or regular pointer file")
    raw = read_regular_bytes(marker, "worktree .git marker", maximum=4096)
    try:
        text = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        fail("worktree .git pointer must be canonical UTF-8 text")
    match = re.fullmatch(r"gitdir: ([^\r\n\0]+)", text)
    if match is None:
        fail("worktree .git pointer has an unsupported shape")
    target = Path(match.group(1))
    if not target.is_absolute():
        target = marker.parent / target
    target = validate_no_reparse_chain(target.absolute(), "worktree Git directory pointer")
    if not target.is_dir():
        fail("worktree Git directory pointer must name a directory")
    return target


def common_git_directory(worktree: Path) -> Path:
    git_dir = validate_worktree_admin_path(worktree)
    marker = git_dir / "commondir"
    if not os.path.lexists(marker):
        return git_dir
    marker = validate_no_reparse_chain(marker, "Git commondir marker")
    raw = read_regular_bytes(marker, "Git commondir marker", maximum=4096)
    try:
        value = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        fail("Git commondir marker must be canonical UTF-8 text")
    if not value or "\0" in value or "\n" in value or "\r" in value:
        fail("Git commondir marker has an unsupported shape")
    path = Path(value)
    if not path.is_absolute():
        path = git_dir / path
    path = validate_no_reparse_chain(path.absolute(), "Git common directory")
    if not path.is_dir():
        fail("Git common directory must be a directory")
    return path


def repo_root(repo: Path) -> Path:
    requested = validate_no_reparse_chain(repo, "repository path")
    if not requested.is_dir():
        fail("repository path must be a directory")
    validate_worktree_admin_path(requested)
    resolved = run_git(requested, ["rev-parse", "--show-toplevel"]).decode().strip()
    root = validate_no_reparse_chain(Path(resolved), "repository root")
    if not root.is_dir():
        fail("repository root must be a directory")
    if os.path.normcase(os.path.realpath(requested)) != os.path.normcase(os.path.realpath(root)):
        fail("--repo must name the exact Git worktree root, not a redirected or nested path")
    return root


def resolve_commit(repo: Path, revision: str, label: str) -> str:
    value = run_git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"]).decode().strip()
    if not HEX_OBJECT_RE.fullmatch(value):
        fail(f"{label} did not resolve to a full Git object ID: {revision}")
    return value


def resolve_tree(repo: Path, revision: str) -> str:
    value = run_git(repo, ["rev-parse", "--verify", f"{revision}^{{tree}}"]).decode().strip()
    if not HEX_OBJECT_RE.fullmatch(value):
        fail(f"tree did not resolve to a full Git object ID: {revision}")
    return value


def resolve_blob_at(repo: Path, revision: str, repo_path: str, label: str) -> str:
    path = validate_repo_path(repo_path, f"{label} path")
    value = run_git(repo, ["rev-parse", "--verify", f"{revision}:{path}"]).decode().strip()
    if not HEX_OBJECT_RE.fullmatch(value):
        fail(f"{label} did not resolve to a full Git object ID")
    object_type = run_git(repo, ["cat-file", "-t", value]).decode().strip()
    if object_type != "blob":
        fail(f"{label} must resolve to a Git blob, not {object_type or 'an unknown object'}")
    return value


def ensure_ancestor(repo: Path, older: str, newer: str, label: str) -> None:
    _assert_no_executable_git_config(repo)
    _assert_no_graph_overrides(repo)
    returncode, _stdout, _stderr = _run_process_bounded(
        git_command(repo, ["merge-base", "--is-ancestor", older, newer]),
        label=f"{label}: Git ancestry check",
        stdout_limit=1024,
    )
    if returncode != 0:
        fail(f"{label}: {older} is not an ancestor of {newer}")


def ensure_clean(repo: Path, label: str) -> None:
    assert_index_visibility(repo)
    status = run_git(
        repo,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=dirty"],
    )
    if status:
        fail(f"{label} working tree is not clean")


def assert_index_visibility(repo: Path) -> None:
    """Reject index flags that intentionally hide tracked working-tree changes."""

    output = run_git(repo, ["ls-files", "-v", "-z"])
    for record in output.split(b"\0"):
        if not record:
            continue
        tag = chr(record[0])
        if tag == "S" or tag.islower():
            path = record[2:].decode("utf-8", "surrogateescape") if len(record) > 2 else ""
            fail(
                "repository index hides tracked changes with skip-worktree or "
                f"assume-unchanged: {path}"
            )


def skill_root() -> Path:
    # Preserve the path by which this verifier was invoked.  resolve() would erase a
    # symlink/junction in the Skill root before method_digest_at() can reject it.
    return Path(__file__).absolute().parents[1]


def method_configuration(root: Path | None = None) -> dict[str, Any]:
    bundle_root = root or skill_root()
    return require_mapping(load_json_file(bundle_root / "method.json", "method.json"), "method.json")


def method_digest_at(root: Path) -> dict[str, Any]:
    root = validate_no_reparse_chain(root, "method bundle root")
    if not root.is_dir():
        fail("method bundle root must be a directory")
    method = method_configuration(root)
    require_exact_keys(
        method,
        {
            "schemaVersion",
            "methodId",
            "methodVersion",
            "transportProfile",
            "digestAlgorithm",
            "canonicalFiles",
        },
        "method.json",
    )
    if require_integer(method.get("schemaVersion"), "method.json schemaVersion") != SCHEMA_VERSION:
        fail("method.json schemaVersion is unsupported")
    if method.get("methodId") != METHOD_ID:
        fail("method.json methodId does not match this tool")
    version = require_string(method.get("methodVersion"), "methodVersion")
    if version != METHOD_VERSION:
        fail(f"method.json methodVersion must be {METHOD_VERSION}")
    if method.get("transportProfile") != "linear-replay-v2":
        fail("method.json transportProfile is unsupported")
    algorithm = require_string(method.get("digestAlgorithm"), "digestAlgorithm")
    if algorithm != "sha256-path-nul-bytes-nul-v1":
        fail(f"unsupported digest algorithm: {algorithm}")
    configured = require_list(method.get("canonicalFiles"), "canonicalFiles", nonempty=True)
    relative_paths = ["method.json", *[require_string(item, "canonicalFiles entry") for item in configured]]
    if len(relative_paths) > MAX_METHOD_ENTRIES:
        fail(f"method bundle cannot declare more than {MAX_METHOD_ENTRIES} canonical files")
    if len({item.casefold() for item in relative_paths}) != len(relative_paths):
        fail("canonicalFiles contains a duplicate path")
    expected_files = set(relative_paths)
    entry_count = 0
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        validate_no_reparse_chain(directory, "method bundle directory")
        try:
            with os.scandir(directory) as iterator:
                entries = []
                for entry in iterator:
                    entry_count += 1
                    if entry_count > MAX_METHOD_ENTRIES:
                        fail(
                            f"method bundle cannot contain more than {MAX_METHOD_ENTRIES} entries"
                        )
                    entries.append(entry)
        except OSError as error:
            fail(f"method bundle cannot be enumerated safely: {error}")
        for entry in sorted(entries, key=lambda item: item.name.casefold(), reverse=True):
            candidate = Path(entry.path)
            relative = candidate.relative_to(root).as_posix()
            candidate_depth = depth + 1
            if candidate_depth > MAX_METHOD_PATH_DEPTH:
                fail(f"method bundle path exceeds depth {MAX_METHOD_PATH_DEPTH}: {relative}")
            try:
                info = candidate.lstat()
            except OSError as error:
                fail(f"method bundle entry changed during inspection ({relative}): {error}")
            if _is_link_or_reparse(info):
                fail(
                    "method bundle contains an unexpected symlink or reparse point: "
                    f"{relative}"
                )
            if stat.S_ISDIR(info.st_mode):
                pending.append((candidate, candidate_depth))
                continue
            if not stat.S_ISREG(info.st_mode):
                fail(f"method bundle contains a non-regular entry: {relative}")
            if relative not in expected_files:
                fail(f"method bundle contains an unpinned file: {relative}")
    digest = hashlib.sha256()
    files: list[dict[str, Any]] = []
    for relative in sorted(relative_paths, key=str.casefold):
        validate_repo_path(relative, "canonical method path")
        path = root / PurePosixPath(relative)
        try:
            info = path.lstat()
        except FileNotFoundError:
            fail(f"canonical method file is missing: {relative}")
        if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
            fail(f"canonical method file must be regular and non-symlink: {relative}")
        data = read_regular_bytes(path, f"canonical method file {relative}")
        encoded = relative.encode("utf-8")
        digest.update(encoded)
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        files.append({"path": relative, "sha256": sha256_bytes(data)})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "methodId": METHOD_ID,
        "methodVersion": version,
        "digestAlgorithm": algorithm,
        "canonicalDigest": f"sha256:{digest.hexdigest()}",
        "files": files,
    }


def method_digest() -> dict[str, Any]:
    return method_digest_at(skill_root())


def verify_recovery_bundle(repo: Path, lock: dict[str, Any], measured: dict[str, Any]) -> None:
    source = lock.get("recoverySource")
    digest = lock.get("recoveryDigest")
    if source is None and digest is None:
        return
    if source is None or digest is None:
        fail("method recoverySource and recoveryDigest must both be null or both be present")
    source_path = validate_repo_path(require_string(source, "method recoverySource"), "method recoverySource")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", require_string(digest, "method recoveryDigest")):
        fail("method recoveryDigest must be a canonical sha256 digest")
    root = repo_root(repo)
    bundle_root = root / PurePosixPath(source_path)
    recovered = method_digest_at(bundle_root)
    if digest != measured["canonicalDigest"] or recovered["canonicalDigest"] != measured["canonicalDigest"]:
        fail("vendored recovery bundle does not byte-match the active method bundle")


def concrete_authority(value: Any, label: str) -> str:
    authority = require_string(value, label)
    folded = authority.casefold()
    if re.fullmatch(
        r"(?:n/?a|na|none|unknown|tbd|todo|replace(?:-me)?|placeholder|null|unchanged|same[-_ ]as[-_ ]before)",
        folded,
    ) or re.search(r"<[^>]+>|\breplace\b|\bplaceholder\b|\btbd\b|\btodo\b", authority, re.IGNORECASE):
        fail(f"{label} must name a concrete authority, not a placeholder")
    if not any(character.isalnum() for character in authority):
        fail(f"{label} must contain at least one Unicode alphanumeric character")
    return authority


def validate_method_provenance(lock: dict[str, Any], label: str) -> None:
    status = require_string(lock.get("provenanceStatus"), f"{label}.provenanceStatus")
    revision = lock.get("sourceRevision")
    authority = lock.get("provenanceAuthority")
    if status == "UNVERIFIED_LOCAL":
        if revision is not None or authority is not None:
            fail(
                f"{label} UNVERIFIED_LOCAL provenance requires "
                "sourceRevision=null and provenanceAuthority=null"
            )
        return
    if status == "VERIFIED":
        revision = require_string(revision, f"{label}.sourceRevision")
        if not HEX_OBJECT_RE.fullmatch(revision):
            fail(f"{label}.sourceRevision must be a full lowercase Git object ID")
        concrete_authority(authority, f"{label}.provenanceAuthority")
        return
    fail(f"{label}.provenanceStatus must be VERIFIED or UNVERIFIED_LOCAL")


def compare_method_lock(
    lock: dict[str, Any], measured: dict[str, Any], *, repo: Path | None = None
) -> None:
    require_exact_keys(lock, METHOD_LOCK_FIELDS, "method lock")
    for field in (
        "schemaVersion",
        "methodId",
        "methodVersion",
        "digestAlgorithm",
        "canonicalDigest",
    ):
        if lock.get(field) != measured.get(field):
            fail(
                f"method lock mismatch for {field}: expected {lock.get(field)!r}, "
                f"measured {measured.get(field)!r}"
            )
    validate_method_provenance(lock, "method lock")
    recovery_source = lock.get("recoverySource")
    recovery_digest = lock.get("recoveryDigest")
    if (recovery_source is None) != (recovery_digest is None):
        fail("method recoverySource and recoveryDigest must both be null or both be present")
    if recovery_source is not None:
        validate_repo_path(require_string(recovery_source, "method recoverySource"), "method recoverySource")
        if recovery_digest != measured["canonicalDigest"]:
            fail("method recoveryDigest must equal the active canonicalDigest")
        if repo is not None:
            verify_recovery_bundle(repo, lock, measured)


def validate_repo_path(value: str, label: str) -> str:
    require_string(value, label)
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        fail(f"{label} must be repository-relative: {value}")
    if any(character in value for character in FORBIDDEN_PATH_CHARS):
        fail(f"{label} cannot contain glob or backslash characters: {value}")
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        fail(f"{label} must use portable ASCII characters only in v2: {value!r}")
    if ":" in value or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        fail(f"{label} contains a non-portable colon, control character, or surrogate: {value}")
    if unicodedata.normalize("NFC", value) != value:
        fail(f"{label} must use canonical Unicode NFC spelling: {value}")
    pure = PurePosixPath(value)
    if value == "." or not pure.parts:
        fail(f"{label} must identify a repository entry, not the repository root")
    if value != pure.as_posix() or value.endswith("/"):
        fail(f"{label} must use canonical '/' spelling: {value}")
    if any(part in ("", ".", "..") for part in pure.parts):
        fail(f"{label} contains a traversal or empty segment: {value}")
    for part in pure.parts:
        if part.endswith((".", " ")):
            fail(f"{label} contains a Windows-aliased trailing dot/space: {value}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            fail(f"{label} contains a reserved Windows device name: {value}")
    return value


def path_is_ancestor(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left.casefold()).parts
    right_parts = PurePosixPath(right.casefold()).parts
    return len(left_parts) < len(right_parts) and right_parts[: len(left_parts)] == left_parts


def string_list(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    return [require_string(item, f"{label} entry") for item in require_list(value, label, nonempty=nonempty)]


def unique_string_list(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    items = string_list(value, label, nonempty=nonempty)
    if len(set(items)) != len(items):
        fail(f"{label} contains duplicate entries")
    return items


def authority_identity(value: str) -> str:
    """Normalize an actor identity so punctuation cannot disguise a writer as a reviewer."""

    identity = "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )
    if not identity:
        fail("actor identity must contain at least one Unicode alphanumeric character")
    return identity


def charter_digest(charter: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(charter))


def replacement_identity(charter: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable part of a linked replacement charter."""

    identity = {
        key: value
        for key, value in charter.items()
        if key not in {"previousCharter", "baselineCommit", "baselineTree", "workspaceAdmission"}
    }
    owner = identity.get("ownerIntegration")
    baseline = charter.get("baselineCommit")
    if isinstance(owner, dict) and isinstance(owner.get("requiredLocalChecks"), list):
        expected = f"git diff --check {baseline}...HEAD"
        owner_copy = dict(owner)
        owner_copy["requiredLocalChecks"] = [
            {
                **check,
                "command": "git diff --check <charter-baseline>...HEAD",
            }
            if isinstance(check, dict) and check.get("command") == expected
            else check
            for check in owner["requiredLocalChecks"]
        ]
        identity["ownerIntegration"] = owner_copy
    return identity


def workspace_admission_identity(charter: dict[str, Any]) -> dict[str, Any]:
    admission = require_mapping(charter.get("workspaceAdmission"), "workspaceAdmission")
    return {
        "mainRef": admission.get("mainRef"),
        "instructionPath": admission.get("instructionPath"),
        "workspaces": [
            {
                "workspaceId": item.get("workspaceId"),
                "actor": item.get("actor"),
                "worktreeGitDir": item.get("worktreeGitDir"),
                "physicalIdentityDigest": item.get("physicalIdentityDigest"),
            }
            for item in require_list(admission.get("workspaces"), "workspaceAdmission.workspaces")
        ],
    }


def validate_replacement_charter(
    repo: Path,
    previous_charter: dict[str, Any],
    replacement_charter: dict[str, Any],
) -> None:
    if replacement_identity(replacement_charter) != replacement_identity(previous_charter):
        fail(
            "replacement charter changes scope, roles, decisions, paths, evidence, or method; "
            "only baselineCommit, baselineTree, previousCharter, and admission measurements may change"
        )
    if workspace_admission_identity(replacement_charter) != workspace_admission_identity(previous_charter):
        fail("replacement charter changes workspace IDs, actors, Git identities, main ref, or instruction path")
    previous_baseline = resolve_commit(
        repo,
        require_string(previous_charter.get("baselineCommit"), "previous baselineCommit"),
        "previous baselineCommit",
    )
    replacement_baseline = resolve_commit(
        repo,
        require_string(replacement_charter.get("baselineCommit"), "replacement baselineCommit"),
        "replacement baselineCommit",
    )
    if previous_baseline == replacement_baseline:
        fail("replacement charter baselineCommit must advance beyond its predecessor")
    ensure_ancestor(
        repo,
        previous_baseline,
        replacement_baseline,
        "replacement charter baseline ancestry",
    )
    if previous_charter.get("baselineTree") != resolve_tree(repo, previous_baseline):
        fail("previous charter baselineTree does not match its baselineCommit")
    if replacement_charter.get("baselineTree") != resolve_tree(repo, replacement_baseline):
        fail("replacement charter baselineTree does not match its baselineCommit")


def validate_workspace_admission_shape(
    charter: dict[str, Any], cells: list[dict[str, Any]], baseline: str, mode: str
) -> dict[str, Any]:
    admission = require_mapping(charter.get("workspaceAdmission"), "workspaceAdmission")
    require_exact_keys(
        admission,
        {"mainRef", "instructionPath", "instructionBlob", "workspaces"},
        "workspaceAdmission",
    )
    require_string(admission.get("mainRef"), "workspaceAdmission.mainRef")
    validate_repo_path(
        require_string(admission.get("instructionPath"), "workspaceAdmission.instructionPath"),
        "workspaceAdmission.instructionPath",
    )
    instruction_blob = require_string(
        admission.get("instructionBlob"), "workspaceAdmission.instructionBlob"
    )
    if not HEX_OBJECT_RE.fullmatch(instruction_blob):
        fail("workspaceAdmission.instructionBlob must be a full Git object ID")
    rows = require_list(admission.get("workspaces"), "workspaceAdmission.workspaces", nonempty=True)
    if len(rows) > MAX_WORKTREES:
        fail(f"workspaceAdmission.workspaces cannot exceed {MAX_WORKTREES} entries")
    expected: dict[str, tuple[str, str]] = {}
    actor_workspaces: dict[str, str] = {}
    for cell in cells:
        workspace_id = cell["workspaceId"]
        actor = cell["actor"]
        folded_workspace = workspace_id.casefold()
        prior = expected.get(folded_workspace)
        if prior is not None and prior[1] != actor:
            fail(f"charter assigns multiple actors to workspaceId: {workspace_id}")
        folded_actor = authority_identity(actor)
        prior_workspace = actor_workspaces.get(folded_actor)
        if prior_workspace is not None and prior_workspace != folded_workspace:
            fail(f"charter assigns actor {actor} to multiple workspaceId values")
        expected[folded_workspace] = (workspace_id, actor)
        actor_workspaces[folded_actor] = folded_workspace
    owner = concrete_authority(charter.get("waveOwner"), "waveOwner")
    owner_identity = authority_identity(owner)
    owner_is_cell_actor = owner_identity in actor_workspaces
    owner_workspace_id: str | None = None
    measured_ids: set[str] = set()
    git_dirs: set[str] = set()
    for index, raw in enumerate(rows):
        row = require_mapping(raw, f"workspaceAdmission.workspaces[{index}]")
        require_exact_keys(
            row,
            {
                "workspaceId",
                "actor",
                "worktreeGitDir",
                "physicalIdentityDigest",
                "headRevision",
                "ahead",
                "behind",
                "clean",
            },
            f"workspaceAdmission.workspaces[{index}]",
        )
        workspace_id = require_string(row.get("workspaceId"), f"workspaceAdmission.workspaces[{index}].workspaceId")
        folded = workspace_id.casefold()
        if folded in measured_ids:
            fail(f"workspaceAdmission contains duplicate workspaceId: {workspace_id}")
        measured_ids.add(folded)
        actor = require_string(
            row.get("actor"), f"workspaceAdmission.workspaces[{index}].actor"
        )
        expected_pair = expected.get(folded)
        if expected_pair is None:
            if (
                mode != "multi-writer"
                or owner_is_cell_actor
                or authority_identity(actor) != owner_identity
                or owner_workspace_id is not None
            ):
                fail(f"workspaceAdmission contains an unassigned workspace: {workspace_id}")
            owner_workspace_id = folded
        elif actor != expected_pair[1]:
            fail(f"workspaceAdmission does not bind the charter actor for {workspace_id}")
        git_dir = validate_repo_path(
            require_string(row.get("worktreeGitDir"), f"workspaceAdmission.workspaces[{index}].worktreeGitDir"),
            f"workspaceAdmission.workspaces[{index}].worktreeGitDir",
        )
        physical_digest = require_string(
            row.get("physicalIdentityDigest"),
            f"workspaceAdmission.workspaces[{index}].physicalIdentityDigest",
        )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", physical_digest):
            fail(
                f"workspaceAdmission.workspaces[{index}].physicalIdentityDigest "
                "must be a canonical sha256 digest"
            )
        folded_git_dir = git_dir.casefold()
        if folded_git_dir in git_dirs:
            fail("workspaceAdmission maps multiple workspace IDs to one Git worktree identity")
        git_dirs.add(folded_git_dir)
        if row.get("headRevision") != baseline:
            fail(f"workspaceAdmission {workspace_id} headRevision must equal baselineCommit")
        if require_integer(row.get("ahead"), f"workspaceAdmission {workspace_id}.ahead", minimum=0) != 0:
            fail(f"workspaceAdmission {workspace_id} must be zero commits ahead")
        if require_integer(row.get("behind"), f"workspaceAdmission {workspace_id}.behind", minimum=0) != 0:
            fail(f"workspaceAdmission {workspace_id} must be zero commits behind")
        if type(row.get("clean")) is not bool or row.get("clean") is not True:
            fail(f"workspaceAdmission {workspace_id}.clean must be the boolean true")
    expected_ids = set(expected)
    if mode == "multi-writer" and not owner_is_cell_actor:
        if owner_workspace_id is None:
            fail(
                "multi-writer workspaceAdmission requires exactly one admitted waveOwner "
                "workspace when the owner is not a cell actor"
            )
        expected_ids.add(owner_workspace_id)
    if measured_ids != expected_ids:
        fail("workspaceAdmission must cover charter cell and required owner workspaces exactly")
    return admission


def validate_owner_integration(charter: dict[str, Any], mode: str) -> dict[str, Any] | None:
    raw = charter.get("ownerIntegration")
    if mode == "evidence-fanout":
        if raw is not None:
            fail("evidence-fanout charter must record ownerIntegration=null")
        return None
    owner = require_mapping(raw, "ownerIntegration")
    require_exact_keys(owner, {"requiredLocalChecks", "independentReview"}, "ownerIntegration")
    checks = bounded_list(
        owner.get("requiredLocalChecks"),
        "ownerIntegration.requiredLocalChecks",
        limit=MAX_OWNER_LOCAL_CHECKS,
        nonempty=True,
    )
    check_ids: set[str] = set()
    for index, raw_check in enumerate(checks):
        check = require_mapping(raw_check, f"ownerIntegration.requiredLocalChecks[{index}]")
        require_exact_keys(check, {"checkId", "command"}, f"ownerIntegration.requiredLocalChecks[{index}]")
        check_id = require_string(check.get("checkId"), f"ownerIntegration.requiredLocalChecks[{index}].checkId")
        command = require_string(
            check.get("command"), f"ownerIntegration.requiredLocalChecks[{index}].command"
        )
        if command == "git diff --check <charter-baseline>...HEAD":
            fail(
                "ownerIntegration requiredLocalChecks reserves "
                "<charter-baseline> for replacement comparison"
            )
        if check_id in check_ids:
            fail("ownerIntegration.requiredLocalChecks contains duplicate checkId")
        check_ids.add(check_id)
    review = require_mapping(owner.get("independentReview"), "ownerIntegration.independentReview")
    require_exact_keys(
        review,
        {"requirementId", "requiredAttestationSource", "requiredCheckIds"},
        "ownerIntegration.independentReview",
    )
    require_string(review.get("requirementId"), "ownerIntegration.independentReview.requirementId")
    concrete_authority(
        review.get("requiredAttestationSource"),
        "ownerIntegration.independentReview.requiredAttestationSource",
    )
    review_checks = unique_string_list(
        review.get("requiredCheckIds"), "ownerIntegration.independentReview.requiredCheckIds"
    )
    if len(review_checks) > MAX_CHECK_IDS:
        fail(
            "ownerIntegration.independentReview.requiredCheckIds cannot exceed "
            f"{MAX_CHECK_IDS} entries"
        )
    return owner


def validate_charter_data(
    repo: Path,
    charter: dict[str, Any],
    *,
    clean: bool = True,
    charter_path: Path | None = None,
    remeasure_admission: bool = False,
    _seen_charters: set[Path] | None = None,
) -> dict[str, Any]:
    reject_unresolved_template_tokens(charter, "charter")
    require_exact_keys(
        charter,
        {
            "schemaVersion",
            "waveId",
            "mode",
            "method",
            "previousCharter",
            "baselineCommit",
            "baselineTree",
            "programmeConductor",
            "waveOwner",
            "workspaceAdmission",
            "objective",
            "inScope",
            "outOfScope",
            "failureDomain",
            "cells",
            "ownerOnlyPaths",
            "authorityCeilings",
            "transportLifecycle",
            "sideEffectClass",
            "rollback",
            "ownerIntegration",
            "externalEvidence",
            "stopConditions",
            "acceptance",
        },
        "charter",
    )
    if require_integer(charter.get("schemaVersion"), "charter.schemaVersion") != SCHEMA_VERSION:
        fail("charter schemaVersion is unsupported")
    require_string(charter.get("waveId"), "waveId")
    mode = charter.get("mode")
    if mode not in ("multi-writer", "evidence-fanout"):
        fail("mode must be 'multi-writer' or 'evidence-fanout'")
    lock = require_mapping(charter.get("method"), "method")
    require_exact_keys(lock, METHOD_LOCK_FIELDS, "charter.method")
    compare_method_lock(lock, method_digest(), repo=repo)
    previous = charter.get("previousCharter")
    if previous is not None:
        previous = require_mapping(previous, "previousCharter")
        require_exact_keys(previous, {"path", "digest"}, "previousCharter")
        validate_repo_path(require_string(previous.get("path"), "previousCharter.path"), "previousCharter.path")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", require_string(previous.get("digest"), "previousCharter.digest")):
            fail("previousCharter.digest must be a canonical sha256 digest")

    baseline = resolve_commit(repo, require_string(charter.get("baselineCommit"), "baselineCommit"), "baselineCommit")
    if charter["baselineCommit"] != baseline:
        fail("baselineCommit must be a full canonical commit ID")
    tree = resolve_tree(repo, baseline)
    if charter.get("baselineTree") != tree:
        fail(f"baselineTree mismatch: expected {tree}")

    if previous is not None and charter_path is not None:
        current_path = validate_no_reparse_chain(charter_path, "charter")
        seen = set() if _seen_charters is None else set(_seen_charters)
        if current_path in seen:
            fail("replacement charter chain contains a cycle")
        seen.add(current_path)
        if len(seen) > MAX_HANDOFFS:
            fail(f"replacement charter chain cannot exceed {MAX_HANDOFFS} generations")
        previous_path = resolve_regular_json(
            current_path.parent, previous["path"], "previousCharter.path"
        )
        if previous_path in seen:
            fail("replacement charter chain contains a cycle")
        previous_charter = require_mapping(load_json_file(previous_path, "previous charter"), "previous charter")
        if charter_digest(previous_charter) != previous["digest"]:
            fail("previousCharter.digest does not match the predecessor file")
        validate_charter_data(
            repo,
            previous_charter,
            clean=False,
            charter_path=previous_path,
            remeasure_admission=False,
            _seen_charters=seen,
        )
        if previous_charter.get("waveId") != charter.get("waveId"):
            fail("replacement charter changes waveId")
        validate_replacement_charter(repo, previous_charter, charter)

    authority_identity(concrete_authority(charter.get("programmeConductor"), "programmeConductor"))
    authority_identity(concrete_authority(charter.get("waveOwner"), "waveOwner"))
    for field in ("objective", "failureDomain", "transportLifecycle", "sideEffectClass", "rollback"):
        require_string(charter.get(field), field)
    for field in ("inScope", "outOfScope", "authorityCeilings", "stopConditions", "acceptance"):
        unique_string_list(charter.get(field), field)
    owner_integration = validate_owner_integration(charter, mode)
    evidence_requirements = bounded_list(
        charter.get("externalEvidence"),
        "externalEvidence",
        limit=MAX_EVIDENCE_REQUIREMENTS,
        nonempty=mode == "multi-writer",
    )
    if mode == "evidence-fanout" and evidence_requirements:
        fail("evidence-fanout derives evidence requirements from its cells")
    evidence_ids: set[str] = set()
    for index, raw_requirement in enumerate(evidence_requirements):
        requirement = require_mapping(raw_requirement, f"externalEvidence[{index}]")
        require_exact_keys(
            requirement,
            {"requirementId", "stage", "subjectRelation", "requiredAttestationSource", "requiredCheckIds", "requiredArtifacts"},
            f"externalEvidence[{index}]",
        )
        requirement_id = require_string(
            requirement.get("requirementId"), f"externalEvidence[{index}].requirementId"
        )
        if requirement_id in evidence_ids:
            fail(f"duplicate external evidence requirementId: {requirement_id}")
        evidence_ids.add(requirement_id)
        concrete_authority(
            requirement.get("requiredAttestationSource"),
            f"externalEvidence[{index}].requiredAttestationSource",
        )
        stage = requirement.get("stage")
        relation = requirement.get("subjectRelation")
        if stage == "pr" and relation not in ("head-exact", "synthetic-two-parent"):
            fail(f"externalEvidence[{index}] PR relation is unsupported")
        if stage == "post-merge" and relation != "merge-exact":
            fail(f"externalEvidence[{index}] post-merge relation must be merge-exact")
        if stage not in ("pr", "post-merge"):
            fail(f"externalEvidence[{index}] stage must be pr or post-merge")
        check_ids = unique_string_list(
            requirement.get("requiredCheckIds"),
            f"externalEvidence[{index}].requiredCheckIds",
            nonempty=False,
        )
        if len(check_ids) > MAX_CHECK_IDS:
            fail(f"externalEvidence[{index}].requiredCheckIds cannot exceed {MAX_CHECK_IDS} entries")
        artifact_requirements = bounded_list(
            requirement.get("requiredArtifacts"),
            f"externalEvidence[{index}].requiredArtifacts",
            limit=MAX_ARTIFACTS,
        )
        if not check_ids and not artifact_requirements:
            fail(f"externalEvidence[{index}] must require at least one check or artifact")
        artifact_ids: set[str] = set()
        for artifact_index, raw_artifact in enumerate(artifact_requirements):
            artifact = require_mapping(
                raw_artifact,
                f"externalEvidence[{index}].requiredArtifacts[{artifact_index}]",
            )
            require_exact_keys(
                artifact,
                {"artifactId", "requiredStatusIds"},
                f"externalEvidence[{index}].requiredArtifacts[{artifact_index}]",
            )
            artifact_id = require_string(
                artifact.get("artifactId"),
                f"externalEvidence[{index}].requiredArtifacts[{artifact_index}].artifactId",
            )
            if artifact_id in artifact_ids:
                fail(f"externalEvidence[{index}] contains duplicate required artifactId")
            artifact_ids.add(artifact_id)
            required_status_ids = unique_string_list(
                artifact.get("requiredStatusIds"),
                f"externalEvidence[{index}].requiredArtifacts[{artifact_index}].requiredStatusIds",
            )
            if len(required_status_ids) > MAX_ARTIFACT_STATUS_IDS:
                fail(
                    f"externalEvidence[{index}].requiredArtifacts[{artifact_index}]"
                    f".requiredStatusIds cannot exceed {MAX_ARTIFACT_STATUS_IDS} entries"
                )
    if owner_integration is not None:
        review_id = owner_integration["independentReview"]["requirementId"]
        if review_id in evidence_ids:
            fail("owner independent-review requirementId duplicates external evidence requirementId")

    cells = require_list(charter.get("cells"), "cells", nonempty=True)
    if len(cells) < 2:
        fail(f"{mode} mode requires at least two cells")
    if len(cells) > MAX_CHARTER_CELLS:
        fail(f"{mode} mode cannot exceed {MAX_CHARTER_CELLS} cells")
    seen_cell_ids: set[str] = set()
    workspaces: set[str] = set()
    contributor_paths: list[tuple[str, str]] = []
    for index, raw_cell in enumerate(cells):
        cell = require_mapping(raw_cell, f"cells[{index}]")
        require_exact_keys(
            cell,
            {
                "cellId",
                "workspaceId",
                "actor",
                "dependsOn",
                "writablePaths",
                "semanticSeams",
                "focusedChecks",
                "nextWork",
                "requiredAttestationSource",
            },
            f"cells[{index}]",
        )
        cell_id = require_string(cell.get("cellId"), f"cells[{index}].cellId")
        if cell_id in seen_cell_ids:
            fail(f"duplicate cellId: {cell_id}")
        seen_cell_ids.add(cell_id)
        workspace = require_string(cell.get("workspaceId"), f"cells[{index}].workspaceId")
        workspaces.add(workspace.casefold())
        authority_identity(concrete_authority(cell.get("actor"), f"cells[{index}].actor"))
        unique_string_list(cell.get("dependsOn"), f"cells[{index}].dependsOn", nonempty=False)
        paths = string_list(
            cell.get("writablePaths"),
            f"cells[{index}].writablePaths",
            nonempty=mode == "multi-writer",
        )
        if mode == "evidence-fanout" and paths:
            fail("evidence-fanout cells must not declare writablePaths")
        for path in paths:
            contributor_paths.append((validate_repo_path(path, f"cell {cell_id} path"), cell_id))
        unique_string_list(cell.get("semanticSeams"), f"cells[{index}].semanticSeams")
        focused_checks = unique_string_list(
            cell.get("focusedChecks"), f"cells[{index}].focusedChecks"
        )
        if len(focused_checks) > MAX_CHECK_IDS:
            fail(f"cells[{index}].focusedChecks cannot exceed {MAX_CHECK_IDS} entries")
        unique_string_list(cell.get("nextWork"), f"cells[{index}].nextWork")
        if mode == "evidence-fanout":
            concrete_authority(
                cell.get("requiredAttestationSource"),
                f"cells[{index}].requiredAttestationSource",
            )
        elif cell.get("requiredAttestationSource") is not None:
            fail("multi-writer cells must record requiredAttestationSource=null")
    if len(workspaces) < 2:
        fail(f"{mode} mode requires at least two isolated workspaceId values")
    admission = validate_workspace_admission_shape(charter, cells, baseline, mode)
    expected_instruction_blob = resolve_blob_at(
        repo,
        baseline,
        admission["instructionPath"],
        "workspaceAdmission instruction",
    )
    if admission["instructionBlob"] != expected_instruction_blob:
        fail("workspaceAdmission instructionBlob does not match baselineCommit")
    if remeasure_admission:
        remeasure_workspace_admission(repo, charter, admission)
    known_ids = seen_cell_ids
    for index, raw_cell in enumerate(cells):
        for dependency in raw_cell.get("dependsOn", []):
            if dependency not in known_ids:
                fail(f"cells[{index}] depends on unknown cellId: {dependency}")
            dependency_index = next(
                position
                for position, candidate in enumerate(cells)
                if candidate["cellId"] == dependency
            )
            if dependency_index >= index:
                fail(
                    f"cells[{index}] dependency {dependency} must precede it in baton order"
                )

    owner_paths = [
        validate_repo_path(path, "ownerOnlyPaths entry")
        for path in string_list(
            charter.get("ownerOnlyPaths"),
            "ownerOnlyPaths",
            nonempty=mode == "multi-writer",
        )
    ]
    if mode == "evidence-fanout" and owner_paths:
        fail("evidence-fanout must not declare ownerOnlyPaths")
    all_paths: list[tuple[str, str]] = [*contributor_paths, *((path, "wave-owner") for path in owner_paths)]
    if len(all_paths) > MAX_OWNED_PATHS:
        fail(f"charter cannot declare more than {MAX_OWNED_PATHS} owned paths")
    by_folded: dict[str, tuple[str, str]] = {}
    for path, owner in all_paths:
        folded = path.casefold()
        previous = by_folded.get(folded)
        if previous:
            fail(f"writable path overlap: {previous[0]} ({previous[1]}) and {path} ({owner})")
        for previous_path, previous_owner in by_folded.values():
            if path_is_ancestor(previous_path, path) or path_is_ancestor(path, previous_path):
                fail(
                    f"writable path ancestor overlap: {previous_path} ({previous_owner}) "
                    f"and {path} ({owner})"
                )
        by_folded[folded] = (path, owner)
    if clean:
        ensure_clean(repo, "charter validation")
    return {
        "ok": True,
        "waveId": charter["waveId"],
        "mode": mode,
        "charterDigest": charter_digest(charter),
        "baselineCommit": baseline,
        "baselineTree": tree,
        "cellCount": len(cells),
        "writablePathCount": len(all_paths),
    }


def stable_patch_id_for_range(repo: Path, parent: str, tip: str) -> str | None:
    _assert_no_executable_git_config(repo)
    _assert_no_graph_overrides(repo)
    with tempfile.TemporaryFile() as diff_file:
        returncode, _stdout, stderr = _run_process_bounded(
            git_command(
                repo,
                [
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--ignore-submodules=none",
                    parent,
                    tip,
                    "--",
                ],
            ),
            label="git diff for stable patch ID",
            stdout_limit=MAX_SNAPSHOT_DIFF_BYTES,
            stdout_file=diff_file,
        )
        if returncode != 0:
            fail(f"git diff failed: {stderr.decode('utf-8', 'replace').strip()}")
        size = diff_file.tell()
        if size == 0:
            return None
        diff_file.seek(0)
        returncode, stdout, stderr = _run_process_bounded(
            git_command(repo, ["patch-id", "--stable"]),
            label="git patch-id --stable",
            stdout_limit=MAX_JSON_BYTES,
            stdin_file=diff_file,
        )
    if returncode != 0:
        fail(f"git patch-id --stable failed: {stderr.decode('utf-8', 'replace').strip()}")
    lines = stdout.decode("ascii", "strict").strip().splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        fail("patch-id produced more than one aggregate result")
    return lines[0].split()[0]


def blob_sha256(
    repo: Path,
    object_id: str,
    *,
    cache: dict[str, str] | None = None,
    budget: dict[str, int] | None = None,
) -> str | None:
    global _OPERATION_BLOB_BYTES
    if set(object_id) == {"0"}:
        return None
    if object_id in _OPERATION_BLOB_CACHE:
        digest = _OPERATION_BLOB_CACHE[object_id]
        if cache is not None:
            cache[object_id] = digest
        return digest
    if cache is not None and object_id in cache:
        return cache[object_id]
    try:
        size = int(run_git(repo, ["cat-file", "-s", object_id]).decode().strip())
    except ValueError:
        fail(f"Git returned a non-integer blob size for {object_id}")
    if size > MAX_SNAPSHOT_BLOB_BYTES:
        fail(f"blob {object_id} exceeds the {MAX_SNAPSHOT_BLOB_BYTES}-byte snapshot ceiling")
    next_operation_total = _OPERATION_BLOB_BYTES + size
    if next_operation_total > MAX_SNAPSHOT_TOTAL_BLOB_BYTES:
        fail(
            "top-level proof unique blobs exceed the "
            f"{MAX_SNAPSHOT_TOTAL_BLOB_BYTES}-byte aggregate ceiling"
        )
    _OPERATION_BLOB_BYTES = next_operation_total
    if budget is not None:
        budget["bytes"] = budget.get("bytes", 0) + size
    digest = sha256_bytes(run_git(repo, ["cat-file", "blob", object_id]))
    _OPERATION_BLOB_CACHE[object_id] = digest
    if cache is not None:
        cache[object_id] = digest
    return digest


def entry_sha256(
    repo: Path,
    object_id: str,
    mode: str,
    *,
    cache: dict[str, str] | None = None,
    budget: dict[str, int] | None = None,
) -> str | None:
    """Hash ordinary file/symlink blobs; a gitlink names a commit, not a blob."""

    if mode == "160000":
        return None
    return blob_sha256(repo, object_id, cache=cache, budget=budget)


def path_manifest(
    repo: Path,
    parent: str,
    tip: str,
    *,
    blob_cache: dict[str, str] | None = None,
    blob_budget: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    raw = run_git(
        repo,
        [
            "diff",
            "--raw",
            "-z",
            "--full-index",
            "--no-abbrev",
            "--find-renames=50%",
            "--no-ext-diff",
            "--no-textconv",
            "--ignore-submodules=none",
            parent,
            tip,
            "--",
        ],
    )
    if not raw:
        return []
    parts = raw.split(b"\0")
    if parts[-1] != b"":
        fail("git raw diff was not NUL terminated")
    parts.pop()
    if len(parts) > MAX_SNAPSHOT_PATH_ENTRIES * 3:
        fail(f"snapshot path manifest cannot exceed {MAX_SNAPSHOT_PATH_ENTRIES} entries")
    index = 0
    entries: list[dict[str, Any]] = []
    while index < len(parts):
        header = parts[index]
        index += 1
        match = RAW_HEADER_RE.fullmatch(header)
        if not match:
            fail(f"unrecognized git raw diff header: {header!r}")
        old_mode, new_mode, old_oid, new_oid, status_bytes = match.groups()
        status_value = status_bytes.decode("ascii")
        if index >= len(parts):
            fail("git raw diff omitted a path")
        first_path = parts[index].decode("utf-8", "surrogateescape")
        index += 1
        old_path: str | None = None
        path = first_path
        if status_value.startswith(("R", "C")):
            if index >= len(parts):
                fail("git raw rename/copy diff omitted its destination")
            old_path = first_path
            path = parts[index].decode("utf-8", "surrogateescape")
            index += 1
        validate_repo_path(path, "changed path")
        if old_path is not None:
            validate_repo_path(old_path, "changed oldPath")
        old_object = old_oid.decode("ascii")
        new_object = new_oid.decode("ascii")
        entries.append(
            {
                "status": status_value,
                "oldPath": old_path,
                "path": path,
                "oldMode": old_mode.decode("ascii"),
                "newMode": new_mode.decode("ascii"),
                "oldObjectId": None if set(old_object) == {"0"} else old_object,
                "newObjectId": None if set(new_object) == {"0"} else new_object,
                "oldBlobSha256": entry_sha256(
                    repo,
                    old_object,
                    old_mode.decode("ascii"),
                    cache=blob_cache,
                    budget=blob_budget,
                ),
                "newBlobSha256": entry_sha256(
                    repo,
                    new_object,
                    new_mode.decode("ascii"),
                    cache=blob_cache,
                    budget=blob_budget,
                ),
            }
        )
        if len(entries) > MAX_SNAPSHOT_PATH_ENTRIES:
            fail(f"snapshot path manifest cannot exceed {MAX_SNAPSHOT_PATH_ENTRIES} entries")
    return entries


def snapshot_range(repo: Path, parent_revision: str, tip_revision: str) -> dict[str, Any]:
    parent = resolve_commit(repo, parent_revision, "parent")
    tip = resolve_commit(repo, tip_revision, "tip")
    ensure_ancestor(repo, parent, tip, "range")
    ordered = run_git(repo, ["rev-list", "--reverse", f"{parent}..{tip}"]).decode().splitlines()
    if not ordered:
        fail("snapshot range must contain at least one commit")
    if len(ordered) > MAX_SNAPSHOT_COMMITS:
        fail(f"snapshot range cannot exceed {MAX_SNAPSHOT_COMMITS} commits")
    commits: list[dict[str, Any]] = []
    expected_parent = parent
    total_manifest_entries = 0
    blob_cache: dict[str, str] = {}
    blob_budget = {"bytes": 0}
    for commit in ordered:
        parents = run_git(repo, ["show", "-s", "--format=%P", commit]).decode().strip().split()
        if parents != [expected_parent]:
            fail(f"linear-replay-v2 requires one direct parent for {commit}; measured {parents}")
        manifest = path_manifest(
            repo,
            expected_parent,
            commit,
            blob_cache=blob_cache,
            blob_budget=blob_budget,
        )
        total_manifest_entries += len(manifest)
        if total_manifest_entries > MAX_SNAPSHOT_PATH_ENTRIES:
            fail(
                "snapshot per-commit manifests cannot exceed "
                f"{MAX_SNAPSHOT_PATH_ENTRIES} aggregate entries"
            )
        commits.append(
            {
                "commit": commit,
                "parent": expected_parent,
                "patchId": stable_patch_id_for_range(repo, expected_parent, commit),
                "tree": resolve_tree(repo, commit),
                "paths": manifest,
            }
        )
        expected_parent = commit
    aggregate_manifest = path_manifest(
        repo,
        parent,
        tip,
        blob_cache=blob_cache,
        blob_budget=blob_budget,
    )
    total_manifest_entries += len(aggregate_manifest)
    if total_manifest_entries > MAX_SNAPSHOT_PATH_ENTRIES:
        fail(
            "snapshot manifests cannot exceed "
            f"{MAX_SNAPSHOT_PATH_ENTRIES} aggregate entries"
        )
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "transportProfile": "linear-replay-v2",
        "parent": parent,
        "tip": tip,
        "finalTree": resolve_tree(repo, tip),
        "commits": commits,
        "aggregatePatchId": stable_patch_id_for_range(repo, parent, tip),
        "paths": aggregate_manifest,
    }
    canonical = canonical_json(result)
    if len(canonical) > MAX_JSON_BYTES:
        fail(f"snapshot exceeds the {MAX_JSON_BYTES}-byte proof ceiling")
    result["rangeDigest"] = sha256_bytes(canonical)
    return result


def snapshot_owned_paths(snapshot: dict[str, Any]) -> set[str]:
    paths: set[str] = set()

    def collect(entries: list[Any], label: str) -> None:
        for entry in entries:
            item = require_mapping(entry, f"{label} entry")
            path = validate_repo_path(
                require_string(item.get("path"), f"{label} path"), f"{label} path"
            )
            paths.add(path)
            old_path = item.get("oldPath")
            if old_path is not None:
                paths.add(
                    validate_repo_path(
                        require_string(old_path, f"{label} oldPath"), f"{label} oldPath"
                    )
                )

    collect(require_list(snapshot.get("paths"), "snapshot.paths"), "snapshot path")
    for index, raw_commit in enumerate(
        require_list(snapshot.get("commits"), "snapshot.commits", nonempty=True)
    ):
        commit = require_mapping(raw_commit, f"snapshot.commits[{index}]")
        collect(
            require_list(commit.get("paths"), f"snapshot.commits[{index}].paths"),
            f"snapshot commit {index} path",
        )
    return paths


def replay_equivalence(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized_commits = []
    for index, raw_commit in enumerate(
        require_list(snapshot.get("commits"), "snapshot.commits", nonempty=True)
    ):
        commit = require_mapping(raw_commit, f"snapshot.commits[{index}]")
        commit_paths = []
        for raw_path in require_list(commit.get("paths"), f"snapshot.commits[{index}].paths"):
            path = require_mapping(raw_path, f"snapshot.commits[{index}] path entry")
            commit_paths.append(
                {
                    field: path.get(field)
                    for field in (
                        "status",
                        "oldPath",
                        "path",
                        "oldMode",
                        "newMode",
                        "oldObjectId",
                        "newObjectId",
                        "oldBlobSha256",
                        "newBlobSha256",
                    )
                }
            )
        normalized_commits.append({"patchId": commit.get("patchId"), "paths": commit_paths})
    normalized_paths = []
    for item in require_list(snapshot.get("paths"), "snapshot.paths"):
        path = require_mapping(item, "snapshot path entry")
        normalized_paths.append(
            {
                field: path.get(field)
                for field in (
                    "status",
                    "oldPath",
                    "path",
                    "oldMode",
                    "newMode",
                    "oldObjectId",
                    "newObjectId",
                    "oldBlobSha256",
                    "newBlobSha256",
                )
            }
        )
    return {
        "commits": normalized_commits,
        "aggregatePatchId": snapshot.get("aggregatePatchId"),
        "paths": normalized_paths,
    }


def load_and_recompute_snapshot(repo: Path, path: Path, label: str) -> dict[str, Any]:
    recorded = require_mapping(load_json_file(path, label), label)
    recomputed = snapshot_range(
        repo,
        require_string(recorded.get("parent"), f"{label}.parent"),
        require_string(recorded.get("tip"), f"{label}.tip"),
    )
    if recorded != recomputed:
        fail(f"{label} does not match the current Git object graph")
    return recorded


def verify_handoff_data(
    repo: Path,
    charter_path: Path,
    handoff_path: Path,
    *,
    require_checkout: bool = True,
    seen_handoffs: set[Path] | None = None,
    verify_previous_chain: bool = True,
) -> dict[str, Any]:
    charter_path = validate_no_reparse_chain(charter_path, "charter")
    charter = require_mapping(load_json_file(charter_path, "charter"), "charter")
    charter_result = validate_charter_data(
        repo, charter, clean=False, charter_path=charter_path, remeasure_admission=False
    )
    if charter_result["mode"] != "multi-writer":
        fail("verify-handoff only accepts multi-writer charters; use verify-evidence for evidence-fanout")
    canonical_handoff = validate_no_reparse_chain(handoff_path, "handoff")
    seen = set() if seen_handoffs is None else seen_handoffs
    if canonical_handoff in seen:
        fail(f"handoff chain contains a cycle: {handoff_path}")
    seen.add(canonical_handoff)
    handoff = require_mapping(load_json_file(handoff_path, "handoff"), "handoff")
    reject_unresolved_template_tokens(handoff, "handoff")
    require_exact_keys(
        handoff,
        {
            "schemaVersion",
            "waveId",
            "charterDigest",
            "cellId",
            "workspaceId",
            "sequence",
            "fromActor",
            "toActor",
            "incomingBaton",
            "outgoingBaton",
            "preparedSnapshot",
            "integratedSnapshot",
            "previousHandoff",
            "focusedVerification",
            "workingTreeClean",
            "conflictResolution",
            "nextWork",
        },
        "handoff",
    )
    if require_integer(handoff.get("schemaVersion"), "handoff.schemaVersion") != SCHEMA_VERSION:
        fail("handoff schemaVersion is unsupported")
    if handoff.get("waveId") != charter.get("waveId"):
        fail("handoff waveId does not match charter")
    if handoff.get("charterDigest") != charter_result["charterDigest"]:
        fail("handoff charterDigest does not match charter bytes")
    cell_id = require_string(handoff.get("cellId"), "handoff.cellId")
    cell_indexes = [
        index for index, item in enumerate(charter["cells"]) if item.get("cellId") == cell_id
    ]
    if len(cell_indexes) != 1:
        fail(f"handoff cellId is not unique in charter: {cell_id}")
    cell_index = cell_indexes[0]
    cell = charter["cells"][cell_index]
    expected_sequence = cell_index + 1
    if require_integer(handoff.get("sequence"), "handoff.sequence", minimum=1) != expected_sequence:
        fail(f"handoff sequence must be {expected_sequence} for cell {cell_id}")
    if handoff.get("workspaceId") != cell.get("workspaceId"):
        fail(f"handoff workspaceId does not match charter cell {cell_id}")
    if handoff.get("fromActor") != cell.get("actor"):
        fail(f"handoff fromActor does not match charter cell {cell_id}")
    expected_recipient = (
        charter["cells"][cell_index + 1]["actor"]
        if cell_index + 1 < len(charter["cells"])
        else charter["waveOwner"]
    )
    if handoff.get("toActor") != expected_recipient:
        fail(f"handoff toActor must be {expected_recipient!r} for cell {cell_id}")
    if handoff.get("conflictResolution") is not None:
        fail("linear-replay-v2 handoff cannot claim conflict resolution")
    if handoff.get("workingTreeClean") is not True:
        fail("handoff must record workingTreeClean=true")

    base = handoff_path.parent
    prepared_path = resolve_regular_json(base, require_string(handoff.get("preparedSnapshot"), "preparedSnapshot"), "prepared snapshot")
    integrated_path = resolve_regular_json(base, require_string(handoff.get("integratedSnapshot"), "integratedSnapshot"), "integrated snapshot")
    prepared = load_and_recompute_snapshot(repo, prepared_path, "prepared snapshot")
    integrated = load_and_recompute_snapshot(repo, integrated_path, "integrated snapshot")
    incoming_value = require_string(handoff.get("incomingBaton"), "incomingBaton")
    outgoing_value = require_string(handoff.get("outgoingBaton"), "outgoingBaton")
    incoming = resolve_commit(repo, incoming_value, "incomingBaton")
    outgoing = resolve_commit(repo, outgoing_value, "outgoingBaton")
    if incoming_value != incoming or outgoing_value != outgoing:
        fail("handoff incomingBaton/outgoingBaton must be full canonical commit IDs")
    if integrated.get("parent") != incoming or integrated.get("tip") != outgoing:
        fail("handoff incoming/outgoing does not match integrated snapshot")
    ensure_ancestor(repo, incoming, outgoing, "handoff")

    previous_reference = handoff.get("previousHandoff")
    if cell_index == 0:
        if previous_reference is not None:
            fail("the first handoff must record previousHandoff=null")
        validate_first_incoming_baton(
            repo,
            charter_result["baselineCommit"],
            charter_result["baselineTree"],
            incoming,
        )
    elif verify_previous_chain:
        previous_path = resolve_regular_json(
            base,
            require_string(previous_reference, "previousHandoff"),
            "previous handoff",
        )
        previous = verify_handoff_data(
            repo,
            charter_path,
            previous_path,
            require_checkout=False,
            seen_handoffs=seen,
        )
        expected_previous_cell = charter["cells"][cell_index - 1]["cellId"]
        if previous["cellId"] != expected_previous_cell:
            fail(
                f"previousHandoff must be the immediately preceding cell {expected_previous_cell}"
            )
        if previous["outgoingBaton"] != incoming:
            fail("previousHandoff outgoing baton does not equal this incoming baton")
    if replay_equivalence(prepared) != replay_equivalence(integrated):
        fail("prepared and integrated ranges are not byte/mode/patch equivalent")
    expected_paths = set(string_list(cell.get("writablePaths"), f"cell {cell_id} writablePaths"))
    measured_paths = snapshot_owned_paths(integrated)
    if expected_paths != measured_paths:
        fail(f"handoff path set mismatch: expected {sorted(expected_paths)}, measured {sorted(measured_paths)}")
    checks = bounded_list(
        handoff.get("focusedVerification"),
        "focusedVerification",
        limit=MAX_CHECK_IDS,
        nonempty=True,
    )
    measured_commands: list[str] = []
    for index, raw_check in enumerate(checks):
        check = require_mapping(raw_check, f"focusedVerification[{index}]")
        require_exact_keys(
            check,
            {"command", "revision", "verdict"},
            f"focusedVerification[{index}]",
        )
        measured_commands.append(
            require_string(check.get("command"), f"focusedVerification[{index}].command")
        )
        if check.get("revision") != outgoing or check.get("verdict") != "PASS":
            fail(f"focusedVerification[{index}] is not PASS at outgoing baton")
    if measured_commands != cell.get("focusedChecks"):
        fail("handoff focusedVerification commands do not exactly equal charter focusedChecks")
    next_work = string_list(handoff.get("nextWork"), "handoff.nextWork")
    if next_work != cell.get("nextWork"):
        fail("handoff nextWork does not exactly equal charter nextWork")
    clean_remeasured: bool | None = None
    if require_checkout:
        admitted_rows = [
            row
            for row in charter["workspaceAdmission"]["workspaces"]
            if row.get("workspaceId") == cell.get("workspaceId")
            and row.get("actor") == cell.get("actor")
        ]
        if len(admitted_rows) != 1:
            fail("handoff cell does not have one admitted physical workspace")
        current_root = repo_root(repo)
        current_git_dir = worktree_git_dir_id(repo, current_root)
        if current_git_dir != admitted_rows[0].get("worktreeGitDir"):
            fail(
                "verify-handoff must run from the exact physical worktree admitted "
                f"for cell {cell_id}"
            )
        registered_path = registered_worktree_path(repo, current_git_dir)
        if os.path.normcase(os.path.realpath(current_root)) != registered_path:
            fail(
                "verify-handoff must run from the Git-registered physical worktree path "
                f"for cell {cell_id}"
            )
        if physical_identity_digest(current_root) != admitted_rows[0].get(
            "physicalIdentityDigest"
        ):
            fail("verify-handoff physical worktree identity differs from charter admission")
        head = resolve_commit(repo, "HEAD", "HEAD")
        if head != outgoing:
            fail("verify-handoff requires the outgoing baton to be checked out")
        ensure_clean(repo, "outgoing baton")
        clean_remeasured = True
    return {
        "ok": True,
        "waveId": charter["waveId"],
        "cellId": cell_id,
        "incomingBaton": incoming,
        "outgoingBaton": outgoing,
        "rangeDigest": integrated["rangeDigest"],
        "workingTreeCleanRemeasured": clean_remeasured,
    }


def commit_parents(repo: Path, revision: str) -> list[str]:
    value = run_git(repo, ["show", "-s", "--format=%P", revision]).decode().strip()
    return value.split() if value else []


def validate_first_incoming_baton(
    repo: Path, baseline: str, baseline_tree: str, incoming: str
) -> None:
    if incoming == baseline:
        return
    if commit_parents(repo, incoming) != [baseline] or resolve_tree(repo, incoming) != baseline_tree:
        fail(
            "the first incoming baton must be the charter baseline or one direct "
            "single-parent tree-neutral charter commit"
        )


def validate_landing_graph(
    repo: Path,
    *,
    charter_baseline: str,
    integration_head: str,
    landing_mode: str,
    base_revision: str,
    merge_revision: str,
    measured_parents: list[str],
) -> None:
    if base_revision != charter_baseline:
        fail("landing baseRevision must equal the final charter baselineCommit")
    ensure_ancestor(repo, base_revision, integration_head, "landing base to integration head")
    if landing_mode == "two-parent-merge":
        if measured_parents != [base_revision, integration_head]:
            fail("two-parent landing must have parents [baseRevision, integrationHead]")
        if resolve_tree(repo, merge_revision) != resolve_tree(repo, integration_head):
            fail("two-parent landing tree must equal the reviewed integrationHead tree")
    elif landing_mode == "fast-forward":
        if merge_revision != integration_head:
            fail("fast-forward landing mergeRevision must equal integrationHead")
    else:
        fail("landing mode must be two-parent-merge or fast-forward")


def _check_id_set(items: list[Any], label: str, subject: str) -> set[str]:
    result: set[str] = set()
    for index, raw_item in enumerate(items):
        item = require_mapping(raw_item, f"{label}[{index}]")
        require_exact_keys(item, {"checkId", "status", "revision"}, f"{label}[{index}]")
        check_id = require_string(item.get("checkId"), f"{label}[{index}].checkId")
        if check_id in result:
            fail(f"{label} contains duplicate checkId: {check_id}")
        result.add(check_id)
        if item.get("status") != "PASS" or item.get("revision") != subject:
            fail(f"{label}[{index}] is not PASS at the evidence subject")
    return result


def verify_evidence_data(
    repo: Path,
    charter_path: Path,
    evidence_path: Path,
    *,
    expected_requirement: dict[str, Any] | None = None,
    integration_head: str | None = None,
    merge_revision: str | None = None,
    landing_base: str | None = None,
) -> dict[str, Any]:
    charter_path = validate_no_reparse_chain(charter_path, "charter")
    charter = require_mapping(load_json_file(charter_path, "charter"), "charter")
    charter_result = validate_charter_data(
        repo, charter, clean=False, charter_path=charter_path, remeasure_admission=False
    )
    evidence = require_mapping(load_json_file(evidence_path, "evidence"), "evidence")
    reject_unresolved_template_tokens(evidence, "evidence")
    require_exact_keys(
        evidence,
        {
            "schemaVersion",
            "waveId",
            "charterDigest",
            "evidenceId",
            "requirementId",
            "stage",
            "cellId",
            "workspaceId",
            "actor",
            "attestationSource",
            "subject",
            "checks",
            "artifacts",
            "verdict",
        },
        "evidence",
    )
    if require_integer(evidence.get("schemaVersion"), "evidence.schemaVersion") != SCHEMA_VERSION:
        fail("evidence schemaVersion is unsupported")
    if evidence.get("waveId") != charter.get("waveId"):
        fail("evidence waveId does not match charter")
    if evidence.get("charterDigest") != charter_result["charterDigest"]:
        fail("evidence charterDigest does not match charter bytes")
    evidence_id = require_string(evidence.get("evidenceId"), "evidence.evidenceId")
    stage = evidence.get("stage")
    if stage not in ("fanout", "independent-review", "pr", "post-merge"):
        fail("evidence stage must be fanout, independent-review, pr, or post-merge")
    attestation_source = require_string(
        evidence.get("attestationSource"), "evidence.attestationSource"
    )

    subject = require_mapping(evidence.get("subject"), "evidence.subject")
    require_exact_keys(
        subject,
        {"relation", "revision", "tree", "parents", "baseRevision", "headRevision"},
        "evidence.subject",
    )
    revision = resolve_commit(
        repo, require_string(subject.get("revision"), "evidence.subject.revision"), "evidence subject"
    )
    if subject.get("revision") != revision:
        fail("evidence subject revision must be a full canonical commit ID")
    if subject.get("tree") != resolve_tree(repo, revision):
        fail("evidence subject tree does not match Git")
    parents = commit_parents(repo, revision)
    if subject.get("parents") != parents:
        fail("evidence subject parents do not match Git in exact order")
    head_revision = resolve_commit(
        repo,
        require_string(subject.get("headRevision"), "evidence.subject.headRevision"),
        "evidence headRevision",
    )
    if subject.get("headRevision") != head_revision:
        fail("evidence headRevision must be a full canonical commit ID")
    relation = subject.get("relation")
    base_value = subject.get("baseRevision")
    base_revision: str | None = None
    if base_value is not None:
        base_revision = resolve_commit(
            repo, require_string(base_value, "evidence.subject.baseRevision"), "evidence baseRevision"
        )
        if base_value != base_revision:
            fail("evidence baseRevision must be a full canonical commit ID")

    checks = bounded_list(
        evidence.get("checks"), "evidence.checks", limit=MAX_CHECK_IDS
    )
    measured_check_ids = _check_id_set(checks, "evidence.checks", revision)
    artifacts = bounded_list(
        evidence.get("artifacts"), "evidence.artifacts", limit=MAX_ARTIFACTS
    )
    if not checks and not artifacts:
        fail("evidence must contain at least one check or artifact")
    measured_artifact_ids: set[str] = set()
    measured_artifact_statuses: dict[str, set[str]] = {}
    for index, raw_artifact in enumerate(artifacts):
        artifact = require_mapping(raw_artifact, f"evidence.artifacts[{index}]")
        require_exact_keys(
            artifact,
            {"artifactId", "revision", "digestAlgorithm", "digest", "statuses"},
            f"evidence.artifacts[{index}]",
        )
        artifact_id = require_string(
            artifact.get("artifactId"), f"evidence.artifacts[{index}].artifactId"
        )
        if artifact_id in measured_artifact_ids:
            fail(f"evidence.artifacts contains duplicate artifactId: {artifact_id}")
        measured_artifact_ids.add(artifact_id)
        if artifact.get("revision") != revision:
            fail(f"evidence.artifacts[{index}] revision does not match evidence subject")
        if artifact.get("digestAlgorithm") != "sha256" or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(artifact.get("digest"))
        ):
            fail(f"evidence.artifacts[{index}] must carry a canonical sha256 digest")
        measured_artifact_statuses[artifact_id] = _check_id_set(
            bounded_list(
                artifact.get("statuses"),
                f"evidence.artifacts[{index}].statuses",
                limit=MAX_ARTIFACT_STATUS_IDS,
                nonempty=True,
            ),
            f"evidence.artifacts[{index}].statuses",
            revision,
        )
    if evidence.get("verdict") != "PASS":
        fail("evidence verdict must be PASS")

    requirement_id = evidence.get("requirementId")
    cell_id = evidence.get("cellId")
    if stage == "fanout":
        if charter_result["mode"] != "evidence-fanout":
            fail("fanout evidence requires an evidence-fanout charter")
        if requirement_id is not None:
            fail("fanout evidence must record requirementId=null")
        matching = [cell for cell in charter["cells"] if cell.get("cellId") == cell_id]
        if len(matching) != 1:
            fail("fanout evidence cellId does not identify one charter cell")
        cell = matching[0]
        if evidence.get("workspaceId") != cell.get("workspaceId") or evidence.get("actor") != cell.get("actor"):
            fail("fanout evidence actor/workspace does not match its charter cell")
        if attestation_source != cell.get("requiredAttestationSource"):
            fail("fanout evidence attestationSource does not match its charter cell")
        if relation != "exact" or revision != charter_result["baselineCommit"] or head_revision != revision:
            fail("fanout evidence must bind exactly to the frozen charter baseline")
        if base_revision is not None:
            fail("fanout evidence baseRevision must be null")
        expected_checks = set(cell["focusedChecks"])
        if measured_check_ids != expected_checks:
            fail("fanout evidence check set does not equal the charter cell focusedChecks")
        if artifacts:
            fail("fanout evidence does not accept external artifacts")
    elif stage == "independent-review":
        if charter_result["mode"] != "multi-writer":
            fail("independent-review evidence requires a multi-writer charter")
        if cell_id is not None or evidence.get("workspaceId") is not None:
            fail("independent-review evidence must record cellId/workspaceId=null")
        review_actor = require_string(evidence.get("actor"), "evidence.actor")
        non_independent_actors = {
            authority_identity(require_string(charter.get("programmeConductor"), "programmeConductor")),
            authority_identity(require_string(charter.get("waveOwner"), "waveOwner")),
            *(authority_identity(require_string(cell.get("actor"), "cell actor")) for cell in charter["cells"]),
        }
        if authority_identity(review_actor) in non_independent_actors:
            fail(
                "independent-review evidence actor must differ from the programmeConductor, "
                "waveOwner, and every contributor"
            )
        requirement = charter["ownerIntegration"]["independentReview"]
        if requirement_id != requirement["requirementId"]:
            fail("independent-review evidence requirementId does not match the charter")
        if expected_requirement is not None and requirement != expected_requirement:
            fail("independent-review evidence does not match the closeout requirement")
        if attestation_source != requirement["requiredAttestationSource"]:
            fail("independent-review attestationSource does not match the charter")
        expected_checks = set(requirement["requiredCheckIds"])
        if measured_check_ids != expected_checks or artifacts:
            fail("independent-review check set must equal the charter and artifacts must be empty")
        if relation != "head-exact" or revision != head_revision or base_revision is not None:
            fail("independent-review evidence must be head-exact")
        if integration_head is not None and head_revision != integration_head:
            fail("independent-review evidence headRevision does not equal integrationHead")
    else:
        if charter_result["mode"] != "multi-writer":
            fail("PR/post-merge evidence requires a multi-writer charter")
        if cell_id is not None or evidence.get("workspaceId") is not None:
            fail("PR/post-merge evidence must record cellId/workspaceId=null")
        if evidence.get("actor") != charter.get("waveOwner"):
            fail("PR/post-merge evidence actor must equal the waveOwner")
        requirement_matches = [
            item for item in charter["externalEvidence"] if item.get("requirementId") == requirement_id
        ]
        if len(requirement_matches) != 1:
            fail("evidence requirementId does not identify one charter requirement")
        requirement = requirement_matches[0]
        if expected_requirement is not None and requirement != expected_requirement:
            fail("evidence does not match the closeout requirement")
        if stage != requirement["stage"] or relation != requirement["subjectRelation"]:
            fail("evidence stage/relation does not match its charter requirement")
        if attestation_source != requirement["requiredAttestationSource"]:
            fail("evidence attestationSource does not match its charter requirement")
        expected_checks = set(requirement["requiredCheckIds"])
        expected_artifacts = {
            item["artifactId"]: set(item["requiredStatusIds"])
            for item in requirement["requiredArtifacts"]
        }
        if measured_check_ids != expected_checks or measured_artifact_ids != set(expected_artifacts):
            fail("evidence check/artifact set does not equal its charter requirement")
        for artifact_id, required_status_ids in expected_artifacts.items():
            if measured_artifact_statuses.get(artifact_id) != required_status_ids:
                fail(
                    "evidence artifact status set does not equal its charter requirement "
                    f"for {artifact_id}"
                )
        if relation == "head-exact":
            if revision != head_revision or base_revision is not None:
                fail("head-exact evidence must use subject=head and baseRevision=null")
        elif relation == "synthetic-two-parent":
            if base_revision is None or parents != [base_revision, head_revision]:
                fail("synthetic-two-parent evidence parents must be [baseRevision, headRevision]")
            if resolve_tree(repo, revision) != resolve_tree(repo, head_revision):
                fail("synthetic-two-parent evidence tree must equal the headRevision tree")
        elif relation == "merge-exact":
            if revision != head_revision or base_revision is not None:
                fail("merge-exact evidence must use subject=head and baseRevision=null")
        if integration_head is not None and stage == "pr" and head_revision != integration_head:
            fail("PR evidence headRevision does not equal the closeout integrationHead")
        if merge_revision is not None and stage == "post-merge" and revision != merge_revision:
            fail("post-merge evidence does not equal the closeout mergeRevision")
        if landing_base is not None and relation == "synthetic-two-parent" and base_revision != landing_base:
            fail("PR synthetic evidence baseRevision does not equal the closeout landing base")

    return {
        "ok": True,
        "waveId": charter["waveId"],
        "evidenceId": evidence_id,
        "requirementId": requirement_id,
        "stage": stage,
        "cellId": cell_id,
        "subjectRevision": revision,
        "headRevision": head_revision,
    }


def parse_worktrees(repo: Path) -> list[Path]:
    output = run_git(repo, ["worktree", "list", "--porcelain", "-z"])
    records = output.split(b"\0\0")
    paths: list[Path] = []
    for record in records:
        if not record:
            continue
        fields = record.split(b"\0")
        first = fields[0].decode("utf-8", "surrogateescape")
        if not first.startswith("worktree "):
            fail("unexpected git worktree porcelain output")
        paths.append(Path(first[len("worktree ") :]).absolute())
        if len(paths) > MAX_WORKTREES:
            fail(f"Git worktree registry cannot exceed {MAX_WORKTREES} entries")
    if not paths:
        fail("no Git worktrees found")
    return paths


def _git_path(repo: Path, value: str) -> Path:
    path = Path(value)
    return path.absolute() if path.is_absolute() else (repo / path).absolute()


def worktree_git_dir_id(repo: Path, worktree: Path) -> str:
    worktree = validate_no_reparse_chain(worktree, "worktree path")
    expected_git_dir = validate_worktree_admin_path(worktree)
    common_raw = run_git(repo, ["rev-parse", "--git-common-dir"]).decode().strip()
    common_unresolved = _git_path(repo, common_raw)
    common = validate_no_reparse_chain(common_unresolved, "Git common directory")
    if not common.is_dir():
        fail("Git common directory must be a directory")
    git_dir_raw = run_git(worktree, ["rev-parse", "--git-dir"]).decode().strip()
    git_dir_unresolved = _git_path(worktree, git_dir_raw)
    git_dir = validate_no_reparse_chain(git_dir_unresolved, "Git worktree directory")
    if not git_dir.is_dir():
        fail("Git worktree directory must be a directory")
    if os.path.normcase(os.path.realpath(git_dir)) != os.path.normcase(
        os.path.realpath(expected_git_dir)
    ):
        fail("Git worktree directory disagrees with the validated .git marker")
    try:
        relative = git_dir.relative_to(common.parent).as_posix()
    except ValueError:
        fail(f"registered worktree Git directory escapes the common repository: {worktree}")
    return validate_repo_path(relative, "worktree Git directory identity")


def registered_worktree_path(repo: Path, git_dir_id: str) -> str:
    matches: list[Path] = []
    for raw_path in parse_worktrees(repo):
        path = validate_no_reparse_chain(raw_path, "registered worktree path")
        if not path.is_dir():
            fail(f"registered worktree path must be a directory: {path}")
        if worktree_git_dir_id(repo, path) == git_dir_id:
            matches.append(path)
    if len(matches) != 1:
        fail(f"Git worktree identity must map to one registered physical path: {git_dir_id}")
    return os.path.normcase(os.path.realpath(matches[0]))


def measure_worktrees(repo: Path, main_ref: str, instruction_path: str) -> dict[str, Any]:
    validate_repo_path(instruction_path, "instructionPath")
    main = resolve_commit(repo, main_ref, "main-ref")
    rows: list[dict[str, Any]] = []
    instruction_blobs: set[str] = set()
    physical_paths: set[str] = set()
    git_dirs: set[str] = set()
    for raw_path in parse_worktrees(repo):
        path = validate_no_reparse_chain(raw_path, "registered worktree path")
        if not path.is_dir():
            fail(f"registered worktree path must be a directory: {path}")
        physical = os.path.normcase(os.path.realpath(path))
        if physical in physical_paths:
            fail("Git registered the same physical worktree path more than once")
        physical_paths.add(physical)
        git_dir = worktree_git_dir_id(repo, path)
        if git_dir.casefold() in git_dirs:
            fail("Git registered the same administrative worktree identity more than once")
        git_dirs.add(git_dir.casefold())
        head = resolve_commit(path, "HEAD", "worktree HEAD")
        counts = run_git(path, ["rev-list", "--left-right", "--count", f"{main}...{head}"]).decode().strip().split()
        if len(counts) != 2:
            fail(f"could not measure ahead/behind for {git_dir}")
        try:
            behind, ahead = (int(counts[0]), int(counts[1]))
        except ValueError:
            fail(f"Git returned non-integer ahead/behind counts for {git_dir}")
        assert_index_visibility(path)
        dirty = bool(
            run_git(
                path,
                [
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                    "--ignore-submodules=dirty",
                ],
            )
        )
        instruction_blob = resolve_blob_at(
            path,
            head,
            instruction_path,
            f"worktree {git_dir} instruction",
        )
        instruction_blobs.add(instruction_blob)
        rows.append(
            {
                "worktreeGitDir": git_dir,
                "physicalIdentity": physical,
                "physicalIdentityDigest": physical_identity_digest(path),
                "head": head,
                "behind": behind,
                "ahead": ahead,
                "dirty": dirty,
                "instructionBlob": instruction_blob,
            }
        )
    return {
        "mainRevision": main,
        "instructionPath": instruction_path,
        "instructionBlobs": instruction_blobs,
        "rows": rows,
    }


def remeasure_workspace_admission(
    repo: Path, charter: dict[str, Any], admission: dict[str, Any]
) -> dict[str, Any]:
    measured = measure_worktrees(repo, admission["mainRef"], admission["instructionPath"])
    if measured["mainRevision"] != charter["baselineCommit"]:
        fail("workspaceAdmission mainRef does not resolve to baselineCommit")
    expected_instruction = resolve_blob_at(
        repo,
        charter["baselineCommit"],
        admission["instructionPath"],
        "workspaceAdmission instruction",
    )
    if admission["instructionBlob"] != expected_instruction:
        fail("workspaceAdmission instructionBlob does not match the baseline")
    by_git_dir = {row["worktreeGitDir"].casefold(): row for row in measured["rows"]}
    admitted_physical: set[str] = set()
    for declared in admission["workspaces"]:
        row = by_git_dir.get(declared["worktreeGitDir"].casefold())
        if row is None:
            fail(f"workspaceAdmission names an unregistered worktree: {declared['worktreeGitDir']}")
        if row["worktreeGitDir"] != declared["worktreeGitDir"]:
            fail(
                "workspaceAdmission worktreeGitDir must use Git's exact canonical spelling: "
                f"{declared['worktreeGitDir']}"
            )
        if row["physicalIdentityDigest"] != declared["physicalIdentityDigest"]:
            fail(
                "workspaceAdmission physical worktree identity changed for "
                f"{declared['workspaceId']}"
            )
        if row["physicalIdentity"] in admitted_physical:
            fail("workspaceAdmission maps multiple workspace IDs to one physical worktree")
        admitted_physical.add(row["physicalIdentity"])
        if (
            row["head"] != declared["headRevision"]
            or row["ahead"] != declared["ahead"]
            or row["behind"] != declared["behind"]
            or row["dirty"] == declared["clean"]
            or row["instructionBlob"] != admission["instructionBlob"]
        ):
            fail(f"workspaceAdmission remeasurement failed for {declared['workspaceId']}")
    return {"ok": True, "workspaceCount": len(admission["workspaces"])}


def verify_worktrees(repo: Path, main_ref: str, instruction_path: str) -> dict[str, Any]:
    measured = measure_worktrees(repo, main_ref, instruction_path)
    main = measured["mainRevision"]
    rows = measured["rows"]
    problems = [row for row in rows if row["head"] != main or row["behind"] or row["ahead"] or row["dirty"] or not row["instructionBlob"]]
    if len(measured["instructionBlobs"]) != 1:
        fail(f"worktrees do not share one committed {instruction_path} blob")
    if problems:
        fail(f"worktree synchronization failed for {len(problems)} of {len(rows)} worktrees")
    return {
        "ok": True,
        "mainRevision": main,
        "instructionPath": instruction_path,
        "instructionBlob": next(iter(measured["instructionBlobs"])),
        "worktreeCount": len(rows),
        "worktrees": [
            {key: value for key, value in row.items() if key != "physicalIdentity"}
            for row in rows
        ],
    }


def verify_closeout_data(repo: Path, closeout_path: Path) -> dict[str, Any]:
    closeout_path = validate_no_reparse_chain(closeout_path, "closeout")
    closeout = require_mapping(load_json_file(closeout_path, "closeout"), "closeout")
    reject_unresolved_template_tokens(closeout, "closeout")
    require_exact_keys(
        closeout,
        {
            "schemaVersion",
            "waveId",
            "mode",
            "method",
            "charters",
            "charterDigest",
            "handoffs",
            "finalBaton",
            "ownerIntegrationSnapshot",
            "integrationHead",
            "ownerVerification",
            "landing",
            "externalEvidence",
            "openDecisions",
            "rollbackAuthority",
            "synchronization",
        },
        "closeout",
    )
    if require_integer(closeout.get("schemaVersion"), "closeout.schemaVersion") != SCHEMA_VERSION:
        fail("closeout schemaVersion is unsupported")
    closeout_method = require_mapping(closeout.get("method"), "closeout.method")
    require_exact_keys(closeout_method, METHOD_LOCK_FIELDS, "closeout.method")
    compare_method_lock(closeout_method, method_digest(), repo=repo)

    base = closeout_path.parent
    charter_refs = string_list(closeout.get("charters"), "closeout.charters")
    if len(charter_refs) > MAX_HANDOFFS:
        fail(f"closeout cannot contain more than {MAX_HANDOFFS} charter generations")
    if len({item.casefold() for item in charter_refs}) != len(charter_refs):
        fail("closeout.charters contains a duplicate path")
    charter_entries: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    previous_digest: str | None = None
    previous_path: Path | None = None
    previous_charter: dict[str, Any] | None = None
    for index, reference in enumerate(charter_refs):
        path = resolve_regular_json(base, reference, f"closeout charter {index + 1}")
        charter = require_mapping(load_json_file(path, f"closeout charter {index + 1}"), "charter")
        result = validate_charter_data(
            repo, charter, clean=False, charter_path=path, remeasure_admission=False
        )
        if charter.get("method") != closeout_method:
            fail("closeout and charter method locks are not byte-equivalent")
        if index == 0:
            if charter.get("previousCharter") is not None:
                fail("the first closeout charter must have previousCharter=null")
        else:
            predecessor = require_mapping(charter.get("previousCharter"), "previousCharter")
            if predecessor.get("digest") != previous_digest:
                fail("replacement charter does not point to the preceding charter digest")
            declared_path = resolve_regular_json(path.parent, predecessor["path"], "previousCharter.path")
            if declared_path != previous_path:
                fail("replacement charter path does not equal the preceding declared closeout charter")
        if previous_charter is not None:
            validate_replacement_charter(repo, previous_charter, charter)
        previous_digest = result["charterDigest"]
        previous_path = path
        previous_charter = charter
        charter_entries.append((path, charter, result))
    charter_path, charter, charter_result = charter_entries[-1]
    if any(item[1].get("waveId") != charter.get("waveId") for item in charter_entries):
        fail("closeout charter chain changes waveId")
    if closeout.get("waveId") != charter.get("waveId"):
        fail("closeout waveId does not match final charter")
    if closeout.get("charterDigest") != charter_result["charterDigest"]:
        fail("closeout charterDigest does not match the final charter")
    if closeout.get("mode") != charter_result["mode"]:
        fail("closeout mode does not match charter mode")
    if require_list(closeout.get("openDecisions"), "closeout.openDecisions"):
        fail("a verified closeout cannot contain unresolved openDecisions")
    rollback_authority = concrete_authority(
        closeout.get("rollbackAuthority"), "closeout.rollbackAuthority"
    )
    allowed_rollback_authorities = {
        authority_identity(charter["programmeConductor"]),
        authority_identity(charter["waveOwner"]),
    }
    if authority_identity(rollback_authority) not in allowed_rollback_authorities:
        fail("closeout.rollbackAuthority must name the programmeConductor or waveOwner")

    handoff_refs = string_list(
        closeout.get("handoffs"),
        "closeout.handoffs",
        nonempty=charter_result["mode"] == "multi-writer",
    )
    if len(handoff_refs) > MAX_HANDOFFS:
        fail(f"closeout cannot contain more than {MAX_HANDOFFS} handoffs")
    if len({item.casefold() for item in handoff_refs}) != len(handoff_refs):
        fail("closeout.handoffs contains a duplicate path")
    evidence_refs = string_list(closeout.get("externalEvidence"), "closeout.externalEvidence")
    if len(evidence_refs) > MAX_EVIDENCE_REQUIREMENTS:
        fail(f"closeout.externalEvidence cannot exceed {MAX_EVIDENCE_REQUIREMENTS} entries")
    if len({item.casefold() for item in evidence_refs}) != len(evidence_refs):
        fail("closeout.externalEvidence contains a duplicate path")

    if charter_result["mode"] == "evidence-fanout":
        if handoff_refs:
            fail("evidence-fanout closeout cannot contain handoffs")
        for field in ("finalBaton", "ownerIntegrationSnapshot", "integrationHead", "ownerVerification", "landing", "synchronization"):
            if closeout.get(field) is not None:
                fail(f"evidence-fanout closeout must record {field}=null")
        if len(evidence_refs) != len(charter["cells"]):
            fail("evidence-fanout closeout requires exactly one evidence record per cell")
        covered_cells: set[str] = set()
        evidence_ids: set[str] = set()
        for index, reference in enumerate(evidence_refs):
            evidence_path = resolve_regular_json(base, reference, f"closeout evidence {index + 1}")
            measured = verify_evidence_data(repo, charter_path, evidence_path)
            if measured["stage"] != "fanout":
                fail("evidence-fanout closeout accepts only fanout evidence")
            measured_cell = require_string(measured["cellId"], "evidence cellId")
            measured_evidence = measured["evidenceId"]
            if measured_cell in covered_cells or measured_evidence in evidence_ids:
                fail("evidence-fanout closeout contains duplicate cell/evidence IDs")
            covered_cells.add(measured_cell)
            evidence_ids.add(measured_evidence)
        expected_cells = {cell["cellId"] for cell in charter["cells"]}
        if covered_cells != expected_cells:
            fail("evidence-fanout closeout does not cover the charter cells exactly")
        remeasure_workspace_admission(
            repo,
            charter,
            require_mapping(charter.get("workspaceAdmission"), "workspaceAdmission"),
        )
        return {
            "ok": True,
            "waveId": charter["waveId"],
            "mode": "evidence-fanout",
            "charterDigest": charter_result["charterDigest"],
            "subjectRevision": charter_result["baselineCommit"],
            "evidenceCount": len(evidence_refs),
        }

    if len(handoff_refs) != len(charter["cells"]):
        fail("multi-writer closeout requires exactly one handoff per charter cell")
    handoff_paths = [
        resolve_regular_json(base, reference, f"closeout handoff {index + 1}")
        for index, reference in enumerate(handoff_refs)
    ]
    measured_handoffs: list[dict[str, Any]] = []
    for index, handoff_path in enumerate(handoff_paths):
        handoff_data = require_mapping(
            load_json_file(handoff_path, f"closeout handoff {index + 1}"),
            f"closeout handoff {index + 1}",
        )
        if index > 0:
            declared_previous = resolve_regular_json(
                handoff_path.parent,
                require_string(
                    handoff_data.get("previousHandoff"),
                    f"closeout handoff {index + 1}.previousHandoff",
                ),
                f"closeout handoff {index + 1} previous handoff",
            )
            if declared_previous != handoff_paths[index - 1]:
                fail(
                    "closeout handoff previousHandoff does not equal the preceding "
                    "declared closeout handoff"
                )
        measured = verify_handoff_data(
            repo,
            charter_path,
            handoff_path,
            require_checkout=False,
            verify_previous_chain=False,
        )
        if measured["cellId"] != charter["cells"][index]["cellId"]:
            fail("closeout handoff order does not equal charter cell order")
        if index > 0 and measured_handoffs[-1]["outgoingBaton"] != measured["incomingBaton"]:
            fail("closeout handoff baton chain is discontinuous")
        measured_handoffs.append(measured)
    final_baton = resolve_commit(
        repo, require_string(closeout.get("finalBaton"), "closeout.finalBaton"), "finalBaton"
    )
    if closeout.get("finalBaton") != final_baton or measured_handoffs[-1]["outgoingBaton"] != final_baton:
        fail("closeout finalBaton does not equal the final handoff outgoing baton")

    integration_head = resolve_commit(
        repo,
        require_string(closeout.get("integrationHead"), "closeout.integrationHead"),
        "integrationHead",
    )
    if closeout.get("integrationHead") != integration_head:
        fail("closeout integrationHead must be a full canonical commit ID")
    ensure_ancestor(repo, final_baton, integration_head, "owner integration")
    owner_snapshot_reference = closeout.get("ownerIntegrationSnapshot")
    if integration_head == final_baton:
        if owner_snapshot_reference is not None:
            fail("ownerIntegrationSnapshot must be null when integrationHead equals finalBaton")
    else:
        owner_snapshot_path = resolve_regular_json(
            base,
            require_string(owner_snapshot_reference, "closeout.ownerIntegrationSnapshot"),
            "owner integration snapshot",
        )
        owner_snapshot = load_and_recompute_snapshot(repo, owner_snapshot_path, "owner integration snapshot")
        if owner_snapshot.get("parent") != final_baton or owner_snapshot.get("tip") != integration_head:
            fail("owner integration snapshot does not bind finalBaton..integrationHead")
        declared_owner_paths = set(charter["ownerOnlyPaths"])
        measured_owner_paths = snapshot_owned_paths(owner_snapshot)
        if not measured_owner_paths.issubset(declared_owner_paths):
            fail("owner integration changed a path outside ownerOnlyPaths")

    owner_verification = require_mapping(
        closeout.get("ownerVerification"), "closeout.ownerVerification"
    )
    require_exact_keys(
        owner_verification,
        {"revision", "localChecks", "independentReviewEvidence"},
        "closeout.ownerVerification",
    )
    if owner_verification.get("revision") != integration_head:
        fail("ownerVerification.revision must equal integrationHead")
    declared_checks = charter["ownerIntegration"]["requiredLocalChecks"]
    measured_checks = bounded_list(
        owner_verification.get("localChecks"),
        "ownerVerification.localChecks",
        limit=MAX_OWNER_LOCAL_CHECKS,
        nonempty=True,
    )
    if len(measured_checks) != len(declared_checks):
        fail("ownerVerification local check count does not equal the charter")
    normalized_checks: list[tuple[str, str]] = []
    for index, raw_check in enumerate(measured_checks):
        check = require_mapping(raw_check, f"ownerVerification.localChecks[{index}]")
        require_exact_keys(
            check,
            {"checkId", "command", "revision", "verdict"},
            f"ownerVerification.localChecks[{index}]",
        )
        if check.get("revision") != integration_head or check.get("verdict") != "PASS":
            fail("every owner local check must be PASS at integrationHead")
        normalized_checks.append(
            (
                require_string(check.get("checkId"), "owner local checkId"),
                require_string(check.get("command"), "owner local command"),
            )
        )
    expected_checks = [(item["checkId"], item["command"]) for item in declared_checks]
    if normalized_checks != expected_checks:
        fail("ownerVerification local check IDs/commands/order do not equal the charter")
    review_path = resolve_regular_json(
        base,
        require_string(
            owner_verification.get("independentReviewEvidence"),
            "ownerVerification.independentReviewEvidence",
        ),
        "owner independent-review evidence",
    )
    review_result = verify_evidence_data(
        repo,
        charter_path,
        review_path,
        expected_requirement=charter["ownerIntegration"]["independentReview"],
        integration_head=integration_head,
    )
    if review_result["stage"] != "independent-review":
        fail("ownerVerification evidence is not independent-review evidence")
    owner_review_evidence_id = review_result["evidenceId"]

    landing = require_mapping(closeout.get("landing"), "closeout.landing")
    require_exact_keys(
        landing,
        {"mode", "baseRevision", "mergeRevision", "mergeParents"},
        "closeout.landing",
    )
    landing_mode = landing.get("mode")
    base_revision = resolve_commit(
        repo,
        require_string(landing.get("baseRevision"), "closeout.landing.baseRevision"),
        "landing baseRevision",
    )
    merge_revision = resolve_commit(
        repo,
        require_string(landing.get("mergeRevision"), "closeout.landing.mergeRevision"),
        "landing mergeRevision",
    )
    if landing.get("baseRevision") != base_revision or landing.get("mergeRevision") != merge_revision:
        fail("landing revisions must be full canonical commit IDs")
    measured_parents = commit_parents(repo, merge_revision)
    if landing.get("mergeParents") != measured_parents:
        fail("landing mergeParents do not match Git in exact order")
    validate_landing_graph(
        repo,
        charter_baseline=charter_result["baselineCommit"],
        integration_head=integration_head,
        landing_mode=landing_mode,
        base_revision=base_revision,
        merge_revision=merge_revision,
        measured_parents=measured_parents,
    )

    requirements = charter["externalEvidence"]
    if len(evidence_refs) != len(requirements):
        fail("closeout evidence count does not equal charter requirements")
    seen_requirement_ids: set[str] = set()
    seen_evidence_ids: set[str] = {owner_review_evidence_id}
    requirements_by_id = {item["requirementId"]: item for item in requirements}
    for index, reference in enumerate(evidence_refs):
        evidence_path = resolve_regular_json(base, reference, f"closeout evidence {index + 1}")
        raw_evidence = require_mapping(load_json_file(evidence_path, "closeout evidence"), "evidence")
        requirement_id = require_string(raw_evidence.get("requirementId"), "evidence.requirementId")
        requirement = requirements_by_id.get(requirement_id)
        if requirement is None:
            fail(f"closeout evidence names unknown requirementId: {requirement_id}")
        measured = verify_evidence_data(
            repo,
            charter_path,
            evidence_path,
            expected_requirement=requirement,
            integration_head=integration_head,
            merge_revision=merge_revision,
            landing_base=base_revision,
        )
        measured_evidence_id = measured["evidenceId"]
        if requirement_id in seen_requirement_ids or measured_evidence_id in seen_evidence_ids:
            fail("closeout contains duplicate requirement/evidence IDs")
        seen_requirement_ids.add(requirement_id)
        seen_evidence_ids.add(measured_evidence_id)
    if seen_requirement_ids != set(requirements_by_id):
        fail("closeout evidence does not cover charter requirements exactly")

    synchronization = require_mapping(closeout.get("synchronization"), "closeout.synchronization")
    require_exact_keys(
        synchronization,
        {"mainRef", "mainRevision", "instructionPath", "instructionBlob", "worktreeCount"},
        "closeout.synchronization",
    )
    main_ref = require_string(synchronization.get("mainRef"), "synchronization.mainRef")
    instruction_path = validate_repo_path(
        require_string(synchronization.get("instructionPath"), "synchronization.instructionPath"),
        "synchronization.instructionPath",
    )
    final_admission = charter["workspaceAdmission"]
    if main_ref != final_admission["mainRef"]:
        fail("synchronization.mainRef must equal final charter workspaceAdmission.mainRef")
    if instruction_path != final_admission["instructionPath"]:
        fail(
            "synchronization.instructionPath must equal final charter "
            "workspaceAdmission.instructionPath"
        )
    if synchronization.get("instructionBlob") != final_admission["instructionBlob"]:
        fail(
            "synchronization.instructionBlob must equal final charter "
            "workspaceAdmission.instructionBlob"
        )
    measured_sync = verify_worktrees(repo, main_ref, instruction_path)
    if measured_sync["mainRevision"] != merge_revision:
        fail("synchronized mainRef does not resolve to mergeRevision")
    require_integer(synchronization.get("worktreeCount"), "synchronization.worktreeCount", minimum=1)
    for field in ("mainRevision", "instructionBlob", "worktreeCount"):
        if synchronization.get(field) != measured_sync[field]:
            fail(f"synchronization.{field} does not match remeasurement")
    synchronized_by_git_dir = {
        row["worktreeGitDir"].casefold(): row for row in measured_sync["worktrees"]
    }
    for admitted in charter["workspaceAdmission"]["workspaces"]:
        measured = synchronized_by_git_dir.get(admitted["worktreeGitDir"].casefold())
        if measured is None:
            fail("one or more admitted worktrees are absent at closeout")
        if measured["worktreeGitDir"] != admitted["worktreeGitDir"]:
            fail("an admitted worktree Git directory changed spelling at closeout")
        if measured.get("physicalIdentityDigest") != admitted["physicalIdentityDigest"]:
            fail("an admitted physical worktree identity changed at closeout")

    return {
        "ok": True,
        "waveId": charter["waveId"],
        "mode": "multi-writer",
        "charterDigest": charter_result["charterDigest"],
        "finalBaton": final_baton,
        "integrationHead": integration_head,
        "mergeRevision": merge_revision,
        "handoffCount": len(measured_handoffs),
        "evidenceCount": len(evidence_refs) + 1,
        "worktreeCount": measured_sync["worktreeCount"],
    }


def command_method_digest(args: argparse.Namespace) -> dict[str, Any]:
    measured = method_digest()
    if args.lock:
        lock_path = Path(args.lock).absolute()
        lock = require_mapping(load_json_file(lock_path, "method lock"), "method lock")
        repository = repo_root(Path(args.repo)) if args.repo else None
        if lock.get("recoverySource") is not None and repository is None:
            fail("method-digest requires --repo when the lock declares recoverySource")
        compare_method_lock(lock, measured, repo=repository)
        measured["lockVerified"] = True
    return measured


def command_validate_charter(args: argparse.Namespace) -> dict[str, Any]:
    repo = repo_root(Path(args.repo))
    charter_path = validate_no_reparse_chain(Path(args.charter), "charter")
    charter = require_mapping(load_json_file(charter_path, "charter"), "charter")
    return validate_charter_data(
        repo,
        charter,
        charter_path=charter_path,
        remeasure_admission=True,
    )


def command_snapshot_range(args: argparse.Namespace) -> dict[str, Any]:
    return snapshot_range(repo_root(Path(args.repo)), args.parent, args.tip)


def command_verify_handoff(args: argparse.Namespace) -> dict[str, Any]:
    return verify_handoff_data(
        repo_root(Path(args.repo)), Path(args.charter).absolute(), Path(args.handoff).absolute()
    )


def command_verify_evidence(args: argparse.Namespace) -> dict[str, Any]:
    return verify_evidence_data(
        repo_root(Path(args.repo)), Path(args.charter).absolute(), Path(args.evidence).absolute()
    )


def command_verify_closeout(args: argparse.Namespace) -> dict[str, Any]:
    return verify_closeout_data(repo_root(Path(args.repo)), Path(args.closeout).absolute())


def command_verify_worktrees(args: argparse.Namespace) -> dict[str, Any]:
    return verify_worktrees(repo_root(Path(args.repo)), args.main_ref, args.instruction_path)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    digest = commands.add_parser("method-digest", help="measure and optionally verify the method bundle")
    digest.add_argument("--lock", help="project method lock JSON")
    digest.add_argument("--repo", help="repository used to verify a pinned recoverySource")
    digest.add_argument(
        "--git-executable",
        help="absolute trusted Git executable; required when --repo is used",
    )
    digest.set_defaults(handler=command_method_digest)

    charter = commands.add_parser("validate-charter", help="validate an immutable wave charter")
    charter.add_argument("--repo", required=True)
    charter.add_argument("--charter", required=True)
    charter.add_argument("--git-executable", required=True)
    charter.set_defaults(handler=command_validate_charter)

    snapshot = commands.add_parser("snapshot-range", help="emit a deterministic committed range snapshot")
    snapshot.add_argument("--repo", required=True)
    snapshot.add_argument("--parent", required=True)
    snapshot.add_argument("--tip", required=True)
    snapshot.add_argument("--git-executable", required=True)
    snapshot.set_defaults(handler=command_snapshot_range)

    handoff = commands.add_parser("verify-handoff", help="verify prepared and replayed baton ranges")
    handoff.add_argument("--repo", required=True)
    handoff.add_argument("--charter", required=True)
    handoff.add_argument("--handoff", required=True)
    handoff.add_argument("--git-executable", required=True)
    handoff.set_defaults(handler=command_verify_handoff)

    evidence = commands.add_parser("verify-evidence", help="verify fixed-revision or external evidence")
    evidence.add_argument("--repo", required=True)
    evidence.add_argument("--charter", required=True)
    evidence.add_argument("--evidence", required=True)
    evidence.add_argument("--git-executable", required=True)
    evidence.set_defaults(handler=command_verify_evidence)

    closeout = commands.add_parser("verify-closeout", help="verify charter, baton, evidence, landing, and sync closure")
    closeout.add_argument("--repo", required=True)
    closeout.add_argument("--closeout", required=True)
    closeout.add_argument("--git-executable", required=True)
    closeout.set_defaults(handler=command_verify_closeout)

    worktrees = commands.add_parser("verify-worktrees", help="verify every registered worktree is synchronized")
    worktrees.add_argument("--repo", required=True)
    worktrees.add_argument("--main-ref", default="origin/main")
    worktrees.add_argument("--instruction-path", default="AGENTS.md")
    worktrees.add_argument("--git-executable", required=True)
    worktrees.set_defaults(handler=command_verify_worktrees)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        if sys.version_info < (3, 10):
            fail("wave_guard.py requires Python 3.10 or newer")
        if sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1:
            fail("wave_guard.py must be invoked with Python -I -B")
        args = parser().parse_args(argv)
        start_operation_budget()
        git_executable = getattr(args, "git_executable", None)
        if git_executable is not None:
            configure_git_executable(git_executable)
        elif getattr(args, "repo", None) is not None:
            fail("commands using --repo require --git-executable with a trusted absolute path")
        result = args.handler(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except GuardError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
