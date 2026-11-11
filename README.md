# Architecture Design Inspector

[Chinese (Simplified)](README.zh-CN.md)

Architecture Design Inspector reviews the structural and cross-system decisions in high-level design documents. It identifies missing decisions, design issues, and internal inconsistencies, then adds concise comments at the relevant locations in the original Word document and delivers an annotated copy.

The review covers application, data, technology, security, integration, and operations concerns at the appropriate design depth. It does not require a fixed chapter structure and distinguishes architecture-level decisions from details that belong in later design stages.

Comments should be supported by evidence in the supplied materials. Unknown facts are raised as questions for confirmation. The source document is left unchanged, and the annotated copy preserves existing content, diagrams, comments, and revisions.

## Installation

This repository is the skill package. To install it, ask an AI agent that supports GitHub-hosted skills:

> Install the `architecture-design-inspector` skill from `https://github.com/soyio/architecture-design-inspector` and tell me when it is ready to use.

The agent should retrieve the repository and place the skill in the skill directory used by that agent. Installation steps vary by platform. If the agent cannot install skills from GitHub directly, use its documented skill installation process with this repository.

## Use

After installation, provide a high-level design Word document and ask the agent to review it with the Architecture Design Inspector skill. You may also provide requirements, standards, or related design materials as review evidence.

The deliverable is a copy of the Word document with concise comments in Chinese at the corresponding locations. The source file is not overwritten.

## Package Contents

The repository root is the skill package root:

```text
SKILL.md
agents/
assets/
references/
scripts/
```

- `SKILL.md` defines when and how to use the skill.
- `references/content-checklist.md` is the single source of truth for design-content requirements.
- `references/word-comments.md` describes Word annotation and document preservation behavior.
- `scripts/` contains document inspection, annotation, and validation utilities.

## Requirements

The host agent needs document understanding and local file access. Python 3.9 or later is required to run the bundled scripts. Reviewing diagrams also requires image-viewing capability. Standard DOCX indexing and annotation use only the Python standard library and do not require a specific MCP server. Legacy DOC conversion and visual layout checks depend on tools available in the host environment.

## Tests

Run the bundled regression tests from the repository root:

```bash
python -X utf8 scripts/test_rules.py
```

The tests check annotation behavior and document preservation. They do not measure model judgment or certify a production design.
