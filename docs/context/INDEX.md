# Context index — job-agent

Route by the **shape of the task**, not by topic name. Load one file. Two only if the
task genuinely spans two rows.

| If the task is… | Load | ~tok |
|---|---|---|
| "what's the state / what's next / what's blocked / is X done" | `STATUS.md` | 400 |
| build a feature, change behaviour, "where does X live", "how does X flow" | `architecture.md` | 900 |
| "why is it like this", proposing a rewrite, replacing a library or pattern | `decisions.md` | 700 |
| how the three loops (hunt / draft / submit) fit together, or building a new one | `three-loop-architecture.md` | 2400 |
| something is broken, flaky, slow, or behaves unexpectedly | `gotchas.md` | 600 |
| anything else, or unclear | `STATUS.md` | 400 |

Bug reports usually want `gotchas.md` first — check it before reading code. If the
symptom isn't listed there, then load `architecture.md`.

Refactor and "can we switch to X" requests want `decisions.md` first. The answer is
often already there, and re-litigating a settled decision is the most expensive way to
be wrong.

Do not read this file's targets speculatively. Do not read all four.
