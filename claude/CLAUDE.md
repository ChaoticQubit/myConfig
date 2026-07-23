# graphify

- `~/.claude/skills/graphify/SKILL.md` - knowledge graph. Trigger: `/graphify`.
- On `/graphify`, use graphify skill/instructions first.

## Rules

- If `graphify-out/graph.json` exists:
  - Run `graphify query "<question>"` first.
  - Use `graphify path "<A>" "<B>"` for relationships.
  - Use `graphify explain "<concept>"` for focused concepts.
  - Prefer scoped subgraph over `GRAPH_REPORT.md`/raw grep.
- If `graphify-out/wiki/index.md` exists, use for broad nav over source browsing.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or if query/path/explain insufficient.
- After code changes, run `graphify update .` to refresh graph (AST-only, no API cost).

# Global agent instructions

- Never use em dash "—". Use "-".
- Never add agent name as commit co-author.
- Never edit auto-generated files, incl. `CHANGELOG.md`.
- Prefer quality, simplicity, robustness, scalability, long-term maintainability over dev cost.
- Bug fixes: reproduce first in E2E, user-realistic env. Find root cause before fix.
- E2E: inspect UI closely. Fix obvious UI issues encountered, even unrelated.
- Apply same standard to lint, test failures, test flakiness. Fix if found, even unrelated.
- Before using "dynamic workflows", "ultra code", or swarm-style harness features, explain tradeoffs, get explicit user approval.
