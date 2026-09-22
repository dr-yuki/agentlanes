# Multi-Lane Wave Engineering Protocol

Method ID: `multi-lane-wave-engineering`
Method version: `2.0.0`
Transport profile: `linear-replay-v2`

This is the reusable method authority. A project overlay supplies concrete paths, commands, tests,
permissions, queue depth, product decisions, evidence formats, and landing rules.

## 1. Outcome and non-goals

The method applies when isolated Git writers can produce independently testable ranges that must
converge on one reviewed head. It reduces serial waiting and repeated external CI without becoming a
single untestable rewrite.

Do not activate it for one writer, read-only parallel review, unrelated deliverables, multiple
writers sharing a working directory, or changes whose writable paths and semantic seams cannot be
partitioned. In those cases use ordinary development, evidence fan-out, or serialization.

## 2. Normative principles

1. **Implement small.** A cell has one purpose, exact paths, bounded authority/side effects, and
   focused acceptance evidence.
2. **Integrate large.** A wave combines compatible cells behind one owner and one final integration
   subject.
3. **Verify continuously.** Verification runs at cell, replay, seam, integrated head, external, and
   post-merge boundaries as required.
4. **Consolidate, never suppress, external evidence.** Avoid one costly submission per cell while
   preserving every mandatory CI, security, release, soak, and platform gate.
5. **Keep one writer per path.** Ownership follows actual repository paths and semantic seams, not
   branch labels or chat.
6. **Make handoffs durable.** History, canonical payloads, path/mode/blob manifests, tests, and
   closeout prove what chat coordinates.
7. **Freeze one method per wave.** Record method ID, version, canonical bundle digest, and verified
   provenance when one exists. A local bundle without publisher provenance says
   `UNVERIFIED_LOCAL`; it never invents a source revision.

## 3. Authority layers

From broad to narrow: user/organization policy, user agent instructions, repository instructions,
project Skill/plan, active charter, and current source/tests/checkers/branch protection/platform
evidence. More specific rules constrain this method. The method, charter, and role names grant no
authority by themselves.

New higher-level safety rules apply immediately even to a wave with a frozen method version. Stop or
replace the charter if they make the current plan invalid.

## 4. Definitions

- **Programme:** ordered waves and decisions needed for one outcome.
- **Cell:** one coherent independently reviewable implementation/test range.
- **Wave:** compatible cells sharing baseline, final head, failure/rollback domain, landing vehicle,
  method version, and external evidence cycle.
- **Charter:** immutable identity, method lock, scope, assignments, decisions, and acceptance.
- **Baton:** current linear integration tip.
- **Owner-only seam:** shared registration, dependency/lock, generated artifact, handler, policy,
  governance, or ledger integrated by one owner.
- **Semantic seam:** API, schema, event, command, invariant, generator, or ownership relationship that
  can conflict despite disjoint file paths.
- **Prepared range:** contributor commits before stacking.
- **Integrated range:** the owned change replayed on the incoming baton.
- **Replacement charter:** identical method and payload on a newer baseline, linked to predecessor.

## 5. Admission and split

Multi-writer wave mode requires all of:

1. two or more isolated writable workspaces;
2. one common final integration head and failure domain;
3. exact contributor paths and owner-only paths fixed before writes;
4. named semantic seams and integration tests;
5. parallel benefit greater than handoff/replay/reverification cost.

Cells may share a wave only when transport/lifecycle, authority boundary, side-effect durability,
rollback/partial-failure behavior, contract transition, platform evidence, security/privacy exposure,
independent removability, and release timing are compatible.

Split on different irreversible writes, identity/secrets, storage migration, unresolved product
decision, unproven platform dependency, compliance gate, incompatible transition, rollback unit, or
landing vehicle. File/command count and CI cost never override truthful failure domains.

