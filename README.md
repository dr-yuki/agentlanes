# agentlanes

> **Are you an AI agent asked to install this?** Read [docs/for-agents.md](docs/for-agents.md)
> first and follow it step by step. It tells you which questions to ask the user before you
> change anything.

**One repository policy that every AI coding agent reads, and a checker that proves the
policy everyone reads is the one you committed.**

Teams now run more than one AI agent product in the same repository. Each product reads its own
instruction file, so the rules get copied - and the copy is the one that goes stale. agentlanes
keeps **one** policy file in the repository, points every product at it with a few lines each,
and ships a checker that verifies the bytes a clone receives, not the bytes on your disk.

It also vendors a method for running several agents in parallel without their work colliding
(see [Parallel work](#parallel-work-the-vendored-method)).

> **Status: v0.1.0, the first release.** Measured on Windows, Linux and macOS (GitHub-hosted
> runners). The handshake below has been measured with two agent products, both in their desktop
> form. Read [What a green does not mean](#what-a-green-does-not-mean) before you rely on it, and
> [tell us](#feedback) where it did not fit.

---

## What you get

| Piece | Where it lands in your project | What it is for |
|---|---|---|
| The policy | `.agents/agentlanes/policy/REPOSITORY_POLICY.md` | The one set of rules every agent reads |
| Bridges | `AGENTS.md`, and `CLAUDE.md` if you use that product | A few lines that send each product to the policy |
| The checker | `.agents/agentlanes/cli/check.py` | Verifies all of the above, from inside your project |
| The method | `.agents/agentlanes/method/` | Optional: rules for several agents working in parallel |
| The license | `.agents/agentlanes/LICENSE` | The MIT notice, which has to travel with these copies |
| Two locks | `.agents/agentlanes.lock.json`, `.agents/multi-lane-wave-method.lock.json` | Digests of everything above |
| Pins | a managed block at the end of `.gitattributes` | Keeps line endings stable across checkouts |

Nothing is installed outside your project and nothing is installed per user. The checker is
vendored into the project so the project can answer questions about itself.

## Get it

```
git clone https://github.com/dr-yuki/agentlanes
```

Clone it **outside** the project you will install it into - a sibling folder is fine. A copy
inside the project is itself swept as instruction files (`templates/AGENTS.md` is one), and the
check goes red. There is nothing to build and nothing to install on your machine: the installer
and the checker are plain Python files, and everything they put into a project stays in that
project.

## Requirements

- **Python 3.10 or newer, run with `-I -B`.** Both programs refuse to run without those flags.
  CI runs every suite with 3.10 and 3.12 on Linux, macOS and Windows; 3.14 was also run on
  Windows.
- **git, passed by absolute path to the real executable** - not a command name, not a link.
  A name looked up through `PATH` is whatever happens to be first there.

Below, `<python>` is your Python executable, `<git>` the absolute path to git, and
`<agentlanes>` wherever you put this package.

## Install it into a project

If an agent is doing this for you, point it at [docs/for-agents.md](docs/for-agents.md): it
asks the same five questions before writing anything.

**1. See what it would do. This writes nothing, anywhere.**

```
<python> -I -B <agentlanes>/cli/agentlanes.py init --plan --repo <project> --git-executable <git>
```

It prints every path it would change, the exact list of paths you will stage, and five questions
to settle before you go on:

1. Which agent products will work in this repository?
2. Will they take turns in one checkout, or work at the same time in separate worktrees?
   (At the same time in one directory is not an option.)
3. Which of them, if any, may create commits? Start with none and grant one at a time.
4. May any of them send this code to a hosted service? Answer separately for each.
5. If the repository already has instruction files, should they be kept, folded into the
   project section, or removed by hand first?

The paths depend on the answer to the first question. Once you have it, run the plan again with
the `--agents` you will pass to `--apply`.

**If the project already has its own `CLAUDE.md`, the plan stops here** with exit `2` and prints
only the reason - not the paths, and not the five questions. `CLAUDE.md` is a whole generated
file, so applying would discard yours. Fold what it says into `AGENTS.md` and delete it (or move
it aside), then run the plan again. If `claude-code` is one of your `--agents` and losing the
file is what you want, pass `--replace-bridges` to say so. A `CLAUDE.md` that is a link, or one
kept while `claude-code` is not selected, is refused whatever the flags. Nothing has been
written at that point.

**2. Write it.** This writes those paths and nothing else. It does not commit.

```
<python> -I -B <agentlanes>/cli/agentlanes.py init --apply --repo <project> --git-executable <git>
```

Use `--agents` to choose products (default `codex,claude-code`; see
[Agent products](#agent-products)). If a write fails part-way, every file it had already written
is put back byte for byte, and the run says "nothing was left changed" only when that is true of
every file. Directories it created for them can be left behind, empty.

**3. Stage exactly the paths it printed, and commit.**

```
git -C <project> add -- .agents/agentlanes .agents/agentlanes.lock.json \
    .agents/multi-lane-wave-method.lock.json .gitattributes AGENTS.md CLAUDE.md
git -C <project> commit -m "Adopt agentlanes"
```

That is the list for the default `--agents`. It depends on which products you chose - with
`--agents codex` alone there is no `CLAUDE.md` - so stage exactly the `stage` list that `--apply`
printed: it comes from the same `--agents` as the files it wrote. A list from a plan for other
products names files that were never written, and `git add` stops at the first of them and
stages nothing.

Never `git add .agents` and never `git add -A`: `.agents` is shared with whatever other tools
your project uses, and staging it wholesale commits their files into this change.

**4. Check it.**

```
<python> -I -B .agents/agentlanes/cli/check.py --repo <project> --git-executable <git>
```

A fresh install that has been committed exits `0`. **Before you commit, it exits `1`, and that
is correct**: what somebody who clones your repository receives is the committed tree, not your
working tree and not the index. Pins in a file git is not tracking protect nobody who clones.

Run the check in CI, and after anybody - person or agent - edits any of these files. In GitHub
Actions, check out with full history, or the check cannot measure
([why](#a-checkout-the-checker-cannot-measure)):

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- shell: bash
  run: |
    GIT_REAL="$(python -c 'import os,shutil;print(os.path.realpath(shutil.which("git")))')"
    python -I -B .agents/agentlanes/cli/check.py --repo . --git-executable "$GIT_REAL"
```

## Existing projects

Nothing here destroys your content unless you pass `--replace-bridges`, which is how you say that
is intended.

- An existing `AGENTS.md` keeps everything outside the generated region, byte for byte. The
  region goes **first**, because several products cap how much instruction text they read.
- An existing `.gitattributes` keeps its own lines; the managed block goes **last**, because the
  last matching line is the one in effect.
- A file whose name differs only in case from one this would write (`agents.md` beside
  `AGENTS.md`) is refused rather than renamed. Those are one file on Windows and macOS.
- An existing whole-file bridge (`CLAUDE.md`) or method lock
  (`.agents/multi-lane-wave-method.lock.json`) that differs from what this would write is
  refused, not overwritten, unless you pass `--replace-bridges` - for `CLAUDE.md`, only while
  `claude-code` is one of the `--agents`, as step 1 above describes. The project lock
  (`.agents/agentlanes.lock.json`) is always written afresh: nothing in it is yours.

## Exit codes

The checker:

| Code | Meaning |
|---|---|
| `0` | Measured, and nothing is wrong |
| `1` | Measured, and there are findings |
| `2` | **Could not measure.** Never read this as green, and never as red |

The installer exits `0` when it did what was asked, and `2` when it did not - it refused (a
collision, an existing file it would discard), or a write failed. It never exits `1`. The JSON it
prints says which: a refusal writes nothing, a failed write puts back every file it had written,
and if even that fails it lists the paths it could not restore under `notRestored`. An argument
error, a Python older than 3.10, or a run without `-I -B` also exits `2`, with the reason on
stderr instead of JSON.

Run each program on its own line. A pipe replaces its exit code with that of the last command.

## What the checker verifies

It measures rather than searching files for strings.

1. The vendored method bundle still matches its lock, and is the version this package ships.
2. The policy, the checker, the license and the templates still match the project lock.
3. Each generated region is byte-identical to its template, appears exactly once, and - in the
   instruction file - comes first.
4. The attributes that keep those bytes stable come from somewhere a clone would get, and hold.
5. No instruction file exists anywhere that the project lock does not know about.
6. The project lock itself is well formed.
7. The bridge states the same policy version the policy carries.

Every question about distribution is asked of the committed tree, and the working tree and the
index are compared with it rather than assumed equal.

### Question 5 is red on the first run in most real repositories

If your project already uses an agent product it almost certainly already has instruction files
- `.claude/commands/`, `.claude/skills/`, `.cursor/rules/`, `.github/copilot-instructions.md`.
A correct, clean install then reports

```
.claude/commands/test.md: an instruction file the project lock does not know
```

and exits 1. **That is question 5 working, not a defect:** the premise here is that there is one
policy, so a second place that tells an agent what to do is exactly what it looks for. But it is
the first thing you will see, and **there is no flag that declares those files known.** Your
options are to fold their content into the project section of `AGENTS.md`, to delete them, or to
decide this is not for you yet. `init --plan` asks you about this before writing anything - it
is the fifth of the questions it prints.

Two cases where the same message is not about your project and there is nothing to fix: a **git
submodule** carries instruction files the superproject cannot change, and so does a vendored
dependency you did not write. The sweep does not know the difference.

### A checkout the checker cannot measure

The vendored method's guard refuses to run in a **shallow clone**, beside a **graft file**, or
inside a **submodule** - git writes `core.worktree` there and it cannot be removed. Those give
exit 2, "could not measure": never green, never red. The common one is CI, because
`actions/checkout` fetches depth 1 by default, so set `fetch-depth: 0` as in the example above.
This package's own CI asks `actions/checkout` both ways on every run: an adopted project checked
out at the default depth exits `2`, and the same project with `fetch-depth: 0` exits `0`. For a
submodule there is no workaround; run the check in the repository that owns the code.

## What a green does not mean

Each of these is a real limit. They are written down because a green that does not state its
scope invites somebody to lean on it for something it never covered.

- **It detects drift, not a deliberate attacker.** Somebody who edits these files on purpose can
  edit the checker too, and a tampered checker can report anything.
- **The instruction-file sweep uses a fixed list** of file names and directories. Products invent
  new ones; a file it does not recognise is a file it does not report.
- **It sweeps files that tell an agent what to do, not files that grant it permission.**
  `.claude/settings.json` and `.mcp.json` are not on the list, and they are the ones that
  pre-approve tools or attach hooks. A pull request that adds one passes.
- **Only the generated region of `AGENTS.md` is checked.** Everything below it is your project's
  own text, kept byte for byte - which also means a line appended there is never compared with
  anything. The policy ranks that text as authority, so read changes to it as you would read
  changes to your build script.
- **A submodule is a different repository.** Its instruction files are invisible until somebody
  runs `submodule update`, so the same commit can answer question 5 differently before and after.
- **Files your project ignores** are left out of the working-tree half of that sweep.
- **A lock and the files it pins, changed together, still agree with each other.** The one
  exception is the method bundle, whose digest is a constant inside the checker.
- **The handshake has been measured with two agent products**, both in their desktop form.

## Agent products

`--agents` takes a comma-separated list:

| Value | What it installs |
|---|---|
| `codex` | Nothing extra - the product reads `AGENTS.md` itself |
| `claude-code` | `CLAUDE.md`, which imports `AGENTS.md` and carries no rule of its own |
| `generic` | Nothing extra - for any product that reads `AGENTS.md` |

Bridges never copy the rules. A rule written in two places is two places to keep in step, and the
copy is the one that goes stale.

### Adding your own product

The package does not depend on how any product loads instructions. Adding one takes four steps,
and the last is the one that matters:

1. **Find which file the product reads on its own.** Its documentation says; test it anyway.
2. **If it reads `AGENTS.md`**, use `generic`, then go to step 4.
3. **If it reads something else**, either configure it to read `AGENTS.md` (some products take a
   project settings file for this), or add a bridge file that points to `AGENTS.md` - a few lines
   that carry no rule of their own.
4. **Measure it** with the handshake below. Do not assume.

### The handshake

The policy's first and last lines are tokens with the policy version on each. Open a fresh session
in the project and say only:

```
Start. Follow AGENTS.md.
```

A product that reached the policy echoes both lines in its first reply and writes nothing before a
human approves. Two tokens rather than one, because a product that truncates long instructions
drops the end - and a missing end token is how you would find out.

## Parallel work: the vendored method

`.agents/agentlanes/method/` is a method for running several agents at the same time, each in its
own worktree, integrating into one reviewed result: exact path ownership per agent, a written
charter before anybody writes, verified hand-offs, and one integration owner.

It is for **several writers in isolated worktrees aiming at one integration**. It is not for one
agent working alone, for read-only research in parallel, or for two writers sharing one directory.
Its own `SKILL.md` says when to use it and when not to.

To set up the folders themselves - where they go, what a new one does not contain, what they
all share, how to check them, and how to keep each lane working with a goal - see
[docs/worktrees.md](docs/worktrees.md). Whether to work in parallel at all is the user's
decision; most projects never need it.

The bundle is pinned by digest and runs from inside the project - there is nothing to install per
user:

```
<python> -I -B .agents/agentlanes/method/scripts/wave_guard.py method-digest \
    --lock .agents/multi-lane-wave-method.lock.json --repo . --git-executable <git>
```

## Undoing a change

Use `git revert`. There is nothing here a revert cannot undo, so a rollback command of its own
would be a second way to do what git already does.

## Developing this package

```
<python> -I -B cli/test_check.py            --git-executable <git>
<python> -I -B cli/test_init.py             --git-executable <git>
<python> -I -B cli/test_guard_supplement.py --git-executable <git>
```

The vendored method's own suite needs the same git in an environment variable:

```
WAVE_GUARD_TEST_GIT_EXECUTABLE=<git> <python> -I -B core/method/scripts/test_wave_guard.py
```

CI runs all four on Linux, macOS and Windows with Python 3.10 and 3.12, on every push and pull
request and once a week. It also installs into a fresh project and checks it, and checks an
adopted project through `actions/checkout` at the default depth and with full history.

**The method bundle is byte-pinned.** Its digest is a constant in `cli/check.py`, so changing the
bundle means changing the checker too. That is deliberate: a bundle that could be re-sealed by
editing a lock inside the project would agree with itself.

| Path | What it is |
|---|---|
| `cli/agentlanes.py` | The installer (`init --plan`, `init --apply`) |
| `cli/check.py` | The checker, vendored into each project |
| `cli/test_*.py` | The suites |
| `core/policy/REPOSITORY_POLICY.md` | The shared policy |
| `core/method/` | The vendored multi-agent method, byte-pinned |
| `templates/` | `AGENTS.md`, `CLAUDE.md` and the `.gitattributes` pins |
| `examples/` | An acceptance scenario and the handshake record, with their measurements |
| `docs/` | Instructions for the agent doing an install, and for setting up parallel lanes |
| `LICENSE` | MIT. The installer copies it into each project beside the vendored files |

## Feedback

Report problems, and say where it did not fit your project, as
[GitHub issues](https://github.com/dr-yuki/agentlanes/issues). The most useful report names
the command you ran, the exit code, and the JSON it printed.

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 dr-yuki.

The installer copies the same file to `.agents/agentlanes/LICENSE`: the MIT notice has to go
with every copy, and the vendored files are copies. The project lock pins it like the policy,
so the checker notices if it is edited.
