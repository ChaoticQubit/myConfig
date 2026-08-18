# deep-docs-marketplace

A one-plugin Claude Code marketplace that distributes **`deep-docs`** — a general-purpose plugin that turns any codebase into deep, diagram-rich product documentation. The same plugin also runs in Cowork; this wrapper is what lets Claude Code install it.

## Install (persistent)

1. **Unzip this folder** somewhere stable, e.g. `~/deep-docs-marketplace` (the folder that contains `.claude-plugin/marketplace.json`).

2. In Claude Code, **add the marketplace** (point it at that folder):

   ```
   /plugin marketplace add ~/deep-docs-marketplace
   ```

3. **Install the plugin**:

   ```
   /plugin install deep-docs@deep-docs-marketplace
   ```

4. **Reload** so the skills load:

   ```
   /reload-plugins
   ```

That's it. The plugin's skills are model-invoked automatically based on what you ask, and are also directly runnable by their namespaced names:

- `/deep-docs:document-product` — generate (or refresh) the full documentation set
- `/deep-docs:diagram-codebase` — generate just the technical mermaid diagram set

Run `/help` to confirm both appear under the `deep-docs` namespace.

## Quick test (no install)

To try it for a single session without installing, point Claude Code straight at the plugin directory:

```
claude --plugin-dir ~/deep-docs-marketplace/plugins/deep-docs
```

## Use it

Open Claude Code in (or point it at) the repo you want documented and ask, for example:

- "Document this product — full architecture docs with mermaid diagrams."
- "Generate a technical handoff / onboarding document for this codebase."
- "Draw the architecture and data-flow diagrams for this repo."
- "Update the product docs — the code changed."

If you have a code graph (e.g. a Graphify export), mention it — discovery will ingest it to drive the architecture and dependency diagrams.

## Update / remove later

```
/plugin marketplace update deep-docs-marketplace   # after you change the plugin
/plugin uninstall deep-docs@deep-docs-marketplace  # remove it
```

## What's inside

```
deep-docs-marketplace/
├── .claude-plugin/
│   └── marketplace.json        # the catalog Claude Code reads
├── plugins/
│   └── deep-docs/              # the actual plugin (skills + reference library)
│       ├── .claude-plugin/plugin.json
│       ├── skills/document-product/   (SKILL.md + references/ + assets/)
│       ├── skills/diagram-codebase/   (SKILL.md)
│       └── README.md
└── README.md                   # this file
```
