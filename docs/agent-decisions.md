# Agent Decisions

This file is the durable source of truth for decisions that survive context compaction. Entries are organized by topic, dated, and linked to the task or ticket when one exists. Agent memory may point here but does not replace it.

## Security

No decisions recorded yet.

## Authorization

No decisions recorded yet.

## Authentication

No decisions recorded yet.

## Services

No decisions recorded yet.

## Agent Workflow

### 2026-08-20 - Direct-to-master workflow preference

Status: Current

Task: Repository workflow preference

Decision: For this repository, work directly on `master` by default. Do not create task branches, switch to feature branches, merge branches, or commit changes unless the user explicitly requests that action. Leave requested changes in the working tree so the user can inspect and stage them manually.

Unresolved questions: None.

### 2026-08-19 - Durable post-grill decision records

Status: Current

Task: `chore/agent-auto-compaction-memory`

Goal: Preserve design decisions across automatic context compaction.

Constraints: Use one tracked document, keep prior decisions recoverable, avoid relying on agent memory as the only copy, and keep the change small and reversible.

Decisions:

- Store all decision records in this file.
- Organize entries by topic, including security, authorization, authentication, services, and agent workflow.
- Create one dated entry after every completed grill-me session that is not a trivial mechanical edit.
- Persist the entry immediately after grill-me and before design, implementation, or long-running tool work.
- Record the goal, constraints, decisions, rejected alternatives, risks, acceptance criteria, and unresolved questions.
- Append or update the relevant topic section without deleting history.
- Mark changed decisions as superseded with the replacement and reason.
- Update available agent memory only with a short pointer or stable preference after this document is written.

Rejected alternatives:

- One file per task was rejected because the user wants a single topic-organized source of truth.
- Raw transcript dumps were rejected because they recreate context bloat and make current decisions harder to identify.
- Agent memory as the source of truth was rejected because it may be unavailable, summarized, or agent-specific.

Risks: A future agent may fail to read this file after compaction, so the shared workflow explicitly requires rereading the relevant topic sections.

Acceptance criteria: The workflow requires a durable write before gate 4, failed writes block continuation, and the Claude compaction threshold is set to 400000 tokens.

Unresolved questions: None.

## Compaction and Memory

### 2026-08-19 - Compaction threshold policy

Status: Current

Task: `chore/agent-auto-compaction-memory`

Decision: Claude uses `CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000`, representing 40% of the configured 1M context window. Codex has no repository-configured percentage threshold, so its native compaction remains enabled and task-specific decisions must be persisted before compaction and reread afterward.

Evidence: The repository already configured Claude’s threshold through `agents/settings.json`. The local Codex configuration exposes no compaction threshold setting, and official OpenAI documentation describes compaction as API-managed rather than documenting a Codex CLI percentage control.

Unresolved questions: None.
