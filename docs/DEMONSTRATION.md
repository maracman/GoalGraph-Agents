# GoalGraph, demonstrated

GoalGraph gives a conversational agent a **goal graph**: a persistent record
of which aims advanced and which were refuted, fed back into the agent so it
does not re-derive, re-litigate, or loop its way toward something already
worked out. It is not a memory store in the RAG sense — it does not archive
facts — it records *paths toward goals*, and its job is to make a proven path
cheaper to take than to rediscover.

Everything below was measured on the shipped code, with a small open model
(llama-3.2-3B) acting and gpt-5.4 judging, on the hidden-rules sentence task
(`constraints`). Each demonstration names the script that reproduces it.

---

## The scaffold keeps a small model on task

The core loop — a current aim in the prompt, a judge revising it each turn,
Go/Progress/NoGo written to the graph — is what separates an agent from a
transcript. Switch it off (`aim_system=off`) and the same model loops: a
third of its messages nearly repeat an earlier one, in streaks up to nine,
and it almost never finishes.

| | no scaffold | full system |
|---|---|---|
| solved | 1/20 | **9/20** |
| near-duplicate messages | 0.27 | 0.15 |
| longest repeat streak | 7.0 | 2.9 |

Layering matters too: looping falls monotonically as the scaffold and then
the graph come on (0.32 → 0.14 → 0.035 near-dup across off / aims-only /
aims+graph).

Reproduce: `studies/constraints_replicate.py`, `studies/constraints_scaffold.py`

## A graph paved by a strong model lifts a weaker one

Nodes that a keeper *proves* — an advance confirmed by evidence, not judged
by opinion — are stamped with the move that proved them: the accepted answer
itself. When another agent later adopts that aim, the proof stays in its
prompt for as long as the aim does. A graph is something one agent can earn
and another can ride.

Demonstrated at the hardest setting (`five_constraints` — five hidden rules
at once, which the 3B cannot crack alone: across every unaided session ever
run it produced roughly one accepted sentence per seven hundred turns and
zero solves):

| | unaided 3B | 3B + paved graph |
|---|---|---|
| accepted answers per session | **0.00** (19 sessions, none) | **0.80** (z = 3.03) |
| full solves | 0/19 | 3/20 |

What transfers is the proven **template**: 18 of 19 accepted answers followed
the sentence shape the donor graph proved. The graph carries it two ways —
as proof examples on the nodes, and as the aim text describing the shape —
and riders use both. Agents also stamp and ride their own in-run proofs: a
sentence accepted mid-session travels forward on the aim that produced it.

Reproduce: `studies/constraints_floorlift.py` (donor paving in the script
docstring); earlier variants in `studies/constraints_concrete.py`.

## Agents want the graph

When the choice of next aim is handed to the agent (`aim_fork_mode=
judgement`) instead of a similarity threshold, agents take a graph aim on
**96% of choices** (481 forks measured, zero fall-backs), and where a graph
is inherited, essentially all adopted aims are inherited ones (642 of 645).
The graph is consulted as a ranked set of proven aims, not walked as a route.

Reproduce: `studies/ddx_fork.py`

## The record defends the run

Three enforcement features act on what the graph knows with certainty —
what has already failed:

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

Frontier-class models carry their working state in their own prose — in the
clinic demo gpt-5.4 solved as well through a 2-message window as a
32-message one — so for them the graph is a record and a steering surface,
not a performance lever. The leverage is:

- **weak and mid actors**, where the scaffold is the difference between
  looping and functioning;
- **handoffs**, where a capable model paves once and cheaper ones ride;
- **inspection**: every run exports per-turn CSV, and every aim, verdict and
  proof is on the graph where you can read it.

Reproduce the boundary: `studies/ddx_gradient.py`, `studies/constraints_memory.py`

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
every row. Scripts under `studies/` are the UI scripted — same endpoints,
same CSV.
