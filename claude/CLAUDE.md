# Mandatory workflow

Gates in order. Higher gate answers question -> stop, no descending for same question. Build/add/change/fix request -> gates 1, 3, 4, 5, 6 all mandatory. Known failure: ponytail + superpowers used, software-practices skipped, grill-me skipped, review skipped to raise PR fast. Skip none.

## 0. Branch first

First action. Before graph, before source, before grill-me.

- Fresh short-lived branch off trunk. Name `type/short-slug` (`feat/`, `fix/`, `chore/`, `docs/`), matching work.
- Never commit task work to trunk. Never reuse unrelated branch. One branch = one task -> PR -> trunk.
- Already on branch matching *current* request -> continue it. Else cut new one from up-to-date trunk.
- Confirm before destructive git op (force-push, `reset --hard`, branch delete).
- Exception: edits only to gitignored files (docs scratch, `CLAUDE.md`, `.claude/settings*`) = no commit, no branch.

## 1. graphify - codebase cache, checked before anything

`~/.claude/skills/graphify/SKILL.md`, trigger `/graphify`. One graph, one place: `graphify-out/` at repo root. Any question about codebase, architecture, file relationships, where/what/how -> **query graph before reading source**. Every task.

- `graphify-out/graph.json` exists -> that is the cache, not raw grep:
  - `graphify query "<question>"` = scoped subgraph. `graphify path "<A>" "<B>"` = how two things relate. `graphify explain "<concept>"` = concept map.
  - Scoped subgraph beats `GRAPH_REPORT.md` and raw grep.
- `graphify-out/wiki/index.md` for broad navigation, over browsing source. `graphify-out/GRAPH_REPORT.md` only for broad architecture review, or when query/path/explain came up short.
- No `graphify-out/` yet -> say so, then `graphify update .` before non-trivial work (ingests docs too). Never block a one-line fix on building a graph from nothing.
- Graph exhausted -> only then open source, only the `file:line` it names.
- After any code change: `graphify update .` (AST-only, no API cost). Gate 7, not an afterthought.

## 2. context-mode - process, no raw dump

Plugin's own SessionStart hook injects the full rule every session. Do not restate it here, do not fight it. One line: Bash/Read only for short fixed output, mutating state, or edits. Everything else goes through `ctx_batch_execute` / `ctx_search` / `ctx_execute` / `ctx_fetch_and_index`.

## 3. grill-me - interrogate every build/change request

Request to build/add/change/fix -> run **grill-me** before design or code. Default entry point for new work, not just big features. Walk design tree one question at a time, each with a recommended answer, resolve dependencies until shared understanding. Answer from codebase/docs instead of asking, whenever possible.

Only exception: trivial fully-specified mechanical edit (typo, exact rename user dictated). Anything carrying a design decision -> grill-me.

## 4. Design - software-practices, ponytail, tiger-style. That order, every time

1. **software-practices = how the work gets done well and landed.** Name applicable practices, pull the sub-skill: `software-practices:engineering-principles` (design/architecture tradeoffs, tech debt, maintainability, build/CI - default advisor), `software-practices:trunk-based-development`, `software-practices:feature-flags` (gate incomplete or risky work when project has a flag system), `software-practices:testing`, `software-practices:code-review`.
2. **ponytail = minimum that works.** Ladder, stop at first rung that holds: needs to exist at all (YAGNI) -> already in codebase -> stdlib -> native platform feature -> installed dependency -> one line -> minimum code that works. ponytail decides *how little*, software-practices decides *how well*.
   - Ladder shortens the solution, never the reading. Trace every file the change touches first. Smallest change in wrong place = second bug, not lazy fix.
   - Bug fix = root cause. Grep every caller before editing: one guard in the shared function is a smaller diff than a guard in every caller. Patching only the ticket's path leaves sibling callers broken.
   - No unrequested abstractions. No interface with one implementation, no factory for one product, no config for a value that never changes, no scaffolding "for later".
   - Deletion over addition. Boring over clever. Fewest files, shortest working diff. Two options same size -> take the one correct on edge cases.
   - Never simplify away: input validation at trust boundaries, error handling preventing data loss, security, accessibility, anything explicitly requested. User wants full version -> build it, no re-arguing.
   - Non-trivial logic leaves ONE runnable check: smallest thing that fails if the logic breaks (assert-based `__main__`, or one small `test_*.py`). No frameworks, no fixtures, unless asked. Trivial one-liners need none.
   - Output: code first, then max three short lines - what was skipped, when to add it. Explanation longer than the code -> delete the explanation.
