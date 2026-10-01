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

- When grill-me completes, immediately persist the decision-relevant context in `docs/agent-decisions.md` before gate 4 or any long-running tool work.
- Each entry includes the date, task or ticket, topic, goal, constraints, decisions, rejected alternatives, risks, acceptance criteria, and unresolved questions.
- Append to or update the relevant topic section. Never erase prior decisions. Mark changed decisions as superseded with the replacement and reason.
- If the durable record cannot be written, stop and report the failure before continuing.
- Update available agent memory with a short pointer or stable preference only after the document is written. The document is the source of truth.

### 3.1 Context durability

- Claude uses `CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000`, which targets 40% of the configured 1M context window.
- Codex uses `model_context_window = 872000` and `model_auto_compact_token_limit = 250000` in `agents/codex/config.toml`: compaction fires at 250k tokens, about 29% of the `gpt-5.6-sol` 872k maximum window. Codex has no percentage setting, so both values are absolute tokens and must be recomputed on a model change. Treat its native compaction as lossy for task-specific decisions and reread the relevant sections of `docs/agent-decisions.md` after compaction.

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

## 6. Review - code review and one security review, in parallel, twice at most

After gate 5, before any push or PR, run exactly two review tracks: normal code review and
Codex Security with DeepSec evidence. DeepSec collects candidates and supplies existing
findings; Codex Security owns security discovery, validation, coverage, and the final report.
Do not add a separate DeepSec AI review or a third Codex Security pass. This experimental
default replaces the older DeepSec-plus-Codex-Security review split.

1. **Freeze the target.** Record the repository, base SHA, head SHA, and authorized scope.
   Nothing is edited while either reviewer runs. Both tracks must review the same source.
   Committed-diff scans require a clean checkout at the frozen head; use an isolated worktree
   when the working checkout is dirty. Never stash or discard unrelated user changes for a scan.
2. **Prepare the DeepSec evidence without discarding history.** Before refreshing scanner state,
   snapshot the existing project candidate records, findings, analysis history, and run metadata
   into a dedicated evidence directory outside the target checkout. Export all findings with
   `deepsec export --project-id <project-id> --format json --include-resolved --out <evidence>/findings-before.json`.
   Do not filter by severity, date, agent, or true-positive status. Confirm the project ID/root.
   Run deterministic discovery with `deepsec scan --project-id <project-id> --root <frozen-checkout>`
   from the existing DeepSec workspace, then snapshot the refreshed candidates separately.
   `export` exports findings, not every raw candidate: preserve both sources. No fresh
   `deepsec process` or AI revalidation pass. If setup or artifacts are unavailable, report
   the gap; do not silently call the combined workflow complete or install anything.
3. **Run both tracks against the frozen target in parallel.**
   - **Code review:** built-in `/code-review`, or the host's normal code-review capability.
   - **Security:** Codex Security, with Daybreak Blue (`gpt-daybreak-blue-latest`), `xhigh`
     effort, and ChatGPT authentication. Use `codex-security:security-diff-scan` for changes
     or `codex-security:security-scan` for an explicitly requested repository/path audit.
     Read `~/myConfig/dotfiles/agents/security-review-prompt.md` and supply the entire evidence
     directory as scan context. A desktop scan uses the selected host model: confirm the
     actual model rather than assuming this instruction switches it. The installed CLI
     can select it explicitly using the command below. These are alternative launch paths,
     not two scans. DeepSec's Codex adapter disables plugins; `--agent codex` alone is not
     Codex Security integration. If model/auth access fails, report it without silently
     falling back to Claude, another model, or API-key billing.
4. **Account for every input.** Keep immutable raw evidence and a manifest with source IDs,
   source revision/run when available, hashes, and counts. Codex Security must examine every
   handed-off finding and candidate and record confirmed, refuted, duplicate, already-fixed,
   or deferred with evidence. Duplicates retain their source IDs and link to the survivor.
   Stale or out-of-scope items remain explicit deferred entries; do not silently expand a
   diff review into a full audit. Review the authorized source independently of matcher hits.
   Missing inputs or incomplete dispositions mean partial coverage, not a clean result.
