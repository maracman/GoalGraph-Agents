# GoalGraph, demonstrated

GoalGraph gives a conversational agent a **goal graph**: a persistent record
of which aims advanced and which were refuted. It feeds that record back into
the agent so the agent does not re-derive, re-litigate, or loop toward
something already worked out. It is not a memory store in the RAG sense
because it does not archive facts. It records *paths toward goals*, and its
job is to make a proven path cheaper to take than to rediscover.

Everything below was measured on the shipped code, with a small open model
(llama-3.2-3B) acting and gpt-5.4 judging, on the hidden-rules sentence task
(`constraints`). Each demonstration names the script that reproduces it.

---

## The scaffold keeps a small model on task

The core loop uses a current aim in the prompt, a judge revising it each turn,
and Go/Progress/NoGo written to the graph. This loop separates an agent from a
transcript. Switch it off (`aim_system=off`) and the same model loops: a third
of its messages nearly repeat an earlier one, in streaks up to nine, and it
almost never finishes.

| | no scaffold | full system |
|---|---|---|
| solved | 1/20 | **9/20** |
| near-duplicate messages | 0.27 | 0.15 |
| longest repeat streak | 7.0 | 2.9 |

Looping also falls monotonically as the scaffold and then the graph come on
(0.32 → 0.14 → 0.035 near-dup across off / aims-only / aims+graph).

Reproduce: `studies/constraints_replicate.py`, `studies/constraints_scaffold.py`

## A graph paved by a strong model lifts a weaker one

A keeper *proves* a node through an advance confirmed by evidence, not judged
by opinion. The node is stamped with the move that proved it: the accepted
answer itself. When another agent later adopts that aim, the proof stays in
its prompt for as long as the aim does. One agent can earn a graph, and
another can ride it.

The hardest setting is `five_constraints`: five hidden rules at once, which
the 3B cannot crack alone. Across every unaided session ever run, it produced
roughly one accepted sentence per seven hundred turns and zero solves:

| | unaided 3B | 3B + paved graph |
|---|---|---|
| accepted answers per session | **0.00** (19 sessions, none) | **0.80** (z = 3.03) |
| full solves | 0/19 | 3/20 |

The proven **template** transfers: 18 of 19 accepted answers followed the
sentence shape the donor graph proved. The graph carries it two ways: as proof
examples on the nodes and as the aim text describing the shape. Riders use
both. Agents also stamp and ride their own in-run proofs because a sentence
accepted mid-session travels forward on the aim that produced it.

Reproduce: `studies/constraints_floorlift.py` (donor paving in the script
docstring); earlier variants in `studies/constraints_concrete.py`.

## Agents want the graph

When the choice of next aim is handed to the agent
(`aim_fork_mode=judgement`) instead of a similarity threshold, agents take a
graph aim on **96% of choices** (481 forks measured, zero fall-backs). Where a
graph is inherited, essentially all adopted aims are inherited ones (642 of
645). The graph is consulted as a ranked set of proven aims, not walked as a
route.

Reproduce: `studies/ddx_fork.py`

## The record defends the run

Three enforcement features act on what the graph knows with certainty: what
has already failed.

- **Provenance floor** (`candidate_ranking=grooved`): inherited aims below a
  similarity floor are never offered; the run's own nodes always are.
  Measured with a deliberately wrong donor graph: foreign aims adopted fell
  from 23 to 2 per arm.
- **Move guard** (`move_guard=true`): a draft that re-treads an
  already-rejected move is regenerated once, with the refutation named.
  Re-tread rate fell from 0.120 to 0.032 per proposal.
- **Evidence-pooling merges**: combining graphs sums the visits and pools
  the confidence of shared edges, so two runs that proved the same path
  deepen it.

Reproduce: `studies/constraints_grooved.py`, `studies/constraints_guard.py`

## When the graph pays

