# Installing agentlanes: instructions for the agent doing it

**You are an AI agent, and a user has given you this repository's address and asked you to use it
in their project.** Follow these steps in order. Several of them are questions for the user, and
those are not optional: the user decides, you do not.

## 0. Tell the user what this is, and ask whether to go on

In a few sentences, in your own words:

- agentlanes puts **one policy file** in the project that every AI agent reads - whichever product
  it is - so rules stop drifting apart between products.
- It adds a **checker** that verifies the committed files are the ones everyone reads.
- It includes an **optional method** for several agents working at the same time.
- It writes about twenty files: under `.agents/`, plus `AGENTS.md`, `CLAUDE.md` if they use that
  product, and a block at the end of `.gitattributes`. **It changes nothing else, and it does not
  commit.**

Ask whether to continue. Stop if they say no.

## 1. Get the package and the tools

- Clone this repository **outside** the user's project - a sibling folder or a temporary directory.
  Inside the project it would end up in their commit.
- Find **Python 3.10 or newer**. Both programs must be run with `-I -B`, and refuse otherwise.
- Find the **absolute path of the real git executable** - not a command name, not a link. Resolve
  it first: on Windows, `where git`; elsewhere, `command -v git` followed by resolving any symlink.

Below, `<python>`, `<git>`, `<agentlanes>` and `<project>` stand for what you found.

## 2. Plan, and show the user

```
<python> -I -B <agentlanes>/cli/agentlanes.py init --plan --repo <project> --git-executable <git>
```

This writes nothing, anywhere. Show the user the paths under `wouldChange`. This first plan uses
the default products, and the paths depend on the answers in step 3, so you will plan again in
step 4 before anything is written.

## 3. Ask the five questions

`--plan` prints them under `answerFirst`. Ask them **in one message and wait for the answers.**
How to put each one:

1. **Which agent products will work in this repository?** This becomes `--agents`: `codex`,
   `claude-code`, `generic` (any product that reads `AGENTS.md` itself). The default is
   `codex,claude-code`.
2. **Will agents take turns, or work at the same time?** Offer two choices, and recommend the first:
   - **One folder, taking turns** - recommended. The shared policy works in full this way.
   - **Separate worktrees, at the same time** - only if they really want several agents writing
     concurrently. It needs more setup; see [worktrees.md](worktrees.md).

   If they are unsure, recommend the first. **Never create worktrees without an explicit yes.**
3. **Which agents may create commits?** Start with none. If you are not allowed to commit, you will
   stop after staging and hand the commit to the user.
4. **May any agent send this code to a hosted service?** Record the answer for each product and
   keep to it.
5. **The project already has instruction files - keep, fold in, or remove first?** Only if it does.
   An existing `AGENTS.md` keeps everything outside the generated region; an existing whole-file
   bridge such as `CLAUDE.md` is refused unless `--replace-bridges` is passed, and passing it is
   the user's call.

## 4. Plan again with their answers, then apply with the same options

The paths depend on the answers - with `--agents codex` alone there is no `CLAUDE.md` - so plan
once more with exactly the options you will apply with, and show the user what changed:

```
<python> -I -B <agentlanes>/cli/agentlanes.py init --plan --repo <project> --git-executable <git> \
    --agents <their answer to question 1>
```

Then apply with the same options - the same `--agents`, and `--replace-bridges` only if the user
chose it in question 5:

```
<python> -I -B <agentlanes>/cli/agentlanes.py init --apply --repo <project> --git-executable <git> \
    --agents <their answer to question 1>
```

It writes the planned paths and nothing else, and prints the `stage` list again. If it refuses,
report the reason to the user as it was printed; do not work around it.

## 5. Stage exactly, and commit only if allowed

Stage **exactly the `stage` list that the apply in step 4 printed** - not the one from step 2,
which was planned before the user chose. A list planned for other products names files that were
never written, and `git add` then stops at the first of them and stages nothing. Never
`git add .agents`, never `git add -A`: `.agents` is shared with other tools, and staging it
wholesale commits their files.

```
git -C <project> add -- <each path in the stage list>
```

Commit only if question 3 allowed you to. Otherwise stop here and ask the user to commit.

## 6. Check

```
<python> -I -B .agents/agentlanes/cli/check.py --repo <project> --git-executable <git>
```

Run it from inside the project, on its own line - a pipe replaces the exit code.

- `0` after the commit is the result you want.
- **`1` before the commit is correct**, not a failure: the checker measures what somebody who
  clones the project receives, and that is the committed tree.
- `2` means it **could not measure**. Report the reason; never present `2` as success or failure.

## 7. Suggest the handshake

The best proof is a **fresh** session of each product, which has never seen this conversation. Ask
the user to open one in the project and say only:

```
Start. Follow AGENTS.md.
```

It should echo the policy's first and last lines and write nothing before the user approves.

## 8. If they chose parallel

Follow [worktrees.md](worktrees.md). Ask its questions again before you create anything.

If they want each lane to keep working without being prompted, the same page shows how to give a
lane a goal. Whether to set one is also their decision.

## Report back

Tell the user: what was installed, the checker's result, which answers you acted on, and anything
you did not do because it was theirs to do - the commit, the handshake, the worktrees.

## Do not

- Edit anything under `.agents/agentlanes/`. The checker reports any change, and that is its job.
- Copy the policy's rules into `CLAUDE.md` or any other file. A rule written in two places is two
  places to keep in step, and the copy is the one that goes stale.
- Create worktrees, commit, push, or change git configuration without the user's go-ahead for that
  exact action.
