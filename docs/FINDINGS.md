# What the goal graph is for — findings from the August 2026 studies

GoalGraph is a **goal graph, not a memory store**. Knowledge graphs used for
RAG keep a continuous record of hyperlinked data so that compaction loses
less; that is a memory job. This graph records which aims advanced and which
were refuted, and its job is to **remove friction along a path to a goal that
has been proven before** — so an agent does not re-derive, re-litigate, or
loop its way toward something a previous run already worked out.

Ten study series (≈480 scored runs, all pre-registered, all with engagement
tripwires) tested it both as what it is and as what it is not. The one-line
summary:

> As a memory store it does not beat the agent's own prose **for the cases we
> built**. As a goal scaffold it is heavily used by every model we tested,
> and for weak models it is the difference between looping and functioning.

---

## 1. The scaffold is the active ingredient — proven, for weak models

The aim system (a current aim in the prompt, a judge revising it on a
1–7 scale, Go/Progress/NoGo verdicts) was built in the Llama-2 era to stop
agents falling into repetitive loops. That claim was never tested until now,
because every earlier ablation kept the scaffold in both arms.

Three arms, llama-3.2-3B acting, gpt-5.4 judging, constraints task, n=12:

| arm | solved | capped | near-dup looping | longest loop |
|---|---|---|---|---|
| no aims (pre-GoalGraph) | 1/12 | 11/12 | **0.321** | **8.9** |
| aims, no graph memory | 3/12 | 9/12 | 0.139 | 2.4 |
| aims + graph | 8/12 | 4/12 | 0.035 | 0.6 |

The aimless weak model loops — a third of its messages nearly repeat an
earlier one. The scaffold halves that (z = 2.02); scaffold + graph nearly
eliminates it (z = 3.35), a clean monotone dose–response. Pooling the
scaffolded arms across both weak-model studies: 20/48 solved vs 1/12 without
aims (p ≈ 0.04).

Honest caveat: the graph-vs-none *solve* split flipped direction between two
studies run days apart (8/12 vs 3/12, then 3/12 vs 6/12) — the 3B is bimodal
and hosted routing adds variance — so "the graph beats bare aims on solve
rate" is **not established**. "The scaffold beats no scaffold" is — and it
**replicated**: a pre-registered confirmatory study (the two decisive arms
only, n=20 each, nothing else varied) found solve 9/20 vs 1/20 (Fisher
p = 0.0084) and looping 0.148 vs 0.271 (Mann-Whitney z = 2.37), both passing
their pre-registered thresholds. This is the one effect in the investigation
with a discovery and an independent replication behind it.

## 2. The paved path gets used — by every model

When the route-or-invent fork is arbitrated by the agent instead of the
`similarity × trust` gate (72-run study, fixed 43-node inherited graph):

- agents took a graph aim on **96% of 481 forks**, and never once fell back;
- **642 of 645** graph-sourced aims were inherited nodes, not nodes the run
  created — reuse of a previous run's path is essentially total where one
  exists;
- graph use roughly doubled (routed aims 336 → 660) with the agent deciding.

What they take is the graph as a *ranked set of proven aims*, not as a walk:
offered the literal next hop on a stored path, agents took it only ~12% of
the time, preferring a relevant proven aim elsewhere in the graph ~24:1. Two
structural facts explain why walking fails: the graph accumulates as a
near-tree (a directed path to the goal-like node exists from ~1 node in 9),
and the trust gate latches off after one failure (trust decays 0.6ⁿ against
a fixed threshold; observed exactly in the recorded runs). Adopting an aim is
not traversing an edge; the path requirement was an artefact.

## 3. Where friction removal does not show: strong models' outcomes

For gpt-5.4, none of this moves solve rate, on any task or regime we could
build — and the studies say precisely why, which is the scoped version of
the negative:

- **Small state:** the agent rebuilds its working state in one or two
  sentences of its own prose every turn (measured: ~260-char messages carry
  the whole ddx investigation; a 2-message window solves as well as a
  32-message one even against a patient who refuses to repeat anything).
  The friction the graph would remove is friction a frontier model does not
  feel: re-deriving the path is cheaper than reading it.
- **Large state:** where forgetting finally devastates (five simultaneous
  hidden constraints: 0/12 at a 3-message window vs 9/12 at 24, p = 0.0003),
  what is missing is *evidence* — which exact sentences passed and failed —
  and a goal graph correctly does not store that layer. Recalling proven and
  refuted **aims** into the prompt (37KB/run) recovered 2/12. That is the
  boundary of the design, not a defect in it: it is a goal graph being asked
  to be a memory store.

