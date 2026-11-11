# 概要设计检查助手

`architecture-design-inspector` reviews the structural and cross-system decisions in high-level designs. It identifies omissions, design issues, and internal conflicts, then adds concise Chinese comments at the corresponding locations in the original Word document and delivers an annotated copy.

The review covers application, data, technology, security, integration, and operations concerns at the appropriate design depth. It does not require a fixed chapter structure and distinguishes architecture decisions from details that belong in later design stages.

Comments are evidence-based. Unavailable facts remain questions for confirmation. The source document remains intact, and the annotated copy preserves existing content, diagrams, comments, and revisions. New comments use the author name “概要设计检查助手”.

## Contents

The repository root contains the installable skill files directly:

```text
SKILL.md
agents/
assets/
references/
scripts/
```

- [SKILL.md](SKILL.md) describes when and how to use the skill.
- [references/content-checklist.md](references/content-checklist.md) is the single source for design-content requirements.
- [references/word-comments.md](references/word-comments.md) documents Word annotation and preservation behavior.

## Requirements

The host agent needs document understanding, local file access, and Python 3.9 or later. Reviewing diagrams requires image-viewing capability. Standard DOCX indexing and annotation use only the Python standard library and do not require a fixed MCP. Legacy DOC conversion and visual layout checks depend on tools available in the host environment.

Run the bundled regression tests from this repository root:

```text
python -X utf8 scripts/test_rules.py
```

These tests check annotation-tool behavior and document preservation. They do not measure model judgment or certify a production design.