Evidence fan-out is separate: one writer freezes one revision; two or more isolated evidence cells
declare empty writable-path sets, one exact `requiredAttestationSource` each, only verify it, and do
not move a baton. Multi-writer cells use the same versioned cell shape with that field set to null.

## 6. Roles and ceilings

| Role | Owns | Does not gain automatically |
| --- | --- | --- |
| Programme conductor | queue, dependencies, admission/split, exact assignments, work continuity | product decisions, shared files, Git history, landing |
| Wave owner | charter, baton intake, owner-only seams, integrated head, allowed landing and closeout | production authority or permissions beyond project rules |
| Contributor | one exact range, focused tests, replay and handoff proof | owner-only seams, foreign fixes, push/PR/merge |
| Independent reviewer | non-mutating fixed-range/evidence verdict | edit, repair, or landing authority |
| Evidence contributor | fixed-revision platform evidence | source edits or baton movement |

An actor may hold multiple roles, but each action names the controlling role. A self-review is never
reported as independent. A reviewer moving to repair becomes a writer through a new assignment.
Spawned subagents remain under their host's Git rules and are not peer lanes by analogy.

## 7. Method lock and immutable charter

Before writable assignment:

1. compute and record method ID, semantic version, bundle digest, digest algorithm, and either
   verified source provenance or the explicit `UNVERIFIED_LOCAL` state;
2. record baseline commit/tree/object format and a machine-remeasured workspace admission that binds
   each charter workspace/actor to one distinct registered physical worktree at the baseline, clean,
   0/0 against the named main ref, using one instruction blob, and carrying a canonical
   `physicalIdentityDigest` of the normalized real checkout path without disclosing that absolute
   path. Multi-writer admission contains
   the cell workspaces plus exactly one owner workspace when the wave owner is not already a cell
   actor; evidence fan-out contains the cell workspaces exactly;
3. define objective, in/out scope, failure domain, roles and authority ceilings;
4. enumerate ordered cells, dependencies, isolated workspace IDs, actors, exact repo-relative paths,
   owner-only paths, and semantic seams;
5. record exact owner-integration local checks, required independent-review authority/checks, plus
   structured external evidence requirement IDs, exact attestation source, subject
   relation, exact required check IDs, artifact IDs and each artifact's required status IDs,
   rollback, stops, and acceptance;
6. canonicalize and hash the payload before cell history depends on it.

Paths use `/`, exact spelling, and repository-relative portable ASCII form. No absolute path, `..`,
glob, backslash, non-ASCII/control or Windows-illegal `< > : " | ? *` component character, Windows device alias, trailing dot/space, case-fold
duplicate, or ancestor/descendant ownership overlap is permitted in the v2 transport. A rename owns both
endpoints. Proof JSON is regular, non-symlink UTF-8 and remains inside its proof bundle.

Identity lists, commands, dependency/seam/next-work values, evidence IDs, check IDs, artifact IDs,
and status IDs are case-sensitive exact strings; changing case does not satisfy a requirement.

Every guard-owned Git subprocess uses a caller-resolved absolute trusted Git executable, removes
inherited `GIT_*` authority, sets `GIT_NO_REPLACE_OBJECTS=1` and `GIT_NO_LAZY_FETCH=1`, disables
system/global configuration, fsmonitor, commit-graph acceleration and interactive helpers, scopes
`safe.directory` to the validated physical repository path, and
uses the sanitized environment for object, graph, ref and worktree measurements. Repository
executable filter/diff drivers, partial-clone/lazy-fetch configuration, grafts, shallow repositories,
and `assume-unchanged`/`skip-worktree` index entries fail closed. A host-local
replace ref, helper, textconv, filter or promised-object fetch must never change the charter,
handoff or closeout graph that the guard accepts.
Proof diffs force `diff.ignoreSubmodules=none`: the superproject snapshot binds each gitlink's mode
`160000` and commit object ID, but does not claim the uncommitted contents of a nested submodule
worktree.

