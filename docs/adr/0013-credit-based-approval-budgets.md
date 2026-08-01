# ADR-0013: Credit-based approval budgets with learned pricing

- **Status:** Proposed
- **Date:** 2026-08-01
- **Deciders:** Wilson
- **Supersedes / Superseded by:** — (extends ADR-0006 terminal command gating; consumes the risk scoring shipped alongside ADR-0009)

## Context

Autopilot rules cap auto-approvals with a flat counter (`limits.max_per_session`).
Every approval is an identical withdrawal: `ls` and a 10-minute full pytest
suite each cost 1. Two problems surfaced on 2026-08-01 in a live
Kai-Platform session:

1. **Large tasks are invisible.** A full-suite pytest rerun reached the user
   only because `allow-unsafe-commands` happened to be at its 50/50 limit.
   At 49/50 the same multi-minute run would have been silently auto-approved.
   "Expensive/long-running" is a real supervision dimension — the user
   watching the dashboard wants a say before the agent disappears into a
   10-minute run — but the classifier only measures danger/reversibility,
   never duration or cost.

2. **The empty-tank UX asks the wrong question.** When the budget is
   exhausted, Kaptn escalates the *next command* ("allow this one?"). The
   actual decision at that moment is "extend autopilot, and by how much?" —
   a budget-governance question, not a per-command one.

What exists today that this design builds on:

- `kaptn/risk.py` — deterministic `score(command, category) → (score,
  reasons)` with a human-readable reason per point. Currently display/audit
  only; not consulted for gating.
- `kaptn/claude/tool_classifier.py` — strict tokenizer; compound commands
  split into segments; **anything that fails strict tokenization classifies
  unsafe** (the fail-closed-on-opacity precedent this ADR generalizes).
- `kaptn_audit.db` — 5,385+ historical decisions (command, category, rule,
  outcome). This is training data for pricing; the cold start is not cold.
- `rule_evaluator.py` — ordered rules with `command_patterns` conditions and
  per-rule limits.

## Decision

