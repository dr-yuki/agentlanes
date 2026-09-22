# Parallel lanes with git worktrees

Several agents writing **at the same time** need one folder each. This page is how to make those
folders so they work from the first day. Every rule here was measured on git 2.54 before it was
written down; the ones that look fussy are the ones that went wrong.

**If the agents take turns, you do not need any of this.** One folder, one writer at a time, and
the shared policy works in full. Parallel lanes cost setup, coordination and an integration step;
they pay off only when real work can run side by side.

This page covers the folders. What happens inside them - who owns which files, how work is handed
over and integrated - is the method vendored at `.agents/agentlanes/method/`. For multi-writer work
that method is the authority, and nothing here overrides it.

## Before creating anything: ask

**The user decides whether to work in parallel. Do not decide it for them.** Put the choice plainly:

- **One folder, agents take turns** - recommended. Nothing more to set up.
- **Separate worktrees, agents write at the same time** - for when two or more agents really need
  to work concurrently on work that splits into separate files.

If they choose parallel, agree on these before running a single command, and show them your
proposal rather than choosing alone:

1. How many lanes, and a short name for each.
2. **Which files each lane owns.** Lanes must not overlap: two writers on one file collide whatever
   folders they are in. If the work cannot be split by files, do it in turns instead.
3. Which agent works in which lane.
4. Who integrates the lanes back into one result.

Parallel is worth it only when all of these hold: at least two agents write at the same time, the
work splits into separate files, one party integrates, and the time saved is larger than the cost
of handing work over and checking it again.

## Preconditions

- agentlanes is installed **and committed**, and `check.py` exits `0`. Every lane starts from the
  committed tree, so every lane then reads the same `AGENTS.md`.
- The main folder is clean: `git status --porcelain` prints nothing.

## Where the folders go

**Beside the main folder, never inside it.** Name them `<project>-<lane>`:

```
Documents/
  myapp/            <- the main folder
  myapp-api/        <- lane "api"
  myapp-web/        <- lane "web"
```

A worktree created inside the main folder shows up there as an untracked directory (`?? inner/`),
where one careless `git add` commits it.

## Write the lanes down

Record the lanes in the **project section of `AGENTS.md`** - the part below the generated region,
which belongs to the project and is never regenerated. Every lane checks out the same committed
`AGENTS.md`, so every agent reads the same map. Copy and fill in:

```markdown
## Lanes

One writer per folder. Say which files you are taking before you start. If you need a file another
lane owns, hand the request to that lane; do not edit it from yours.

| Folder | Branch | Owns | Done when | Held by | Since |
| --- | --- | --- | --- | --- | --- |
| `myapp` | `main` | integration only; nothing is developed here | - | - | - |
| `myapp-api` | `lane/api` | `server/`, `api/` | `npm test --workspace api` exits 0 | Agent A | 2026-01-15 |
| `myapp-web` | `lane/web` | `web/`, `public/` | `npm run build --workspace web` exits 0 | Agent B | 2026-01-15 |

Replace your own row when you take or hand over a folder. A row that has not moved in weeks is a
row to distrust, not to act on.
```

Commit that change from the main folder **before** creating the lanes, so every lane starts with it.

## Create a lane

From the main folder, one command per lane, **one new branch per lane**:

```
git -C <project> worktree add ../<project>-<lane> -b <lane-branch>
```

- **Never copy the folder instead.** A copy has its own history, and joining two histories later is
  the work worktrees exist to avoid. Worktrees share one history: a commit made in one lane is
  visible from every other lane at once.
- **A branch can be open in only one worktree.** Git refuses a second one with
  `already used by worktree`. That is a protection, not an error to work around.

## What a new lane does not have

A worktree contains **only what git tracks**. Measured, a fresh lane had the committed files and
none of these:

- `.env` and other local settings
- `node_modules/`, virtual environments, build output, caches

So in each lane:

- **Run the project's own setup again** - `npm install`, `pip install -r requirements.txt`, or
  whatever the project uses.
- **Local settings and secrets are copied, never committed.** If a lane needs `.env`, copy it from
  the main folder **with the user's agreement**. Committing it so the other lanes "get it" publishes
  it to everyone who ever clones the repository.

## What every lane shares

Measured: these live once, in the main folder's `.git`, and every lane sees the same one.

- **Repository git configuration.** A setting made with `git config` in one lane is in effect in all
  of them.
- **Hooks.**

Treat both as shared state. **Before changing one, tell the user and the other lanes.** A single
credential setting changed in one folder has stopped every lane's pushes at once; nothing in any
lane's own files showed why.

## Check the lanes

Right after creating them, every lane should be at the same commit as `main`, clean, and reading
the same `AGENTS.md`. The vendored guard measures exactly that:

