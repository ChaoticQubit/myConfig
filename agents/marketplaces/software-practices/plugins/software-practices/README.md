# Software Practices

A plugin that makes Claude apply the software engineering practices from Google's book **[Software Engineering at Google](https://abseil.io/resources/swe-book/html/toc.html)** — trunk-based development, feature-flag-guarded releases, small reviewed changes, and the test-size pyramid.

The skills load automatically when your conversation touches the relevant topic; you don't have to invoke them by name.

## Skills

| Skill | What it does | Sample triggers |
|-------|--------------|-----------------|
| **trunk-based-development** | One trunk, small commits to `main`, no long-lived feature branches, One-Version Rule, release branches, monorepo, splitting large changes | "should I make a feature branch", "push to main", "merge conflicts", "one version rule", "monorepo" |
| **feature-flags** | Flag-guard incomplete work on trunk, dark launch / canary / staged rollout, decouple deploy from release, roll back by config, flag cleanup | "feature flag", "feature toggle", "dark launch", "canary", "gradual rollout", "kill switch" |
| **code-review** | Small single-purpose changes (~200 LOC), LGTM/OWNERS/readability, good change descriptions, constructive review, 24h turnaround | "review this PR", "how big should this change be", "commit message", "OWNERS" |
| **testing** | Test-size (small/medium/large) + scope pyramid, hermetic tests, behavior-not-implementation, real-over-fake-over-stub-over-mock, flaky-test fixes, coverage sanity | "write tests", "unit vs integration", "mock vs fake", "flaky test", "test pyramid" |
| **engineering-principles** | The cross-cutting mental models: Hyrum's Law, Beyoncé Rule, code-is-a-liability, shift-left, style rules, deprecation/migration, build systems, CI, and an AI-era framing | "tech debt", "deprecate", "should we rewrite", "style guide", "build system", "design tradeoff" |

Each skill has a lean `SKILL.md` plus a `references/` file with playbooks, checklists, and language-agnostic code patterns for progressive disclosure.

## What "Google-style" means here

- **Push to trunk, not to long-lived branches.** Work in small increments against `main`; get stability from tests + CI + review, not from branch isolation.
- **Hide unfinished work behind flags, not branches.** New code lands on trunk disabled and rolls out gradually; rollback is a config flip, not a redeploy.
- **Small, single-purpose, reviewed changes.** One concern per change, ~200 lines, a description that says *why*.
- **Many small hermetic tests** of behavior over top-heavy end-to-end suites; real implementations over mocks.
- **Code is a liability.** Reuse and delete over rewrite; assume Hyrum's Law; shift problems left.

## Source

All practices are drawn from *Software Engineering at Google* (O'Reilly, free online at abseil.io), plus framing from Adam Bender's Google I/O 2026 talk *"Software engineering at the tipping point."* This plugin is an independent study aid and is not affiliated with or endorsed by Google.