5. **Merge both reports into one triage list.** Resolve contradictions by inspecting the code
   once. Fix critical/high findings and any genuine security or data-loss defect regardless
   of label. Medium/low/style suggestions do not otherwise block merge. A critical/high
   design error restarts gate 3; other fixes are patched in place or filed.
6. **One confirm round at most**, only after substantial fixes. Review the new frozen target
   for regressions from those fixes. Two rounds is the ceiling; a third needs asking first.
7. **Retain evidence and measure the experiment.** Record scan ID, actual model, target SHAs,
   evidence manifest, input/disposition counts, validated findings by source, independent
   Codex Security discoveries, coverage gaps, elapsed time, and usage/cost when reported.
   A successful exit or empty findings list alone does not prove a completed review: check
   the scan manifest, coverage, final report, and evidence ledger. Record IDs on the ticket,
   batch deferred work into the backlog, then raise the PR. Compare results with prior
   reviewed baselines where available; do not run extra reviews solely to manufacture a
   comparison or claim improved security before evidence exists.

CLI launch for a committed diff, with shell variables set to the verified target and evidence paths:

```sh
codex-security scan "$review_repo" --diff "$review_base_sha" --head "$review_head_sha" \
  --auth chatgpt --model gpt-daybreak-blue-latest --effort xhigh \
  --knowledge-base "$review_evidence_dir" \
  --scan-prompt-file "$HOME/myConfig/dotfiles/agents/security-review-prompt.md" \
  --output-dir "$review_output_dir"
```

Use a fresh output directory outside the checkout. Add `--dry-run` to verify local input
resolution without starting a review; it does not verify authentication or live inference.
For full repository/path audits omit `--diff`/`--head` and explicitly select the authorized
scope. Do not use Deep mode for routine diffs. Preserve project-specific manual-test gates.

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

- **Prompt carries both a question and a task -> answer the question FIRST, in the same reply, before the first tool call.** The user sits blocked waiting on the answer while the work runs; deferring it until the task finishes wastes their time. Applies to any question asked alongside the work - explanation, comparison, "is X done", "why did Y happen" - and a one-line answer still goes first. Answer needs a lookup? Do the minimum reads to answer, answer, then start the task. Never park the answer at the end of the turn, never fold it into the completion report.
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
- **Never edit under `~/.claude/*` or any global/system config location directly. Never install a tool (`nix`, `npm`, `brew`, other) without asking first.** Machine config is code in `~/myConfig/dotfiles`. `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/skills/`, `~/.claude/hooks/` are symlinks off that repo. Edit the source under `dotfiles/agents/...` - one shared folder for every agent (Claude Code, Codex, Pi). `dotfiles/agents/AGENTS.md` is this file; `~/.claude/CLAUDE.md` is a symlink to it. Need a tool -> say what and why, then wait. User adds it to the dotfiles config, user installs it. Never run `rebuild.sh` or any nix-darwin/home-manager rebuild.
- **Every project `.gitignore` ignores**: codebase-graph cache dir (`graphify-out/` or equivalent), all `.env`/credential files, generated tool-state dotfiles that are genuinely local/ephemeral.
  - Check the tool's own convention first. Some (DeepSec `.deepsec/`) are meant to be committed - shared state across runs/CI/teammates. Ignoring one defeats the tool.
  - New agent-instruction files (`CLAUDE.md`, `AGENTS.md`) default to tracked, matching ScholarScope. Ignoring one is a per-project call, not the default: an untracked file does not ship on clone, does not show in PR diffs.
  - Never ignore `.github/` or `.gitignore` itself. "Dotfiles" here = tool-generated state, not every file starting with a dot.