3. **tiger-style = robustness on what survives.** Assertions, bounds, shape, naming. See skill.

tiger-style vs ponytail conflict (assertion-density floor, zero tech debt) -> **tiger-style wins**. Decided, not re-litigated. Everywhere else ponytail's ladder governs. None of the three skipped.

## 5. superpowers - plan from gate 4, then implement

- `superpowers:brainstorming` for creative/feature work, unless grill-me + gate 4 already produced an approved design.
- `superpowers:writing-plans` -> written plan on top of the gate-4 synthesis. Encodes trunk-based / feature-flag / test / review decisions, not just feature steps.
- Implement via `superpowers:executing-plans` / `subagent-driven-development`. TDD per `superpowers:test-driven-development`.
- Bugs -> `superpowers:systematic-debugging` before proposing fixes.
- software-practices stays active through implementation: land trunk-based, flag incomplete work, test per testing sub-skill, review per code-review before merge.

## 6. Review - both gates in parallel, on one frozen commit, twice at most

After gate 5, before any push or PR. **Never run the two gates in sequence.** Sequential is
what does not converge: DeepSec reads commit X, the fixes produce X+1, `/code-review` then reads
X+1 - a tree no reviewer has seen - and finds new things, whose fixes produce an X+2 DeepSec has
never seen. Each gate reviews the other's edits, forever. Review output is a function of the
diff and every fix changes the diff, so "until zero open comments" is an instruction to loop
until the budget runs out. It has cost an evening and $250 on a single ticket.

1. **Freeze the commit.** Note the SHA. Nothing is edited while a review is running - editing
   the tree under a reviewer invalidates its verdicts and it will report against a mix.
2. **Run both against that one SHA, in parallel, in the same message.**
   - **Security**: DeepSec. Scope to changes: `process --diff <base-ref> --agent claude --model <model>`.
     Verify the run **actually ran**: it exits `0` on an unknown option, so a typo'd flag reports
     success having done nothing. A run that produced no findings and no analyses did not run.
   - **Code review**: built-in `/code-review`.
3. **Merge both outputs into one triage list.** Where they contradict each other, read the code
   once and decide; never re-run a gate to break a tie.
4. **Fix critical and high only** - plus any genuine security or data-loss defect whatever label
   it carries. Medium, low, style, nitpicks, "consider extracting this" do not block a merge.
5. **One confirm round, at most**, and only when step 4 changed something substantial. It asks
   whether the fixes opened something worse. It is not a fresh hunt. **Two rounds is the ceiling** -
   a third needs asking first.
6. Record the run id on the ticket, cut the leftovers into the backlog as a batch, raise the PR.

A critical or high finding that is really a design error restarts at **gate 3**. Everything else
is patched in place or filed.

## 7. Update graph

`graphify update .` from repo root after any code change, and again once work is done AND reviewed. Automatic, without being asked. Graph must reflect merged, reviewed reality.

## 8. Linear Method - tickets, issues, product planning

Ticket/issue created, analysis broken into work items, spec/PRD written, initiatives/cycles/roadmaps planned -> Linear Method, not ad-hoc lists.

- `linear-method` first: issue writing, cycle planning, backlog, prioritization, roadmaps, product direction.
- `to-releases` / `to-features` / `to-linear-projects` slice broad scope into releases -> features/epics -> Linear projects.

Issues small and vertical, written from the problem not the task. One issue = one grabbable slice.

# Engineering priorities

Ranked. Lower never wins a tradeoff against higher.

1. **Security** - codebase, users, data. Every step, architecture-level decisions included. Beats delivery speed, convenience, performance.
2. **Performance** - below security, above everything else. Technology, framework, architecture choices from the base up, not just hot-path code.
3. **Testing** - four kinds. Unit first (TDD): write test, watch it fail, implement until pass.
   - **Unit** - written before implementation exists. Test the real function/module. Mock only when testing the real thing is genuinely impossible (believable case: a database dependency). Mocking is the fallback, never the default.
   - **Integration** - one feature in its own context (e.g. "add a second shipping address" as its own capability), against real systems. No mocking.
   - **End-to-end** - whole user flow the feature sits inside (full checkout, not just the addresses step), against the real running application. No mocking. Tooling (Cucumber, Playwright, other) = per-project call.
   - **Smoke** - infra/API health only: real system up, reachable, functioning. Not every code path. No mocking.

   Mocking = unit-test-only last resort. Integration, e2e, smoke mock nothing.
   - **CI security scan** - nuclei in the PR pipeline alongside the other suites, not nightly. Scans a running instance -> PR stack must be booted. Severity-gated medium/high/critical so template noise does not fail the build. Dynamic complement to gate 6, not a replacement.

