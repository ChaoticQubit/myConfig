# Software Practices Marketplace

A one-plugin Claude Code / Cowork marketplace hosting **software-practices** — a plugin that makes Claude apply Google's software engineering practices (trunk-based development, feature flags, code review, testing, and core engineering principles) from *[Software Engineering at Google](https://abseil.io/resources/swe-book/html/toc.html)*.

```
software-practices-marketplace/
├── .claude-plugin/
│   └── marketplace.json          # marketplace manifest (lists the plugin)
├── plugins/
│   └── software-practices/
│       ├── .claude-plugin/plugin.json
│       ├── README.md
│       └── skills/
│           ├── trunk-based-development/
│           ├── feature-flags/
│           ├── code-review/
│           ├── testing/
│           └── engineering-principles/
└── README.md
```

## Install in Claude Code

You add the marketplace once, then install the plugin from it.

**Option A — from a local folder** (this unzipped directory):

```bash
# In an interactive Claude Code session:
/plugin marketplace add /absolute/path/to/software-practices-marketplace
/plugin install software-practices@software-practices-marketplace
```

**Option B — from GitHub** (after you push this folder to a repo):

```bash
/plugin marketplace add your-username/software-practices-marketplace
/plugin install software-practices@software-practices-marketplace
```

Then restart or reload, and verify:

```bash
/plugin marketplace list
/help                     # the skills load automatically by topic
```

To update after changing files: `/plugin marketplace update software-practices-marketplace`.

> The marketplace name (`software-practices-marketplace`) comes from `.claude-plugin/marketplace.json`; the plugin name (`software-practices`) comes from `plugins/software-practices/.claude-plugin/plugin.json`. The `@` install syntax is `<plugin-name>@<marketplace-name>`.

## Install in Cowork (Claude desktop)

Use the packaged **`software-practices.plugin`** file (delivered alongside this folder). Open it in the Cowork desktop app and accept the install prompt. The skills then activate automatically when your conversation touches the relevant topic.

## Usage

You don't call the skills by name. Just work — ask about branching, PR size, feature rollout, tests, tech debt, deprecation, etc. — and the matching skill loads. Example prompts:

- "I'm about to build a big feature — should I make a feature branch?"
- "How do I roll this out safely without a risky deploy?"
- "Review this change before I merge."
- "Should I mock the database here or use something else?"
- "We have two systems doing the same thing — how do we retire the old one?"

## Source & attribution

Practices are distilled from *Software Engineering at Google* (O'Reilly; free at abseil.io) and framing from Adam Bender's Google I/O 2026 talk *"Software engineering at the tipping point."* Independent study aid; not affiliated with or endorsed by Google.
