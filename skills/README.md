# Agent Skills for Hunter-Seeker

Four skills in the open SKILL.md format (Claude Code, Claude.ai, Codex, Cursor, Gemini CLI).
The canonical home is the Hunter-Seeker skills repository; this copy is kept in sync for
people who install the SDK.

| Skill | Use it when |
|---|---|
| `hs-decision-loop` | an agent needs a defensible yes/no prediction, or must decide on one entity with a score it can prove |
| `hs-observe` | preparing CRM / product / event data; choosing an outcome column; avoiding leakage |
| `hs-trace-audit` | learning which of your agent runs succeed and why, from traces |
| `hs-act-faithfully` | writing any text or taking any action based on a Verdict |

Install into a project: copy a folder to `.claude/skills/`. Each folder carries `evals/`.
