import logging
import re
import time
import json
import random
import difflib
import networkx as nx
import pandas as pd
from .schemas import (
    json_schemas,
    json_schema_aim_choice,
    json_schema_review_goal,
    json_schema_new_subgoal,
    json_schema_response
)
from .llm_service import llm_service
from .graph_memory import (GraphMemory, legacy_nogo_statement, NOTEPAD_FIELD,
                           notepad_prompt, render_notepad, trim_notepad,
                           verdict_confidence, NOGO, PROOF, OPINION)
from .graph_intelligence import (
    find_path_to_goal,
    find_nearest_goal_node,
    import_graph,
    combine_graphs,
    link_similar_nodes
)

# Set up logging
logger = logging.getLogger('agent_logger')


class AgentGenerationError(RuntimeError):
    """Raised when an agent response cannot be generated."""


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def extract_json(response_text):
    """Extract a JSON object from a string that might contain extra text."""
    try:
        start_index = response_text.find('{')
        end_index = response_text.rfind('}') + 1
        if start_index != -1 and end_index > 0:
            return response_text[start_index:end_index]
    except Exception as e:
        logger.error(f"Error extracting JSON: {e}")
    return response_text


def validate_json(response_text, schema):
    """Parse JSON text and validate against a schema (best-effort)."""
    try:
        output = json.loads(response_text)
        # Light validation: check required keys exist
        for key in schema.get("required", []):
            if key not in output:
                logger.warning(f"Missing required key '{key}' in JSON output")
                return None
        return output
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error: {e}")
        # Try extracting JSON from surrounding text
        extracted = extract_json(response_text)
        if extracted != response_text:
            try:
                output = json.loads(extracted)
                for key in schema.get("required", []):
                    if key not in output:
                        return None
                return output
            except json.JSONDecodeError:
                pass
    return None


def is_too_similar(text1, text2, threshold=0.2):
    """Return True if two strings are more similar than the threshold."""
    if not text1 or not text2:
        return False
    similarity = difflib.SequenceMatcher(None, text1, text2).ratio()
    return similarity > threshold


# ---------------------------------------------------------------------------
# LLM helper – sends a prompt through the existing llm_service
# ---------------------------------------------------------------------------

