# A Toy Research Project: does a decision graph substitute for context?

A worked example you can run in about twenty minutes, using GoalGraph as the
instrument. It exists to show what the software is *for*, and to be honest about
where its answers are solid and where they are not.

---

## The question

An agent pursuing a goal in an environment it does not fully understand will
form beliefs about that environment, and some of those beliefs will be wrong.
GoalGraph records each belief as an **aim** and each verdict on it as a
**Go / Progress / NoGo** edge in a decision graph.

That raises a question you can actually test:

> When an agent cannot see its whole history, can the decision graph carry what
> scrolled out of view — and does that let a short-context agent behave like a
> long-context one?

This is not an artificial concern. It is the shape of any agent working against
an API with undocumented constraints, a negotiation with unstated limits, or a
configuration space where some states are silently invalid. The agent has a
goal, the environment has rules nobody wrote down, and the transcript grows
faster than the context window.

---

## The task

**Run type: `transformation`.** The agent must turn a starting sentence into a
target sentence, one small edit at a time, while every intermediate sentence
obeys a rule it has *not* been told.

```
start   The cat repaired three schedule twice?
target  The cat counted the parcels again.
rule    (hidden) the sentence has an even number of letters
```

Two constraints, and only one is secret:

| constraint | visible? | what it does |
|---|---|---|
| **step rule** | yes — the agent is told | a proposal may differ by at most 2 words, so it cannot jump to the target |
| **invariant** | no | a state that breaks it is rejected and the agent stays put |

This shape was chosen after three simpler ones failed, and the reason is worth
recording because it is the main practical lesson of this project.

### Why not just "guess the rule"?

We first built pure induction games — guess a rule about number triples, then
about words, then about sentences. All three produced a **star**: a hub of
refuted hypotheses at depth one, with no route through it.

```
nodes=7   edges={'Go': 1, 'NoGo': 5}
branching=1   max depth from start=2
```

Worse, on the easy rules the agent was simply *right on the first turn*. It
guessed `a < b < c` immediately, was never contradicted, and so the graph never
recorded anything. Across 96 judged turns of the number game there were **zero**
refutations and **zero** bytes of recall. Every memory setting behaved
identically because none of them had anything to remember.

The transformation task fixes both problems:

- **Progression is measurable.** Distance to the target falls as the agent
  advances, independently of any judge's opinion.
- **States are places.** An intermediate sentence is somewhere you can be and
  return to, so in principle a `Go` edge connects rather than terminates. In
  practice this has only partly arrived — see the limitations below.
- **Being wrong is unavoidable.** A legal-looking edit silently breaks the
  invariant, so the agent forms wrong beliefs and gets contradicted.

---

## What makes the verdicts trustworthy

The interesting design decision is that **the counterparty is code, not a
model**. A `keeper` holds the hidden rule and answers from it. That makes three
things decidable that are otherwise matters of opinion:

1. whether a move satisfied the rule
2. whether the agent's stated belief contradicts what it has been told
3. whether its final belief is actually right, tested on held-out items

Point 2 is the one that matters. The agent states its current belief as a
checkable expression:

```
"rule": "is_question() and wc() == 6"
```

and the keeper runs it against every observation so far. If it disagrees with
even one, the belief is **refuted as a fact**, and the resulting `NoGo` edge
carries confidence `1.0` rather than a judge's opinion.

This is not a stylistic preference. Measured against ground truth over 349
judged turns, the LLM judge's verdicts are not equally reliable:

| verdict | precision | recall |
|---|---|---|
| **NoGo / abandon** | **93%** | **84%** |
| Progress | 20% | 2% |
| Go / achieved | 33% | 3% |

Refutation is decidable from finite evidence — one contradicting observation
settles it. Confirmation never is. That asymmetry is why judge opinion is capped
at confidence `0.53` while checked evidence gets `1.0`, and why a 33%-precision
verdict can no longer outweigh a checked one when the graph is used to choose
what to do next.

---

## Running it

Start the app, open **Decision Graph** in the sidebar, and set:

| setting | value |
|---|---|
| What this session is doing | `transformation` |
| Hidden rule | the sentence has an even number of letters |
| Messages the agent can see | `0` for the control arm, `4` for the short-context arm |
| What the agent is told about ruled-out aims | one of the four modes below |
| Run label | something that identifies the arm, e.g. `even-graph-w4` |

Press **Start new run**, then **Play**. When the arm finishes, press
**Download this run as CSV** and repeat with the next setting.

### The four memory modes

These are the comparison. Each decides what the agent is told about aims already
ruled out.

| mode | what reaches the prompt | why it is in the experiment |
|---|---|---|
| `none` | nothing | the control — does the graph matter at all? |
| `inline` | the refutation is stated **once**, in the conversation, then left to scroll away | the honest baseline: maybe you do not need a graph, you just need to say it |
| `description` | every ruled-out aim, re-inserted every turn | the original behaviour; cost grows with the graph |
| `graph` | the nearest few, each with the observation that killed it | retrieval; cost fixed by `k` and a character budget |

