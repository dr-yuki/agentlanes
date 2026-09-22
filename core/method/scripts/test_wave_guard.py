#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).with_name("wave_guard.py")
_TEST_GIT_VALUE = os.environ.get("WAVE_GUARD_TEST_GIT_EXECUTABLE")
if not _TEST_GIT_VALUE or not Path(_TEST_GIT_VALUE).is_absolute():
    raise RuntimeError(
        "test suite requires WAVE_GUARD_TEST_GIT_EXECUTABLE as an absolute trusted path"
    )
TEST_GIT = str(Path(_TEST_GIT_VALUE))
SPEC = importlib.util.spec_from_file_location("wave_guard", SCRIPT)
assert SPEC and SPEC.loader
wave_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wave_guard)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [TEST_GIT, "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode().strip()


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def commit_tree(repo: Path, tree: str, parents: list[str], message: str) -> str:
    command = [TEST_GIT, "-C", str(repo), "commit-tree", tree]
    for parent in parents:
        command.extend(["-p", parent])
    command.extend(["-m", message])
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.decode().strip()


class WaveGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        wave_guard.start_operation_budget()
        self.git_executable = Path(TEST_GIT)
        wave_guard.configure_git_executable(self.git_executable)
        self.temp = tempfile.TemporaryDirectory(prefix="wave-guard-")
        self.repo = Path(self.temp.name) / "repo"
        self.proof = Path(self.temp.name) / "proof"
        self.repo.mkdir()
        self.proof.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.email", "wave-guard@example.invalid")
        git(self.repo, "config", "user.name", "Wave Guard")
        git(self.repo, "config", "core.autocrlf", "false")
        write(self.repo / "README.md", "base\n")
        write(self.repo / "AGENTS.md", "instructions\n")
        write(self.repo / "docs" / "instruction.txt", "not an instruction blob\n")
        self.base = commit(self.repo, "base")
        self.base_tree = git(self.repo, "rev-parse", "HEAD^{tree}")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def charter(self, digest: str, *, mode: str = "multi-writer") -> dict:
        cells = [
            {
                "cellId": "A",
                "workspaceId": "workspace-a",
                "actor": "actor-a",
                "dependsOn": [],
                "writablePaths": ["cell-a.txt"] if mode == "multi-writer" else [],
                "semanticSeams": ["seam-a"],
                "focusedChecks": ["test-a"],
                "nextWork": ["handoff A"],
                "requiredAttestationSource": "unit-test" if mode == "evidence-fanout" else None,
            },
            {
                "cellId": "B",
                "workspaceId": "workspace-b",
                "actor": "actor-b",
                "dependsOn": ["A"],
                "writablePaths": ["cell-b.txt"] if mode == "multi-writer" else [],
                "semanticSeams": ["seam-b"],
                "focusedChecks": ["test-b"],
                "nextWork": ["handoff B"],
                "requiredAttestationSource": "unit-test" if mode == "evidence-fanout" else None,
            },
        ]
        admitted_workspaces = [
            {
                "workspaceId": "workspace-a",
                "actor": "actor-a",
                "worktreeGitDir": ".git",
                "physicalIdentityDigest": wave_guard.physical_identity_digest(self.repo),
                "headRevision": self.base,
                "ahead": 0,
                "behind": 0,
                "clean": True,
            },
            {
                "workspaceId": "workspace-b",
                "actor": "actor-b",
                "worktreeGitDir": ".git/worktrees/workspace-b",
                "physicalIdentityDigest": "sha256:" + "b" * 64,
                "headRevision": self.base,
                "ahead": 0,
                "behind": 0,
                "clean": True,
            },
        ]
        if mode == "multi-writer":
            admitted_workspaces.append(
                {
                    "workspaceId": "workspace-owner",
                    "actor": "owner",
                    "worktreeGitDir": ".git/worktrees/workspace-owner",
                    "physicalIdentityDigest": "sha256:" + "c" * 64,
                    "headRevision": self.base,
                    "ahead": 0,
                    "behind": 0,
                    "clean": True,
                }
            )
        return {
            "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "mode": mode,
            "method": {
                "schemaVersion": 2,
                "methodId": "multi-lane-wave-engineering",
                "methodVersion": "2.0.0",
                "digestAlgorithm": "sha256-path-nul-bytes-nul-v1",
                "canonicalDigest": digest,
                "provenanceStatus": "UNVERIFIED_LOCAL",
                "sourceRevision": None,
                "provenanceAuthority": None,
                "recoverySource": None,
                "recoveryDigest": None,
            },
            "previousCharter": None,
            "baselineCommit": self.base,
            "baselineTree": self.base_tree,
            "programmeConductor": "conductor",
            "waveOwner": "owner",
            "workspaceAdmission": {
                "mainRef": "HEAD",
                "instructionPath": "AGENTS.md",
                "instructionBlob": git(self.repo, "rev-parse", f"{self.base}:AGENTS.md"),
                "workspaces": admitted_workspaces,
            },
            "objective": "exercise deterministic handoff",
            "inScope": ["two isolated cells"],
            "outOfScope": ["external mutation"],
            "failureDomain": "one test head",
            "cells": cells,
            "ownerOnlyPaths": ["owner.txt"] if mode == "multi-writer" else [],
            "authorityCeilings": ["no external mutation"],
            "transportLifecycle": "linear replay",
            "sideEffectClass": "repository only",
            "rollback": "revert final integration",
            "ownerIntegration": (
                {
                    "requiredLocalChecks": [
                        {"checkId": "local-integration", "command": "test-local"}
                    ],
                    "independentReview": {
                        "requirementId": "independent-review",
                        "requiredAttestationSource": "unit-test",
                        "requiredCheckIds": ["review-check"],
                    },
                }
                if mode == "multi-writer"
                else None
            ),
            "externalEvidence": (
                [
                    {
                        "requirementId": "pr-head",
                        "stage": "pr",
                        "subjectRelation": "synthetic-two-parent",
                        "requiredAttestationSource": "unit-test",
                        "requiredCheckIds": ["pr-check"],
                        "requiredArtifacts": [],
                    },
                    {
                        "requirementId": "post-main",
                        "stage": "post-merge",
                        "subjectRelation": "merge-exact",
                        "requiredAttestationSource": "unit-test",
                        "requiredCheckIds": ["main-check"],
                        "requiredArtifacts": [],
                    },
                ]
                if mode == "multi-writer"
                else []
            ),
            "stopConditions": ["scope mismatch"],
            "acceptance": ["handoff verifies"],
        }

    def dump(self, name: str, value: dict) -> Path:
        path = self.proof / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def evidence(
        self,
        charter: dict,
        charter_digest: str,
        *,
        evidence_id: str,
        requirement_id: str | None,
        stage: str,
        relation: str,
        revision: str,
        head_revision: str,
        base_revision: str | None,
        check_id: str,
        cell_id: str | None = None,
        artifacts: list[dict] | None = None,
    ) -> dict:
        cell = next((item for item in charter["cells"] if item["cellId"] == cell_id), None)
        return {
            "schemaVersion": 2,
            "waveId": charter["waveId"],
            "charterDigest": charter_digest,
            "evidenceId": evidence_id,
            "requirementId": requirement_id,
            "stage": stage,
            "cellId": cell_id,
            "workspaceId": cell["workspaceId"] if cell else None,
            "actor": cell["actor"] if cell else charter["waveOwner"],
            "attestationSource": "unit-test",
            "subject": {
                "relation": relation,
                "revision": revision,
                "tree": git(self.repo, "rev-parse", f"{revision}^{{tree}}"),
                "parents": git(self.repo, "show", "-s", "--format=%P", revision).split(),
                "baseRevision": base_revision,
                "headRevision": head_revision,
            },
            "checks": [{"checkId": check_id, "status": "PASS", "revision": revision}],
            "artifacts": artifacts or [],
            "verdict": "PASS",
        }

    def test_method_digest_and_lock(self) -> None:
        measured = wave_guard.method_digest()
        wave_guard.compare_method_lock(
            {
                "schemaVersion": measured["schemaVersion"],
                "methodId": measured["methodId"],
                "methodVersion": measured["methodVersion"],
                "digestAlgorithm": measured["digestAlgorithm"],
                "canonicalDigest": measured["canonicalDigest"],
                "provenanceStatus": "UNVERIFIED_LOCAL",
                "sourceRevision": None,
                "provenanceAuthority": None,
                "recoverySource": None,
                "recoveryDigest": None,
            },
            measured,
        )
        bad = {
            "schemaVersion": measured["schemaVersion"],
            "methodId": measured["methodId"],
            "methodVersion": measured["methodVersion"],
            "digestAlgorithm": "wrong",
            "canonicalDigest": measured["canonicalDigest"],
            "provenanceStatus": "UNVERIFIED_LOCAL",
            "sourceRevision": None,
            "provenanceAuthority": None,
            "recoverySource": None,
            "recoveryDigest": None,
        }
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.compare_method_lock(bad, measured)
        verified_provenance = {
            **bad,
            "digestAlgorithm": measured["digestAlgorithm"],
            "provenanceStatus": "VERIFIED",
            "sourceRevision": "a" * 40,
            "provenanceAuthority": "publisher.example/method-release",
        }
        wave_guard.compare_method_lock(verified_provenance, measured)
        for mutation in (
            {"provenanceStatus": "VERIFIED", "sourceRevision": "a" * 40, "provenanceAuthority": None},
            {"provenanceStatus": "UNVERIFIED_LOCAL", "sourceRevision": "a" * 40, "provenanceAuthority": None},
            {"provenanceStatus": "VERIFIED", "sourceRevision": "not-a-full-sha", "provenanceAuthority": "publisher"},
            {"provenanceStatus": "VERIFIED", "sourceRevision": "a" * 40, "provenanceAuthority": "TBD"},
            {"provenanceStatus": "VERIFIED", "sourceRevision": "a" * 40, "provenanceAuthority": "same-as-before"},
            {"provenanceStatus": "VERIFIED", "sourceRevision": "a" * 40, "provenanceAuthority": "<publisher>"},
        ):
            invalid = {**verified_provenance, **mutation}
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.compare_method_lock(invalid, measured)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.compare_method_lock({**bad, "installLocation": "somewhere"}, measured)

        copied = Path(self.temp.name) / "copied-skill"
        shutil.copytree(wave_guard.skill_root(), copied)
        (copied / "scripts" / "json.py").write_text("raise RuntimeError('shadow')\n", encoding="utf-8")
        with mock.patch.object(wave_guard, "skill_root", return_value=copied):
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.method_digest()

        wrong_version = Path(self.temp.name) / "wrong-version-skill"
        shutil.copytree(wave_guard.skill_root(), wrong_version)
        method = json.loads((wrong_version / "method.json").read_text(encoding="utf-8"))
        method["methodVersion"] = "2.0.1"
        (wrong_version / "method.json").write_text(json.dumps(method), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.method_digest_at(wrong_version)

    def test_distributed_charter_template_requires_complete_materialization(self) -> None:
        template_path = (
            wave_guard.skill_root() / "assets" / "templates" / "wave-charter.json"
        )
        template = json.loads(template_path.read_text(encoding="utf-8"))
        template["method"]["canonicalDigest"] = wave_guard.method_digest()["canonicalDigest"]
        template["baselineCommit"] = self.base
        template["baselineTree"] = self.base_tree
        template["workspaceAdmission"]["instructionBlob"] = git(
            self.repo, "rev-parse", f"{self.base}:AGENTS.md"
        )
        for row in template["workspaceAdmission"]["workspaces"]:
            row["headRevision"] = self.base
        with self.assertRaisesRegex(
            wave_guard.GuardError, "unresolved distributed-template token REPLACE"
        ):
            wave_guard.validate_charter_data(self.repo, template)
        with self.assertRaisesRegex(
            wave_guard.GuardError, "unresolved distributed-template token REPLACE"
        ):
            wave_guard.reject_unresolved_template_tokens(
                {"authority": "replace-provider"}, "lowercase template"
            )

        materialized = self.charter(wave_guard.method_digest()["canonicalDigest"])
        materialized["objective"] = "a concrete replacement strategy"
        self.assertEqual(wave_guard.validate_charter_data(self.repo, materialized)["cellCount"], 2)

    def test_replacement_charter_changes_only_baseline_and_predecessor_digest(self) -> None:
        original = self.charter(wave_guard.method_digest()["canonicalDigest"])
        original["ownerIntegration"]["requiredLocalChecks"].append(
            {
                "checkId": "baseline-diff",
                "command": f"git diff --check {self.base}...HEAD",
            }
        )
        advanced = commit_tree(self.repo, self.base_tree, [self.base], "advanced baseline")
        replacement = json.loads(json.dumps(original))
        replacement["previousCharter"] = {
            "path": "previous.json",
            "digest": wave_guard.charter_digest(original),
        }
        replacement["baselineCommit"] = advanced
        replacement["baselineTree"] = self.base_tree
        replacement["ownerIntegration"]["requiredLocalChecks"][-1]["command"] = (
            f"git diff --check {advanced}...HEAD"
        )
        for row in replacement["workspaceAdmission"]["workspaces"]:
            row["headRevision"] = advanced
        wave_guard.validate_replacement_charter(self.repo, original, replacement)
        mutations = (
            ("objective", "changed objective"),
            ("waveOwner", "changed owner"),
        )
        for field, value in mutations:
            changed = json.loads(json.dumps(replacement))
            changed[field] = value
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.validate_replacement_charter(self.repo, original, changed)
        changed = json.loads(json.dumps(replacement))
        changed["cells"][0]["writablePaths"] = ["changed-path.txt"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_replacement_charter(self.repo, original, changed)
        changed = json.loads(json.dumps(replacement))
        changed["externalEvidence"][0]["requiredCheckIds"] = ["changed-check"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_replacement_charter(self.repo, original, changed)
        changed = json.loads(json.dumps(replacement))
        changed["ownerIntegration"]["requiredLocalChecks"][-1]["command"] = (
            "git diff --check HEAD^...HEAD"
        )
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_replacement_charter(self.repo, original, changed)
        moved_checkout = json.loads(json.dumps(replacement))
        moved_checkout["workspaceAdmission"]["workspaces"][0]["physicalIdentityDigest"] = (
            "sha256:" + "0" * 64
        )
        with self.assertRaisesRegex(wave_guard.GuardError, "workspace IDs, actors, Git identities"):
            wave_guard.validate_replacement_charter(self.repo, original, moved_checkout)

        unchanged_baseline = json.loads(json.dumps(original))
        unchanged_baseline["previousCharter"] = replacement["previousCharter"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_replacement_charter(
                self.repo, original, unchanged_baseline
            )
        sibling = commit_tree(self.repo, self.base_tree, [self.base], "sibling baseline")
        sibling_replacement = json.loads(json.dumps(replacement))
        sibling_replacement["baselineCommit"] = sibling
        for row in sibling_replacement["workspaceAdmission"]["workspaces"]:
            row["headRevision"] = sibling
        previous_on_other_child = json.loads(json.dumps(original))
        previous_on_other_child["baselineCommit"] = advanced
        previous_on_other_child["baselineTree"] = self.base_tree
        for row in previous_on_other_child["workspaceAdmission"]["workspaces"]:
            row["headRevision"] = advanced
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_replacement_charter(
                self.repo, previous_on_other_child, sibling_replacement
            )

    def test_handoff_binds_author_replay_and_exact_physical_checkout(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        charter_result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("charter.json", charter)

        git(self.repo, "checkout", "-b", "prepared")
        write(self.repo / "cell-a.txt", "payload\n")
        prepared_tip = commit(self.repo, "cell A")
        prepared = wave_guard.snapshot_range(self.repo, self.base, prepared_tip)

        incoming = commit_tree(self.repo, self.base_tree, [self.base], "tree-neutral charter")
        git(self.repo, "branch", "incoming", incoming)
        wave_guard.validate_first_incoming_baton(
            self.repo, self.base, self.base_tree, incoming
        )
        git(self.repo, "checkout", "-b", "bad-incoming", self.base)
        write(self.repo / "prior.txt", "unowned baton change\n")
        bad_incoming = commit(self.repo, "unowned baton change")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_first_incoming_baton(
                self.repo, self.base, self.base_tree, bad_incoming
            )
        git(self.repo, "checkout", "prepared")
        git(self.repo, "rebase", "--onto", incoming, self.base, "prepared")
        outgoing = git(self.repo, "rev-parse", "HEAD")
        integrated = wave_guard.snapshot_range(self.repo, incoming, outgoing)

        self.dump("prepared.json", prepared)
        integrated_path = self.dump("integrated.json", integrated)
        handoff = {
            "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "charterDigest": charter_result["charterDigest"],
            "cellId": "A",
            "workspaceId": "workspace-a",
            "sequence": 1,
            "fromActor": "actor-a",
            "toActor": "actor-b",
            "incomingBaton": incoming,
            "outgoingBaton": outgoing,
            "preparedSnapshot": "prepared.json",
            "integratedSnapshot": "integrated.json",
            "previousHandoff": None,
            "focusedVerification": [{"command": "test-a", "revision": outgoing, "verdict": "PASS"}],
            "workingTreeClean": True,
            "conflictResolution": None,
            "nextWork": ["handoff A"],
        }
        handoff_path = self.dump("handoff.json", handoff)
        self.assertTrue(wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)["ok"])

        wrong_workspace = Path(self.temp.name) / "wrong-handoff-workspace"
        git(self.repo, "worktree", "add", "--detach", str(wrong_workspace), outgoing)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_handoff_data(
                wrong_workspace, charter_path, handoff_path
            )

        copied_pointer = Path(self.temp.name) / "copied-git-pointer"
        copied_pointer.mkdir()
        write(copied_pointer / ".git", f"gitdir: {(self.repo / '.git').as_posix()}\n")
        with self.assertRaisesRegex(wave_guard.GuardError, "Git-registered physical worktree"):
            wave_guard.verify_handoff_data(copied_pointer, charter_path, handoff_path)

        handoff["incomingBaton"] = "incoming"
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
        with self.assertRaisesRegex(wave_guard.GuardError, "full canonical commit IDs"):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)
        handoff["incomingBaton"] = incoming
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        for replacement_checks in (
            [],
            [{"command": "not-the-chartered-check", "revision": outgoing, "verdict": "PASS"}],
            [
                {"command": "test-a", "revision": outgoing, "verdict": "PASS"},
                {"command": "test-a", "revision": outgoing, "verdict": "PASS"},
            ],
        ):
            handoff["focusedVerification"] = replacement_checks
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)
        handoff["focusedVerification"] = [
            {"command": "test-a", "revision": outgoing, "verdict": "PASS"}
        ]
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        handoff["nextWork"] = ["different next work"]
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
        with self.assertRaisesRegex(wave_guard.GuardError, "exactly equal charter nextWork"):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)
        handoff["nextWork"] = ["handoff A"]
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        git(self.repo, "checkout", "incoming")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)
        git(self.repo, "checkout", "prepared")
        write(self.repo / "dirty.tmp", "dirty\n")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)
        (self.repo / "dirty.tmp").unlink()

        integrated["paths"][0]["newBlobSha256"] = "sha256:" + "0" * 64
        integrated_path.write_text(json.dumps(integrated), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)

    def test_charter_rejects_overlap_order_and_windows_aliases(self) -> None:
        digest = wave_guard.method_digest()["canonicalDigest"]
        charter = self.charter(digest)
        charter["cells"][0]["writablePaths"] = ["folder"]
        charter["cells"][1]["writablePaths"] = ["folder/child.txt"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, charter)

        charter = self.charter(digest)
        charter["cells"][0]["dependsOn"] = ["B"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, charter)

        for field, duplicates in (
            ("dependsOn", ["A", "A"]),
            ("semanticSeams", ["seam", "seam"]),
            ("nextWork", ["next", "next"]),
        ):
            charter = self.charter(digest)
            charter["cells"][1][field] = duplicates
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.validate_charter_data(self.repo, charter)

        for authority_field in ("programmeConductor", "waveOwner"):
            charter = self.charter(digest)
            charter[authority_field] = "TBD"
            with self.assertRaisesRegex(wave_guard.GuardError, "concrete authority"):
                wave_guard.validate_charter_data(self.repo, charter)

        placeholder_actor = self.charter(digest)
        placeholder_actor["cells"][0]["actor"] = "unknown"
        placeholder_actor["workspaceAdmission"]["workspaces"][0]["actor"] = "unknown"
        with self.assertRaisesRegex(wave_guard.GuardError, "concrete authority"):
            wave_guard.validate_charter_data(self.repo, placeholder_actor)

        disguised_duplicate = self.charter(digest)
        disguised_duplicate["cells"][1]["actor"] = "a-c-t-o-r-a"
        disguised_duplicate["workspaceAdmission"]["workspaces"][1]["actor"] = "a-c-t-o-r-a"
        with self.assertRaisesRegex(wave_guard.GuardError, "multiple workspaceId"):
            wave_guard.validate_charter_data(self.repo, disguised_duplicate)

        reserved_replacement_command = self.charter(digest)
        reserved_replacement_command["ownerIntegration"]["requiredLocalChecks"][0][
            "command"
        ] = "git diff --check <charter-baseline>...HEAD"
        with self.assertRaisesRegex(wave_guard.GuardError, "reserves"):
            wave_guard.validate_charter_data(self.repo, reserved_replacement_command)

        missing_owner = self.charter(digest)
        missing_owner["workspaceAdmission"]["workspaces"].pop()
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, missing_owner)

        fanout_extra_owner = self.charter(digest, mode="evidence-fanout")
        fanout_extra_owner["workspaceAdmission"]["workspaces"].append(
            {
                "workspaceId": "workspace-owner",
                "actor": "owner",
                "worktreeGitDir": ".git/worktrees/workspace-owner",
                "physicalIdentityDigest": "sha256:" + "d" * 64,
                "headRevision": self.base,
                "ahead": 0,
                "behind": 0,
                "clean": True,
            }
        )
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, fanout_extra_owner)

        for bad_path in (
            ".",
            "NUL.txt",
            "folder/name. ",
            "folder:alias/file.txt",
            'folder/name"quote.txt',
            "folder/name<left.txt",
            "folder/name>right.txt",
            "folder/name|pipe.txt",
            "folder/e\u0301.txt",
        ):
            charter = self.charter(digest)
            charter["cells"][1]["writablePaths"] = [bad_path]
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.validate_charter_data(self.repo, charter)

        for bad_path in ("straße.txt", "bad\ud800.txt"):
            charter = self.charter(digest)
            charter["cells"][1]["writablePaths"] = [bad_path]
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.validate_charter_data(self.repo, charter)

        directory_instruction = self.charter(digest)
        directory_instruction["workspaceAdmission"]["instructionPath"] = "docs"
        directory_instruction["workspaceAdmission"]["instructionBlob"] = git(
            self.repo, "rev-parse", f"{self.base}:docs"
        )
        with self.assertRaisesRegex(wave_guard.GuardError, "must resolve to a Git blob"):
            wave_guard.validate_charter_data(self.repo, directory_instruction)

        for field_path, hostile in (
            (("ownerIntegration", "independentReview", "requiredAttestationSource"), "TBD"),
            (("ownerIntegration", "independentReview", "requiredAttestationSource"), "..."),
            (("externalEvidence", 0, "requiredAttestationSource"), "same-as-before"),
        ):
            hostile_charter = self.charter(digest)
            cursor = hostile_charter
            for segment in field_path[:-1]:
                cursor = cursor[segment]
            cursor[field_path[-1]] = hostile
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.validate_charter_data(self.repo, hostile_charter)

        fanout_placeholder = self.charter(digest, mode="evidence-fanout")
        fanout_placeholder["cells"][0]["requiredAttestationSource"] = "placeholder"
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, fanout_placeholder)

        punctuation_actor = self.charter(digest)
        punctuation_actor["cells"][0]["actor"] = "..."
        punctuation_actor["workspaceAdmission"]["workspaces"][0]["actor"] = "..."
        with self.assertRaisesRegex(wave_guard.GuardError, "alphanumeric character"):
            wave_guard.validate_charter_data(self.repo, punctuation_actor)

    def test_json_surrogate_validation_is_controlled_and_utf8_safe(self) -> None:
        hostile = self.proof / "unpaired.json"
        hostile.write_bytes(b'{"value":"\\ud800"}')
        with self.assertRaisesRegex(wave_guard.GuardError, "unpaired Unicode surrogate"):
            wave_guard.load_json_file(hostile, "surrogate probe")

        valid = self.proof / "paired.json"
        valid.write_bytes(b'{"value":"\\ud83d\\ude00"}')
        self.assertEqual(wave_guard.load_json_file(valid, "paired probe"), {"value": "\U0001f600"})

    def test_transient_foreign_path_is_owned_and_rejected(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        charter_result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("charter.json", charter)
        git(self.repo, "checkout", "-b", "transient", self.base)
        write(self.repo / "cell-a.txt", "owned\n")
        write(self.repo / "foreign.txt", "foreign\n")
        commit(self.repo, "touch owned and foreign")
        (self.repo / "foreign.txt").unlink()
        tip = commit(self.repo, "restore foreign path")
        snapshot = wave_guard.snapshot_range(self.repo, self.base, tip)
        self.assertEqual({entry["path"] for entry in snapshot["paths"]}, {"cell-a.txt"})
        self.assertIn("foreign.txt", wave_guard.snapshot_owned_paths(snapshot))
        self.dump("prepared-transient.json", snapshot)
        self.dump("integrated-transient.json", snapshot)
        handoff = {
            "schemaVersion": 2,
            "waveId": charter["waveId"],
            "charterDigest": charter_result["charterDigest"],
            "cellId": "A",
            "workspaceId": "workspace-a",
            "sequence": 1,
            "fromActor": "actor-a",
            "toActor": "actor-b",
            "incomingBaton": self.base,
            "outgoingBaton": tip,
            "preparedSnapshot": "prepared-transient.json",
            "integratedSnapshot": "integrated-transient.json",
            "previousHandoff": None,
            "focusedVerification": [
                {"command": "test-a", "revision": tip, "verdict": "PASS"}
            ],
            "workingTreeClean": True,
            "conflictResolution": None,
            "nextWork": ["stop on foreign path"],
        }
        handoff_path = self.dump("handoff-transient.json", handoff)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_handoff_data(self.repo, charter_path, handoff_path)

    def test_snapshot_reference_rejects_traversal_and_symlink(self) -> None:
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.resolve_regular_json(self.proof, "../outside.json", "probe")
        target = self.proof / "target.json"
        target.write_text("{}", encoding="utf-8")
        link = self.proof / "link.json"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            original_lstat = Path.lstat

            def lstat_with_simulated_link(path: Path):
                if path == link:
                    return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                return original_lstat(path)

            with mock.patch.object(Path, "lstat", lstat_with_simulated_link):
                with self.assertRaises(wave_guard.GuardError):
                    wave_guard.resolve_regular_json(self.proof, "link.json", "probe")
        else:
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.resolve_regular_json(self.proof, "link.json", "probe")

    def test_top_level_proof_parent_link_and_toc_tou_are_rejected(self) -> None:
        real_parent = Path(self.temp.name) / "real-proof"
        real_parent.mkdir()
        proof_file = real_parent / "proof.json"
        proof_file.write_text("{}", encoding="utf-8")
        linked_parent = Path(self.temp.name) / "linked-proof"
        try:
            os.symlink(real_parent, linked_parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            original_lstat = Path.lstat

            def lstat_with_parent_link(path: Path):
                if path == linked_parent:
                    return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                return original_lstat(path)

            with mock.patch.object(Path, "lstat", lstat_with_parent_link):
                with self.assertRaises(wave_guard.GuardError):
                    wave_guard.load_json_file(linked_parent / "proof.json", "top-level proof")
        else:
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.load_json_file(linked_parent / "proof.json", "top-level proof")

        reparse_parent = Path(self.temp.name) / "reparse-proof"
        reparse_parent.mkdir()
        original_lstat = Path.lstat

        def lstat_with_reparse(path: Path):
            if path == reparse_parent:
                return mock.Mock(
                    st_mode=stat.S_IFDIR,
                    st_file_attributes=wave_guard.FILE_ATTRIBUTE_REPARSE_POINT,
                )
            return original_lstat(path)

        with mock.patch.object(Path, "lstat", lstat_with_reparse):
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.load_json_file(reparse_parent / "proof.json", "reparse proof")

        original_fstat = os.fstat
        calls = 0

        def changed_fstat(descriptor: int):
            nonlocal calls
            calls += 1
            measured = original_fstat(descriptor)
            if calls == 2:
                values = list(measured)
                values[6] = measured.st_size + 1
                return os.stat_result(values)
            return measured

        with mock.patch.object(os, "fstat", changed_fstat):
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.load_json_file(proof_file, "racing proof")

        parent_calls = 0

        def changed_parent_identity(path: Path):
            nonlocal parent_calls
            measured = original_lstat(path)
            if path == real_parent:
                parent_calls += 1
                if parent_calls == 2:
                    return mock.Mock(
                        st_dev=measured.st_dev,
                        st_ino=measured.st_ino + 1,
                        st_mode=measured.st_mode,
                        st_size=measured.st_size,
                        st_mtime_ns=measured.st_mtime_ns,
                        st_file_attributes=0,
                    )
            return measured

        with mock.patch.object(Path, "lstat", changed_parent_identity):
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.load_json_file(proof_file, "parent-racing proof")

    def test_hostile_git_environment_is_removed_from_every_guard_call(self) -> None:
        hostile = {
            "GIT_DIR": str(Path(self.temp.name) / "attacker.git"),
            "GIT_WORK_TREE": str(Path(self.temp.name) / "attacker-tree"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": str(Path(self.temp.name) / "hooks"),
            "GIT_OBJECT_DIRECTORY": str(Path(self.temp.name) / "objects"),
        }
        with mock.patch.dict(os.environ, hostile, clear=False):
            environment = wave_guard.git_environment()
            for key in hostile:
                self.assertNotIn(key, environment)
            self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
            self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
            command = wave_guard.git_command(self.repo, ["rev-parse", "HEAD"])
            self.assertEqual(Path(command[0]), self.git_executable)
            self.assertIn(f"safe.directory={self.repo.resolve()}", command)
            self.assertEqual(wave_guard.resolve_commit(self.repo, "HEAD", "head"), self.base)
        replacement = commit_tree(self.repo, self.base_tree, [], "replacement-visible")
        git(self.repo, "replace", self.base, replacement)
        try:
            self.assertEqual(git(self.repo, "show", "-s", "--format=%s", self.base), "replacement-visible")
            self.assertEqual(
                wave_guard.run_git(self.repo, ["show", "-s", "--format=%s", self.base]).decode().strip(),
                "base",
            )
        finally:
            git(self.repo, "replace", "-d", self.base)

        fsmonitor_sentinel = Path(self.temp.name) / "fsmonitor-invoked.txt"
        if os.name == "nt":
            fsmonitor_hook = Path(self.temp.name) / "fsmonitor-probe.cmd"
            fsmonitor_hook.write_text(
                f"@echo off\r\necho invoked>\"{fsmonitor_sentinel}\"\r\nexit /b 0\r\n",
                encoding="utf-8",
            )
        else:
            fsmonitor_hook = Path(self.temp.name) / "fsmonitor-probe.sh"
            fsmonitor_hook.write_text(
                f"#!/bin/sh\nprintf invoked > {str(fsmonitor_sentinel)!r}\n",
                encoding="utf-8",
            )
            fsmonitor_hook.chmod(0o700)
        git(self.repo, "config", "core.fsmonitor", str(fsmonitor_hook))
        try:
            wave_guard.ensure_clean(self.repo, "fsmonitor isolation probe")
            self.assertFalse(fsmonitor_sentinel.exists(), "guard Git must disable repository-local fsmonitor hooks")
        finally:
            git(self.repo, "config", "--unset-all", "core.fsmonitor")

    def test_git_execution_surfaces_and_submodule_hiding_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(wave_guard.GuardError, "absolute trusted path"):
            wave_guard.configure_git_executable("git")
        wave_guard.configure_git_executable(self.git_executable)

        root_git_sentinel = Path(self.temp.name) / "repo-git-invoked.txt"
        if os.name == "nt":
            fake_git = self.repo / "git.cmd"
            fake_git.write_text(
                f"@echo off\r\necho invoked>\"{root_git_sentinel}\"\r\nexit /b 99\r\n",
                encoding="utf-8",
            )
        else:
            fake_git = self.repo / "git"
            fake_git.write_text(
                f"#!/bin/sh\nprintf invoked > {str(root_git_sentinel)!r}\nexit 99\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o700)
        original_cwd = Path.cwd()
        try:
            os.chdir(self.repo)
            self.assertEqual(wave_guard.resolve_commit(self.repo, "HEAD", "HEAD"), self.base)
        finally:
            os.chdir(original_cwd)
        self.assertFalse(root_git_sentinel.exists())

        write(self.repo / ".gitattributes", "*.filtered filter=evil\n*.probe diff=evil\n")
        write(self.repo / "payload.filtered", "clean-filter probe\n")
        write(self.repo / "payload.probe", "textconv probe\n")
        attributes_tip = commit(self.repo, "attributes probes")
        command_sentinel = Path(self.temp.name) / "git-driver-invoked.txt"
        if os.name == "nt":
            driver_command = f'cmd /c echo invoked>"{command_sentinel}"'
        else:
            driver_command = f"sh -c 'printf invoked > {command_sentinel}'"
        git(self.repo, "config", "filter.evil.clean", driver_command)
        with self.assertRaisesRegex(wave_guard.GuardError, "executable filter/diff drivers"):
            wave_guard.ensure_clean(self.repo, "filter probe")
        self.assertFalse(command_sentinel.exists())
        git(self.repo, "config", "--unset-all", "filter.evil.clean")
        git(self.repo, "config", "diff.evil.textconv", driver_command)
        with self.assertRaisesRegex(wave_guard.GuardError, "executable filter/diff drivers"):
            wave_guard.stable_patch_id_for_range(self.repo, self.base, attributes_tip)
        self.assertFalse(command_sentinel.exists())
        git(self.repo, "config", "--unset-all", "diff.evil.textconv")

        git(self.repo, "config", "extensions.partialClone", "origin")
        with self.assertRaisesRegex(wave_guard.GuardError, "lazy-fetch settings"):
            wave_guard.resolve_commit(self.repo, "HEAD", "HEAD")
        git(self.repo, "config", "--unset-all", "extensions.partialClone")

        grafts = self.repo / ".git" / "info" / "grafts"
        write(grafts, f"{self.base}\n")
        with self.assertRaisesRegex(wave_guard.GuardError, "unsupported grafts"):
            wave_guard.resolve_commit(self.repo, "HEAD", "HEAD")
        grafts.unlink()

        git(self.repo, "update-index", "--assume-unchanged", "README.md")
        write(self.repo / "README.md", "hidden local change\n")
        with self.assertRaisesRegex(wave_guard.GuardError, "assume-unchanged"):
            wave_guard.ensure_clean(self.repo, "hidden-index probe")
        git(self.repo, "update-index", "--no-assume-unchanged", "README.md")
        write(self.repo / "README.md", "base\n")

        git(
            self.repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.base},vendor/submodule",
        )
        git(self.repo, "commit", "-m", "gitlink probe")
        gitlink_tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "config", "diff.ignoreSubmodules", "all")
        manifest = wave_guard.path_manifest(self.repo, attributes_tip, gitlink_tip)
        self.assertEqual([item["path"] for item in manifest], ["vendor/submodule"])
        git(self.repo, "config", "--unset-all", "diff.ignoreSubmodules")

    def test_integer_fields_reject_json_booleans(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        charter["workspaceAdmission"]["workspaces"][0]["ahead"] = True
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, charter)

    def test_resource_ceilings_reject_oversized_charters_and_blobs(self) -> None:
        digest = wave_guard.method_digest()["canonicalDigest"]
        too_many_cells = self.charter(digest)
        template = too_many_cells["cells"][1]
        owner_workspace = too_many_cells["workspaceAdmission"]["workspaces"].pop()
        too_many_cells["cells"] = []
        too_many_cells["workspaceAdmission"]["workspaces"] = []
        for index in range(wave_guard.MAX_CHARTER_CELLS + 1):
            cell = json.loads(json.dumps(template))
            cell["cellId"] = f"cell-{index}"
            cell["workspaceId"] = f"workspace-{index}"
            cell["actor"] = f"actor-{index}"
            cell["dependsOn"] = [] if index == 0 else [f"cell-{index - 1}"]
            cell["writablePaths"] = [f"cell-{index}.txt"]
            too_many_cells["cells"].append(cell)
            too_many_cells["workspaceAdmission"]["workspaces"].append(
                {
                    "workspaceId": cell["workspaceId"],
                    "actor": cell["actor"],
                    "worktreeGitDir": f".git/worktrees/workspace-{index}",
                    "physicalIdentityDigest": "sha256:" + f"{index % 16:x}" * 64,
                    "headRevision": self.base,
                    "ahead": 0,
                    "behind": 0,
                    "clean": True,
                }
            )
        too_many_cells["workspaceAdmission"]["workspaces"].append(owner_workspace)
        with self.assertRaisesRegex(wave_guard.GuardError, "cannot exceed"):
            wave_guard.validate_charter_data(self.repo, too_many_cells)

        too_many_requirements = self.charter(digest)
        requirement = too_many_requirements["externalEvidence"][0]
        too_many_requirements["externalEvidence"] = []
        for index in range(wave_guard.MAX_EVIDENCE_REQUIREMENTS + 1):
            item = json.loads(json.dumps(requirement))
            item["requirementId"] = f"requirement-{index}"
            too_many_requirements["externalEvidence"].append(item)
        with self.assertRaisesRegex(wave_guard.GuardError, "externalEvidence cannot exceed"):
            wave_guard.validate_charter_data(self.repo, too_many_requirements)

        too_many_local_checks = self.charter(digest)
        too_many_local_checks["ownerIntegration"]["requiredLocalChecks"] = [
            {"checkId": f"check-{index}", "command": f"command-{index}"}
            for index in range(wave_guard.MAX_OWNER_LOCAL_CHECKS + 1)
        ]
        with self.assertRaisesRegex(wave_guard.GuardError, "requiredLocalChecks cannot exceed"):
            wave_guard.validate_charter_data(self.repo, too_many_local_checks)

        too_many_focused_checks = self.charter(digest)
        too_many_focused_checks["cells"][0]["focusedChecks"] = [
            f"check-{index}" for index in range(wave_guard.MAX_CHECK_IDS + 1)
        ]
        with self.assertRaisesRegex(wave_guard.GuardError, "focusedChecks cannot exceed"):
            wave_guard.validate_charter_data(self.repo, too_many_focused_checks)

        too_many_workspaces = self.charter(digest)
        template_workspace = too_many_workspaces["workspaceAdmission"]["workspaces"][0]
        too_many_workspaces["workspaceAdmission"]["workspaces"] = [
            {
                **template_workspace,
                "workspaceId": f"extra-{index}",
                "actor": f"extra-actor-{index}",
                "worktreeGitDir": f".git/worktrees/extra-{index}",
                "physicalIdentityDigest": "sha256:" + f"{index % 16:x}" * 64,
            }
            for index in range(wave_guard.MAX_WORKTREES + 1)
        ]
        with self.assertRaisesRegex(wave_guard.GuardError, "workspaces cannot exceed"):
            wave_guard.validate_charter_data(self.repo, too_many_workspaces)

        too_many_owned_paths = self.charter(digest)
        too_many_owned_paths["ownerOnlyPaths"] = [
            f"owner-{index}.txt" for index in range(wave_guard.MAX_OWNED_PATHS + 1)
        ]
        with self.assertRaisesRegex(wave_guard.GuardError, "owned paths"):
            wave_guard.validate_charter_data(self.repo, too_many_owned_paths)

        with mock.patch.object(
            wave_guard,
            "run_git",
            return_value=str(wave_guard.MAX_SNAPSHOT_BLOB_BYTES + 1).encode("ascii"),
        ):
            with self.assertRaisesRegex(wave_guard.GuardError, "snapshot ceiling"):
                wave_guard.blob_sha256(self.repo, "a" * 40)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.require_integer(True, "sequence")

        write(self.repo / "README.md", "x" * 4096)
        large_diff_tip = commit(self.repo, "large diff")
        with mock.patch.object(wave_guard, "MAX_SNAPSHOT_DIFF_BYTES", 32):
            with self.assertRaisesRegex(wave_guard.GuardError, "output ceiling"):
                wave_guard.stable_patch_id_for_range(self.repo, self.base, large_diff_tip)

    def test_workspace_admission_binds_ids_actors_physical_worktrees_and_state(self) -> None:
        workspace_a = Path(self.temp.name) / "workspace-a"
        workspace_b = Path(self.temp.name) / "workspace-b"
        workspace_owner = Path(self.temp.name) / "workspace-owner"
        git(self.repo, "worktree", "add", "--detach", str(workspace_a), self.base)
        git(self.repo, "worktree", "add", "--detach", str(workspace_b), self.base)
        git(self.repo, "worktree", "add", "--detach", str(workspace_owner), self.base)
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        charter["workspaceAdmission"]["workspaces"][0]["worktreeGitDir"] = wave_guard.worktree_git_dir_id(
            self.repo, workspace_a
        )
        charter["workspaceAdmission"]["workspaces"][1]["worktreeGitDir"] = wave_guard.worktree_git_dir_id(
            self.repo, workspace_b
        )
        charter["workspaceAdmission"]["workspaces"][2]["worktreeGitDir"] = wave_guard.worktree_git_dir_id(
            self.repo, workspace_owner
        )
        for row, workspace in zip(
            charter["workspaceAdmission"]["workspaces"],
            (workspace_a, workspace_b, workspace_owner),
        ):
            row["physicalIdentityDigest"] = wave_guard.physical_identity_digest(workspace)
        charter_path = self.dump("workspace-charter.json", charter)
        result = wave_guard.validate_charter_data(
            self.repo,
            charter,
            charter_path=charter_path,
            remeasure_admission=True,
        )
        self.assertEqual(result["cellCount"], 2)

        duplicate = json.loads(json.dumps(charter))
        duplicate["workspaceAdmission"]["workspaces"][1]["worktreeGitDir"] = duplicate[
            "workspaceAdmission"
        ]["workspaces"][0]["worktreeGitDir"]
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, duplicate)

        spoofed_actor = json.loads(json.dumps(charter))
        spoofed_actor["workspaceAdmission"]["workspaces"][0]["actor"] = "actor-b"
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, spoofed_actor)

        spoofed_workspace_id = json.loads(json.dumps(charter))
        spoofed_workspace_id["workspaceAdmission"]["workspaces"][0][
            "workspaceId"
        ] = "workspace-attacker"
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, spoofed_workspace_id)

        declared_behind = json.loads(json.dumps(charter))
        declared_behind["workspaceAdmission"]["workspaces"][0]["behind"] = 1
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, declared_behind)

        case_variant = json.loads(json.dumps(charter))
        case_variant["workspaceAdmission"]["workspaces"][0]["worktreeGitDir"] = case_variant[
            "workspaceAdmission"
        ]["workspaces"][0]["worktreeGitDir"].upper()
        with self.assertRaisesRegex(wave_guard.GuardError, "exact canonical spelling"):
            wave_guard.validate_charter_data(
                self.repo,
                case_variant,
                charter_path=charter_path,
                remeasure_admission=True,
            )

        write(workspace_a / "dirty.tmp", "dirty\n")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(
                self.repo,
                charter,
                charter_path=charter_path,
                remeasure_admission=True,
            )
        (workspace_a / "dirty.tmp").unlink()

        write(workspace_a / "ahead.txt", "ahead\n")
        git(workspace_a, "add", "ahead.txt")
        git(workspace_a, "commit", "-m", "ahead")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(
                self.repo,
                charter,
                charter_path=charter_path,
                remeasure_admission=True,
            )

    def test_symlinked_skill_root_is_rejected_before_digest(self) -> None:
        linked_root = Path(self.temp.name) / "linked-method"
        try:
            linked_root.symlink_to(wave_guard.skill_root(), target_is_directory=True)
        except (OSError, NotImplementedError):
            original_lstat = Path.lstat

            def lstat_with_simulated_link(path: Path):
                if path == linked_root:
                    return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                return original_lstat(path)

            patcher = mock.patch.object(Path, "lstat", lstat_with_simulated_link)
        else:
            patcher = contextlib.nullcontext()
        with patcher:
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.method_digest_at(linked_root)
            with mock.patch.object(
                wave_guard, "__file__", str(linked_root / "scripts" / "wave_guard.py")
            ):
                with self.assertRaises(wave_guard.GuardError):
                    wave_guard.method_digest()

    def test_replacement_predecessor_is_loaded_before_work(self) -> None:
        original = self.charter(wave_guard.method_digest()["canonicalDigest"])
        original_path = self.dump("original-charter.json", original)
        advanced = commit_tree(self.repo, self.base_tree, [self.base], "replacement baseline")
        replacement = json.loads(json.dumps(original))
        replacement["previousCharter"] = {
            "path": "original-charter.json",
            "digest": wave_guard.charter_digest(original),
        }
        replacement["baselineCommit"] = advanced
        replacement["baselineTree"] = self.base_tree
        for row in replacement["workspaceAdmission"]["workspaces"]:
            row["headRevision"] = advanced
        replacement_path = self.dump("replacement-charter.json", replacement)
        self.assertTrue(
            wave_guard.validate_charter_data(
                self.repo,
                replacement,
                charter_path=replacement_path,
                remeasure_admission=False,
            )["ok"]
        )
        original["objective"] = "tampered predecessor"
        original_path.write_text(json.dumps(original), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(
                self.repo,
                replacement,
                charter_path=replacement_path,
                remeasure_admission=False,
            )

        overlong = self.charter(wave_guard.method_digest()["canonicalDigest"])
        overlong["previousCharter"] = {
            "path": "unused-predecessor.json",
            "digest": "sha256:" + "0" * 64,
        }
        overlong_path = self.dump("overlong.json", overlong)
        with self.assertRaisesRegex(wave_guard.GuardError, "cannot exceed"):
            wave_guard.validate_charter_data(
                self.repo,
                overlong,
                charter_path=overlong_path,
                remeasure_admission=False,
                _seen_charters={
                    self.proof / f"seen-{index}.json"
                    for index in range(wave_guard.MAX_HANDOFFS)
                },
            )

    def test_recovery_bundle_is_exact_but_does_not_invent_provenance(self) -> None:
        measured = wave_guard.method_digest()
        vendor = self.repo / ".agents" / "vendor" / "multi-lane-wave-engineering"
        shutil.copytree(wave_guard.skill_root(), vendor)
        lock = {
            "schemaVersion": measured["schemaVersion"],
            "methodId": measured["methodId"],
            "methodVersion": measured["methodVersion"],
            "digestAlgorithm": measured["digestAlgorithm"],
            "canonicalDigest": measured["canonicalDigest"],
            "provenanceStatus": "UNVERIFIED_LOCAL",
            "sourceRevision": None,
            "provenanceAuthority": None,
            "recoverySource": ".agents/vendor/multi-lane-wave-engineering",
            "recoveryDigest": measured["canonicalDigest"],
        }
        wave_guard.compare_method_lock(lock, measured, repo=self.repo)
        (vendor / "SKILL.md").write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.compare_method_lock(lock, measured, repo=self.repo)

        recovery_parent = self.repo / ".agents" / "linked-vendor"
        real_parent = self.repo / ".agents" / "real-vendor"
        real_parent.mkdir(parents=True)
        shutil.copytree(wave_guard.skill_root(), real_parent / "method")
        try:
            recovery_parent.symlink_to(real_parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            original_lstat = Path.lstat

            def lstat_with_recovery_link(path: Path):
                if path == recovery_parent:
                    return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                return original_lstat(path)

            patcher = mock.patch.object(Path, "lstat", lstat_with_recovery_link)
        else:
            patcher = contextlib.nullcontext()
        linked_lock = {
            **lock,
            "recoverySource": ".agents/linked-vendor/method",
        }
        with patcher:
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.compare_method_lock(linked_lock, measured, repo=self.repo)

    def test_cli_requires_python_310_isolated_and_no_bytecode(self) -> None:
        hostile_imports = Path(self.temp.name) / "hostile-pythonpath"
        hostile_imports.mkdir()
        import_sentinel = hostile_imports / "argparse-imported.txt"
        (hostile_imports / "argparse.py").write_text(
            f"from pathlib import Path\nPath({str(import_sentinel)!r}).write_text('unsafe import')\n",
            encoding="utf-8",
        )
        hostile_environment = {**os.environ, "PYTHONPATH": str(hostile_imports)}
        direct = subprocess.run(
            [sys.executable, str(SCRIPT), "method-digest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=hostile_environment,
        )
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn(b"-I -B", direct.stderr)
        self.assertFalse(import_sentinel.exists(), "unsafe invocation must refuse before PYTHONPATH imports")
        isolated_only = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "method-digest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(isolated_only.returncode, 0)
        correct = subprocess.run(
            [sys.executable, "-I", "-B", str(SCRIPT), "method-digest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(correct.returncode, 0, correct.stderr.decode("utf-8", "replace"))
        missing_git = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(SCRIPT),
                "method-digest",
                "--repo",
                str(self.repo),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(missing_git.returncode, 0)
        self.assertIn(b"--git-executable", missing_git.stderr)
        trusted_git = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(SCRIPT),
                "method-digest",
                "--repo",
                str(self.repo),
                "--git-executable",
                str(self.git_executable),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(
            trusted_git.returncode,
            0,
            trusted_git.stderr.decode("utf-8", "replace"),
        )

    def test_evidence_fanout_exact_revision(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"], mode="evidence-fanout")
        fanout_a = Path(self.temp.name) / "fanout-workspace-a"
        fanout_b = Path(self.temp.name) / "fanout-workspace-b"
        git(self.repo, "worktree", "add", "--detach", str(fanout_a), self.base)
        git(self.repo, "worktree", "add", "--detach", str(fanout_b), self.base)
        for row, workspace in zip(
            charter["workspaceAdmission"]["workspaces"], (fanout_a, fanout_b)
        ):
            row["worktreeGitDir"] = wave_guard.worktree_git_dir_id(self.repo, workspace)
            row["physicalIdentityDigest"] = wave_guard.physical_identity_digest(workspace)
        result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("fanout-charter.json", charter)
        evidence = self.evidence(
            charter,
            result["charterDigest"],
            evidence_id="fanout-a",
            requirement_id=None,
            stage="fanout",
            relation="exact",
            revision=self.base,
            head_revision=self.base,
            base_revision=None,
            check_id="test-a",
            cell_id="A",
        )
        evidence_path = self.dump("fanout-a.json", evidence)
        self.assertTrue(wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)["ok"])
        unresolved_evidence = json.loads(json.dumps(evidence))
        unresolved_evidence["attestationSource"] = "REPLACE-PROVIDER"
        with self.assertRaisesRegex(
            wave_guard.GuardError, "unresolved distributed-template token REPLACE"
        ):
            wave_guard.verify_evidence_data(
                self.repo,
                charter_path,
                self.dump("fanout-unresolved.json", unresolved_evidence),
            )
        evidence["attestationSource"] = "hostile-source"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)
        evidence["attestationSource"] = "unit-test"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        evidence_b = self.evidence(
            charter,
            result["charterDigest"],
            evidence_id="fanout-b",
            requirement_id=None,
            stage="fanout",
            relation="exact",
            revision=self.base,
            head_revision=self.base,
            base_revision=None,
            check_id="test-b",
            cell_id="B",
        )
        self.dump("fanout-b.json", evidence_b)
        closeout = {
            "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "mode": "evidence-fanout",
            "method": charter["method"],
            "charters": ["fanout-charter.json"],
            "charterDigest": result["charterDigest"],
            "handoffs": [],
            "finalBaton": None,
            "ownerIntegrationSnapshot": None,
            "integrationHead": None,
            "ownerVerification": None,
            "landing": None,
            "externalEvidence": ["fanout-a.json", "fanout-b.json"],
            "openDecisions": [],
            "rollbackAuthority": charter["programmeConductor"],
            "synchronization": None,
        }
        self.assertTrue(
            wave_guard.verify_closeout_data(self.repo, self.dump("fanout-closeout.json", closeout))["ok"]
        )
        unauthorized_rollback = json.loads(json.dumps(closeout))
        unauthorized_rollback["rollbackAuthority"] = "independent-reviewer"
        with self.assertRaisesRegex(wave_guard.GuardError, "programmeConductor or waveOwner"):
            wave_guard.verify_closeout_data(
                self.repo,
                self.dump("fanout-closeout-unauthorized-rollback.json", unauthorized_rollback),
            )
        write(fanout_a / "dirty.tmp", "dirty\n")
        with self.assertRaisesRegex(wave_guard.GuardError, "remeasurement failed"):
            wave_guard.verify_closeout_data(
                self.repo, self.dump("fanout-closeout-dirty.json", closeout)
            )
        (fanout_a / "dirty.tmp").unlink()
        unresolved_closeout = json.loads(json.dumps(closeout))
        unresolved_closeout["rollbackAuthority"] = "REPLACE-ROLLBACK-AUTHORITY"
        with self.assertRaisesRegex(
            wave_guard.GuardError, "unresolved distributed-template token REPLACE"
        ):
            wave_guard.verify_closeout_data(
                self.repo, self.dump("fanout-closeout-unresolved.json", unresolved_closeout)
            )
        evidence["subject"]["headRevision"] = git(self.repo, "rev-parse", "HEAD") + "bad"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)

    def test_artifact_statuses_exactly_match_charter_requirement(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        requirement = charter["externalEvidence"][0]
        requirement["subjectRelation"] = "head-exact"
        requirement["requiredArtifacts"] = [
            {
                "artifactId": "native-capture",
                "requiredStatusIds": ["fmt", "test"],
            }
        ]
        charter_result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("artifact-charter.json", charter)
        write(self.repo / "cell-a.txt", "head\n")
        head = commit(self.repo, "evidence head")
        artifact = {
            "artifactId": "native-capture",
            "revision": head,
            "digestAlgorithm": "sha256",
            "digest": "sha256:" + "1" * 64,
            "statuses": [
                {"checkId": "fmt", "status": "PASS", "revision": head},
                {"checkId": "test", "status": "PASS", "revision": head},
            ],
        }
        evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="artifact-evidence",
            requirement_id="pr-head",
            stage="pr",
            relation="head-exact",
            revision=head,
            head_revision=head,
            base_revision=None,
            check_id="pr-check",
            artifacts=[artifact],
        )
        evidence_path = self.dump("artifact-evidence.json", evidence)
        self.assertTrue(
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)["ok"]
        )
        evidence["checks"][0]["checkId"] = "PR-CHECK"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)
        evidence["checks"][0]["checkId"] = "pr-check"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        for replacement_statuses in (
            [{"checkId": "fmt", "status": "PASS", "revision": head}],
            [
                {"checkId": "FMT", "status": "PASS", "revision": head},
                {"checkId": "test", "status": "PASS", "revision": head},
            ],
        ):
            evidence["artifacts"][0]["statuses"] = replacement_statuses
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)

    def test_artifact_only_evidence_and_exact_attestation_source(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        requirement = charter["externalEvidence"][0]
        requirement["subjectRelation"] = "head-exact"
        requirement["requiredCheckIds"] = []
        requirement["requiredAttestationSource"] = "native-auditor"
        requirement["requiredArtifacts"] = [
            {"artifactId": "native-capture", "requiredStatusIds": ["fmt"]}
        ]
        charter_result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("artifact-only-charter.json", charter)
        write(self.repo / "cell-a.txt", "head\n")
        head = commit(self.repo, "artifact-only head")
        artifact = {
            "artifactId": "native-capture",
            "revision": head,
            "digestAlgorithm": "sha256",
            "digest": "sha256:" + "2" * 64,
            "statuses": [{"checkId": "fmt", "status": "PASS", "revision": head}],
        }
        evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="artifact-only",
            requirement_id="pr-head",
            stage="pr",
            relation="head-exact",
            revision=head,
            head_revision=head,
            base_revision=None,
            check_id="unused",
            artifacts=[artifact],
        )
        evidence["checks"] = []
        evidence["attestationSource"] = "native-auditor"
        evidence_path = self.dump("artifact-only.json", evidence)
        self.assertTrue(
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)["ok"]
        )
        evidence["attestationSource"] = "wrong-source"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_evidence_data(self.repo, charter_path, evidence_path)

        empty_requirement = self.charter(wave_guard.method_digest()["canonicalDigest"])
        empty_requirement["externalEvidence"][0]["requiredCheckIds"] = []
        empty_requirement["externalEvidence"][0]["requiredArtifacts"] = []
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_charter_data(self.repo, empty_requirement)

    def test_multi_writer_closeout_binds_chain_evidence_landing_and_sync(self) -> None:
        charter = self.charter(wave_guard.method_digest()["canonicalDigest"])
        charter["workspaceAdmission"]["mainRef"] = "refs/heads/main"
        charter_result = wave_guard.validate_charter_data(self.repo, charter)
        charter_path = self.dump("charter.json", charter)

        git(self.repo, "checkout", "-b", "cell-a", self.base)
        write(self.repo / "cell-a.txt", "A\n")
        prepared_a_tip = commit(self.repo, "cell A")
        prepared_a = wave_guard.snapshot_range(self.repo, self.base, prepared_a_tip)

        git(self.repo, "checkout", "-b", "cell-b", self.base)
        write(self.repo / "cell-b.txt", "B\n")
        prepared_b_tip = commit(self.repo, "cell B")
        prepared_b = wave_guard.snapshot_range(self.repo, self.base, prepared_b_tip)

        git(self.repo, "checkout", "cell-a")
        baton_a = git(self.repo, "rev-parse", "HEAD")
        integrated_a = wave_guard.snapshot_range(self.repo, self.base, baton_a)
        git(self.repo, "checkout", "cell-b")
        git(self.repo, "rebase", "--onto", baton_a, self.base, "cell-b")
        baton_b = git(self.repo, "rev-parse", "HEAD")
        integrated_b = wave_guard.snapshot_range(self.repo, baton_a, baton_b)

        self.dump("prepared-a.json", prepared_a)
        self.dump("integrated-a.json", integrated_a)
        self.dump("prepared-b.json", prepared_b)
        self.dump("integrated-b.json", integrated_b)
        handoff_a = {
                "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "charterDigest": charter_result["charterDigest"],
            "cellId": "A",
            "workspaceId": "workspace-a",
            "sequence": 1,
            "fromActor": "actor-a",
            "toActor": "actor-b",
            "incomingBaton": self.base,
            "outgoingBaton": baton_a,
            "preparedSnapshot": "prepared-a.json",
            "integratedSnapshot": "integrated-a.json",
            "previousHandoff": None,
            "focusedVerification": [{"command": "test-a", "revision": baton_a, "verdict": "PASS"}],
            "workingTreeClean": True,
            "conflictResolution": None,
            "nextWork": ["handoff A"],
        }
        handoff_b = {
            "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "charterDigest": charter_result["charterDigest"],
            "cellId": "B",
            "workspaceId": "workspace-b",
            "sequence": 2,
            "fromActor": "actor-b",
            "toActor": "owner",
            "incomingBaton": baton_a,
            "outgoingBaton": baton_b,
            "preparedSnapshot": "prepared-b.json",
            "integratedSnapshot": "integrated-b.json",
            "previousHandoff": "handoff-a.json",
            "focusedVerification": [{"command": "test-b", "revision": baton_b, "verdict": "PASS"}],
            "workingTreeClean": True,
            "conflictResolution": None,
            "nextWork": ["handoff B"],
        }
        self.dump("handoff-a.json", handoff_a)
        self.dump("handoff-b.json", handoff_b)

        write(self.repo / "owner.txt", "owner\n")
        integration_head = commit(self.repo, "owner integration")
        owner_snapshot = wave_guard.snapshot_range(self.repo, baton_b, integration_head)
        self.dump("owner.json", owner_snapshot)
        integration_tree = git(self.repo, "rev-parse", f"{integration_head}^{{tree}}")
        pr_subject = commit_tree(self.repo, integration_tree, [self.base, integration_head], "synthetic PR")
        merge_revision = commit_tree(self.repo, integration_tree, [self.base, integration_head], "normal merge")

        pr_evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="pr",
            requirement_id="pr-head",
            stage="pr",
            relation="synthetic-two-parent",
            revision=pr_subject,
            head_revision=integration_head,
            base_revision=self.base,
            check_id="pr-check",
        )
        main_evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="main",
            requirement_id="post-main",
            stage="post-merge",
            relation="merge-exact",
            revision=merge_revision,
            head_revision=merge_revision,
            base_revision=None,
            check_id="main-check",
        )
        self.dump("evidence-pr.json", pr_evidence)
        self.dump("evidence-main.json", main_evidence)
        review_evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="independent-review",
            requirement_id="independent-review",
            stage="independent-review",
            relation="head-exact",
            revision=integration_head,
            head_revision=integration_head,
            base_revision=None,
            check_id="review-check",
        )
        review_evidence["actor"] = "independent-reviewer"
        self.dump("evidence-review.json", review_evidence)

        wrong_tree_subject = commit_tree(
            self.repo, self.base_tree, [self.base, integration_head], "wrong-tree synthetic PR"
        )
        wrong_tree_evidence = self.evidence(
            charter,
            charter_result["charterDigest"],
            evidence_id="wrong-tree-pr",
            requirement_id="pr-head",
            stage="pr",
            relation="synthetic-two-parent",
            revision=wrong_tree_subject,
            head_revision=integration_head,
            base_revision=self.base,
            check_id="pr-check",
        )
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_evidence_data(
                self.repo,
                charter_path,
                self.dump("evidence-wrong-tree-pr.json", wrong_tree_evidence),
                expected_requirement=charter["externalEvidence"][0],
                integration_head=integration_head,
                landing_base=self.base,
            )

        git(self.repo, "branch", "main", merge_revision)
        git(self.repo, "checkout", "main")
        instruction_blob = git(self.repo, "rev-parse", f"{merge_revision}:AGENTS.md")
        sync_result = {
            "ok": True,
            "mainRevision": merge_revision,
            "instructionPath": "AGENTS.md",
            "instructionBlob": instruction_blob,
            "worktreeCount": 3,
            "worktrees": [
                {
                    "worktreeGitDir": ".git",
                    "physicalIdentityDigest": charter["workspaceAdmission"]["workspaces"][0][
                        "physicalIdentityDigest"
                    ],
                },
                {
                    "worktreeGitDir": ".git/worktrees/workspace-b",
                    "physicalIdentityDigest": charter["workspaceAdmission"]["workspaces"][1][
                        "physicalIdentityDigest"
                    ],
                },
                {
                    "worktreeGitDir": ".git/worktrees/workspace-owner",
                    "physicalIdentityDigest": charter["workspaceAdmission"]["workspaces"][2][
                        "physicalIdentityDigest"
                    ],
                },
            ],
        }
        sync_patcher = mock.patch.object(
            wave_guard, "verify_worktrees", return_value=sync_result
        )
        sync_mock = sync_patcher.start()
        self.addCleanup(sync_patcher.stop)
        closeout = {
            "schemaVersion": 2,
            "waveId": "TEST-WAVE",
            "mode": "multi-writer",
            "method": charter["method"],
            "charters": ["charter.json"],
            "charterDigest": charter_result["charterDigest"],
            "handoffs": ["handoff-a.json", "handoff-b.json"],
            "finalBaton": baton_b,
            "ownerIntegrationSnapshot": "owner.json",
            "integrationHead": integration_head,
            "ownerVerification": {
                "revision": integration_head,
                "localChecks": [
                    {
                        "checkId": "local-integration",
                        "command": "test-local",
                        "revision": integration_head,
                        "verdict": "PASS",
                    }
                ],
                "independentReviewEvidence": "evidence-review.json",
            },
            "landing": {
                "mode": "two-parent-merge",
                "baseRevision": self.base,
                "mergeRevision": merge_revision,
                "mergeParents": [self.base, integration_head],
            },
            "externalEvidence": ["evidence-pr.json", "evidence-main.json"],
            "openDecisions": [],
            "rollbackAuthority": charter["waveOwner"],
            "synchronization": {
                "mainRef": "refs/heads/main",
                "mainRevision": merge_revision,
                "instructionPath": "AGENTS.md",
                "instructionBlob": instruction_blob,
                "worktreeCount": 3,
            },
        }
        closeout_path = self.dump("closeout.json", closeout)
        result = wave_guard.verify_closeout_data(self.repo, closeout_path)
        self.assertEqual(result["mergeRevision"], merge_revision)
        relocated_sync = json.loads(json.dumps(sync_result))
        relocated_sync["worktrees"][0]["physicalIdentityDigest"] = "sha256:" + "f" * 64
        sync_mock.return_value = relocated_sync
        with self.assertRaisesRegex(
            wave_guard.GuardError, "physical worktree identity changed at closeout"
        ):
            wave_guard.verify_closeout_data(self.repo, closeout_path)
        sync_mock.return_value = sync_result
        review_evidence["attestationSource"] = "wrong-review-authority"
        self.dump("evidence-review.json", review_evidence)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_closeout_data(self.repo, closeout_path)
        review_evidence["attestationSource"] = "unit-test"
        self.dump("evidence-review.json", review_evidence)
        review_evidence["actor"] = charter["waveOwner"].upper()
        self.dump("evidence-review.json", review_evidence)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_closeout_data(self.repo, closeout_path)
        for non_independent_actor in (
            charter["programmeConductor"],
            charter["cells"][0]["actor"],
            charter["cells"][0]["actor"].replace("-", "_"),
            "\uff21\uff23\uff34\uff2f\uff32\uff0d\uff21",
            charter["waveOwner"] + " ",
            "...",
        ):
            review_evidence["actor"] = non_independent_actor
            self.dump("evidence-review.json", review_evidence)
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.verify_closeout_data(self.repo, closeout_path)
        review_evidence["actor"] = "independent-reviewer"
        self.dump("evidence-review.json", review_evidence)
        for field, hostile in (
            ("mainRef", "HEAD"),
            ("instructionPath", "README.md"),
            ("instructionBlob", "0" * 40),
        ):
            original = closeout["synchronization"][field]
            closeout["synchronization"][field] = hostile
            closeout_path.write_text(json.dumps(closeout), encoding="utf-8")
            with self.assertRaises(wave_guard.GuardError):
                wave_guard.verify_closeout_data(self.repo, closeout_path)
            closeout["synchronization"][field] = original
        closeout_path.write_text(json.dumps(closeout), encoding="utf-8")
        closeout["ownerVerification"]["localChecks"][0]["command"] = "wrong-command"
        closeout_path.write_text(json.dumps(closeout), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_closeout_data(self.repo, closeout_path)
        closeout["ownerVerification"]["localChecks"][0]["command"] = "test-local"
        closeout_path.write_text(json.dumps(closeout), encoding="utf-8")
        self.dump("handoff-a-alternate.json", handoff_a)
        handoff_b["previousHandoff"] = "handoff-a-alternate.json"
        self.dump("handoff-b.json", handoff_b)
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_closeout_data(self.repo, closeout_path)
        handoff_b["previousHandoff"] = "handoff-a.json"
        self.dump("handoff-b.json", handoff_b)
        wrong_base_merge = commit_tree(
            self.repo, integration_tree, [baton_a, integration_head], "wrong-base merge"
        )
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_landing_graph(
                self.repo,
                charter_baseline=self.base,
                integration_head=integration_head,
                landing_mode="two-parent-merge",
                base_revision=baton_a,
                merge_revision=wrong_base_merge,
                measured_parents=[baton_a, integration_head],
            )
        altered_tree_merge = commit_tree(
            self.repo, self.base_tree, [self.base, integration_head], "altered-tree merge"
        )
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.validate_landing_graph(
                self.repo,
                charter_baseline=self.base,
                integration_head=integration_head,
                landing_mode="two-parent-merge",
                base_revision=self.base,
                merge_revision=altered_tree_merge,
                measured_parents=[self.base, integration_head],
            )
        closeout["finalBaton"] = integration_head
        closeout_path.write_text(json.dumps(closeout), encoding="utf-8")
        with self.assertRaises(wave_guard.GuardError):
            wave_guard.verify_closeout_data(self.repo, closeout_path)

    def test_snapshot_records_rename_and_blob_hashes(self) -> None:
        git(self.repo, "checkout", "-b", "rename-cell")
        write(self.repo / "old.bin", "payload\n")
        first = commit(self.repo, "add old")
        git(self.repo, "mv", "old.bin", "new.bin")
        second = commit(self.repo, "rename old")
        snapshot = wave_guard.snapshot_range(self.repo, first, second)
        self.assertEqual(snapshot["paths"][0]["status"], "R100")
        self.assertEqual(snapshot["paths"][0]["oldPath"], "old.bin")
        self.assertEqual(snapshot["paths"][0]["path"], "new.bin")
        self.assertEqual(snapshot["paths"][0]["oldBlobSha256"], snapshot["paths"][0]["newBlobSha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
