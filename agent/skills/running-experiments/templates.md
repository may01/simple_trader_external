# Templates

Four documents per experiment plus one shared register. All live in the external docs repo.

```
external/docs/superpowers/
  experiment/REPORT.md                     # register: every experiment, verdict, disposition
  experiment/<name>.md                     # spec (user-authored, you extend)
  plans/YYYY-MM-DD-<name>.md               # plan (single file, or a task-NN/ dir)
  experiment/<name>/iter_NN.md             # one per loop iteration (loops only)
  experiment/results/<name>_results.md     # the deliverable
```

## 1. Spec — `experiment/<name>.md`

The user writes this. If a section is missing, fill it during the clarify phase and write
it back.

```markdown
# Goal
One paragraph: what must be decided, in measurable terms.

# Rationale and algorithm
Why this should work; the mechanism, step by step, with the exact quantities.

# Steps
Ordered, each producing something measurable.

# Results
Deliverables: reports, artifact files, charts, viewer markers, reusable params.

# Constraints
Branch, no-commit rule, read-only frames, TFs, train dataset, OOS dataset,
what may not be recalculated.

# Data
Training: 2y. Validation: 2m OOS. Column naming for new fields.

# Open questions
```

## 2. Plan — `plans/YYYY-MM-DD-<name>.md`

Header, then Docker entry points, then tasks. Use a `task-NN-*.md` directory when the
experiment has more than ~5 tasks.

```markdown
# <Name> Experiment — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans.

**Spec:** external/docs/superpowers/experiment/<name>.md
**Goal:** one sentence, measurable.
**Architecture:** where the code lives, what it reads, what it never touches.
**Tech stack:** exact libraries available in the experiment image.

## Locked decisions (user-confirmed YYYY-MM-DD)
| # | Decision | Choice |
Ground truth, point selection, loop mode, scoring rule, tie-breaks.

## Global constraints (verbatim from spec + project rules)
Bullets, including "do not commit anything" and the read-only rule.

## Known facts (research, YYYY-MM-DD)
Real column names, dataset paths and sizes, frozen cut values, base rates to beat,
missing inputs and their proxies, precedent modules, host RAM limits.

## Step 0 — Docker entry points (ground truth)
Build, test gate, each run command with its env file.

## Tasks
| task | deliverable | boundary |
Rule: task N+1 does not start until task N's tests are green.

## Verification
Per-task test command; smoke run expectations with concrete row counts.
```

Each task file: **Files** (create/modify/test), **Interfaces** (exact names later tasks
depend on), then steps — write failing tests, run them and see them fail, implement, run
green, real-data spot check with expected numbers, checkpoint reporting changed files with
no commit.

## 3. Iteration report — `experiment/<name>/iter_NN.md`

For autonomous improvement loops. One per iteration, rejected ones included.

```markdown
# Iteration NN -- <transform name>
- transform: ... - horizon: ...
## Counts        | combo | n_pos | n_neg | excluded | skipped |
## Robustness    | agreement of truth vs realized forward return |
## Metrics       | combo | model | split | auc | acc | base_rate | prec@decile | lift | n |
## Verdict       kept / rejected, versus which baseline, by how much
```

Close the loop with `loop_summary.md`: iteration history table
(`iter | transform | metric | status`), the best iteration, and its full metric table.

## 4. Results report — `experiment/results/<name>_results.md`

The deliverable the user approves. Structure that has worked:

```markdown
# <Name> — Results & Conclusion

**Date:** **Spec:** **Plan:** **Branch:**
**Data:** train and OOS ranges, row counts, dataset names.
**Pipeline:** module path, entry command, where artifacts landed.
**Final configuration:** the exact parameter set the numbers below refer to.

## Headline conclusion
The decision, in three sentences, with the single best number and its coverage.
State plainly what is NOT proven (fees? realized P&L? selection bias?).

## The progression
One table, one row per combo, one column per variant — baseline first, chosen last.

## Degeneracies found (and what each fix did)
Numbered. What the optimizer exploited, the symptom, the fix, the effect.

## Validity gates
Null floor, base rate, truth ladder, ablation, look-ahead, provenance, reproduction —
each with its number.

## What generalized vs what did not
Two bullet lists. Negative results stated as findings.

## Config & artifacts (final state)
Artifact paths, params file, plots, viewer overlay names and how to see them,
test count and where they run, what is left uncommitted.

## Next arbiter
The one measurement that would settle what this experiment could not.
```

## 5. Register row — `experiment/REPORT.md`

Two writes per experiment. On start, append to the table:

```markdown
| YYYY-MM-DD | [<name>](<name>.md) | the idea in one line | running | branch `<branch>` off `<base>` |
```

On approval, set the verdict (`success` / `partial` / `negative`), set the disposition
(`merged → <base>`, `pushed, worktree removed`, `branch kept`, `no branch (read-only)`),
link the results file, and add a short entry under `## Entries`: what held, what did not,
and the number that decided it. Rows are never deleted — a re-run is a new row that
references the old one.

## Closing the experiment

After approval: commit on the experiment branch, update the spec and the task files with
what actually happened, write a memory entry with the frozen params, the traps hit, and
the artifact paths. Then dispose of the branch with the user:

- **Successful** — merge into the base branch, remove the worktree.
- **Unsuccessful** — push the branch to the remote so the attempt stays in history, remove
  the local worktree. The results md carries the number that killed it.

Either way the `REPORT.md` row is closed in the same pass. An experiment is not finished
while its register row still says `running`.