The canonical method lock (and each charter/closeout `method` object) has exactly ten fields:
`schemaVersion`, `methodId`, `methodVersion`, `digestAlgorithm`, `canonicalDigest`,
`provenanceStatus`, `sourceRevision`, `provenanceAuthority`, `recoverySource`, and
`recoveryDigest`. `UNVERIFIED_LOCAL` requires null source revision and authority. `VERIFIED`
requires a full lowercase 40- or 64-hex Git object ID and a concrete nonblank authority string.
Recovery source/digest are jointly null or jointly present; recovery proves exact bytes, not source
trust. An installation path is deliberately not part of the portable method identity.

The distributed templates are scaffolds, not valid evidence. Every canonical `REPLACE-*` sentinel
must be materialized before validation; the guard rejects a remaining sentinel anywhere in charter,
handoff, evidence or closeout proof data, including when two records repeat the same placeholder.

`worktreeGitDir` is the absolute `git rev-parse --git-dir` result expressed as a portable POSIX path
relative to the parent of the absolute `git rev-parse --git-common-dir` result. Typical identities
are `.git` for the primary checkout and `.git/worktrees/<name>` for a linked worktree. The guard also
compares canonical physical paths internally, but never writes those private absolute paths to proof
JSON or command output.

Before activation, `validate-charter` must load a replacement's named predecessor, verify its digest,
and prove same scope before any writable assignment. `previousCharter.path` is relative to the
replacement charter's proof directory and must resolve through regular non-reparse parents. The
replacement baseline must be a strict descendant of the predecessor baseline (equal and sibling
baselines fail), and each recorded tree must resolve from its own baseline commit. After activation
the admitted `physicalIdentityDigest` remains immutable across same-wave replacements: remeasure the
same physical checkout; relocating it requires a new wave ID. The charter is immutable. A base-only move may use a linked replacement whose scope,
roles, decisions and evidence requirements remain identical while baseline commit/tree and
linked `previousCharter` path/digest change. A local-check command whose exact value is
`git diff --check <baselineCommit>...HEAD` is the sole baseline-derived identity field: each
generation records its own full baseline, while replacement comparison normalizes only that exact
command. Any other command change remains a scope change. Scope, path, authority,
product-decision, semantic-seam, or method change requires a new wave ID.

## 8. Conductor loop and queue health

Repeat until programme completion or a named stop:

1. measure repository/workspaces, integration branch, dependencies, and executable truth;
2. close the last cycle and reorder/split from measured facts;
3. assign each live lane enough independent work to avoid a reply-only idle state;
4. progress an owner/conductor item in parallel;
5. validate handoffs and independently verify behavior-changing measurements;
6. refill queues immediately;
7. integrate only when the charter is satisfied.

Queue depth is project-specific. Every handoff names concrete next work, including safe read-only or
preparation items behind a blocker. A blocked cell never grants foreign path authority.

## 9. Cell preparation

Each contributor confirms charter/baseline/method/exact paths, captures a real before-RED where
applicable, implements one coherent cell, makes every self-contained focused check green, records
seam-dependent exact REDs, and creates only the locally authorized checkpoint.

Unexpected paths, formatter spill, generated files, conflict, dirty unrelated state, or scope
expansion stops the cell. Never reset, clean, stash, or overwrite unrelated work to manufacture
scope. The handoff reports actual paths, tests, open items, and concrete next work.

## 10. Baton transport: linear-replay-v2

In dependency order, each author replays only their owned prepared range on the incoming baton. The
handoff binds:

- charter/wave/cell/workspace/actor identity, exact sequence, recipient, and preceding handoff;
- incoming, prepared parent/tip, outgoing, ordered commit range, and final tree ID;
- ordered per-commit stable patch IDs and aggregate range patch ID;
- exact add/modify/delete/rename path status;
- before/after file mode, object ID, and committed blob SHA-256;
- focused checks at the exact outgoing revision;
- clean working-tree assertion; and
- `nextWork` exactly equal to the chartered cell queue.