The `inline` arm is the one to watch. It should hold up at full context and
collapse as the window shrinks, because a refutation mentioned once survives
exactly as long as the window holds it. If `graph` does not beat `inline` at a
short window, the graph is not earning its place.

---

## What comes out

Every judged turn is one CSV row, with the settings repeated on it, so exports
from different arms concatenate and group without reshaping:

```
session_id, run_label, run_type, keeper_rule, provider, model, temperature,
graph_memory_mode, context_window, graph_recall_k, graph_recall_chars, nogo_ungated,
turn, agent, aim, aim_source, stated_rule, verdict_source, rating, aim_status,
next_aim, justification, persistence_count, history_len,
keeper_move, keeper_verdict,
llm_calls, input_tokens, output_tokens, tokens_estimated,
graph_contribution_chars, graph_nodes, graph_edges
```

Four columns carry most of the meaning:

- **`verdict_source`** — `evidence` where the keeper settled it, `judge` where it
  is opinion. This is the column that tells you how much of the graph is fact.
- **`aim_source`** — `graph_path` when the graph chose the aim, `llm_subgoal`
  when the planner invented one, `carried` when it persisted.
- **`graph_contribution_chars`** — how much the graph actually put into that
  turn's prompt. **If this is 0, the memory never engaged and the arm is not a
  test of anything.** Check it first.
- **`input_tokens`** — token cost across the whole pipeline: agent, judge and
  planner, recorded at the single point all three pass through.

---

## The result from running it

Eight arms of the transformation task, `even_letter_count`, four memory modes at
two window sizes:

| mode | window | turns | reached goal | tokens | recall/turn |
|---|---|---|---|---|---|
| `none` | all | 10 | yes | 27,259 | 0 |
| `inline` | all | 10 | yes | 26,192 | 0 |
| `description` | all | 9 | yes | 24,591 | 286 |
| `graph` | all | 11 | yes | 33,460 | 439 |
| `none` | 4 | 11 | yes | 21,857 | 0 |
| `inline` | 4 | 11 | yes | 20,953 | 0 |
| `description` | 4 | 11 | yes | 23,208 | 303 |
| `graph` | 4 | 11 | yes | 23,891 | 378 |

**Every arm reached the goal**, and that is the most important line in the
table. A four-message window costs roughly **20% fewer tokens** than full
context (21,857 vs 27,259 with no memory aid at all) and the agent still solves
the task. The window is close to free here.

**But so is the graph, and that cuts against it.** If every arm succeeds, the
memory was not *needed* — the task is solvable at a four-message window with
nothing recalled. `graph` mode is the most expensive arm at full context
(33,460 tokens) because it adds recall on top of a history the agent could
already see. That is the honest reading: on a task this short, the graph is
overhead.

The place it should earn its keep is a task long enough that the relevant
refutation has scrolled away — which this one, at ten or eleven turns and a
four-message window, only barely is. Demonstrating that is the obvious next
experiment, not a claim this data supports.

### The verdicts really are facts now

A second run, after a fix described below, shows what the keeper buys:

```
verdict_source : {'evidence': 32, 'judge': 4}
aim_status     : {'abandon': 32, 'achieved': 4}

mode     win  turns  proof  in/turn  recall
graph      0     11     11     2585     380
none       0     11     10     2341       0
none       4     11     10     1686       0
```

**Thirty-two of thirty-six verdicts were settled by evidence rather than
opinion** — the agent stated a checkable belief, the keeper contradicted it, and
the resulting `NoGo` carries confidence `1.0`. That is what the whole keeper
design is for, and it is the clearest thing this project demonstrates.

Windowing again looks cheap: 2,341 → 1,686 input tokens per turn, a **28%
reduction**, with the same number of turns and the same outcome.

**A caution on reading any single cell.** One arm here finished in three turns
because the agent happened to guess well, and one did not reach the target at
all. These are single runs, not averages. Treat the columns as directional and
the individual numbers as noisy.

### A bug worth knowing about, because it invalidated the first run

The first eight-arm matrix reported `verdict_source: judge` on all 84 rows —
while the graphs written by those same runs contained `evidence` edges. The
export was writing each row *before* the keeper's override executed, so it
captured a verdict that was about to be overruled. Every number about verdict
provenance in that run was wrong, and it looked entirely plausible.

The fix was to record the row after the keeper settles rather than before. The
lesson generalises: **when a column claims to say how much of your data is fact,
check that it can ever say anything else.**

---

## A result we can stand behind

Windowing works, and it is worth what it costs:

