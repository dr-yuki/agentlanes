# Recovery and Stop Matrix

Use this reference when a wave no longer matches its charter or evidence.

| Condition | Required response |
| --- | --- |
| writer path is unknown or overlaps | do not activate; assign owner-only or serialize |
| multiple writers share one working directory | stop writes; isolate workspaces or serialize |
| dirty or unrelated change appears | stop and return to the holder; do not reset/stash/clean |
| unchartered path or rename endpoint | stop; new charter or explicit reassignment |
| semantic conflict despite disjoint paths | add owner seam/integration test or split |
| contributor conflict | original owner resolves; cross-boundary conflict requires new charter |
| incoming baton differs | do not merge around it; author replays on the correct baton |
| path/mode/blob/patch mismatch | reject byte-preserving claim; rebuild handoff with explanation |
| baseline moved | linked same-scope replacement whose new baseline strictly descends from the prior baseline (new base/tree + prior path/digest), then author-owned ordered replay |
| predecessor charter path/digest or same-scope validation fails | do not assign work; repair the proof bundle or start a new wave |
| method digest changed | restore frozen bytes or stop and start a new-method charter |
| higher-level safety rule changed | apply immediately; stop/replace if incompatible |
| contributor unavailable | explicitly reassign ownership in a new charter |
| reviewer begins fixing | change role and path assignment; prior verdict is not independent |
| final head changes after review/CI | invalidate all head-bound evidence and rerun |
| required platform evidence absent | report UNVERIFIED, never inferred PASS |
| mandatory CI exceeds planned one cycle | run it; cadence never waives mandatory gates |
| signed/merge-preserving history required | stop until another transport profile is specified |
| only unreachable local SHAs prove handoff | preserve durable closeout or immutable evidence first |
| handoff sequence/actor/workspace/current physical worktree/previous link differs from the charter or preceding declared closeout entry | reject it; original author rebuilds the exact handoff from the admitted workspace |
| fan-out/review attestation source or evidence requirement/check/artifact/status ID differs, including case | recollect the named authority; never rename a result into compliance |
| PR synthetic parents differ or its tree differs from the reviewed head | mark evidence wrong-subject and recollect on the exact Git graph/tree |
| proof, active Skill, or recovery path escapes, aliases, or traverses a symlink/reparse parent | reject it and rebuild below one regular directory; do not resolve away the hostile parent |
| integration owner becomes bottleneck | split by truthful failure/rollback domain, not arbitrary size |
| workspace admission is dirty, non-0/0, duplicated, unregistered, wrong-head or wrong-instruction | do not activate; restore isolation/synchronization and regenerate the charter |
| workspace `physicalIdentityDigest` or current registered real checkout differs | reject the moved/copied label; restore the same admitted physical checkout or start a new wave because same-wave replacement preserves physical identity |
| graft, shallow repository, hidden index flag, executable driver or lazy-fetch configuration is present | stop; remove only through authorized repository administration, then rerun from a stable state; commit-graph acceleration is forced off by the guard rather than repaired |
| local Git config/index/admin/worktree registration changes during verification | discard the result as non-atomic; stabilize the repository and rerun, never accept the raced measurement |
| owner local verification or independent review is absent/wrong-head/wrong-source/non-independent actor | do not start external CI or close; rerun on the frozen integration head |
| installed Skill is unavailable but a recoverySource is pinned | copy only the exact vendored allowlist into a new install, remeasure the digest, and retain UNVERIFIED_LOCAL provenance |
| closeout substitutes another main ref, instruction path, or instruction blob | reject it; synchronize using the final charter admission identity and remeasure |
| handoff `nextWork` differs from the charter cell queue or rollback authority is not owner/conductor | reject the proof; regenerate it from the immutable charter, without editing the charter to fit history |
| fan-out closeout cannot remeasure every admitted cell at the frozen subject | remain open/UNVERIFIED; restore the exact read-only workspaces or create a new fan-out |
| verifier is launched without Python 3.10+ `-I -B` | stop and resolve an approved runtime; never waive isolation or bytecode suppression |
| `--git-executable` is missing, relative, command-only or non-regular | stop before entering the checkout and resolve a trusted absolute regular Git executable |
| worktree registry exceeds 64 entries | reduce it only through separately authorized repository administration or use an approved bounded clone; never truncate the registry proof |
| blob/call/deadline ceiling is exhausted | report no proof; split the operation or scope through an approved new charter, never raise the limit ad hoc or accept partial output |

Replacement means the same scope, roles, decisions, evidence requirements and method lock on a strict
descendant baseline, with changed base/tree and a predecessor proof path/digest. Changed scope, owner decision, authority,
path, semantic seam, or method bytes is a new wave.