So: "does not beat prose memory for the cases we built" is the accurate
claim. The cases where a goal graph should pay by design — a *proven* path,
an agent for whom re-derivation is expensive — are exactly where the effects
appeared (§1, §2).

## 4. Cross-goal transfer: tested, and the answer is asymmetric

The framing's own test (48 runs): gpt-5.4 paved donor graphs on a level and
its superset neighbour; the 3B then faced the target level fresh, or
inheriting the same-level donor, the adjacent donor, or a real graph from a
different task entirely (placebo).

- **Benefit: not detectable.** fresh 7/12, same 6/12, adjacent 8/12 (all
  p = 1.0), and the same-level gate failing means the design could not see
  transfer at this n - chiefly because the fresh arm was never pathless: with
  a competent scaffold the agent **paves its own graph within-run** (fresh
  runs took their own graph's aims on 169 of 171 forks) and self-paving cost
  only ~9 turns. Inheritance competes with self-paving, and at any level the
  weak model can self-pave, there is no friction left to remove. The level it
  cannot self-pave floors it entirely - for this model pair the window where
  inheritance could pay is razor-thin.
- **Harm: significant.** The mismatched graph dropped the weak model from
  7/12 to **1/12** (p = 0.027), at the same donor-aim uptake as the true
  donors - it rode clinical aims through a sentence game to the cap in 11 of
  12 runs. The paved path gets ridden wherever it leads. An inherited graph
  is an active commitment, and curation is a safety property of the design,
  not housekeeping.
- **The competence window.** Friction removal pays between two lines: above
  (gpt-5.4) re-derivation is free; far below, the agent cannot read 10KB of
  recall (the 3B re-proposed rejected sentences ~80 times per run with the
  answers in its prompt). The 3B-with-strong-judge sits inside the window
  for behaviour; where the window's edges are for outcomes is open.
- **Narrative/behavioural value for mid models.** The original use — a
  character consistently pursuing a goal — is behavioural, and behavioural
  metrics are where the effects live. A blinded coherence comparison on
  open-ended roleplay would test the original claim on its own terms.

## 5. Making the groove explicit: five mechanisms tested, one lesson

The "deeper groove / easier path" intuition was implemented five ways and
each was tested against its own pre-registration on the weak-model platform:

- **goal-hop ordering** (candidates sorted nearest-the-goal first): actively
  harmful — on a young self-paved graph everything is one hop from
  everything, the ordering made the agent's own first ideas look
  authoritative, fork uptake doubled and the guard arm's solve rate halved.
  The groove became a rut. Reverted to annotations.
- **groove/hops annotations** (evidence shown per candidate, order
  untouched): no detectable effect either way.
- **similarity floor on inherited candidates**: mechanically perfect (junk
  adoption 23 → 2 in the mismatch arm) but no outcome change — the harm it
  guards against did not recur in the seasons it was tested.
- **evidence-pooling merges** (visits sum, weights pool, instead of keeping
  the shallower edge): kept as a straightforward bug fix — merging two
  graphs that both proved a route used to make the groove shallower.
- **the move guard** (a draft re-treading a rejected move is regenerated
  once, with the refutation named): cuts re-treads ~4x (0.032 vs 0.120 per
  proposal) but misses significance at n=16, converts to nothing on progress
  or solve, and costs 12% more tokens. Re-treads were ~14% of proposals;
  eliminating them could not move a task whose binding constraint is
  cracking the rules.

The lesson across all five matches the wider investigation: mechanisms that
**withhold refuted or foreign options work as designed**, mechanisms that
**push proven options do not help and can hurt**, and none of it moves
outcomes while the arbiter already takes graph aims on ~96% of its choices.
The scaffold carries the effect; the embellishments decorate it.

## 6. Instrument findings that stand regardless of framing

The graph-as-record earned its keep this week in a different way: the audits
it enabled found and fixed real scoring bugs — the exported `aim_source`
column silently held a different variable for the project's entire history
(~18.5% of rows mislabelled); "differential diagnosis: X, Y" scored as a
commitment to X, from any speaker including the patient; the constraints
keeper answered a *successful* repair of a rejected sentence with "you
already tried that and I rejected it" while scoring it accepted. All fixed
and regression-tested. Every study above was run after these fixes; results
from before them undercount routing and are not comparable.

Full data: `studies/results/v3_fork_w3.json`, `v3_gradient.json`,
`v3_constraints_w3.json`, `v3_weak_w3.json`, `v3_scaffold_w24.json`,
`v3_transfer_two.json`, `v3_grooved.json`, `v3_grooved2.json`,
`v3_guard.json`, `v3_replicate.json`. Study scripts under `studies/`, each
with its design and pre-registration in the docstring.