def llm_judge_call(system_prompt, user_prompt, generation_vars):
    """Make a lightweight LLM call for the judge / subgoal generator.

    Uses lower temperature and fewer tokens than the main agent call.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    options = {
        'temperature': 0.5,
        'max_tokens': 400,
        'top_p': 0.9,
    }
    # Carry over provider / model from generation_vars so the judge uses the
    # same backend the agent is configured with - unless a judge override is
    # set. In a model comparison the judge and keeper are the instrument, not
    # the subject: a weak model judging a weak model confounds acting with
    # scoring, and a judge that cannot emit JSON stops recording verdicts, so
    # the graph never gets built and the memory arm silently dies.
    for key in ('provider', 'model', 'offline', 'strict_provider'):
        if key in generation_vars:
            options[key] = generation_vars[key]
    if generation_vars.get('judge_provider'):
        options['provider'] = generation_vars['judge_provider']
        options['model'] = generation_vars.get('judge_model') or options.get('model')

    if options.get('offline', False):
        return None  # Cannot judge in offline mode

    try:
        raw = llm_service.complete(messages, options)
        # Small delay to respect rate limits. Rapid graph runs can set this to 0.
        judge_delay = float(generation_vars.get('judge_delay_seconds', 1))
        if judge_delay > 0:
            time.sleep(judge_delay)
        return raw
    except Exception as e:
        logger.error(f"LLM judge call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_go_nogo_nodes(graph):
    """Return lists of Go and NoGo destination nodes from the graph."""
    go_nodes = []
    nogo_nodes = []
    for u, v, data in graph.edges(data=True):
        label = data.get('label', '')
        if label == 'Go':
            go_nodes.append(v)
        elif label == 'NoGo':
            nogo_nodes.append(v)
    return go_nodes, nogo_nodes


# Columns that hold text but can be inferred as float64 when every agent starts
# with them empty. Under pandas 2.x, writing a string into such a column raises
# rather than widening it, which breaks the write-back after an aim is set.
_TEXT_COLUMNS = ('current_aim', 'suggestion', 'current_node_location',
                 'last_response', 'last_narration', 'persistance_score',
                 'current_aim_source', 'notepad')


def ensure_text_columns(agent_df):
    """Widen text columns to object so aim write-back cannot fail on dtype."""
    for col in _TEXT_COLUMNS:
        if col not in agent_df.columns:
            # A session created before a column existed still has to accept a
            # write-back to it, and pandas will not create one from `.at`.
            agent_df[col] = ''
        elif agent_df[col].dtype != object:
            agent_df[col] = agent_df[col].astype(object)
    return agent_df


def annotate_aim(graph, node, status, reason=None, rating=None, turn=None,
                 ruleset=None, enabled=True, evidence=False):
    """Attach to a node the payload the graph would otherwise throw away.

    Without this, `graph` memory mode has nothing to retrieve: recall looks for
    nodes marked as aims and finds none, so it silently returns nothing and
    behaves exactly like having the graph switched off. Node identity is left
    alone so saved graphs and the graph views keep working.
    """
    if not enabled or node not in graph:
        return graph
    from .graph_memory import canonical_status
    data = graph.nodes[node]
    data['kind'] = 'aim'
    data['status'] = canonical_status(status)
    if not data.get('full_text'):
        data['full_text'] = str(node)
    if ruleset:
        data['ruleset'] = ruleset
    if evidence:
        # An evidence-settled verdict re-earns trust for a node that arrived
        # marked unverified from an earlier run. setdefault alone kept the
        # doubt flag forever: once False, nothing ever set it back, so recall
        # went on hedging about claims this very run had already confirmed.
        data['verified'] = True
    else:
        data.setdefault('verified', True)
    if rating is not None:
        data['rating'] = int(rating)
    if turn is not None:
        data['turn'] = int(turn)
    # The first, specific justification beats a later vague restatement.
    if reason and len(str(reason)) > len(str(data.get('reason', ''))):
        data['reason'] = str(reason)[:300]
    return graph


def update_graph(graph, current_node, next_node, label, weight=1.0):
    """Add or update an edge, accumulating confidence across visits.

    The weight is a running estimate, not a snapshot of the last verdict. That
    matters as soon as a graph outlives the run that built it: an agent that
    inherits a route, follows a `Go` edge and then finds it does not work
    should not have that edge still sitting at full confidence, and should not
    have it relabelled either. The route stays on the graph and gets cheaper to
    doubt.

    Agreement moves the estimate toward 1 and contradiction toward 0, both at a
    rate that falls as evidence accumulates, so a single bad experience dents a
    well-established route rather than erasing it. Costs never reach zero,
    because a free edge wins every search regardless of merit.
    """
    if current_node not in graph:
        graph.add_node(current_node)
    if next_node not in graph:
        graph.add_node(next_node)

    if not graph.has_edge(current_node, next_node):
        graph.add_edge(current_node, next_node, label=label, weight=weight,
                       visits=1)
        return graph

    edge = graph[current_node][next_node]
    visits = int(edge.get('visits', 1)) + 1
    try:
        prior = float(edge.get('weight', weight))
    except (TypeError, ValueError):
        prior = weight
    agrees = edge.get('label') == label
    target = weight if agrees else 0.0
    # 1/visits: the second visit moves the estimate halfway, the tenth barely
    # at all. Long-standing routes are hard to overturn on one bad case, which
    # is the behaviour a reusable graph needs.
    updated = prior + (target - prior) / visits
    edge['weight'] = round(min(max(updated, 0.05), 1.0), 4)
    edge['visits'] = visits
    if agrees:
        edge['label'] = label
    else:
        # A contradiction does not rewrite history. The edge keeps the verdict
        # it was built with and records that something later disagreed, so the
        # graph shows a route that has become doubtful rather than one that
        # silently changed its mind.
        edge['contested'] = int(edge.get('contested', 0)) + 1
    return graph


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def clean_text(value, default=None):
    """A usable string, or the default.

    Values round-trip through a pandas DataFrame between turns, so an absent
    aim comes back as NaN rather than None. NaN is truthy, so it survives every
    `if aim:` check and ends up added to the graph as a node, where the first
    string operation on it fails.
    """
    if value is None:
        return default
    if isinstance(value, float):          # NaN and anything else numeric
        return default
    text = str(value).strip()
    if not text or text.lower() == 'nan':
        return default
    return text


def already_ruled_out(graph, proposed, threshold=0.86):
    """Has this aim, or one meaning the same thing, already been refuted?

    Nothing currently stops the judge handing back an aim the graph has already
    buried, which is the cheapest possible use of a decision graph and was not
    being made.
    """
    proposed = clean_text(proposed)
    if not proposed:
        return None
    from .graph_memory import rank_by_similarity, normalise, NOGO
    dead = []
    for node, data in graph.nodes(data=True):
        if data.get('status') == NOGO or str(node).endswith('_NoGo'):
            dead.append((node, data.get('full_text') or str(node).replace('_NoGo', '')))
    if not dead:
        return None
    scores = rank_by_similarity(proposed, [text for _, text in dead], use_embeddings=True)
    best = max(range(len(scores)), key=lambda i: scores[i])
    if scores[best] >= threshold or normalise(dead[best][1]) == normalise(proposed):
        return dead[best][1]
    return None


TRUST_FLOOR = 0.15          # never quite stop listening to the graph
TRUST_DECAY = 0.6           # a graph route that fails costs this much trust
# Similarity x trust needed for a graph route to override the judge. The
# similarity is cosine between a node label (a sentence) and the agent's goal
# (often a multi-kilobyte brief), which tops out around 0.45-0.55 even for a
# genuinely on-goal route - the first value here, 0.55, was above the maximum
# ever observed, so routing was impossible at any trust and 16 runs produced
# one routed aim. At 0.40, a relevant route qualifies at full trust and one
# failure (trust 0.6) pauses routing until a success earns it back.
ROUTE_MIN_SCORE = 0.40


def tuning(generation_vars, name, default):
    """A knob that a study can set per run without editing code.

    The trust and routing constants were chosen by judgement and never swept;
    an optimisation pass needs them settable through the same settings channel
    as everything else, or every configuration would be a code edit and an app
    restart.
    """
    try:
        v = float((generation_vars or {}).get(name, default))
        return v if v == v else default          # NaN guard
    except (TypeError, ValueError):
        return default


def groove_depth(graph, node):
    """How well-worn this aim is: proven advances, weighted by evidence.

    Go and Progress edges deepen the groove in proportion to their running
    confidence and how often they were walked (log-damped, matching
    update_graph's diminishing steps); NoGo edges cut against it. This is the
    same evidence prune_for_transfer ranks by - one notion of "worth keeping"
    doubling as "worth offering".
    """
    import math
    score = 0.0
    for _u, _v, e in list(graph.in_edges(node, data=True)) + \
            list(graph.out_edges(node, data=True)):
        sign = {'Go': 1.0, 'Progress': 0.6, 'NoGo': -0.5}.get(e.get('label'), 0.0)
        try:
            w = float(e.get('weight') or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        visits = int(e.get('visits') or 1)
        score += sign * w * math.log1p(visits)
    return round(score, 2)


def goal_hops(graph, goal_text):
    """Edge-distance from every node to the goal-nearest node, or {}.

    Undirected on purpose: the graph accumulates as a near-tree, so a
    directed path to the goal-like node exists from about one node in nine,
    while undirected hops are defined for nearly every pair. Adopting an aim
    is not traversing an edge - what the count carries is how close an aim
    sits to the goal region in the graph's own experience, not whether it is
    walkable from here.
    """
    result = find_nearest_goal_node(graph, goal_text)
    if result is None:
        return {}, None
    goal_node, _sim = result
    try:
        hops = nx.single_source_shortest_path_length(
            graph.to_undirected(as_view=True), goal_node)
    except Exception:                                              # noqa: BLE001
        return {}, goal_node
    return hops, goal_node


def route_candidates(graph, current_node, path_result, current_aim='',
                     ruleset='default', k=4, limit=6, goal_text='',
                     ranking='similarity'):
    """The places on the graph worth going next from here.

    Three sources, because one of them is nearly always empty. Measured on the
    richest graph these runs produce (54 nodes, 53 edges): the nearest-goal
    node is found comfortably — similarity 0.515, above every threshold in the
    code — but a *directed path* to it exists from only 6 of 53 nodes. The
    graph accumulates as a near-tree, so a node is reachable only from its own
    ancestors, and `find_path_to_goal` asks for the goal-like node to be a
    descendant of wherever the agent happens to be standing.

    That is a third reason routing does not fire, underneath the trust latch
    and independent of it: here trust was 1.0 and the similarity was fine, and
    there was still no route. A fork offered only path candidates would have
    nothing to choose between on nine turns in ten.

    So the fork is also shown what the graph knows but cannot walk to: the most
    relevant live aims anywhere in it. Adopting an aim is not traversing an
    edge, and the path requirement is an artefact of modelling aims as a route
    rather than as a set. Each candidate carries its `kind`, so a choice of a
    genuine path can still be counted separately from the wider notion and
    stays comparable with every result recorded before this existed.
    """
    out, seen = [], {current_node}
    if path_result is not None:
        path, target, similarity = path_result
        if len(path) > 1:
            out.append({'node': path[1], 'kind': 'path',
                        'similarity': round(float(similarity), 2),
                        'why': f"next step on the known path to '{target}'"})
            seen.add(path[1])
    if current_node in graph:
        for nbr in graph.successors(current_node):
            if nbr in seen or str(nbr).endswith('_NoGo'):
                continue
            data = graph.nodes[nbr]
            if data.get('status') in (NOGO, 'abandon'):
                continue
            out.append({'node': nbr, 'kind': 'neighbour', 'similarity': None,
                        'why': f"reached from here before "
                               f"({data.get('status') or 'open'})"})
            seen.add(nbr)

    if len(out) < limit and current_aim:
        mem = GraphMemory(graph, ruleset=ruleset)
        live = tuple(s for s in {d.get('status') for _, d in graph.nodes(data=True)}
                     if s and s != NOGO)
        # Under 'grooved' ranking, dissimilar INHERITED candidates are cut
        # rather than offered. Top-k with no floor is how a clinical graph got
        # its aims adopted into a sentence game: the least-dissimilar wrong
        # things were still the k things on the list, and the arbiter trusted
        # the list. The floor checks provenance because its first version did
        # not: it filtered the agent's own young nodes along with the junk -
        # own-run nodes start with thin similarity too - and the guard arm's
        # solve rate paid for it. Foreign content earns its place; the run's
        # own work is always on the table. 0.30 matches
        # find_nearest_goal_node's own floor.
        floor = 0.30 if ranking == 'grooved' else None
        if live:
            for node, data, score in mem.recall(current_aim, k=k + len(seen),
                                                statuses=live):
                if node in seen or str(node).endswith('_NoGo'):
                    continue
                if (floor is not None and float(score) < floor
                        and data.get('origin') == 'inherited'):
                    continue
                out.append({'node': node, 'kind': 'similar',
                            'similarity': round(float(score), 2),
                            'why': f"recorded earlier as "
                                   f"{data.get('status') or 'open'}, and close "
                                   f"to what you are doing now"})
                seen.add(node)
                if len(out) >= limit:
                    break

    if ranking == 'grooved' and out:
        # The groove and the goal-distance are ANNOTATIONS, not sort keys.
        # The first version ordered nearest-the-goal-first, and on a young
        # self-paved graph everything is one hop from everything - the
        # ordering made the agent's own first ideas look authoritative, the
        # fork re-took them at twice the rate, and the guard arm's solve rate
        # halved. The groove became a rut. Evidence goes to the arbiter;
        # the list keeps its structural order (path, neighbours, similar).
        hops, _goal_node = goal_hops(graph, goal_text or current_aim)
        for c in out:
            c['groove'] = groove_depth(graph, c['node'])
            c['hops'] = hops.get(c['node'])
            bits = []
            if c['hops'] is not None:
                bits.append(f"{c['hops']} edge{'s' if c['hops'] != 1 else ''} "
                            f"from the goal area")
            if c['groove'] > 0:
                bits.append(f"well-worn (groove {c['groove']})")
            elif c['groove'] < 0:
                bits.append(f"mostly dead ends nearby (groove {c['groove']})")
            if bits:
                c['why'] = f"{c['why']}; {', '.join(bits)}"
    return out[:limit]


def fork_mode(generation_vars):
    """Who arbitrates the route-or-invent fork on this run."""
    mode = (generation_vars or {}).get('aim_fork_mode', 'gate')
    return mode if mode in ('gate', 'judgement', 'scratchpad') else 'gate'


def scratchpad_fork(graph, current_node, goal_text, proposed, rejected,
                    path_result, notepad, generation_vars):
    """Let the agent decide, from its own notes, where to go next.

    Returns (aim, source, suggestion) or None to fall back to the gate.

    This replaces `similarity * trust >= route_min_score` as the arbiter of the
    route-or-invent fork. That product latches off and cannot recover: one
    failed route puts trust at 0.6, which needs similarity >= 0.67 to route
    again, and node-label-to-goal-brief similarity tops out near 0.46. The
    trust values in the recorded results are exactly 0.6^n, so the latch is
    observed rather than argued.

    What is replaced is only the arbiter. The retrieval that finds candidates
    is unchanged, and the similarity is still computed and shown — the agent
    gets the same evidence the gate had, plus the one thing the gate never had,
    which is a record of where the investigation actually stands.

    Trust is deliberately not shown. It is the artefact being removed, and
    telling the agent "the graph has been unreliable" would reintroduce the
    latch through the prompt instead of through arithmetic.
    """
    candidates = route_candidates(
        graph, current_node, path_result,
        current_aim=(proposed or goal_text),
        ruleset=generation_vars.get('_ruleset', 'default'),
        k=int(generation_vars.get('graph_recall_k', 4)),
        goal_text=goal_text,
        ranking=generation_vars.get('candidate_ranking', 'similarity'))
    notepad = (notepad or '').strip()
    # Both arbitrated arms fork under identical conditions - candidates exist.
    # Letting the scratchpad arm also fork on an empty candidate list would
    # make the two arms differ in how often they fork as well as in what they
    # read, and no comparison could separate the two.
    if not candidates:
        return None

    lines = []
    for i, c in enumerate(candidates, 1):
        sim = f", similarity {c['similarity']}" if c['similarity'] is not None else ""
        lines.append(f"  {i}. {c['node']}\n     ({c['why']}{sim})")
    offered = "\n".join(lines) if lines else "  (the graph offers nothing from here)"

    memory = render_notepad(notepad) if notepad else ""
    dead = (f"\nA judge has proposed: \"{proposed}\"\n"
            f"That proposal means the same as something already ruled out "
            f"(\"{rejected}\"), so taking it as written would repeat a "
            f"refuted attempt.\n" if rejected else
            (f"\nA judge has proposed: \"{proposed}\"\n" if proposed else ""))

    system_prompt = ("You are choosing what to pursue next. Always respond with "
                     "valid JSON only.")
    user_prompt = f"""{memory}Your long-range goal: {goal_text}

Places the record of your own past attempts offers to go next:
{offered}
{dead}
Take whichever numbered option is the next thing worth doing. Choose 0 only if
none of them is, and name the aim you would pursue instead — "none of these"
without an aim of your own leaves the decision unmade.

Respond with JSON: {{"choice": <the option number, or 0>, "new_aim": "<the aim to \
pursue instead, required when choice is 0>", "why": "<one sentence>"}}"""

    scratchpad_fork.last_context = memory + offered
    scratchpad_fork.last_outcome = 'fell_through'
    # A decline is only evidence about the graph if a real route was on offer.
    # Where find_path_to_goal gives nothing, all the fork can show is aims
    # already reached from here, and declining to revisit them says nothing
    # about the graph's routes. Recorded per fork so the decline rate can be
    # read conditional on a route existing, rather than pooled and misread.
    scratchpad_fork.last_stats = {
        'fork_candidates': len(candidates),
        'fork_has_path': int(path_result is not None),
        'fork_path_sim': (round(float(path_result[2]), 3)
                          if path_result is not None else ''),
        'fork_choice': '',
        'fork_choice_kind': '',
        'fork_path_offered': int(any(c['kind'] == 'path' for c in candidates)),
    }
    raw = llm_judge_call(system_prompt, user_prompt, generation_vars)
    if raw is None:
        return None
    out = validate_json(raw, json_schema_aim_choice)
    if out is None:
        logger.warning(f"Failed to parse scratchpad fork response: {raw[:200]}")
        return None

    why = clean_text(out.get('why'), '') or ''
    try:
        choice = int(out.get('choice'))
    except (TypeError, ValueError):
        choice = 0

    scratchpad_fork.last_stats['fork_choice'] = choice
    if 1 <= choice <= len(candidates):
        picked = candidates[choice - 1]
        scratchpad_fork.last_stats['fork_choice_kind'] = picked['kind']
        scratchpad_fork.last_stats['fork_choice_hops'] = picked.get('hops', '')
        scratchpad_fork.last_stats['fork_choice_groove'] = picked.get('groove', '')
        scratchpad_fork.last_outcome = 'graph_path'
        return (picked['node'], 'graph_path',
                f"Taken from the record: {picked['why']}. {why}".strip())

    # None of them fit. An aim of its own is the other half of the fork - the
    # point is that it can leave the graph, not only move around inside it.
    new_aim = clean_text(out.get('new_aim'), '')
    if new_aim:
        scratchpad_fork.last_outcome = 'carried'
        return new_aim, 'carried', why

    # It rejected every option and named nothing. That is still a decision not
    # to route, so the judge's proposal stands - handing the fork back to the
    # gate here would let the mechanism being replaced route after the agent
    # had declined to, and put the control arm's behaviour inside the
    # treatment arm's results.
    if proposed and rejected is None:
        scratchpad_fork.last_outcome = 'carried'
        return proposed, 'carried', why or 'None of the recorded routes fit.'

    # Nothing chosen, nothing proposed, or the only proposal is already
    # refuted: there is no decision here to record, so let the gate run.
    return None


scratchpad_fork.last_context = ''
scratchpad_fork.last_outcome = ''
scratchpad_fork.last_stats = {}


def record_fork_cost(trail, generation_vars):
    """Fold what the fork read into the turn that ran it, and return it.

    The fork happens after this turn's row is already appended - the verdict
    has to land before there is anything to route from - so the row is topped
    up in place rather than the cost being carried to the next turn, where it
    would be attributed to a turn that did not spend it.

    Returns the text so the caller can keep its own running total. Empty when
    the fork did not run, which is what makes graph_contribution_chars in the
    control arm mean exactly what it always did.
    """
    if fork_mode(generation_vars) == 'gate':
        return ''
    context, outcome = scratchpad_fork.last_context, scratchpad_fork.last_outcome
    stats = scratchpad_fork.last_stats or {}
    scratchpad_fork.last_context, scratchpad_fork.last_outcome = '', ''
    scratchpad_fork.last_stats = {}
    if context and trail:
        trail[-1]['graph_contribution_chars'] = (
            int(trail[-1].get('graph_contribution_chars') or 0) + len(context))
        trail[-1]['fork_context_chars'] = len(context)
        # What the agent did with the choice, kept separate from what it cost:
        # a fork that fell through still spent the call, and counting it as a
        # decision would overstate how often the scratchpad actually decided.
        trail[-1]['fork_outcome'] = outcome
        trail[-1].update(stats)
    return context


def choose_aim(graph, current_node, goal_text, proposed, generation_vars,
               min_similarity=0.45, trust=1.0, notepad=''):
    """Pick the next aim, weighing the judge's proposal against the graph's route.

    Returns (aim, source, suggestion, rejected).

    The graph used to get a say only when the judge's proposal collided with a
    known dead end: any proposal that was merely *new* was accepted unchecked,
    so `find_path_to_goal` never ran and the graph chose the direction on about
    2% of turns across four thousand. It was a veto, not a planner.

    Now the route is always computed and compared. `trust` is how much the
    graph has been worth *in this run* - it falls when a route it supplied
    fails and recovers when one works, so a graph built for a different problem
    is quietly stopped being followed without being deleted or distrusted for
    the next run. Edge confidence already carries what is learned across runs;
    this carries what is learned about the present one.
    """
    proposed = clean_text(proposed)
    if generation_vars.get('graph_memory_mode', 'description') == 'none':
        return proposed, 'carried', None, None

    rejected = already_ruled_out(graph, proposed)

    result = find_path_to_goal(graph, current_node, goal_text, min_similarity)

    # The scratchpad decides the fork when it is switched on: same candidates,
    # same similarity, a different arbiter. It returns None when it could not
    # decide - no model, unparseable reply, or it rejected everything and named
    # nothing - and the gate below then runs exactly as it always has, so a
    # failure here costs a decision rather than the run.
    if fork_mode(generation_vars) != 'gate':
        chosen = scratchpad_fork(graph, current_node, goal_text, proposed,
                                 rejected, result, notepad, generation_vars)
        if chosen is not None:
            aim, source, hint = chosen
            return aim, source, hint, rejected

    if rejected is None and proposed:
        # The proposal is not a known dead end. Take the graph's route instead
        # only when it is both a good match for the goal and has been earning
        # its keep this run; otherwise stay responsive to what is in front of
        # the agent rather than replaying an old one.
        if result is not None:
            path, target, similarity = result
            route_gate = tuning(generation_vars, 'route_min_score', ROUTE_MIN_SCORE)
            if len(path) > 1 and similarity * trust >= route_gate:
                return (path[1], 'graph_path',
                        f"Follow known path toward '{target}' "
                        f"(similarity={similarity:.2f}, trust={trust:.2f}). "
                        f"Path: {' -> '.join(path)}", None)
        return proposed, 'carried', None, None

    if result is not None:
        path, target, similarity = result
        if len(path) > 1:
            return (path[1], 'graph_path',
                    f"Follow known path toward '{target}' (similarity={similarity:.2f}). "
                    f"Path: {' -> '.join(path)}",
                    rejected)

    # The aim is known dead and the graph has no route to offer. Handing it
    # back anyway would have the agent pursue something already refuted, so it
    # is dropped: the planner picks fresh next turn, with the refutation in
    # front of it.
    return None, 'rejected', None, rejected


def effective_window(agent, generation_vars):
    """The context window this agent actually converses under.

    Per-agent because the agents are not all the thing under test: in the
    clinical tasks the patient is the environment, and an environment that
    forgets what it already said lets a short-window agent re-elicit any
    dropped fact for the price of a turn - which is why shrinking the window
    never hurt anyone. A row-level 'context_window' (0 = unlimited) overrides
    the session's; rows without one keep the session window, so nothing
    changes for existing tasks.

    The judge and planner deliberately do NOT get the override: they evaluate
    the agent under test, so they stay on the session horizon.
    """
    # No `agent or {}`: the row is a pandas Series here, and truth-testing a
    # Series raises. Missing column -> None (dict) or NaN (DataFrame row);
    # both fall through to the session window.
    override = agent.get('context_window') if agent is not None else None
    try:
        if override is not None and float(override) == float(override):  # NaN guard
            return int(override)
    except (TypeError, ValueError):
        pass
    return generation_vars.get('context_window', 0)


def judge_view(history, generation_vars, default=10):
    """What a judge or planner is allowed to see of the conversation.

    Every component must share one horizon, otherwise the graph is not the only
    thing carrying information past the window and any measurement of what the
    graph contributes is confounded. When no window is set this keeps the
    original last-ten behaviour.
    """
    window = 0
    try:
        window = int((generation_vars or {}).get('context_window', 0) or 0)
    except (TypeError, ValueError):
        window = 0
    limit = window if window > 0 else default
    shown = history[-limit:]
    return shown, max(0, len(history) - len(shown))


def windowed(history, context_window):
    """The most recent messages, plus a note saying what was dropped.

    Silently truncating would let an agent mistake a partial history for the
    whole one. Saying how much is missing is what makes a short window an
    honest constraint rather than a hidden one - and it is the condition under
    which stored aims can be worth more than raw history.
    """
    try:
        window = int(context_window or 0)
    except (TypeError, ValueError):
        window = 0
    if window <= 0 or len(history) <= window:
        return history, 0
    return history[-window:], len(history) - window


def format_prompt(history, agent_description, goal, name, user_name,
                  current_aim=None, suggestion=None, last_narration=None,
                  ruled_out=None, context_window=0, rule_field=''):
    """Format the prompt for the agent, including subgoal context.

    `ruled_out` is what the decision graph has already established does not
    work. It belongs here, on every turn, rather than only where a new aim is
    generated: an agent repeats a dead approach while pursuing an aim, not
    while choosing one, so consulting the record only at aim-selection time
    means consulting it at the one moment it cannot help.
    """

    system_prompt = f"""You are {name}, an intelligent agent with the following description:
{agent_description}

Your long-range workspace goal is: {goal}
Your aims can change as the conversation reveals new information. Treat the graph as a
workspace of possible aims, not as a single fixed route.
"""
    if current_aim:
        system_prompt += f"\nYour current aim is: {current_aim}\n"
    if suggestion:
        system_prompt += f"Suggested next action: {suggestion}\n"
    if ruled_out:
        system_prompt += f"\n{ruled_out}"

    system_prompt += f"""
Always respond in character. Maintain consistent behavior and personality throughout the conversation.
Respond with a JSON object containing:
- "agent_response": your in-character response text
- "narration": (optional) brief narration describing actions, appearances, or behaviors accompanying your response
{rule_field}

IMPORTANT: Do NOT repeat previous responses or narration.
Respond ONLY with the JSON object, no other text."""

    history, elided = windowed(history, context_window)
    conversation = ""
    if elided:
        conversation += (f"[{elided} earlier message(s) are no longer available "
                         f"to you.]\n")
    for speaker, message in history:
        if speaker == "user":
            conversation += f"{user_name}: {message}\n"
        else:
            conversation += f"{speaker}: {message}\n"

    full_prompt = f"{system_prompt}\n\nConversation:\n{conversation}"
    return full_prompt


def format_chat_messages(history, agent_description, goal, name, user_name,
                         current_aim=None, suggestion=None):
    """Format as chat messages for providers that support it."""
    messages = []

    system_content = f"""You are {name}, an intelligent agent with the following description:
{agent_description}

Your long-range workspace goal is: {goal}
Your aims can change as the conversation reveals new information. Treat the graph as a
workspace of possible aims, not as a single fixed route.
"""
    if current_aim:
        system_content += f"\nYour current aim is: {current_aim}\n"
    if suggestion:
        system_content += f"Suggested next action: {suggestion}\n"

    system_content += """
Always respond in character. Respond with a JSON object containing:
- "agent_response": your in-character response text
- "narration": (optional) brief narration of actions/behaviors

Respond ONLY with the JSON object."""

    messages.append({"role": "system", "content": system_content})

    for speaker, message in history:
        role = "user" if speaker == "user" else "assistant"
        messages.append({"role": role, "content": message})

    return messages


# ---------------------------------------------------------------------------
# Aim management
# ---------------------------------------------------------------------------

def review_subgoal(history, agent, generation_vars, current_aim=None):
    """Use the LLM to judge progress on the current aim.

    Returns (rating, justification, suggestion, aim_status, next_aim) on success.

    The judge is deliberately graph-blind: it sees the windowed conversation
    and nothing else, so a verdict can only be earned by what the agent
    actually did. (An earlier signature accepted the graph and never read it,
    which implied a coupling that does not exist.)

    The rating scale is anchored to observable outcomes because an unanchored
    one measured nothing: across 6,182 judgements under the old prompt - a
    Likert scale with the proposition left unstated - 92% of ratings were
    exactly 5 and the values 1-3 never occurred once. Every threshold keyed to
    the scale was dead: strong-failure (<=2) and regression (<=4) could not
    fire from a judge verdict, leaving patience as the only working abandon
    path on opinion tasks. A scale the model will not use is not a scale.
    """
    agent_name = agent['agent_name']
    current_aim = current_aim or agent['current_aim']
    workspace_goal = agent['goal']
    shown, hidden = judge_view(history, generation_vars)
    recent_exchanges = ("" if not hidden
                        else f"[{hidden} earlier message(s) not shown.]\n") + "\n".join(
        [f"{m[0]}: {m[1]}" for m in shown]
    )

    system_prompt = "You are an impartial evaluator. Always respond with valid JSON only."

    user_prompt = f"""This is the current conversation:
{recent_exchanges}

Based on this chat, evaluate {agent_name}'s progress:
Long-range workspace goal: "{workspace_goal}"
Current aim: "{current_aim}"

Classify the current aim:
- "continue": the aim is still useful and should continue.
- "progress": the conversation has moved the aim forward, refined it, or revealed a better next aim.
- "achieved": the current aim has been completed.
- "abandon": the current aim is no longer useful or is clearly failing.

Rate this statement: "{agent_name}'s most recent turns moved the current aim
forward." Use the full scale - most turns in a long conversation genuinely
belong at 3 or 4, and inflating stalled turns to 5 hides failure:
1 = the conversation contradicts the aim; pursuing it is making things worse
2 = the aim is failing; recent replies undercut it and no path forward is visible
3 = no movement; the last few turns added nothing the aim can use
4 = unclear; mixed signals, too early to say
5 = modest progress; one concrete step the aim can build on
6 = clear progress; the aim is close or has resolved into a sharper next aim
7 = the aim is fully achieved, demonstrated in the conversation

Justify your response, then provide a suggestion that guides {agent_name}'s next action in this
workspace. If the aim should progress, provide the next_aim as a concise graph node label. If not,
set next_aim to null.

Respond with JSON: {{"rating": <int 1-7>, "justification": "<text>", "suggestion": "<text>", "aim_status": "continue|progress|achieved|abandon", "next_aim": "<text or null>"}}"""

    raw = llm_judge_call(system_prompt, user_prompt, generation_vars)
    if raw is None:
        return None, None, None, None, None

    output = validate_json(raw, json_schema_review_goal)
    if output is None:
        logger.warning(f"Failed to parse review_subgoal response: {raw[:200]}")
        return None, None, None, None, None

    rating = output.get('rating')
    justification = output.get('justification', '')
    suggestion = output.get('suggestion', '')
    aim_status = output.get('aim_status')
    next_aim = output.get('next_aim')

    # Clamp rating to valid range
    if isinstance(rating, (int, float)):
        rating = max(1, min(7, int(rating)))
    else:
        return None, None, None, None, None

    if aim_status not in ("continue", "progress", "achieved", "abandon"):
        aim_status = 'achieved' if rating >= 6 else 'continue'

    if isinstance(next_aim, str):
        next_aim = next_aim.strip() or None
    else:
        next_aim = None

    logger.info(
        f"Aim review for '{current_aim}': rating={rating}, status={aim_status}, "
        f"justification={justification[:80]}"
    )
    return rating, justification, suggestion, aim_status, next_aim


def generate_new_subgoal(history, agent, generation_vars, graph):
    """Use the LLM to generate a new aim for the agent.

    Returns (new_aim, planned_action) or (None, None) on failure.
    """
    agent_name = agent['agent_name']
    goal = agent['goal']
    description = agent['description']
    target_impression = agent.get('target_impression', '')
    environment_changes = agent.get('environment_changes', '')
    new_information = agent.get('new_information', '')

    shown, hidden = judge_view(history, generation_vars)
    recent_exchanges = ("" if not hidden
                        else f"[{hidden} earlier message(s) not shown.]\n") + "\n".join(
        [f"{m[0]}: {m[1]}" for m in shown]
    )

    # What the graph contributes to the next aim. "description" is the
    # original behaviour - every ruled-out label, dumped whole, growing with
    # the graph. "graph" retrieves only the nearest few and says why each was
    # ruled out, so the cost is bounded by k rather than by graph size.
    mode = generation_vars.get('graph_memory_mode', 'description')
    nogo_statement = ""
    if mode == 'graph':
        mem = GraphMemory(graph, ruleset=agent.get('goal', 'default'))
        nogo_statement = mem.render(
            agent.get('current_aim') or agent.get('goal', ''),
            k=int(generation_vars.get('graph_recall_k', 4)),
            max_chars=int(generation_vars.get('graph_recall_chars', 600)),
        )
    elif mode == 'description':
        _, nogo_nodes = get_go_nogo_nodes(graph)
        if nogo_nodes:
            clean_nodes = [n.replace('_NoGo', '') for n in nogo_nodes]
            nogo_list = "\n".join([f" - {node}" for node in clean_nodes])
            nogo_statement = f"The following approaches at achieving the goal were unsuccessful:\n{nogo_list}\n\n"

    # The other half of the fork. When the graph offers no route at all there
    # is nothing to choose between, and the aim has to be invented - so the
    # scratchpad belongs here too, or the agent invents its next aim knowing
    # only the last few messages and which labels are dead.
    scratchpad = ""
    if fork_mode(generation_vars) == 'scratchpad':
        scratchpad = render_notepad(clean_text(agent.get('notepad'), ''))

    environment_info = ""
    if environment_changes:
        environment_info += f"Recent environment changes: {environment_changes}\n"
    if new_information:
        environment_info += f"New information: {new_information}\n"

    # Exposed so the run trail can record what the graph actually contributed
    # to this turn, rather than only that it contributed something.
    generate_new_subgoal.last_nogo_statement = nogo_statement + scratchpad

    system_prompt = "You are a strategic planner. Always respond with valid JSON only."

    user_prompt = f"""Current Context:
Recent chat: {recent_exchanges}
{environment_info}
{agent_name} description: {description}
{agent_name} long-range workspace goal: {goal}
{nogo_statement}{scratchpad}
Consider the current situation and provide {agent_name} with an achievable next aim. The aim
should be a useful node in a shared knowledge workspace: it may advance, refine, branch, or
temporarily redirect the larger goal as new information appears. Additionally, detail the
specific action they should take to pursue this aim.

Respond with JSON: {{"new_subgoal": "<subgoal text>", "planned_action": "<action text>"}}"""

    raw = llm_judge_call(system_prompt, user_prompt, generation_vars)
    if raw is None:
        # Offline fallback: generate a simple subgoal
        return f"Work toward: {goal}", "Continue the conversation naturally."

    output = validate_json(raw, json_schema_new_subgoal)
    if output is None:
        logger.warning(f"Failed to parse new_subgoal response: {raw[:200]}")
        return f"Work toward: {goal}", "Continue the conversation naturally."

    new_subgoal = output.get('new_subgoal', '')
    planned_action = output.get('planned_action', '')
    logger.info(f"New subgoal for {agent_name}: '{new_subgoal}' / action: '{planned_action}'")
    return new_subgoal, planned_action


# ---------------------------------------------------------------------------
# Agent response generation
# ---------------------------------------------------------------------------

generate_new_subgoal.last_nogo_statement = ''


def get_agent_response(prompt, agent_name, generation_vars, last_narration=''):
    """Generate a response from the agent using the configured LLM.

    Returns (response_text, narration, stated_rule, notes). The rule is the
    agent's current claim in a form a keeper can check; it is empty on chat
    runs, where there is nothing to check it against. The notes are the agent's
    own memory in its own words, and are asked for only in notepad mode.
    """

    try:
        # Offline mode: simulated response
        if generation_vars.get('offline', False):
            sim_response = (
                f"This is a simulated response from {agent_name}. "
                f"In production, this would be generated by the AI model."
            )
            return sim_response, "", "", ""

        provider = generation_vars.get('provider', 'local')
        model = generation_vars.get('model')
        temperature = generation_vars.get('temperature', 0.7)
        max_tokens = generation_vars.get('max_tokens', 150)
        top_p = generation_vars.get('top_p', 0.9)
        fallback_to_local = generation_vars.get('fallback_to_local', True)

        llm_service.set_provider(provider)

        options = {
            'model': model,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'top_p': top_p,
            'fallback_to_local': fallback_to_local,
            'strict_provider': generation_vars.get('strict_provider', False),
            'offline_allowed': True
        }

        # For providers that support chat format, convert the prompt
        if provider in ('openai', 'openai-codex', 'anthropic') and isinstance(prompt, str):
            sections = prompt.split("\n\nConversation:\n")
            if len(sections) == 2:
                system_prompt_text = sections[0]
                conversation = sections[1]

                messages = [{"role": "system", "content": system_prompt_text}]
                for line in conversation.split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        speaker, content = parts[0].strip(), parts[1].strip()
                        role = "user" if speaker not in (agent_name,) else "assistant"
                        messages.append({"role": role, "content": content})
                    elif messages[-1]["role"] != "system":
                        # A colon-free line continues the previous message -
                        # multi-line replies and narration. Dropping them also
                        # dropped the '[N earlier message(s) are no longer
                        # available]' notice, which silently turned the
                        # documented honest window into a hidden one.
                        messages[-1]["content"] += "\n" + line.strip()
                    else:
                        # Leading colon-free text (the elision notice) becomes
                        # its own user-role note rather than vanishing.
                        messages.append({"role": "user", "content": line.strip()})

                prompt = messages

        logger.info(f"Generating response using {provider} provider")
        raw = llm_service.complete(prompt, options)
        raw = raw.strip()

        # Try to parse as structured JSON response
        output = validate_json(raw, json_schema_response)
        if output:
            agent_response = output.get('agent_response', raw)
            narration = output.get('narration', '')
            stated_rule = (output.get('rule') or '').strip()
            notes = (output.get(NOTEPAD_FIELD) or '').strip()

            # Suppress narration if too similar to previous
            if narration and is_too_similar(narration, last_narration):
                narration = ''

            return agent_response, narration, stated_rule, notes

        # Fallback: treat entire response as plain text.
        # Strip stray JSON wrapper artifacts the LLM sometimes leaves behind,
        # e.g. a trailing  "}  from an incomplete {"agent_response": "..."}.
        cleaned = raw
        # Try to unwrap if it looks like a partial JSON response wrapper
        m = re.match(r'\s*\{\s*"agent_response"\s*:\s*"', cleaned)
        if m:
            cleaned = cleaned[m.end():]
            # Remove the matching trailing  "}
            cleaned = re.sub(r'"\s*\}\s*$', '', cleaned)
        else:
            # Just strip a trailing  "}  or  }  that leaked from JSON
            cleaned = re.sub(r'"\s*\}\s*$', '', cleaned)
        return cleaned.strip(), "", "", ""

    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        raise AgentGenerationError(
            f"Failed to generate response for {agent_name}: {str(e)}"
        ) from e


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def offline_main(history, agents_df, settings, user_name, is_user, agent_mutes, len_last_history, turn_index=0):
    """Main function for offline mode (without real LLM)."""
    return main(history, agents_df, settings, user_name, is_user, agent_mutes, len_last_history, offline=True, turn_index=turn_index)


def main(history, agents_df, settings, user_name, is_user, agent_mutes,
         len_last_history, offline=False, turn_index=0, trail=None):
    """Main function for agent processing.

    Implements the full loop:
    1. Pick an unmuted agent
    2. If no current subgoal, generate one via LLM
    3. Generate agent response (with subgoal context)
    4. Review subgoal progress via LLM judge
    5. Go/NoGo decision updates the graph
    """

    logger.info(f"Agent processing started with {len(agents_df)} agents, is_user={is_user}")

    if is_user:
        logger.info("User turn, not generating agent responses")
        return history, agents_df, []

    # Only block on first turn (turn_index=0) if history hasn't changed since last user message
    # For subsequent turns (turn_index>0), the previous agent's response is the new content
    if turn_index == 0 and len(history) == len_last_history:
        logger.info("History unchanged, not generating new responses")
        return history, agents_df, []

    logs = []

    # Pick agent via round-robin (cycle through unmuted agents in order)
    unmuted_agents = [i for i, muted in enumerate(agent_mutes) if not muted]
    if not unmuted_agents:
        logger.warning("All agents are muted, no responses generated")
        return history, agents_df, ["All agents are muted"]

    agent_idx = unmuted_agents[turn_index % len(unmuted_agents)]
    agent = agents_df.iloc[agent_idx]
    logger.info(f"Round-robin turn {turn_index}: selected agent '{agent['agent_name']}' (idx={agent_idx})")

    # Build generation vars
    generation_vars = (
        agent['generation_variables'].copy()
        if agent['is_agent_generation_variables']
        else settings.copy()
    )
    for runtime_key in ('fast_graph_run', 'judge_delay_seconds',
                        'graph_memory_mode', 'graph_recall_k',
                        'graph_recall_chars', 'nogo_ungated', 'aim_fork_mode',
                        'order_salt', 'task_variant', 'aim_system',
                        'candidate_ranking', 'move_guard',
                        'context_window', 'run_type', 'keeper_rule', 'seed'):
        if runtime_key in settings:
            generation_vars[runtime_key] = settings[runtime_key]
    if offline:
        generation_vars['offline'] = True

    # Load the agent's graph
    graph_path = agent['graph_file_path']
    try:
        G = nx.read_graphml(graph_path)
    except Exception as e:
        logger.error(f"Error reading graph, creating new one: {e}")
        G = nx.DiGraph()
        G.add_node('start')

    agent_name = agent['agent_name']
    current_aim = clean_text(agent['current_aim'])
    suggestion = clean_text(agent['suggestion'], '')
    persistence_count = agent['persistance_count']
    # How much the graph has been worth *this run*. Falls when a route it
    # supplied fails, recovers when one works, and never persists past the
    # run - cross-run learning is the edge confidence, not this.
    try:
        graph_trust = float(agent.get('graph_trust', 1.0) or 1.0)
    except (TypeError, ValueError):
        graph_trust = 1.0
    aim_came_from = clean_text(agent.get('current_aim_source'), '') or 'carried'
    persistence_score = agent['persistance_score']
    current_node = clean_text(agent['current_node_location'], 'start')
    # Per-agent values, overridable per run so a study can sweep them.
    patience_min = int(tuning(generation_vars, 'persistence_min',
                              agent.get('persistance', 3)))
    patience_max = int(tuning(generation_vars, 'patience_max',
                              agent.get('patience', 6)))
    last_narration = agent.get('last_narration', '')
    # The agent's own notes, carried across turns on the agent rather than in
    # the graph. This mode is the cheap alternative the graph has to beat, so
    # it must not borrow the graph's machinery to work.
    notepad = clean_text(agent.get('notepad'), '')

    # ------------------------------------------------------------------
    # Step 1: If no active aim, try graph-guided path first, then LLM
    # ------------------------------------------------------------------
    # Token accounting covers the whole pipeline for this turn: the agent's
    # own call plus the judge and the planner. Reset here so each row is a
    # per-turn figure rather than a running total.
    if trail is not None:
        llm_service.reset_usage()
    verdict_src = OPINION   # upgraded to PROOF when a keeper settles it
    move_guard_fired = 0
    stated_rule = ''
    inline_notes = []   # refutations spoken once into the conversation
    guided_path = None  # Will hold the path if graph search finds one
    # Reset per turn: this is a module-level attribute, so leaving it set
    # would report a previous turn's recall text on any turn that did not
    # call the subgoal generator.
    generate_new_subgoal.last_nogo_statement = ''
    aim_source = 'carried'

    # aim_system 'off' is the ablation of the scaffold itself: no aim is ever
    # selected, so nothing aim-shaped reaches the prompt, no judge reviews
    # progress, and no verdict ever writes to the graph - the review block
    # below already gates on current_aim, and the prompt builder already
    # omits the aim line when there is none. The keeper, its status hints and
    # the conversation are untouched, so an aims-off arm differs from an
    # aims-on arm in exactly one thing: whether the agent is given a running
    # goal at all. This is the control the original design never had.
    if generation_vars.get('aim_system', 'on') == 'off':
        current_aim = None
    elif current_aim is None:
        # First: check if the graph already has a node close to our goal
        # and a viable path to it. Gated on memory mode exactly as choose_aim
        # is: 'none' means the graph is recorded and never consulted, and this
        # site consults it - it fires after every NoGo, and a NoGo-heavy run
        # would have the "no graph" arm steering by stored aims while its
        # contamination checks (which watch recall, not routing) stayed green.
        goal_text = agent['goal']
        path_result = None
        if generation_vars.get('graph_memory_mode', 'description') != 'none':
            path_result = find_path_to_goal(G, current_node, goal_text)

        # This is a route-or-invent decision too - it runs at the start of a
        # run and after every abandoned aim - so whoever arbitrates the fork
        # arbitrates here as well. Leaving it on the gate would have a large
        # slice of aim selection behave identically in every arm, diluting the
        # contrast the study exists to measure.
        # choose_aim short-circuits mode 'none' before its fork runs; this
        # site must match, or 'none' would mean two different things.
        forked = (scratchpad_fork(G, current_node, goal_text, '', None,
                                  path_result, notepad, generation_vars)
                  if (fork_mode(generation_vars) != 'gate'
                      and generation_vars.get('graph_memory_mode',
                                              'description') != 'none')
                  else None)
        if forked is not None:
            current_aim, forked_source, forked_hint = forked
            # An aim it named itself is an invented one, whatever the fork
            # calls it internally: at this site there is no judge proposal to
            # carry, so 'carried' would be a third name for 'llm_subgoal'.
            aim_source = ('graph_path' if forked_source == 'graph_path'
                          else 'llm_subgoal')
            suggestion = forked_hint or suggestion
            persistence_count = 0
            persistence_score = None
            logs.append(f"Fork chose the opening aim for {agent_name} "
                        f"({aim_source}): {current_aim}")
            aim_came_from = aim_source
        elif path_result is not None:
            path, target_node, similarity = path_result
            # The next node on the path becomes our aim
            next_step = path[1]  # path[0] is current_node
            current_aim = next_step
            suggestion = (
                f"Follow known path toward '{target_node}' "
                f"(similarity={similarity:.2f}). "
                f"Path: {' -> '.join(path)}"
            )
            guided_path = path
            aim_source = 'graph_path'
            persistence_count = 0
            persistence_score = None
            logs.append(
                f"Graph-guided aim for {agent_name}: '{current_aim}' "
                f"(path to '{target_node}', similarity={similarity:.2f})"
            )
            aim_came_from = aim_source
        else:
            # No useful path found – ask the LLM to generate a new aim
            new_subgoal, planned_action = generate_new_subgoal(
                history, agent, generation_vars, G
            )
            current_aim = new_subgoal
            aim_source = 'llm_subgoal'
            suggestion = planned_action
            persistence_count = 0
            persistence_score = None
            logs.append(f"New aim for {agent_name}: {current_aim}")
            aim_came_from = aim_source

    # ------------------------------------------------------------------
    # What the graph put into this turn's prompt. Recorded rather than
    # discarded: comparing graph settings across runs is impossible if the
    # only trace of what the agent was told is a log line.

    # Step 2: Generate agent response with aim context
    # ------------------------------------------------------------------
    # What the graph already knows does not work, retrieved for the aim in
    # hand. Computed every turn so the record is actually consulted while the
    # agent is acting on an aim.
    ruled_out = ''
    graph_mode = generation_vars.get('graph_memory_mode', 'description')
    recall_chars = int(generation_vars.get('graph_recall_chars', 600))
    # 'inline' deliberately retrieves nothing: the refutation was stated once,
    # in the conversation, and survives only as long as the window holds it.
    # That is the control for what persistent recall actually buys.
    if graph_mode == 'inline':
        ruled_out = ''
    elif graph_mode == 'graph':
        ruled_out = GraphMemory(G, ruleset=agent.get('goal', 'default')).render(
            clean_text(current_aim) or clean_text(agent.get('goal'), ''),
            k=int(generation_vars.get('graph_recall_k', 4)),
            max_chars=recall_chars,
        )
    elif graph_mode == 'description':
        ruled_out = legacy_nogo_statement(G)
    if ruled_out:
        generate_new_subgoal.last_nogo_statement = ruled_out
    graph_contribution = ruled_out

    # On a keeper run the agent must state its claim in a checkable form.
    # Without it nothing can be proven refuted, so no NoGo is ever recorded and
    # the graph has nothing to recall - which is what kept every memory mode
    # behaving identically.
    keeper = None
    try:
        from .keeper import make_keeper
        keeper = make_keeper(generation_vars if 'run_type' in generation_vars
                             else settings)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"keeper unavailable: {e}")

    # Scorer-known task state the window cannot carry. Appended to the
    # suggestion rather than the goal so it appears only while true, and
    # through the keeper so both arms of a comparison get it identically.
    if keeper and hasattr(keeper, 'status_hint'):
        try:
            hint = keeper.status_hint(history)
        except Exception:                                          # noqa: BLE001
            hint = ''
        if hint:
            suggestion = f"{suggestion} {hint}".strip() if suggestion else hint

    # The scratchpad is written every turn and read at the fork, so the ask
    # goes out every turn too. It sits alongside whatever the keeper already
    # wants rather than displacing it: asked for by capability, not by task, so
    # a keeper that needs a checkable claim still gets one.
    rule_field = keeper.rule_prompt() if keeper else ''
    if fork_mode(generation_vars) == 'scratchpad':
        rule_field = f"{rule_field}\n{notepad_prompt(recall_chars)}".strip()

    prompt = format_prompt(
        history,
        agent['description'],
        agent['goal'],
        agent_name,
        user_name,
        current_aim=current_aim,
        suggestion=suggestion,
        last_narration=last_narration,
        ruled_out=ruled_out,
        context_window=effective_window(agent, generation_vars),
        rule_field=rule_field
    )

    logger.info(f"Generating response for {agent_name}")
    try:
        response_text, narration, stated_rule, notes = get_agent_response(
            prompt, agent_name, generation_vars, last_narration
        )
        # The groove as a guard-rail: where the keeper can recognise a
        # re-tread of already-refuted ground deterministically, the draft is
        # sent back ONCE with the offending move named, before the turn is
        # spent. One retry, not a loop: an agent that re-treads twice in a
        # row keeps its second answer, and the failure stays visible in the
        # record rather than being laundered by endless regeneration.
        if (generation_vars.get('move_guard')
                and keeper and hasattr(keeper, 'known_bad_move')):
            try:
                bad = keeper.known_bad_move(response_text, history)
            except Exception:                                      # noqa: BLE001
                bad = None
            if bad:
                logs.append(f"Move guard: draft re-trod refuted ground "
                            f"('{str(bad)[:50]}'); regenerating once")
                guard_note = (
                    f"\n\nIMPORTANT: your draft proposed \"{bad}\", which was "
                    f"already tried and rejected in this conversation. Do not "
                    f"propose it or a near-rewording again. Propose something "
                    f"substantially different.")
                response_text, narration, stated_rule, notes = get_agent_response(
                    prompt + guard_note, agent_name, generation_vars,
                    last_narration)
                move_guard_fired = 1
    except AgentGenerationError as e:
        logger.error(str(e))
        logs.append(str(e))

        agent_df = ensure_text_columns(pd.DataFrame(agents_df))
        agent_df.at[agent_idx, 'current_aim'] = current_aim
        agent_df.at[agent_idx, 'suggestion'] = suggestion
        agent_df.at[agent_idx, 'persistance_count'] = persistence_count
        agent_df.at[agent_idx, 'graph_trust'] = round(float(graph_trust), 4)
        agent_df.at[agent_idx, 'current_aim_source'] = str(aim_came_from)
        agent_df.at[agent_idx, 'persistance_score'] = persistence_score
        agent_df.at[agent_idx, 'current_node_location'] = current_node
        nx.write_graphml(G, graph_path)
        return history, agent_df, logs

    logs.append(f"Generated response for {agent_name}")

    if fork_mode(generation_vars) == 'scratchpad':
        # A turn that wrote nothing keeps the previous page rather than
        # blanking it: a malformed reply should cost the agent the turn, not
        # everything it had already worked out.
        written = trim_notepad(notes, recall_chars)
        if written:
            notepad = written
            logs.append(f"Scratchpad rewritten ({len(notepad)} chars)")
        else:
            logs.append("No notes this turn; the previous page stands")

    # Combine response with narration for display
    display_response = response_text
    if narration:
        display_response = f"{response_text}\n\n{narration}"

    # Increment persistence count
    persistence_count += 1

    # ------------------------------------------------------------------
    # Step 3: Review aim progress (only after enough history)
    # ------------------------------------------------------------------
    if len(history) > 2 and current_aim:
        rating, justification, new_suggestion, aim_status, next_aim = review_subgoal(
            history + [(agent_name, response_text)],
            agent, generation_vars, current_aim=current_aim
        )

        # Where the keeper can settle it, evidence outranks the judge. A claim
        # contradicted by an observation is refuted as a matter of fact, so the
        # verdict is taken rather than asked for, and the edge carries proof
        # confidence instead of opinion.
        holdout_accuracy = None
        if keeper and stated_rule:
            check = keeper.check_aim(stated_rule,
                                     keeper.observations_from(history))
            holdout_accuracy = check.get('holdout_accuracy')
            if check.get('checkable') and check.get('consistent') is False:
                contradiction = check.get('contradicted_by') or {}
                aim_status, rating, verdict_src = 'abandon', 1, PROOF
                justification = (
                    f"Refuted by evidence: {contradiction.get('move')} was "
                    f"{'accepted' if contradiction.get('keeper') else 'rejected'}, "
                    f"which this rule does not allow.")
                logs.append(f"REFUTED by evidence: {stated_rule[:60]}")
            elif check.get('holdout_accuracy') is not None:
                logs.append(f"Rule holds so far; {check['holdout_accuracy']:.0%} "
                            f"on unseen items.")

        # Advancement is a fact too, and the keeper can settle it. This is the
        # other half of the refutation check above, and leaving it out is what
        # made every graph a depth-1 star: the keeper could prove an aim wrong
        # but never prove the run had moved, so the only thing that could
        # advance the cursor was a judge volunteering a high rating. It rarely
        # did, so aims accumulated as spokes and no route was ever built.
        #
        # It outranks the refutation above deliberately. A turn that produced a
        # genuinely new accepted answer advanced the run whatever the agent
        # believed about why, and a mistaken hypothesis will still be refuted on
        # a later turn if it is really wrong.
        if keeper:
            after_history = history + [(agent_name, response_text)]
            try:
                advanced = keeper.progress_made(history, after_history)
                finished = keeper.is_complete(after_history)
                wasted = (not advanced and not finished
                          and hasattr(keeper, 'wasted_move')
                          and keeper.wasted_move(history, after_history))
            except Exception as e:                                 # noqa: BLE001
                logger.warning(f"keeper progress check failed: {e}")
                advanced = finished = wasted = False
            # Completion is checked on its own rather than nested inside
            # advancement, because the winning move often does not advance by
            # the run's own measure. On a troubleshooting task the repair that
            # fixes the fault eliminates nothing - the candidate set is already
            # as small as it will get - so gating the Go behind "did this
            # narrow anything" meant a solved run recorded no Go at all.
            if finished:
                aim_status, rating, verdict_src = 'achieved', 7, PROOF
                justification = "Task completed, confirmed by the keeper."
                logs.append("ACHIEVED, confirmed by evidence")
            elif advanced:
                # rating stays below the Go threshold so this records as a
                # step taken rather than an aim finished
                aim_status, rating, verdict_src = 'progress', 5, PROOF
                justification = "Advanced, confirmed by the keeper: " + \
                    keeper.progress_note(after_history)
                # Progress needs somewhere to go, or the branch cannot fire
                if not next_aim or next_aim == current_aim:
                    next_aim = keeper.progress_note(after_history)
                logs.append("PROGRESS, confirmed by evidence")
            elif wasted:
                try:
                    wasted_kind = keeper.wasted_scope(history, after_history) \
                        if hasattr(keeper, 'wasted_scope') else 'structural'
                except Exception:                                  # noqa: BLE001
                    wasted_kind = 'structural'
                # A move that eliminated nothing is a dead end proven by
                # arithmetic. Recording it is what puts branches on the graph
                # beside the route - without it a run that wandered and a run
                # that went straight to the answer draw identically.
                aim_status, rating, verdict_src = 'abandon', 1, PROOF
                justification = keeper.wasted_note(after_history)
                nogo_scope = wasted_kind
                logs.append(f"NOGO: that move eliminated nothing ({wasted_kind})")
            elif rating >= 6 or aim_status == 'achieved':
                # Evidence outranks the judge in *both* directions, not just
                # when it refutes. Where the keeper can measure success, a judge
                # calling an aim achieved while nothing measurable happened is a
                # false positive, and letting it advance the cursor built graphs
                # seven hops deep on runs that never got a single answer
                # accepted. Fake progress is worse than a visible dead end: the
                # dead end is at least true.
                rating = min(rating, 5)
                aim_status = 'continue'
                justification = (
                    "The judge rated this achieved, but the keeper recorded no "
                    "advance, so it is held open rather than marked reached. "
                    + (justification or ''))
                logs.append("Judge said achieved; keeper saw no advance, so not a Go")

        if trail is not None:
            # The agent row comes from a DataFrame and the graph from networkx,
            # so several of these arrive as numpy scalars. They must be plain
            # Python here: the session is JSON-serialised on every request, and
            # a numpy int64 anywhere in it fails the whole save.
            def _int(value):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            trail.append({
                'turn': _int(turn_index),
                'agent': str(agent_name),
                'aim': str(current_aim) if current_aim is not None else '',
                # Whether a decision was taken THIS turn, and what it chose;
                # 'carried' where the aim simply persisted. The 'aim_source'
                # column below is the origin of the aim being pursued, which
                # survives across turns until something changes it.
                #
                # Both keys were once spelled 'aim_source' in this literal, so
                # this one was silently dropped, and because only the
                # post-verdict fork refreshed the survivor, a turn whose aim
                # had just been chosen by Step 1 was stamped with the previous
                # aim's label. In 654 recorded rows 'llm_subgoal' never once
                # appeared, and 121 rows carried a label describing an aim
                # already abandoned. Every aim-selection site now refreshes it,
                # so the column finally means what its name says - at the cost
                # of routed-aim counts no longer matching runs recorded before
                # this, which were undercounting.
                'aim_chosen_this_turn': str(aim_source),
                # One column for the agent's structured self-report. Where the
                # keeper asks for a checkable claim that is what lands here;
                # where it asks for nothing - the clinical tasks, where this
                # column has always been empty - the scratchpad does. Only one
                # of the two is ever requested on a given run, so the column
                # stays unambiguous without a second being invented for it.
                'stated_rule': str(stated_rule or notepad or ''),
                # Topped up by record_fork_cost when the fork runs after this
                # row is appended; present here so the columns exist on every
                # row rather than only on the rows that forked.
                'fork_context_chars': 0,
                'fork_outcome': '',
                'fork_candidates': '',
                'fork_has_path': '',
                'fork_path_offered': '',
                'fork_choice_kind': '',
                'fork_choice_hops': '',
                'fork_choice_groove': '',
                'move_guard_fired': int(move_guard_fired),
                # How the stated rule scores on unseen items, where the task
                # has a holdout. The log line was the only place this landed,
                # and on tasks with no completion condition it IS the outcome.
                'holdout_accuracy': (holdout_accuracy
                                     if holdout_accuracy is not None else ''),
                'fork_path_sim': '',
                'fork_choice': '',
                'verdict_source': str(verdict_src),
                'rating': _int(rating),
                'aim_status': str(aim_status) if aim_status else '',
                'justification': str(justification) if justification else '',
                'next_aim': str(next_aim) if next_aim else '',
                'persistence_count': _int(persistence_count),
                'graph_memory_mode': str(generation_vars.get('graph_memory_mode', 'description')),
                'context_window': _int(generation_vars.get('context_window', 0)) or 0,
                'history_len': int(len(history)),
                'llm_calls': int(llm_service.usage()['calls']),
                'input_tokens': int(llm_service.usage()['input_tokens']),
                'output_tokens': int(llm_service.usage()['output_tokens']),
                'tokens_estimated': int(llm_service.usage()['estimated']),
                'graph_contribution_chars': int(len(graph_contribution)),
                'graph_contribution': str(graph_contribution)[:1000],
                'graph_trust': round(float(graph_trust), 3),
                'aim_source': str(aim_came_from),
                'graph_nodes': int(G.number_of_nodes()),
                'graph_edges': int(G.number_of_edges()),
            })

        if rating is not None:
            previous_score = persistence_score if persistence_score is not None else 4
            persistence_score = rating

            # The verdict just reached is a verdict on the aim the graph (or
            # the judge) supplied last turn. If the graph chose it, that is
            # evidence about whether this graph fits the problem in front of
            # the agent - which is a different question from whether the route
            # is generally sound, and belongs on a different timescale.
            if aim_came_from == 'graph_path':
                advanced_ok = (rating >= 6 or aim_status in ('progress', 'achieved'))
                decay = tuning(generation_vars, 'trust_decay', TRUST_DECAY)
                floor = tuning(generation_vars, 'trust_floor', TRUST_FLOOR)
                if advanced_ok:
                    graph_trust = min(1.0, graph_trust / max(decay, 1e-6))
                elif aim_status == 'abandon' or rating <= 2:
                    graph_trust = max(floor, graph_trust * decay)
                logs.append(f"graph trust now {graph_trust:.2f} "
                            f"({'route worked' if advanced_ok else 'route did not'})")

            if new_suggestion:
                suggestion = new_suggestion

            # GO: rating >= 6 or explicit achieved means aim achieved.
            if rating >= 6 or aim_status == 'achieved':
                logger.info(f"GO: {agent_name} achieved aim '{current_aim}' (rating={rating})")
                new_node = current_aim
                G = update_graph(G, current_node, new_node, "Go",
                                 verdict_confidence(verdict_src, rating))
                G[current_node][new_node]['verdict_source'] = verdict_src
                annotate_aim(G, new_node, 'Go', reason=justification, rating=rating,
                             turn=turn_index, ruleset=agent.get('goal'),
                             enabled=generation_vars.get('graph_memory_mode') == 'graph',
                             evidence=(verdict_src == PROOF))
                current_node = new_node
                current_aim, aim_source, graph_hint, rejected = choose_aim(
                    G, current_node, agent['goal'], next_aim, generation_vars,
                    trust=graph_trust, notepad=notepad)
                aim_came_from = aim_source
                graph_contribution += record_fork_cost(trail, generation_vars)
                suggestion = graph_hint or (new_suggestion if current_aim else '')
                persistence_count = 0
                persistence_score = None
                logs.append(f"GO: aim achieved -> {new_node}")
                if rejected:
                    logs.append(f"Proposed aim was already ruled out ('{rejected[:60]}')")
                if aim_source == 'graph_path':
                    logs.append(f"Graph supplied the next aim: {current_aim}")
                if next_aim:
                    logs.append(f"Next aim: {next_aim}")

            # PROGRESS: the aim changed or advanced before a binary finish.
            elif aim_status == 'progress' and next_aim and next_aim != current_aim:
                logger.info(
                    f"PROGRESS: {agent_name} moving from aim '{current_aim}' "
                    f"to '{next_aim}' (rating={rating})"
                )
                new_node = current_aim
                G = update_graph(G, current_node, new_node, "Progress",
                                 verdict_confidence(verdict_src, rating))
                G[current_node][new_node]['verdict_source'] = verdict_src
                annotate_aim(G, new_node, 'Progress', reason=justification, rating=rating,
                             turn=turn_index, ruleset=agent.get('goal'),
                             enabled=generation_vars.get('graph_memory_mode') == 'graph',
                             evidence=(verdict_src == PROOF))
                current_node = new_node
                current_aim, aim_source, graph_hint, rejected = choose_aim(
                    G, current_node, agent['goal'], next_aim, generation_vars,
                    trust=graph_trust, notepad=notepad)
                aim_came_from = aim_source
                graph_contribution += record_fork_cost(trail, generation_vars)
                suggestion = graph_hint or new_suggestion
                persistence_count = 0
                persistence_score = None
                logs.append(f"PROGRESS: aim evolved -> {new_node} -> {current_aim}")
                if rejected:
                    logs.append(f"Proposed aim was already ruled out ('{rejected[:60]}')")
                if aim_source == 'graph_path':
                    logs.append(f"Graph supplied the next aim: {current_aim}")

            # NOGO checks. Only a *proof* skips the patience gate.
            #
            # Patience is the mechanism the whole paradigm runs on: an aim needs
            # a few turns to develop before it can be judged, and abandoning it
            # on the first bad rating means it can never mature into a Go. With
            # every NoGo ungated, aims died on turn one, a fresh aim was chosen
            # from the same node, and the graph came out as a depth-1 star with
            # no Go edges at all - which is what a run looks like when nothing
            # is allowed to progress.
            #
            # The bug that prompted the ungating was real (persistence_count
            # resets on each aim change, so aims moving faster than the gate
            # were never refuted), but it only ever needed to apply to verdicts
            # the keeper settled from evidence. A fact does not need a waiting
            # period; a judge's opinion does. So a keeper proof refutes at once
            # and everything else - abandon, strong failure, regression,
            # impatience - waits for a fair run.
            else:
                nogo = False
                proven = verdict_src == PROOF
                past_gate = persistence_count >= patience_min
                # Escape hatch, off by default, so the old ungated behaviour is
                # still reachable for comparison in a study.
                if generation_vars.get('nogo_ungated', False):
                    past_gate = True

                # Refuted by evidence, or explicitly abandoned by the judge
                if aim_status == 'abandon' and (proven or past_gate):
                    nogo = True
                    logs.append("NOGO: aim abandoned by "
                                f"{'evidence' if proven else 'judge'}")

                # Strong failure
                elif rating <= 2 and (proven or past_gate):
                    nogo = True
                    logs.append(f"NOGO: strong failure (rating={rating})")

                elif past_gate:
                    # Regression
                    if (rating < (previous_score - 1)) and rating <= 4:
                        nogo = True
                        logs.append(f"NOGO: regression (rating={rating}, prev={previous_score})")

                    # Exceeded patience
                    elif persistence_count > patience_max:
                        nogo = True
                        logs.append(f"NOGO: exceeded patience ({persistence_count} > {patience_max})")

                if nogo:
                    logger.info(f"NOGO: {agent_name} abandoning aim '{current_aim}'")
                    nogo_node = f"{current_aim}_NoGo"
                    G = update_graph(G, current_node, nogo_node, "NoGo",
                                     verdict_confidence(verdict_src, rating))
                    G[current_node][nogo_node]['verdict_source'] = verdict_src
                    # The payload goes on the aim itself, so recall surfaces the
                    # aim and why it failed rather than a bare "_NoGo" marker.
                    annotate_aim(G, nogo_node, 'NoGo', reason=justification, rating=rating,
                                 turn=turn_index, ruleset=agent.get('goal'),
                                 enabled=generation_vars.get('graph_memory_mode') == 'graph',
                                 evidence=(verdict_src == PROOF))
                    if nogo_node in G:
                        # Run-scoped dead ends stay useful for the rest of this
                        # conversation and are dropped at transfer; see
                        # prune_for_transfer.
                        G.nodes[nogo_node]['scope'] = locals().get('nogo_scope',
                                                                  'structural')
                    if nogo_node in G:
                        G.nodes[nogo_node]['full_text'] = str(current_aim)
                    if generation_vars.get('graph_memory_mode') == 'inline':
                        why = (justification or '').strip()
                        note = (f"That approach has been ruled out: {current_aim}."
                                + (f" {why[:160]}" if why else ""))
                        inline_notes.append(('narrator', note))
                        logs.append("Stated the refutation inline, once.")
                    current_aim = None
                    suggestion = ''
                    persistence_count = 0
                    persistence_score = None

    # The per-turn record lives inside the review block, which is skipped
    # whenever there is no aim - correctly, except that an aims-off run then
    # recorded nothing at all: no tokens, no turns, invisible to any study,
    # and indistinguishable from a dead provider. A bare row keeps the
    # accounting; every aim-shaped column stays empty because there is
    # honestly nothing to put in it.
    if (trail is not None
            and generation_vars.get('aim_system', 'on') == 'off'):
        trail.append({
            'turn': int(turn_index),
            'agent': str(agent_name),
            'aim': '', 'aim_source': '', 'aim_chosen_this_turn': '',
            'aim_status': '', 'stated_rule': str(stated_rule or ''),
            'graph_memory_mode': str(generation_vars.get('graph_memory_mode',
                                                         'description')),
            'context_window': int(generation_vars.get('context_window', 0) or 0),
            'history_len': int(len(history)),
            'llm_calls': int(llm_service.usage()['calls']),
            'input_tokens': int(llm_service.usage()['input_tokens']),
            'output_tokens': int(llm_service.usage()['output_tokens']),
            'tokens_estimated': int(llm_service.usage()['estimated']),
            'graph_contribution_chars': 0,
            'move_guard_fired': int(move_guard_fired),
            'graph_nodes': int(G.number_of_nodes()),
            'graph_edges': int(G.number_of_edges()),
        })

    # ------------------------------------------------------------------
    # Step 4: Save updated state back to the DataFrame
    # ------------------------------------------------------------------
    # Save graph
    nx.write_graphml(G, graph_path)

    agent_df = ensure_text_columns(pd.DataFrame(agents_df))
    agent_df.at[agent_idx, 'current_aim'] = current_aim
    agent_df.at[agent_idx, 'suggestion'] = suggestion
    agent_df.at[agent_idx, 'persistance_count'] = persistence_count
    agent_df.at[agent_idx, 'graph_trust'] = round(float(graph_trust), 4)
    agent_df.at[agent_idx, 'current_aim_source'] = str(aim_came_from)
    agent_df.at[agent_idx, 'persistance_score'] = persistence_score
    agent_df.at[agent_idx, 'current_node_location'] = current_node
    agent_df.at[agent_idx, 'last_response'] = response_text
    agent_df.at[agent_idx, 'last_narration'] = narration
    agent_df.at[agent_idx, 'notepad'] = notepad
    agent_df.at[agent_idx, 'personal_history'] = history + [(agent_name, display_response)]

    # Add the response to the conversation history
    new_history = history + [(agent_name, display_response)] + inline_notes

    logger.info(
        f"Agent processing completed. "
        f"Subgoal: {current_aim}, Node: {current_node}, "
        f"Persistence: {persistence_count}, Score: {persistence_score}"
    )

    return new_history, agent_df, logs
