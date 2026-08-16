# Mandatory workflow

Every task runs through these gates in order. Higher gate answers the question -> stop, don't
descend into a lower one for that same question. For any request to **build, add, change, or fix**
code, gates 1, 3, 4, 5 and 6 are not optional and run every time. The failure mode to avoid:
ponytail and superpowers get used but software-practices gets skipped, grill-me isn't run by
default, and the review gate gets skipped in a hurry to raise the PR - don't skip any of them.

## 0. Branch first - before touching anything

Every task starts on a fresh short-lived branch off trunk. No exceptions, no "quick fix on the
current branch". Literal first action - before the graph, before reading source, before grill-me.

- Branch name: `type/short-slug` (`feat/…`, `fix/…`, `chore/…`, `docs/…`) matching the work.
- Never commit task work onto trunk or reuse an unrelated existing branch. One branch = one logical
  task -> PR -> trunk.
- If already on a task branch that matches the *current* request, continue it; otherwise cut a new
  one from up-to-date trunk.
- Confirm before any destructive git op (force-push, reset --hard, branch delete).
- Exception: edits only to gitignored files (docs scratch, `CLAUDE.md`, `.claude/settings*`) aren't
  commits - no branch needed.

## 1. graphify - the codebase cache, checked before anything else

`~/.claude/skills/graphify/SKILL.md`. Trigger: `/graphify`. One graph, one place: `graphify-out/`
at the repo root. For any question about the codebase, architecture, file relationships, or
"where/what/how" - **check for it and query it before reading source**, on every task.

- If `graphify-out/graph.json` exists, it is the cache, not raw grep - query it first:
  - `graphify query "<question>"` - a scoped subgraph for the task at hand.
  - `graphify path "<A>" "<B>"` - how two things relate.
  - `graphify explain "<concept>"` - a focused concept map.
  - Prefer the scoped subgraph over `GRAPH_REPORT.md`/raw grep.
- `graphify-out/wiki/index.md`, if present, for broad navigation over source browsing.
- `graphify-out/GRAPH_REPORT.md` only for a broad architecture review, or when query/path/explain
  came up short.
- If `graphify-out/` doesn't exist yet, say so, then build it with `graphify update .` before
  non-trivial work - it can ingest docs too, not just code. Don't block a one-line fix on building
  a graph from nothing.
- Only after the graph is exhausted, and only for the exact files it names, open source directly -
  it names file:line, go straight there.
- After any code change, run `graphify update .` to refresh (AST-only, no API cost) - this is gate
  7, not an afterthought.

## 2. context-mode - process, don't raw-dump

Already enforced automatically every session by the installed context-mode plugin's own
hook-injected instructions - don't restate its content here, just don't fight it. Short version:
Bash/Read stay correct only for short fixed output, mutating state, or edits (Edit needs the exact
bytes); everything else - filter, count, parse, aggregate, search - goes through `ctx_batch_execute`
/ `ctx_search` / `ctx_execute` / `ctx_fetch_and_index`.

## 3. grill-me first - interrogate every build/change request

The moment a request is to build, add, change, or fix something, run **grill-me** before any design
or code. This is the default entry point for new work, not reserved for big features. Walk the
design tree one question at a time, each with a recommended answer, resolving dependencies until
shared understanding. Explore the codebase/docs to answer a question instead of asking, whenever
possible.

Only exception: a trivial, fully-specified mechanical edit (a typo, an exact rename the user
dictated) skips straight to doing it. Anything carrying a design decision goes through grill-me.

## 4. Design - software-practices, ponytail and tiger-style, together, every time

For every build/change, run all three, in this order, feeding each other:

1. **software-practices decides how the work is done well and landed.** Read the requirement, name
   which practices apply, pull the sub-skill that fits:
   - `software-practices:engineering-principles` - design/architecture tradeoffs, tech debt,
     maintainability, build/CI. Default "how would this be engineered well" advisor.
   - `software-practices:trunk-based-development` - short-lived branch -> PR -> trunk, no
     long-lived divergence.
   - `software-practices:feature-flags` - gate incomplete or risky work behind a flag/toggle when
     the project has one.
   - `software-practices:testing` - test strategy (unit/integration/e2e, doubles, coverage).
   - `software-practices:code-review` - make the change reviewable; review before merge.
2. **ponytail then cuts it to the minimum that actually works.** YAGNI, already-in-codebase,
   stdlib/native platform/installed dependency before new code, one line before fifty, root cause
   over symptom. ponytail decides *how little*; software-practices decides *how well*.
3. **tiger-style makes what's left robust.** Assertions, bounds, shape, naming - see the skill.
   Where tiger-style and ponytail disagree (assertion-density floor, zero technical debt),
   tiger-style wins - decided, not a default to re-litigate. Everywhere else ponytail's ladder
   still governs.

None of the three is skipped - ponytail trims software-practices' plan, tiger-style hardens what
survives the trim.

## 5. superpowers - plan from gate 4, then implement per the practices

- `superpowers:brainstorming` for creative/feature work (if grill-me + gate 4 haven't already
  produced an approved design).
- `superpowers:writing-plans` -> a written plan built on top of the gate-4 synthesis - it encodes
  the trunk-based/feature-flag/test/review decisions, not just the feature steps.
- Implement (`superpowers:executing-plans` / `subagent-driven-development`), TDD per
  `superpowers:test-driven-development`.
- Bugs -> `superpowers:systematic-debugging` before proposing fixes.
- software-practices stays active through implementation, not just design: land it trunk-based,
  gate incomplete work behind flags where applicable, test per the testing sub-skill, review per
  code-review before merge.

