#!/usr/bin/env python3
"""One test the vendored bundle's own suite has but does not actually make.

`test_transient_foreign_path_is_owned_and_rejected` builds a handoff that touches a path the
cell does not own, and asserts only that *some* GuardError is raised. Its handoff also carries
`nextWork: ["stop on foreign path"]` while the charter's cell A carries `["handoff A"]`, and the
guard checks that first - so the error it observes is "handoff nextWork does not exactly equal
charter nextWork", and deleting the ownership check entirely leaves that test green. Measured:
an independent review disabled the ownership rejection and the test still passed 1/1.

The bundle is byte-pinned by `.agents/multi-lane-wave-method.lock.json` in every adopting
project, so its digest is not something this package may quietly change. The test that was
missing is written here instead: same fixture, reached through the bundle's own test module, and
with the other inputs made valid so that the ownership diagnostic is the one that has to appear.

    <python> -I -B cli/test_guard_supplement.py --git-executable <git>
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.stderr.write("test_guard_supplement.py requires Python 3.10 or newer\n")
    raise SystemExit(2)
if sys.flags.isolated != 1 or sys.flags.dont_write_bytecode != 1:
    sys.stderr.write("test_guard_supplement.py must be invoked with Python -I -B\n")
    raise SystemExit(2)

import argparse
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
SUITE = os.path.join(PACKAGE, "core", "method", "scripts", "test_wave_guard.py")


def load_bundle_tests(git_exe: str):
    """Import the bundle's test module, which brings its fixture and wave_guard with it."""
    os.environ["WAVE_GUARD_TEST_GIT_EXECUTABLE"] = git_exe
    spec = importlib.util.spec_from_file_location("bundle_tests", SUITE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def foreign_path_is_named(module) -> tuple[bool, str]:
    """The bundle's own scenario, with everything else valid.

    Only the ownership rule can refuse this handoff, so the error it raises is the one the
    bundle's test meant to require.
    """
    case = module.WaveGuardTests("test_transient_foreign_path_is_owned_and_rejected")
    case.setUp()
    try:
        charter = case.charter(module.wave_guard.method_digest()["canonicalDigest"])
        result = module.wave_guard.validate_charter_data(case.repo, charter)
        charter_path = case.dump("charter.json", charter)
        module.git(case.repo, "checkout", "-b", "transient", case.base)
        module.write(case.repo / "cell-a.txt", "owned\n")
        module.write(case.repo / "foreign.txt", "foreign\n")
        module.commit(case.repo, "touch owned and foreign")
        (case.repo / "foreign.txt").unlink()
        tip = module.commit(case.repo, "restore foreign path")
        snapshot = module.wave_guard.snapshot_range(case.repo, case.base, tip)
        case.dump("prepared-transient.json", snapshot)
        case.dump("integrated-transient.json", snapshot)

        cell = next(c for c in charter["cells"] if c["cellId"] == "A")
        handoff = {
            "schemaVersion": 2,
            "waveId": charter["waveId"],
            "charterDigest": result["charterDigest"],
            "cellId": "A",
            "workspaceId": "workspace-a",
            "sequence": 1,
            "fromActor": "actor-a",
            "toActor": "actor-b",
            "incomingBaton": case.base,
            "outgoingBaton": tip,
            "preparedSnapshot": "prepared-transient.json",
            "integratedSnapshot": "integrated-transient.json",
            "previousHandoff": None,
            "focusedVerification": [
                {"command": "test-a", "revision": tip, "verdict": "PASS"}
            ],
            "workingTreeClean": True,
            "conflictResolution": None,
            # The bundle's own test writes a made-up string here, and the guard compares this
            # before it looks at any path. That comparison is what its assertRaises was
            # catching.
            "nextWork": cell["nextWork"],
        }
        handoff_path = case.dump("handoff-transient.json", handoff)
        try:
            module.wave_guard.verify_handoff_data(case.repo, charter_path, handoff_path)
        except module.wave_guard.GuardError as error:
            message = str(error)
            # The diagnostic by name, not just any error that happens to print the path. The
            # bundle's own test accepted any GuardError, which is how the nextWork comparison
            # came to stand in for this one.
            named = message.startswith("handoff path set mismatch") and "foreign.txt" in message
            return named, message[:160]
        return False, "no GuardError was raised at all"
    finally:
        case.tearDown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-executable", required=True)
    args = parser.parse_args()
    if not os.path.isabs(args.git_executable) or not os.path.isfile(args.git_executable):
        print(json.dumps({"ok": None, "measured": False,
                          "reason": "--git-executable must be an absolute regular file"},
                         indent=2))
        return 2

    results = []
    try:
        module = load_bundle_tests(args.git_executable)
        named, detail = foreign_path_is_named(module)
    except Exception as error:  # noqa: BLE001 - a crash is a question that was not answered
        print(json.dumps({"ok": None, "measured": False,
                          "reason": f"unexpected {type(error).__name__}: {error}"}, indent=2))
        return 2
    results.append({
        "case": "a handoff touching a path the cell does not own is refused for that reason",
        "pass": named,
        "detail": detail,
    })
    failed = [r for r in results if not r["pass"]]
    print(json.dumps({"ok": not failed, "checked": results}, indent=2, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
