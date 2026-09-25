# Example projects

Throwaway projects, never committed here. They exist so that a person can see what installing
produces without reading any code. Build one with the commands below - the
[acceptance scenario](acceptance-2026-09-05.md) runs the same steps on a second - and nothing in
this repository depends on your having them.

    git init -b main ../agentlanes-fixture
    <python> -I -B cli/agentlanes.py init --plan  --repo ../agentlanes-fixture --git-executable <git>
    <python> -I -B cli/agentlanes.py init --apply --repo ../agentlanes-fixture --git-executable <git>
    git -C ../agentlanes-fixture add -- <the paths init printed under "stage">
    git -C ../agentlanes-fixture -c user.name=you -c user.email=you@example.invalid \
        commit -m "chore: adopt agentlanes"
    <python> -I -B cli/check.py --repo ../agentlanes-fixture --git-executable <git>

`init` prints the exact list to stage, so it is never guessed:

    .agents/agentlanes    .agents/agentlanes.lock.json
    .gitattributes        .agents/multi-lane-wave-method.lock.json
    AGENTS.md             CLAUDE.md

Neither the `add` nor the `commit` is a formality, and `check` says so at each step. Before
staging it reports an untracked `.gitattributes`, because pins in a file Git is not tracking
reach nobody who clones. After staging and before committing it reports that nothing is
committed, because what a clone receives is the committed tree and not the index — a project
could stage every path the install wrote, measure clean, never commit, and hand out a clone
containing none of them. That `init --apply` does not commit for you is the same reasoning once
more: a person reads the diff and decides.

**Exact paths: never `.agents`, and never `git add -A`.** The policy this package installs
forbids `git add -A` by name, and `.agents` is a directory the project shares with whatever else
it uses — staging it wholesale commits another tool's files into the commit that adopts this
package. Both mistakes were in this page and in the package's own test suite: an install
procedure contradicting the policy it installs. That is the same defect family as shipping this
package's own directory names inside a file meant for other people's repositories. The
line-ending pins, the `core/method/` path in the policy, `git add -A` and `.agents` all belong to
it.

## The vendored bundle needs no installation

The lock `init` writes names the vendored bundle as its own recovery source:

    "recoverySource": ".agents/agentlanes/method",

Measured, not assumed: the guard accepts that. Run from the project root —

    <python> -I -B .agents/agentlanes/method/scripts/wave_guard.py method-digest \
        --lock .agents/multi-lane-wave-method.lock.json --repo . --git-executable <git>

— it exits 0 and reports
`"canonicalDigest": "sha256:f32c95d926e3e0dc…"` for all eleven files, with `recoverySource`
being the same directory the guard is running from. So a project can vendor the method and
execute it with no per-user installation. Altering one hex digit of the digest, or appending one
byte to a bundle file, exits 1.

The command above is written out in full because the short form this page used to print —
`method-digest --lock --repo .` — does not run: `--lock` takes a value and `--git-executable`
is required, so it exits 2 and then 1 without ever reaching the lock. A command in a record
that nobody has run is a claim, not a measurement.

## Why the pins exist

Without `templates/gitattributes`, a checkout on a machine with `core.autocrlf=true` rewrites
the vendored bundle's line endings and the project lock is wrong on every fresh clone. Measured
in this package's own fixture, before the pins were added: `SKILL.md` came out 12792 bytes with
183 CR instead of 12609 with none, and its sha256 moved from `f8fa533c` to `b8561935`.

That measurement is recorded here rather than in the file itself. The pins ship into every
adopting project, and a comment describing something measured here would have read, in someone
else's repository, as a description of their history.

## The dated records

[acceptance-2026-09-05.md](acceptance-2026-09-05.md) and
[handshake-2026-09-05.md](handshake-2026-09-05.md) measured the v0.1 policy; "today" in them
means that date. [handshake-2026-09-25.md](handshake-2026-09-25.md) measures the v0.2 policy and
supersedes the earlier handshake record for current bytes. The acceptance record was amended in
place before the policy made superseding the rule, and its CI table predates the change its own
paragraph above the table describes: `.github/workflows/suites.yml` is current.