Replace flat per-rule counters with a **credit economy**: each approval
request has a deterministic credit price, autopilot windows carry a credit
budget, and exhaustion triggers a **refill escalation** instead of
per-command escalations. Prices start uniform (everything costs 1 — day-one
behavior is identical to today's counter) and are differentiated over time
by an offline learner reading the audit log. (Proposed — details TBD until
accepted.)

### Pricing model

```
price(request) = learned_base(fingerprint) × static_modifiers(request)
```

- **`learned_base` starts at 1 for every fingerprint.** Never start at 0 /
  escalate-everything: that punishes the user on day one. Baseline behavior
  must be indistinguishable from the current flat counter; learning only
  ever *improves* the experience (safe things drift toward free, risky
  things climb).
- **Static modifiers apply from first sight**, because the learner cannot
  price what it has not seen: full-suite test run with no `-k`/path filter,
  build/compile, migration, large Bash `timeout` parameter,
  `run_in_background`. Deterministic table, no model in the hot path.
- **Compound commands SUM segment prices** (danger category still takes the
  max, as today). Max-pricing would make `a && b && c` cheaper than three
  calls and incentivize the agent to batch under the meter.
- **Every price is a receipt.** `kaptn_explain_last` shows the arithmetic:
  "cost 20 = base 5 (command_unsafe) × 4 (full-suite, no filter)". This
  inherits risk.py's reasons discipline; a price with no explanation is a
  bug.

### Precedent book (the learned layer)

- **Fingerprints, not raw strings.** Cache key = executable + subcommand +
  flag shape with volatile values masked (reuse the existing tokenizer).
  `git -C <any> status` is one fingerprint; `pytest tests/` full-suite and
  `pytest -k <expr>` are different fingerprints.
- **Hot path is lookup-only.** Deterministic, fast, explainable. **A lookup
  miss prices at the baseline (1 × modifiers) — it never defaults a decision;
  rules still decide approve/escalate/deny exactly as today.**
- **Repricing runs off the hot path**, periodically, over the audit log:
  frequency, deny history, observed duration, what was touched. This job MAY
  use an LLM — it is offline and its output is a table entry a human can
  review; determinism is only required at decision time.
- **Asymmetric learning.** Prices decay downward slowly (many clean
  approvals earn a discount) and jump instantly on a deny — one human "no"
  sends that fingerprint to escalate until re-reviewed. Trust earned slowly,
  lost fast.
- **Scope the book per project** (or include a cwd class in the
  fingerprint). The same command is safe in a scratchpad and dangerous in a
  checkout. Books are never shared across machines without review — a
  shared price book is a poisoning target.

### Budget modes and the per-action gate

The cumulative budget and the per-action price gate are orthogonal knobs:

```
budget:
  credits: 100 | "unlimited"
  escalate_above: 20     # any single action priced >= this escalates
```

- **Metered (default):** finite credits; exhaustion raises the refill
  escalation below. The per-action gate applies here too — a huge one-shot
  action must not slip through just because the tank happens to be full.
- **Unlimited:** no cumulative meter at all. Supervision rides entirely on
  the per-action gate: cheap, well-precedented actions flow freely forever;
  anything priced at or above `escalate_above` (large tasks, opaque
  scripts, deny-demoted fingerprints) escalates regardless of spend. This
  is the mature end-state once prices are trusted — user attention is spent
  only on expensive actions, never on counting cheap ones.
- **Unlimited with no gate set is a misconfiguration** — that is just
  approve-everything. Kaptn warns on it and the dashboard shows a running
  spend ticker; audit and periodic spend notifications (soft checkpoints,
  no gating) remain active in every mode.

### Refill escalation

Budget exhaustion raises a `governor`-category escalation (always
escalates, never auto-approvable) that is a *budget* decision, not a
command decision:

> Autopilot spent 100 credits across 47 actions (summary from audit db:
> N files written, M commands, top spenders …). Refill 100 / refill 500 /
> stop and review?

The refill prompt turns every empty tank into a natural supervision
checkpoint with a receipt for what the last tank bought.

### Ad-hoc scripts (Python et al.)

A script is a compound command in another syntax; price it by decomposing
it, with the same philosophy risk.py applies to command lines:

- **AST analysis, not regex.** Map constructs onto the existing taxonomy:
  `open()` writes → `file_write`; `os.remove`/`shutil.rmtree` →
  `file_delete`; `requests`/`urllib`/`socket` → network signal;
  `os.environ` reads, `pickle.loads`, `ctypes` → their own signals. Literal
  paths in the script run through the same `path_patterns` conditions
  (a script writing `**/.env*` trips `protect-secrets` exactly as the Write
  tool would). `subprocess.run([...])` with literal args recurses into
  `classify_command`.
- **Aggregate like the shell side:** max for danger category, sum for
  price.
- **Opacity fails closed.** Anything the AST pass cannot resolve to
  literals — `eval`/`exec`, string-built commands, args from stdin,
  unresolvable local imports — marks the script opaque → high price or
  escalate, with the blind spot named in the receipt ("opaque: builds
  command from variable, line 41"). The analyzer never needs to be smart;
  it needs to know when it is blind. (Generalizes the tokenizer's
  fails-strict-tokenization-→-unsafe rule.)
- **Transitive local imports** are files on disk: resolve and analyze them
  (bounded). Third-party imports are priced by a name table (`requests` =
  network) — imperfect but deterministic.
- **Cache by content hash.** Analyze once per hash; identical reruns are
  free lookups; any edit re-analyzes. The common run→fix→rerun loop costs
  one analysis.
- **Honest framing:** this is pricing and accident-prevention, not a
  sandbox. A deliberately evasive script beats static analysis only by
  being opaque, which escalates it anyway. As risk.py says: a low score
  never means "safe".

### Self-evaluation (re-evaluate over time)

The pricing system measures its own quality from the audit log and reports
on the dashboard; the design is revisited against these numbers:

- **Regret rate:** denies (or user overrides) on actions autopilot
  approved — the number that must stay near zero.
- **Nag rate:** escalated fingerprints the user approves ~100% of the
  time — evidence the price is too high; candidates for discount.
- **Refill cadence:** refills per session-hour — too frequent means budgets
  or prices are miscalibrated; too rare means the checkpoint rhythm is lost.
- **Coverage:** % of traffic priced from the precedent book vs. baseline.
- **Opacity share:** % of scripts priced opaque — high share means the
  analyzer needs more resolvable patterns, not that users need more prompts.

Repricing runs on a TTL and on drift events (any deny/override triggers
immediate demotion of the fingerprint). The metric definitions themselves
are reviewed after the first month of live data.

## Options considered

1. **Pattern-based escalate rule for heavy commands (config only)** — an
   `escalate-heavy-commands` rule with `command_patterns` before the allow
   rules. Works today, zero code. But fnmatch is blunt (`pytest
   tests/unit/one.py` matches `*pytest tests/*`), it is binary
   (escalate/not) so it fixes neither budget UX nor pricing, and every new
   heavy shape is a manual config edit. Kept as an interim mitigation.
2. **New `command_heavy` classifier category** — deterministic heuristics in
   the classifier, a real feature with tests. Still binary: a category can
   escalate a heavy task but cannot make 50 trivial reads cheaper than 5
   risky writes, and it leaves the empty-tank UX untouched.
3. **Credit economy with learned pricing (chosen)** — subsumes both: heavy
   tasks are a pricing problem, budget exhaustion becomes a governance
   checkpoint, and the flat counter is the degenerate case (all prices = 1),
   so migration risk is near zero.
4. **Zero-trust start (all prices at 0 auto-approvals / escalate
   everything, learn upward)** — rejected. Maximally annoying on day one;
   no one wants that. The audit log makes it unnecessary anyway: the first
   repricing pass differentiates against 5,385 historical decisions before
   the feature ships.

## Consequences

- **Positive:** large tasks surface proportionally to their weight without a
  brittle "large" definition; user attention is spent where risk/cost is;
  empty tanks become supervision checkpoints with receipts; day-one behavior
  identical to today (no migration pain); every price explainable; script
  risk finally inspected rather than treated as one opaque blob.
- **Negative / cost:** a pricing table and modifier set to maintain; an
  offline repricing job (new moving part, though failure degrades to
  baseline prices, not to wrong decisions); AST analyzer is real
  engineering with a long tail of Python dynamism (mitigated by
  fail-closed opacity, at the cost of some over-escalation); per-project
  precedent books add state to back up and reason about.
- **Neutral:** config schema migration `limits.max_per_session` →
  `budget.credits` / `budget.escalate_above`, including the `"unlimited"`
  mode (with a compat shim reading old configs as all-prices-1, metered);
  dashboard work to show spend, receipts, and the self-evaluation metrics;
  refill flow needs a first-class UI affordance; the interim pattern rule
  (option 1) can ship immediately and be retired when pricing lands.