Frontier-class models carry their working state in their own prose. In the
clinic demo, gpt-5.4 solved as well through a 2-message window as a 32-message
one, so for them the graph is a record and a steering surface, not a
performance lever. The leverage is:

- **weak and mid actors**, where the scaffold is the difference between
  looping and functioning;
- **handoffs**, where a capable model paves once and cheaper ones ride;
- **inspection**: every run exports per-turn CSV, and every aim, verdict and
  proof is on the graph where you can read it.

Reproduce the boundary: `studies/ddx_gradient.py`, `studies/constraints_memory.py`

## Method

All demonstrations drive the app over its own HTTP endpoints, exactly as the UI
does. Every run starts a fresh server session with the second agent muted, so
one agent proposes.

The actor is `meta-llama/llama-3.2-3b-instruct` via an OpenAI-compatible host
in strict provider mode: provider failure fails the run rather than switching
models. The judge, planner, and fork arbiter use `gpt-5.4` through
`judge_provider` / `judge_model`. Actor turns have a 250-token maximum;
judge calls use temperature 0.5 and a 400-token maximum.

Where graph recall is on, `k = 6` and the budget is 1,200 characters. Runs are
capped at 40 generate calls, except the ddx uptake study, which uses 70. Arm
order rotates per replicate block, runs resume by label, and
`studies/results/` receives one JSON row per run.

A `near-duplicate` has trigram-Jaccard >= 0.6 against any earlier message by
the same agent. `distinct accepted` uses the keeper's novelty rule: word-overlap
< 0.6 against the worked example and all earlier accepted answers. The paved-
graph primary is a tie-corrected Mann-Whitney z on distinct accepted per run.

The scaffold uses the constraints task, level `two_constraints`, window 24,
gate fork, and n = 20 per arm. The three-arm layering figures use n = 12 per
arm. Arms differ only in `aim_system` / `graph_memory_mode`.

The paved-graph study uses level `five_constraints`, window 24, judgement fork,
and n = 20 donor versus 19 unaided. `gpt-5.4` paves the donor graph on the same
level with gate fork and window 24, carrying each solved run's graph into the
next until three have solved. The final 28-node graph has 6 proof-stamped
accepted sentences and transfers through the saved-graphs API; run-scoped dead
ends are pruned on transfer. A template family has >= 0.5 word-overlap with a
donor proof, or the sentence shape “was/is/are the ..., or not?”.

The uptake study uses the ddx clinic task, window 3, a fixed 43-node inherited
graph, and 72 runs across three fork arms. The 96% figure covers the 481 forks
of the two agent-arbitrated arms.

The provenance-floor study uses the ddx graph in the constraints task,
judgement fork, and n = 8 per arm. Move-guard figures use gate-fork arms at
n = 16.

The named scripts are canonical: every setting they POST is the method, and
each script's docstring states its design.

## Settings shipped

| setting | values | what it does |
|---|---|---|
| `aim_system` | on / off | the scaffold itself |
| `graph_memory_mode` | none / inline / description / graph | what recall feeds back |
| `aim_fork_mode` | gate / judgement / scratchpad | who picks the next aim |
| `candidate_ranking` | similarity / grooved | provenance floor + groove/hop annotations |
| `move_guard` | on / off | regenerate a re-tread once |
| `graph_recall_k`, `graph_recall_chars` | ints | recall budget |
| `context_window` | int, 0 = all | messages visible; per-role overrides supported |
| `judge_provider`, `judge_model` | provider ids | judge on a different model than the actor |
| `strict_provider` | on / off | a provider failure fails the run instead of silently switching |
| `task_variant` | task-defined | e.g. ddx `stateful_patient` |
| `order_salt` | string | pin candidate ordering across paired runs |

Node proofs (`proof_move`) and aim-riding proofs (`aim_proof`) are automatic
wherever a keeper verifies an advance.

All data: `studies/results/*.json`, one row per run, settings repeated on
every row. Scripts under `studies/` are the UI scripted: same endpoints,
same CSV.