The first incoming baton is the baseline itself, or one direct single-parent tree-neutral charter
commit whose parent and tree equal that baseline. Every commit's changed-path union is owned even
when a later commit restores a foreign path; aggregate endpoint diff alone never hides transient
scope. Handoff focused commands equal the charter list exactly.

Ancestry alone, patch ID alone, or final content alone is insufficient. Patch ID is weak for binary,
mode-only, and duplicate patches; end-state bytes alone can hide missing commits or ordering.

The range author performs the replay. Conflict, nonlinear ancestry, path difference, patch mismatch,
mode/blob mismatch, or missing evidence returns the range to that author. A byte change requires a
new prepared snapshot and explicit charter-compatible reason; never call it byte-preserving.

The verifier binds each workspace/actor label to one distinct Git-registered physical worktree and
administrative worktree identity at admission. It does not prove the physical identity of a human or
process. A top-level handoff verification additionally requires that the checkout's current
administrative worktree identity and real path exactly equal the Git-registered admitted row for that cell,
`HEAD==outgoingBaton`, and a clean worktree; historical handoffs are rechecked from Git objects
during closeout.

If baseline moves, create that linked same-scope replacement charter and have original authors replay
their prior integrated ranges in original order. The owner does not rewrite everyone alone. Signed
or merge-preserving history requires a separately specified transport; do not improvise it.

## 11. Owner integration

After all cells stack, only the owner edits owner-only seams. Turn every recorded seam RED green
before producing generated or immutable evidence. Derive hashes/artifacts from the final base with
approved tools; never hand-repair them.

The owner runs every chartered local integration command on the exact integration head and records
its check ID, command, revision and PASS verdict. A required independent reviewer then attests that
same head through the chartered source and check IDs. Closeout remeasures both; prose is insufficient.
The generic guard binds these records to the fixed Git subject and declared authority. It does not
execute the commands, query the provider, or decide whether an attestation is truthful; the project
overlay must perform and independently query those checks.
The independent-review actor is normalized only for the independence comparison and must be
distinct, ignoring case and punctuation, from the conductor, owner, and every contributor.
Surrounding whitespace is invalid rather than an identity escape. Evidence fan-out similarly fixes one exact
`requiredAttestationSource` on each cell and rejects any other source.

Keep irreversible state transitions, schema edges, cutovers, and record steps in separate commits or
landings required by the project. A large wave does not collapse truthful intermediate states.

## 12. Verification ladder

1. cell focused behavior, contract, error, and boundary checks;
2. replay scope/method/baton verification and affected focused checks;
3. owner seam exact RED-to-GREEN;
4. full affected local integration, formatting, build, lint, security/privacy, and diff hygiene;
5. independent fixed-head review where required;
6. exact frozen PR base/head workflows and artifacts;
7. fresh landing preflight and permitted non-rewriting merge;
8. distinct required exact-merge/post-merge evidence;
9. closeout ancestry, ledger, open decisions, and workspace synchronization.

Queued, stale, partial, cancelled, unexpectedly skipped, wrong-revision, or wrongly parented evidence
is not PASS. Any head change, including lock/generated/metadata changes, invalidates prior head-bound
review and CI. Same-head infrastructure retries remain same-subject evidence; code changes do not.
For a synthetic two-parent PR subject, both parents are exactly `[base, head]` and its tree is exactly
the reviewed head tree. Parent names alone never bind the bytes that ran.

## 13. External evidence cadence

Plan one authoritative external PR cycle for the frozen final head, not one per cell. This is a
default optimization, not a hard maximum. Never omit branch protection, security/compliance,
platform-only checks, signing/notarization, exact post-merge evidence, explicit soaks, or an early
sentinel whose absence would create larger rework.

Run cheap focused checks continuously. External evidence begins only after the local integration
head is green and frozen.

## 14. Completion

