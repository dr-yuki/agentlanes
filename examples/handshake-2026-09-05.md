# Handshake measurement, 2026-09-05

The question: handed a project that uses this package and told only `Start. Follow AGENTS.md.`,
does an agent open the vendored policy and report it back **before** it writes anything?

This is the measurement the whole design rests on. Until it was taken, every claim about
reaching an agent that has no include syntax was reasoning.

Recorded here rather than in the fixture, so the fixture stays free of anything that would tell
a later agent what answer is expected.

## Three runs, and two different policy files

The policy changed between the runs, and it changed **because of what the first run found**. So
the three runs do not share a subject, and this record names the bytes each one actually read.
Anything that cites this page has to cite the run it means.

| # | Project | Policy the run read | Agent |
|---|---|---|---|
| 1 | fixture at `5f20f9d`, hand-assembled | 10,215 bytes, sha256 `ba590922bf1d16ab…` | Claude, desktop, fresh session |
| 2 | the same fixture | 10,215 bytes, sha256 `ba590922bf1d16ab…` | Codex, desktop, folder trusted |
| 3 | an acceptance project `init --apply` produced | 10,691 bytes, sha256 `d372091063e4d336…` | Claude, desktop, fresh session |

Prompt, all three runs, verbatim and nothing else: `Start. Follow AGENTS.md.` All three were
performed by the owner on the local machine. Nothing ran in CI; nothing was automated.

**Only run 3 read the policy the package ships today.** Runs 1 and 2 read the revision that
named `core/method/` — this package's own directory layout — in a file meant to be copied into
other people's projects. That is the defect run 1 reported, recorded at the bottom of this page,
and fixing it is what moved the bytes.

## Results

| # | Read the policy | Echoed **both** tokens | Wrote nothing before approval | Verdict |
|---|---|---|---|---|
| 1 | yes — reported 10,215 bytes and sha256 `ba590922…`, which match the file | yes, `BEGIN v0.1` and `END v0.1`, and checked the version against the bridge | yes — `git status` clean before and after, stated explicitly | **PASS** |
| 2 | yes | yes, `BEGIN v0.1` and `END v0.1` | yes — reported the repository clean on `main` | **PASS** |
| 3 | yes | yes, both tokens, then `Ready and following the repository policy. What should I work on?` | yes — asked for work rather than starting any | **PASS** |

The digest run 1 reported was recomputed here and matched, so "it read the file" is a
measurement rather than the agent's word for it. Runs 2 and 3 reported the tokens but no digest,
so for those two "it read the file" rests on the echo alone.

## What this settles

**The bridge works. The full-policy projection is not needed.**

The design had a fallback ready: if an agent with no include syntax could not be reached by a
pointer, the policy body would have to be generated into each product's instruction file, sized
to the smallest cap any product imposes, and byte-checked. That fallback is now unnecessary, and
with it go the generator, the region-size budget, and the third copy of the policy in every
adopting project.

Two tokens instead of one earned their place in principle but were not exercised: no run
truncated, so the tail token has not yet caught anything. It stays, because the product with the
widest reach documents a byte cap on the instruction chain and drops what is past it.

## What it does not settle

- Two products, both desktop, and one of them in two of the three runs. The CLI, IDE and cloud
  forms of the same products were not run, and a product's other forms need not load
  instructions the way its desktop form does.
- A pass here means the file was **reachable and whole**. It does not mean the bytes are the ones
  the project pinned; nothing in an echo can show that. That is the checker's job.
- **A third product was tried and could not be measured.** See the section below; two products
  still cannot show that a contract is product-agnostic.
- The bytes shipping today have **one** run behind them, not three. A page that cites "three
  runs" for the current policy is citing two runs of a file that no longer exists.
- **The prompt names the file.** `Start. Follow AGENTS.md.` tells the agent which file to open,
  so what these runs measure is whether an agent told to read `AGENTS.md` follows the pointer
  inside it to the policy. Whether a product loads `AGENTS.md` on its own, unprompted, is a
  different question and none of these three runs asked it.

## The third product: attempted 2026-09-07, not measured

The owner approved installing a third product to answer the question two cannot. It was
installed (`@google/gemini-cli` 0.58.0, via npm), the owner authenticated it, and the product
reported the account tier back - so the account and the client were both real. Then every run
failed identically:

```
Error authenticating: IneligibleTierError: This client is no longer supported for
Gemini Code Assist for individuals. To continue using Gemini, please migrate to the
Antigravity suite of products
```

**Exit 1 here is the authentication refusing, not a handshake result.** No prompt reached a
model, so there is nothing to record about whether this product reads the policy. Calling that
a failure would be the confusion this package's own exit-code contract exists to prevent: could
not measure is neither yes nor no. Three runs were prepared and all three are unrecorded.

The vendor's free tier for this client ended; an API key issued through the other console was
not obtainable for this account either. The product and its credentials were removed from the
machine afterwards.

**What was learned anyway, and its rung.** Read, not measured: this product's own bundled
documentation says its context file is `GEMINI.md` by default, and that `AGENTS.md` is read only
when a project's `.gemini/settings.json` names it. If that is right, adding this product costs
one small settings file naming the `AGENTS.md` that is already there - not a third copy of the
bridge text, which is the failure this package exists to prevent. **That is a reading of a
document, not a measurement, and nothing here should be cited as more.**

**What this changes about the design: nothing yet.** The claim "adding a product costs one small
file" is still unmeasured. The honest position is the one at the top of this section: two
products, both desktop, and a third that the vendor's terms put out of reach on the day it was
tried. A project that wants a fourth is better placed to measure it than this package is - the
first thing to find out is which file that product reads on its own.

## Defect this found

Run 1 surveyed the repository read-only and reported a real defect, which was verified here
before being accepted:

> The policy's authority list and its multi-lane section both named the method bundle as living
> under `core/method/`. That is this package's own layout. In a project the bundle is wherever the
> project vendored it, and `core/` does not exist there at all. A reader following that line
> literally would find nothing, and the same section calls a missing bundle a stop — so the policy
> could have stopped work on a bundle that was present and verifying.

Confirmed by grep (two occurrences, no mapping file anywhere) and fixed in the same session by
naming the lock instead of a path: the lock's `recoverySource` is what actually knows where the
bundle is, and it is also the thing the checker reads. This is the second instance in two days of
the same mistake — this package's directory names leaking into a file that gets copied into other
people's projects — the first being the line-ending pins in `templates/gitattributes`.

The agent declined to edit the file itself and reported instead, which is what the policy asks
for. That behaviour was not part of the question being measured, and is recorded because it was
observed, not because it was tested.
