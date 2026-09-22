---
name: multi-lane-wave-engineering
description: Coordinate isolated Git writer lanes that must integrate into one reviewed outcome using immutable wave charters, exact path ownership, verified baton handoffs, continuous local verification, and one integration owner. Use for concurrent worktrees with disjoint cells or fixed-revision cross-platform evidence. Do not use for ordinary single-writer work, read-only parallel research, multiple writers sharing one working directory, independent deliverables, or unpartitionable overlapping writes.
metadata:
  method-version: "2.0.0"
---

# Multi-Lane Wave Engineering

Use this Skill to gain parallel implementation without competing branches, stale evidence, or
ambiguous integration authority. It is a reusable Git method. The user, repository instructions,
project Skill, branch protection, and current source/tests remain more specific authority.

## Select the mode before any lane writes

Use ordinary single-lane development when there is one writer, only read-only parallel help, or work
that can land and roll back independently. Multiple agents do not by themselves create a wave.

Use **multi-writer wave mode** only when all are true:

1. at least two writers have isolated workspaces;
2. they target the same final integration head and failure domain;
3. contributor paths and owner-only seams can be enumerated without overlap; and
4. parallel benefit exceeds charter, replay, and verification cost.

Use **evidence fan-out mode** when one writer freezes a revision and independent platforms or
machines verify that same revision. Evidence lanes never move the baton.

Never allow multiple writers in one working directory. If unavoidable writes cannot be assigned to
one owner-only seam, serialize or split the wave.

For any writable wave, read [references/protocol.md](references/protocol.md) completely first. Read
[references/recovery.md](references/recovery.md) when main, method bytes, ownership, evidence, or a
handoff changes unexpectedly. Templates are under `assets/templates/`.

## Declare the role for each action

- **Programme conductor:** owns queue order, dependency state, admission/split decisions, exact
  cell/path/lane assignment, and keeping useful work available. Coordination grants no write or Git
  authority.
- **Wave owner:** owns the immutable charter, only external wave branch allowed by project policy,
  owner-only seams, final integration, verification, landing flow, and closeout.
- **Contributor:** owns one exact disjoint range, focused RED/GREEN, and its replay/handoff proof.
- **Independent reviewer:** remeasures a fixed range and evidence without mutation.
- **Evidence contributor:** verifies one frozen revision on a distinct platform without source edits
  or baton movement.

One actor may hold conductor and owner duties, but must keep the authority boundaries explicit.
Spawned subagents remain under their host's Git rules and are not peer writer lanes by analogy.

## Freeze the method and charter

Before writable work, compute this Skill's canonical digest and verify any project lock:

```text
<python> -I -B <skill>/scripts/wave_guard.py method-digest --git-executable <git> [--lock <project-lock.json>] [--repo <repo>]
```

Resolve `<python>` to a Python 3.10-or-newer executable and `<git>` to a trusted absolute regular
Git executable before entering an untrusted repository; never pass a command name or relative path.
On managed Codex hosts use the bundled
workspace runtime when `python` is not on `PATH`. The executable itself is a trust prerequisite; the
guard refuses a missing `-I` or `-B` before importing any shadowable module. Every guard-owned Git subprocess clears inherited
Git authority, sets `GIT_NO_REPLACE_OBJECTS=1` and `GIT_NO_LAZY_FETCH=1`, disables repository
fsmonitor and commit-graph acceleration plus system/global configuration and interactive helpers,
scopes `safe.directory` to the validated physical repository path,
refuses partial-clone/lazy-fetch configuration, executable filter/diff drivers, grafts, shallow
repositories, and hidden `assume-unchanged`/`skip-worktree` index entries, and therefore measures the objects that can
actually land rather than a host-local replace or helper view. Every proof diff forces
`diff.ignoreSubmodules=none`: a superproject gitlink binds mode `160000` and its commit object ID,
while the guard makes no claim about uncommitted contents inside a nested submodule worktree. Create a charter from
`assets/templates/wave-charter.json`. It fixes method ID/version/digest,
baseline, roles, exact paths, owner-only seams, semantic integration seams, decisions, verification,
CI requirement IDs/checks/artifacts, stop/split, and completion. A local user Skill records
`provenanceStatus=UNVERIFIED_LOCAL`, `sourceRevision=null`, and
`provenanceAuthority=null`: its digest proves byte identity, not publisher provenance. A verified
distribution instead records a full Git source revision and concrete provenance authority. The
method lock and every charter/closeout `method` object use the same exact ten-field schema; an
installation location is not part of that canonical identity. Validate before assigning writes:

```text
<python> -I -B <skill>/scripts/wave_guard.py validate-charter --git-executable <git> --repo <repo> --charter <charter.json>
```

Distributed JSON templates are intentionally invalid until every canonical `REPLACE-*` sentinel is
materialized. The guard rejects an unresolved sentinel anywhere in charter, handoff, evidence or
closeout proof data; matching the same placeholder on both sides never turns it into authority.
`workspaceAdmission.instructionPath` must identify a tracked Git blob, never the repository root or
a tree. Attestation sources and reviewer identities must be concrete and contain Unicode
alphanumeric identity; punctuation or matching placeholders do not establish independent authority.
The v2 guard caps a charter and its physical workspace registry at 64 cells/worktrees and 512 total owned paths, external evidence at 64
requirements with bounded checks/artifacts/statuses, owner local checks at 64, a closeout at 64
handoffs or charter generations, and a range at 256 commits/2,048 cumulative manifest entries.
One snapshot blob/diff above 64 MiB or aggregate unique blobs above 256 MiB refuse before unbounded
verification; generated proof JSON is capped at 4 MiB, one Git subprocess at 120 seconds, and one
top-level guard operation at 4,096 Git calls and 600 seconds.