A wave closes only when implementation, owner integration, verification, evidence, durable closeout,
rollback/open items, and required workspace synchronization are complete. `verify-closeout`
remeasures the same-scope linked charter chain; ordered contiguous handoffs; final baton; owner-only
integration range; final-charter landing base, exact Git landing parents and reviewed-head tree;
one-to-one charter evidence requirements including artifact status sets; and clean, 0/0 registered
worktrees with one instruction blob. Its synchronization `mainRef`, `instructionPath`, and
`instructionBlob` exactly equal the final charter admission before their current values are
remeasured, preventing closure through a substitute ref or instruction file. A verified closeout
contains no unresolved decision.
Its `rollbackAuthority` is exactly the chartered wave owner or programme conductor in either mode.
An evidence-fan-out closeout has no landing or baton, but still remeasures every admitted cell
workspace at the exact frozen subject before it can close.
The closeout handoff array is the chain: each handoff's resolved `previousHandoff` is the immediately
preceding declared array entry, not merely some other valid handoff for the prior cell.

Evidence JSON is a revision/digest binding for an attestation already collected from the named
authority. The generic guard cannot independently query every CI/provider/platform, and a PASS from
it never substitutes for the project-required provider query or independent review. PR and
post-merge records remain separate subjects.

Dirty, ahead-only, diverged, missing-checkpoint, wrong-instruction, or wrong-method workspaces stop.
Use only the safe synchronization operation permitted by the repository; do not reset/stash another
lane to make a status board green.

## 15. Versioning and distribution

- Patch: clarification or validator correction that does not change participant action.
- Minor: backward-compatible optional capability or evidence.
- Major: changed role authority, admission, transport, landing, or mandatory evidence.

Freeze one version per active wave. Digest proves byte identity, not publisher trust; use a trusted
Git revision/tag, signed package, or approved plugin provenance for distribution authenticity.

Invoke the deterministic guard as `<python> -I -B ... --git-executable <git>`, where `<python>`
resolves to Python 3.10 or newer and `<git>` is an absolute trusted regular Git executable resolved
before entering an untrusted checkout. Both flags are checked before any shadowable Python import,
but both resolved executables remain caller trust prerequisites. The bundle is an exact file allowlist: an
unpinned source, bytecode cache, symlink, helper or instruction file is method drift and stops work.
Every guard-owned Git command also forces `core.fsmonitor=false` and `core.commitGraph=false`, has a bounded timeout, and snapshots
through bounded path/blob/diff/proof ceilings. Version 2 accepts at most 64 cells, 512 total owned
paths, 64 admitted/registered worktrees, 64 external evidence requirements, 64 owner local checks, bounded per-requirement
checks/artifacts/statuses, 64 handoffs or charter generations, and 256 commits/2,048 cumulative
manifest entries in one replay range. A single blob/diff is capped at 64 MiB, unique snapshot blobs
at 256 MiB across the whole top-level operation, proof JSON at 4 MiB, one subprocess at 120 seconds,
and one top-level operation at 4,096 Git calls/600 seconds.

The physical worktree and its Git administration are stability prerequisites. If local config,
index flags, graft/shallow state, administrative files, or worktree registration changes while a
guard is running, the result is not an atomic proof: stop, restore an authorized stable state, and
rerun. The guard reduces executable/configuration ambiguity and performs stable-file rechecks; it
does not grant an exclusive lock over another process mutating the repository.

User installation makes the Skill available across repositories on one account/machine. For
recoverability, a project may vendor the exact allowlisted Skill directory and set `recoverySource`
and `recoveryDigest` in the method lock; the guard rehashes that directory and requires byte identity
with the active Skill. This is a recovery copy, not publisher provenance, so
`provenanceStatus=UNVERIFIED_LOCAL` remains truthful. Cross-machine/team distribution otherwise
needs a version-controlled source or plugin. Another agent product needs a thin
adapter and conformance check; never assume it reads Codex `AGENTS.md`.