## 6. Review - before the PR, loop until clean

After gate 5, before anything is pushed or a PR raised. Two checks, both must come back clean:

- **Security**: DeepSec, `--model-auth local` (rides the existing Claude subscription, no
  per-token bill). Scope to what changed - `process --filter <changed paths>`, then `revalidate`
  before treating a finding as real rather than a false positive.
- **Code review**: the built-in `/code-review` slash command. Not `no-mistakes` - excluded.

Any finding from either -> fix it -> re-run both -> repeat until there are zero open comments.
Only then raise the PR. A finding here restarts from **gate 3**, not gate 5 - it's new information
about the design, not a typo to patch in place.

## 7. Update the graph - after dev, after review, automatic

- After any code change, run `graphify update .` from the repo root (AST-only, no API cost).
- After the work is done AND reviewed and looks good, update the graph as the closing step of the
  task - automatically, without being asked. The graph must always reflect merged, reviewed
  reality.

## 8. Linear Method - tickets, issues, product planning

Any time a ticket/issue gets created, analysis gets broken into work items, a spec/PRD gets
written, or initiatives/cycles/roadmaps get planned - use the Linear Method, not ad-hoc lists.

- `linear-method` - core principles/practices: issue writing, cycle planning, backlog &
  prioritization, roadmaps, product direction. Start here.
- `to-releases` / `to-features` / `to-linear-projects` - slice broad scope into releases ->
  features/epics -> Linear projects.

Issues small and vertical, written from the problem not the task. One issue = one grabbable slice.

# Engineering priorities

Ranked, in order - a lower priority never wins a tradeoff against a higher one.

## 1. Security

- Security of the codebase, of users, of data - every step, including architecture-level
  decisions, not just code-level ones.
- When a design trades security against delivery speed, convenience, or performance, security
  wins.

## 2. Performance

- Ranked below security, above everything else.
- Applies to technology, framework, and architecture choices from the base up - not just
  hot-path code.

## 3. Testing

Four kinds. Unit tests come first (TDD): write the test, watch it fail, implement until it
passes.

- **Unit** - written first, before the implementation exists. Minimize mocking - test the real
  function/module wherever possible. Mock only when testing the real thing genuinely isn't
  possible (the believable case: a database dependency); mocking is the fallback, never the
  default.
- **Integration** - one feature in its own context (e.g. "add a second shipping address" tested
  as its own capability), against real systems. No mocking.
- **End-to-end** - the whole user flow the feature sits inside, not the feature in isolation
  (e.g. the full checkout, not just the addresses step it added), against the real, running
  application. No mocking. Tooling (Cucumber, Playwright, or otherwise) is still an open call,
  decide per project.
- **Smoke** - infrastructure/API health only: confirms the real system is up, reachable, and
  functioning, not that every code path is correct. No mocking.

Mocking is a unit-test-only, last-resort tool. Integration, end-to-end, and smoke tests mock
nothing - real systems only.

- **CI security scan** - nuclei runs in the PR pipeline alongside unit/integration/e2e/smoke, not
  on a nightly schedule. Needs the PR's stack actually booted (it scans a running instance, not a
  diff); severity-gated to medium/high/critical so template noise doesn't fail the build. This is
  the dynamic complement to gate 6's static/agent review, not a replacement for it.

# Global agent instructions

- Never use em dash "—". Use "-".
- Never add agent name as commit co-author.
- Never edit auto-generated files, incl. `CHANGELOG.md`.
- Prefer quality, simplicity, robustness, scalability, long-term maintainability over dev cost.
- Bug fixes: reproduce first in E2E, user-realistic env. Find root cause before fix.
- E2E: inspect UI closely. Fix obvious UI issues encountered, even unrelated.
- Apply same standard to lint, test failures, test flakiness. Fix if found, even unrelated.
- Before using "dynamic workflows", "ultra code", or swarm-style harness features, explain tradeoffs, get explicit user approval.
- No inline comments in code, ever. Every function, module, and file gets a docstring instead: a
  3-5 line summary of what it does, its inputs, and its outputs, properly formatted for the
  language's convention.
- Never edit anything under `~/.claude/*` or any other global/system config location directly, and
  never install a tool (`nix`, `npm`, `brew`, or otherwise) without asking first. This machine's
  config is code, in `~/myConfig/dotfiles` - `~/.claude/CLAUDE.md`, `~/.claude/settings.json`,
  `~/.claude/skills/` are symlinks off that repo. Edit the source under `dotfiles/claude/...`.
  Need a new tool? Say what's needed and why, then wait - the user adds it to the dotfiles config
  and installs it themselves. Never run `rebuild.sh` or any nix-darwin/home-manager rebuild - the
  user always runs that.
- Every project's `.gitignore` ignores: any codebase-graph cache dir (`graphify-out/` or
  equivalent), all `.env`/credential files, and generated tool-state dotfiles that are genuinely
  local/ephemeral. Check a tool's own convention before adding its dotfile here - some (DeepSec's
  `.deepsec/`) are designed to be committed, holding shared state across runs/CI/teammates, and
  ignoring one of those defeats the tool rather than tidying the repo. Default new agent-instruction
  files (`CLAUDE.md`, `AGENTS.md`) to tracked, matching ScholarScope's own choice - ignoring them is
  a per-project call, not this rule's default, since an untracked one doesn't ship on clone or show
  in PR diffs. Never ignore `.github/` or `.gitignore` itself - "dotfiles" here means tool-generated
  state, not every file that starts with a dot.