`validate-charter` also remeasures the embedded workspace admission and, for a replacement, loads
and verifies the predecessor immediately. Each cell has one admitted registered physical worktree;
a canonical `physicalIdentityDigest` binds the normalized real checkout path without placing that
private absolute path in proof JSON, and replacement charters must freshly remeasure it;
a multi-writer owner who is not a cell actor has exactly one additional admitted workspace, while
evidence fan-out admits cell workspaces only. The charter is immutable after activation. A base-only
movement uses a linked replacement charter whose predecessor path is relative to the replacement
charter's proof directory and whose baseline strictly descends from the predecessor baseline:
scope and decisions stay identical while baseline commit/tree, workspace measurements, and the
linked `previousCharter` path/digest change.
The sole baseline-derived identity field is a local-check command exactly equal to
`git diff --check <that-generation-baseline>...HEAD`; replacement comparison normalizes only that
command, and every other command remains immutable.
Changed scope, paths, authority, product decisions, or method version requires a new wave ID.
New higher-level safety rules apply immediately and may stop a frozen wave; a method lock cannot
freeze out safety.

## Run the conductor loop

Until programme completion or a named stop:

1. remeasure repository/worktrees, open integration work, dependencies, executable checks and
   external state; do not route from conversation memory alone;
2. close the prior cycle, reorder or split the queue, and assign exact disjoint startable work;
3. progress one conductor- or owner-owned item while contributors work;
4. validate handoffs and independently remeasure facts that change another lane's action;
5. refill queues immediately; and
6. integrate only a charter-complete wave, close exact evidence, then synchronize before new writes.

Queue depth is a project parameter. A blocked cell does not idle unrelated lanes and never grants
permission to cross another lane's paths.

## Preserve the execution shape

- **Implement small:** one coherent cell, exact paths, focused RED/GREEN, bounded side effects.
- **Integrate large:** one compatible failure-domain wave; one owner integrates shared seams.
- **Verify continuously:** cell, replay, seam, full local head, external evidence, and post-merge as
  required. External CI is never the first integration test.
- **Consolidate external evidence:** plan one authoritative PR cycle for the frozen head when policy
  permits. This is not a hard cap and never waives mandatory security, platform, release, soak,
  branch-protection, or exact-merge checks. A changed head invalidates earlier review and evidence.

## Verify baton and workspace state

Generate committed range snapshots and validate handoffs with `scripts/wave_guard.py`. The handoff
binds linear ancestry, ordered commit patch IDs, aggregate range patch ID, exact path status/mode,
before/after committed blob SHA-256, final tree ID, and `nextWork` exactly equal to the chartered
cell queue. Ancestry or patch ID alone is insufficient.

```text
<python> -I -B <skill>/scripts/wave_guard.py snapshot-range --git-executable <git> --repo <repo> --parent <sha> --tip <sha>
<python> -I -B <skill>/scripts/wave_guard.py verify-handoff --git-executable <git> --repo <repo> --charter <charter.json> --handoff <handoff.json>
<python> -I -B <skill>/scripts/wave_guard.py verify-evidence --git-executable <git> --repo <repo> --charter <charter.json> --evidence <evidence.json>
<python> -I -B <skill>/scripts/wave_guard.py verify-closeout --git-executable <git> --repo <repo> --closeout <closeout.json>
<python> -I -B <skill>/scripts/wave_guard.py verify-worktrees --git-executable <git> --repo <repo> --main-ref origin/main
```

Always use isolated mode (`-I`) and suppress bytecode (`-B`); the method digest rejects every
unpinned file or symlink in the Skill tree, and the CLI rejects a runtime missing either flag.
`verify-handoff` also rejects a checkout whose registered administrative identity or physical path
is not the exact Git-registered charter admission for that cell. Conflict,
extra/missing/overlapping or transient foreign
path, nonlinear history, patch mismatch, mode/blob mismatch,
method drift, dirty unrelated work, or wrong revision is a stop. The range returns to its author.
Do not reset, stash, force-push, or call changed bytes equivalent to manufacture a pass.
Mutation of local Git configuration, index flags, shallow/graft state, administrative files, or
worktree registration while a guard runs is outside the proof model: stop, restore an authorized
stable repository state, and rerun instead of treating a race as evidence.

`verify-closeout` remeasures the ordered handoff chain, owner-only integration, exact-head local
checks, required independent review, Git landing parents,
each declared previous-handoff link, reviewed PR subject tree, charter-declared evidence bindings and
registered-worktree synchronization. Evidence records bind
attestations to Git revisions/digests; they do not independently query or replace the named CI,
platform, signing or reviewer authority. A fan-out closeout remeasures every admitted evidence
workspace at the frozen subject even though it has no baton or landing. Every closeout's
`rollbackAuthority` must name the chartered wave owner or programme conductor. Local-check records likewise bind command/revision/verdict;
the guard does not execute the command. Fan-out sources, owner review sources, check/artifact/status
IDs, and closeout synchronization identity are exact charter bindings. A project overlay must still
collect that authoritative evidence and define the required IDs.

## Respect authority ceilings

This Skill never grants commit, rebase, push, PR, merge, deployment, production, secret, dashboard,
or destructive authority. Perform only actions already authorized by the user and repository. Stop
when this generic method conflicts with a narrower project rule.
