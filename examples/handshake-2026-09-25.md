# Handshake measurement, 2026-09-25

The question is the one [handshake-2026-09-05.md](handshake-2026-09-05.md) asked: handed a
project that uses this package and told only `Start. Follow AGENTS.md.`, does an agent open the
vendored policy and report it back **before** it writes anything?

That record measured the v0.1 policy and stays as it was. This one measures the v0.2 policy, and
supersedes it for the bytes this package ships now.

## Two runs, one policy file

| # | Project | Policy the run read | Agent |
|---|---|---|---|
| 1 | fixture at `666c6d0`, made by `init --apply` from this package's 0.2.0 files | 12,977 bytes, 219 lines, sha256 `db052314c6264fce…` | Claude Code, desktop, fresh session |
| 2 | the same fixture, unchanged | the same file | Codex, desktop, new session |

Prompt, both runs, verbatim and nothing else: `Start. Follow AGENTS.md.` Both runs were performed by
the owner on the local machine, and the owner relayed each first reply verbatim. Nothing ran in
CI; nothing was automated.

## Results

| # | Read the policy | Echoed **both** tokens | Wrote nothing before approval | Verdict |
|---|---|---|---|---|
| 1 | yes - reported all 219 lines, and hashed the seven files the project lock pins with its own tool before running the checker | yes, `BEGIN v0.2` and `END v0.2`, and compared them with the bridge's `Policy version:` | yes - reported `git status` clean after its checks | **PASS** |
| 2 | yes - reported reading `AGENTS.md` and the full policy, and the checker passing at `666c6d0` | yes, `BEGIN v0.2` and `END v0.2`, as the first two lines of its reply | yes - reported no changes on `main` | **PASS** |

Measured here after both runs: the fixture was still at `666c6d0` on `main`,
`git status --porcelain --untracked-files=all --ignored` printed nothing, and the vendored checker
exited `0` with no findings. The seven digests run 1 reported as matching were recomputed here and
matched, and so did its claims that `AGENTS.md`'s region and `CLAUDE.md` equal their templates.
So "it wrote nothing" is a measurement of the working tree. "It read the file" rests on each run's
report and its echo; run 1's own hashing adds to that, run 2's report does not.

## What this settles

The v0.2 policy - 12,977 bytes, about a fifth larger than the 10,691 bytes of v0.1 - reached both
products whole: both tail tokens arrived, with the version the bridge states.

## What it does not settle

- **Two products, both desktop**, as before. Their CLI, IDE and cloud forms were not run.
- A pass here means the file was **reachable and whole**, not that its bytes are the ones the
  project pinned. That is the checker's job, and here it was run separately.
- **The prompt names the file.** Whether a product loads `AGENTS.md` on its own, unprompted, is
  still a different question that neither run asked.
- **Neither run truncated**, so the tail token has still not caught anything.
- **The replies were relayed.** What each session did is what it reported; only the working tree,
  the digests and the checker were measured here.

## Observed, not tested

- Run 1 wrote the two tokens at the end of its first turn, after its own integrity checks and
  several progress lines. Run 2 wrote them first. Both are "in your first reply", which is all the
  bridge asks.
- Run 1 reported, unasked, that the method lock records `provenanceStatus: UNVERIFIED_LOCAL` with
  no source revision, and that section 10 makes that a stop for multi-writer waves while
  single-writer work is unaffected. The first half is what the lock and section 10 say. The second
  half is its reading of section 10's scope, not text the policy contains.
- Run 2 reported that git warned it could not access the global ignore file. No `core.excludesFile`
  is configured on this machine, so that is git's default location. Why that session could not
  reach it was not measured; the checker passed in that session by its report, and again here.