```
<python> -I -B .agents/agentlanes/method/scripts/wave_guard.py verify-worktrees \
    --repo <project> --main-ref main --git-executable <git>
```

**Know what this answers.** It checks that every lane is *synchronized with main*. That is true
right after creation and again at the end, once the lanes' work is integrated and every lane has
caught up. **In between, while lanes carry their own commits, it is red by design.** A red there
is not a broken setup.

- `--main-ref` defaults to `origin/main`. A project with no remote must pass `--main-ref main`;
  without it the guard stops with `Needed a single revision`.
- The guard ignores the git configuration of whoever runs it, on purpose. On a machine where
  `core.autocrlf` is set system-wide or user-wide, a file with no end-of-line attribute can look
  modified to the guard while `git status` shows nothing. agentlanes pins its own files, so they do
  not cause this; the project's other files can. Whether to pin line endings across the whole
  project is the user's decision.

Each lane's agent can also run `check.py` in its own folder. It measures that folder's committed
state, so a lane that edits the generated region of `AGENTS.md` is caught there.

## Keep a lane working with a goal

An agent in a lane stops when its turn ends, and waits there until somebody sends the next
message - so a turn that ends with nothing queued stops the lane. Claude Code and Codex both have
a `/goal` command that gives the agent a target to keep working toward. Claude Code's
documentation says that with a goal set, Claude keeps working without being prompted for each
step, starting another turn until the condition holds.

**What a goal does not change.** It keeps an agent working on what it is already allowed to do. A
lane that may only review stays a reviewer. A question only the user can answer still waits for
the user, a broken build or an expired sign-in still stops every lane, and a goal gives nobody a
permission they did not have. If only one lane may write, goals will not make the others writers.

**Finishing is judged, not measured.** Claude Code checks the goal after every turn with a separate
small model that reads only the conversation: it runs no commands and opens no files. Codex's
documentation does not say how it decides. Write the goal for the stricter of the two:

1. **End on a command's result that is shown in the conversation.** "`npm test` exits 0 and its
   output is shown" can be judged; "the feature works" cannot.
2. **Make stopping to report a correct way to finish.** A goal pushes toward "done", and pressure
   to finish is how a lane ends up working around a rule. Name what stops the lane instead: a file
   another lane owns, a decision only the user can make, anything the project forbids or asks
   about first, the same blocker coming back twice.
3. **Put a limit in it,** such as "stop after 30 turns". Claude Code's documentation recommends a
   turn or time clause for exactly this.

**Point at the Lanes table; do not copy it.** What "done" means for each lane belongs in the
table's `Done when` column, where every lane reads the same committed copy, and the goal only names
the lane. Codex's documentation gives the same advice for anything long: put the details in a file
and point the goal at it. A goal that restates a lane's files is a second copy that nothing keeps
in step. Both products cap a goal at 4,000 characters.

Fill in the lane name and set it in that lane's session:

```
/goal Work as lane <lane> in the Lanes table of AGENTS.md: take the next item in the files that
lane owns, and keep going. Done when the lane's "Done when" check has run and passed and its
output is shown in this conversation; then say what you finished and what you are still holding.
Stop and report instead of continuing if you need a file another lane owns, a decision from the
user, or a step this project forbids or asks about first, or if the same blocker comes back twice.
Stop after 30 turns in any case.
```

If the lanes work under the method's charters, a lane's next work and its finish are already
written there - `nextWork`, and `verify-handoff` passing for that lane - so point the goal at those
instead of the table.

Before you set one in every lane:

- **Try one lane first.** Nothing on this page has been measured in a lane yet. Watch how long it
  keeps going, whether it stops where it should, and what it costs, then decide about the rest.
- **Nobody approves each step any more - decide whether that is acceptable.** A goal does not
  change the permission mode: in Claude Code's manual mode the lane still stops to ask before tool
  calls your settings do not already allow. Running unattended is the user's decision, and a rule
  written only in `AGENTS.md` is not enforced by any permission mode.
- **One goal at a time.** In Claude Code, setting a new goal replaces the active one. `/goal clear`
  removes it in both products.

Read against [Claude Code's `/goal` page](https://code.claude.com/docs/en/goal) and [Codex's
command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli) on 2026-09-14,
and the Claude Code page again on 2026-09-22. Both products are changing; check the current pages
before relying on a detail.

## Remove a lane

When its work is integrated:

```
git -C <project> worktree remove ../<project>-<lane>
```

**Do not just delete the folder.** Measured: the registration stays behind (`git worktree list`
marks it `prunable`), and the lane's branch stays locked - opening it anywhere else fails with
`already used by worktree` - until `git worktree prune` is run.

## Next

For assigning exact files, handing work between lanes, and integrating: read
`.agents/agentlanes/method/SKILL.md`, then `references/protocol.md`, before any lane writes.