| turn | window 0 | window 6 | window 3 |
|---|---|---|---|
| 1 | 1,370 | 1,300 | 1,308 |
| 4 | 1,815 | 1,343 | 1,180 |
| 8 | **2,482** | 1,438 | **1,070** |

Unwindowed input cost grows **+81% over eight turns and is still climbing**.
Windowed cost is flat. Output tokens are identical to within 3% and call counts
to within 5%, so the window buys a flat cost curve without changing what the
agent produces.

And in a replay over recorded transcripts, remembering refutations past the
window is worth a great deal when the window is short:

| window | no graph | judge-built graph | evidence-built graph |
|---|---|---|---|
| 2 | 71% | 82% | **95%** |
| 4 | 78% | 87% | 95% |
| 8 | 89% | 93% | 95% |
| all | 95% | 95% | 95% |

Two things to read here. The gain decays monotonically to **exactly zero** at
full context — the signature of a mechanism that is doing real work rather than
an artefact. And an **evidence-built graph pulls away from a judge-built one as
it grows**: the judge's 84% recall is survivable on a small graph and costs 13
points on a large one, because missed refutations accumulate and a short window
cannot re-derive them.

---

## What the graph actually looks like

A completed transformation run produces this:

```
nodes 6   edges 5   depth 2
labels  {'Go': 1, 'NoGo': 4}
sources {'judge': 1, 'evidence': 4}

[Go    c=0.525 judge   ] start -> Test whether changing the verb and determiner...
[NoGo  c=1.0   evidence] ...   -> Test whether the hidden rule blocks changing...
[NoGo  c=1.0   evidence] ...   -> Test whether the rule permits changes to...
```

![A transformation run's decision graph](../screenshots/transform_graph_full.png)

Line weight is confidence and dashes mean opinion. The single thin dashed edge
out of `start` is the `Go` a judge offered at `0.525`; the five thick solid
edges are refutations the keeper settled at `1.0`. Two things to read from it.

**The confidence layer works.** Every refutation the keeper settled carries
`1.0`; the single `Go`, which only a judge could offer, carries `0.525`. The
graph now records not just *what* was decided but *how much that decision is
worth*, and pathfinding reads it — a proven dead end costs `1 + 10c` to traverse
while a well-supported route costs `1.1 - c`.

**The shape is still a two-level star, not a path.** Only `Go` and `Progress`
advance the current node, and `Go` stays rare, so refutations pile up around
whichever aim is current instead of extending a route. Depth 2 is better than
the depth-1 hub the pure guessing games produced, but it is not yet the
branching route structure a transformation task was chosen to create.

---

## What this project does *not* show

Being straight about this is the point of a toy project.

- **The live four-arm comparison is thin.** The threshold result above is a
  replay over re-sequenced transcripts, not lived runs. The ordering is
  synthetic even though every observation in it is real.
- **One model, one task family.** Everything here is `gpt-5.4-mini` on
  induction-shaped problems. Nothing licenses a claim about agents in general.
- **Route reuse is not demonstrated.** The graph reaches depth 2, which is not
  enough to contain an alternative route, let alone show one being reused. The
  cause is structural rather than incidental: `NoGo` does not advance the
  current node, so a run dominated by refutations builds width instead of depth.
  Until `Go` fires more often, or refutations are attached to the state they
  were discovered from rather than to the aim, this remains an argument rather
  than a result.
- **Difficulty is the whole ballgame.** Three separate task designs produced
  null results purely because the agent solved them on sight. If you extend this,
  check `graph_contribution_chars > 0` before believing any comparison. A clean
  null from a mechanism that never fired looks exactly like a clean null from a
  mechanism that does not work.

---

## The data

The runs described above are in this folder, so every number can be checked
rather than taken on trust:

| file | what it is |
|---|---|
| `transform_matrix.csv` | the eight-arm run: four memory modes at two window sizes |
| `transform_matrix2.csv` | the two-mode re-run, after the verdict-provenance fix |

Both were produced by driving the app over HTTP exactly as the UI drives it, so
what they measure is the product and not a private harness.

---

## Extending it

The task lives in `src/agent/`. To add one:

1. Write a rules module with pure predicates and a balanced held-out set —
   `sentence_rules.py` is the clearest model to copy.
2. Add a branch to `keeper.py` for `describe`, `opening`, `extract_move`,
   `verdict`, `reply` and `check_aim`.
3. Add the id to the enum in `schemas.py` and the validator in `app.py`.

It will appear in the Decision Graph panel automatically — the run-type list is
served from Python by `/api/run_types` rather than hardcoded in the UI.

**One warning from experience.** Three of the bugs that cost the most time in
building this were a missing branch in exactly that dispatch: a run type with no
`verdict()` case returned `None` for every move, so every observation was
discarded and no claim could ever be refuted. It produced a clean, plausible,
entirely empty result. Add all six branches, then check
`verdict_source == 'evidence'` appears in your CSV before trusting a single
number.