# Global agent instructions

- Never use em dash. Use "-".
- Never add agent name as commit co-author.
- Never edit auto-generated files, incl. `CHANGELOG.md`.
- Prefer quality, simplicity, robustness, scalability, long-term maintainability over dev cost.
- Bug fixes: reproduce first in E2E, user-realistic env. Root cause before fix.
- E2E: inspect UI closely. Fix obvious UI issues found, even unrelated. Same standard for lint failures, test failures, flakiness - fix if found, even unrelated.
- Before "dynamic workflows", "ultra code", swarm-style harness features: explain tradeoffs, get explicit user approval.
- **No comments in any file of any kind, ever.** Not `//` in a function body or above a statement, not `{/* */}` in JSX, not `#` in YAML / `.gitignore` / `go.mod` / Dockerfile / Makefile / env file / shell script, not `--` in SQL, not an HTML comment in Markdown.
  - Only permitted form: **docstring**. Language's declaration-attached doc construct, directly above the declaration, nowhere else. 3-5 lines: what it does, inputs, outputs. Go doc comment above `package`/`type`/`func`/`const`/`var`, TSDoc `/** */` above a declaration, Python `"""` as first statement.
  - Formats with no docstring construct (YAML, Markdown, Dockerfile, Makefile, shell, SQL): write nothing. Explain in the PR or in `docs/`.
  - Never migrate a comment verbatim into a docstring. Rewrite as prose, move it to `docs/`, or drop it. Never invent a wrapper function to house an orphaned comment.
  - User asking explicitly = the only thing that authorises a comment.
  - Existing comments predate this rule. Do not strip them as a side effect of an unrelated change - that sweep is its own task.
- **Assertions: language has a usable runtime assert -> use it.** Where it does not, pick the idiom once per layer, not per author, and write the choice into the project's agent file. An assertion states a postcondition on an internal invariant that should be structurally impossible. Input validation is not an assertion. Validation that already exists is not a missing one. An assertion no test can trip is not done.
- **Parallel agent work: one agent per git worktree. Never several agents in one checkout.** Disjoint file scopes assigned up front. Symlink the gitignored agent files and any code-graph cache into each worktree, or the agent is blind to every project rule. Ration shared resources (Docker stack, published port, scratch DB) to one named agent. Agents commit, never push, never open a PR.
  - Idle notification is not a report. Read the transcript, verify claims against `git log` and `git diff`.
  - Verify "nothing was removed" with a count **at HEAD**, never a count over a diff. A diff of added lines reports zero for the failure that actually happens: content deleted with nothing written in its place.
  - Agents may commit and amend the tip. Reset, rebase, drop -> ask first. `git reflog` in the worktree recovers one that did not.
- **Never edit under `~/.claude/*` or any global/system config location directly. Never install a tool (`nix`, `npm`, `brew`, other) without asking first.** Machine config is code in `~/myConfig/dotfiles`. `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/` are symlinks off that repo. Edit the source under `dotfiles/claude/...`. Need a tool -> say what and why, then wait. User adds it to the dotfiles config, user installs it. Never run `rebuild.sh` or any nix-darwin/home-manager rebuild.
- **Every project `.gitignore` ignores**: codebase-graph cache dir (`graphify-out/` or equivalent), all `.env`/credential files, generated tool-state dotfiles that are genuinely local/ephemeral.
  - Check the tool's own convention first. Some (DeepSec `.deepsec/`) are meant to be committed - shared state across runs/CI/teammates. Ignoring one defeats the tool.
  - New agent-instruction files (`CLAUDE.md`, `AGENTS.md`) default to tracked, matching ScholarScope. Ignoring one is a per-project call, not the default: an untracked file does not ship on clone, does not show in PR diffs.
  - Never ignore `.github/` or `.gitignore` itself. "Dotfiles" here = tool-generated state, not every file starting with a dot.
