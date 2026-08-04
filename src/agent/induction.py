"""Rule-induction run type for GoalGraph, with a dual judge.

The agent's long-range goal is fixed — identify a hidden rule about triples of
integers — and its *aims* are hypotheses about what that rule is. That maps
onto the existing Go / Progress / NoGo paradigm directly:

    current_aim        the hypothesis currently being tested
    agent response     the probe triple it chooses
    Go                 the hypothesis reproduces the true rule on unseen items
    Progress           the hypothesis survived and was refined into a new one
    NoGo               the keeper's answer contradicted the hypothesis

The point of this run type is the second judge. Everywhere else in GoalGraph,
`review_subgoal` is an LLM rating an aim 1-7 with no way to check it. Here the
question "was this hypothesis falsified?" is decidable: the guesser publishes
its hypothesis as an executable predicate, and we run that predicate against
every observation so far. Disagreement is refutation, as a fact rather than an
opinion.

So each turn is judged twice — once by the LLM judge, once by ground truth —
and the run reports how often the LLM judge was right. Two graphs are built in
parallel, one driven by each judge, so the cost of judge error is visible as a
structural difference between them.
"""

import ast
import json
import logging
import operator

import networkx as nx

from . import induction_rules as R
from .graph_memory import GraphMemory, legacy_nogo_statement, node_id as aim_id
from .llm_service import llm_service

logger = logging.getLogger('induction_logger')

DEFAULT_MODEL = 'gpt-5.4-mini'
DEFAULT_EFFORT = 'low'

# Aim statuses, shared with schemas.json_schema_review_goal
CONTINUE, PROGRESS, ACHIEVED, ABANDON = 'continue', 'progress', 'achieved', 'abandon'

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {
            "type": "string",
            "description": "Your current best guess at the hidden rule, in one sentence.",
        },
        "predicate": {
            "type": "string",
            "description": (
                "The same hypothesis as a Python boolean expression over the "
                "variables a, b, c (the three integers in order). Example: "
                "'a < b < c'. Use only arithmetic, comparisons, and/or/not, and "
                "the functions abs, min, max, len, set, sorted, sum, all, any."
            ),
        },
        "action": {"type": "string", "enum": ["probe", "declare"]},
        "probe": {
            "type": ["array", "null"],
            "items": {"type": "integer"},
            "minItems": 3, "maxItems": 3,
            "description": "Three integers 1-100 to test. Null when declaring.",
        },
    },
    "required": ["hypothesis", "predicate", "action", "probe"],
    "additionalProperties": False,
}

# Mirrors schemas.json_schema_review_goal so the game judge and the chat judge
# speak the same language and their verdicts are directly comparable.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "rating": {"type": "integer", "minimum": 1, "maximum": 7},
        "justification": {"type": "string"},
        "suggestion": {"type": "string"},
        "aim_status": {"type": "string", "enum": [CONTINUE, PROGRESS, ACHIEVED, ABANDON]},
        "next_aim": {"type": ["string", "null"]},
    },
    "required": ["rating", "justification", "suggestion", "aim_status", "next_aim"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Safe predicate evaluation
# ---------------------------------------------------------------------------
# The guesser writes these, so they are untrusted input and are never eval'd
# as-is. Only an explicit whitelist of AST nodes is allowed through, which
# rules out attribute access, imports, calls to anything unlisted, and any
# statement form. Anything else is rejected and the turn falls back to the
# natural-language hypothesis alone.

_ALLOWED_FUNCS = {
    'abs': abs, 'min': min, 'max': max, 'len': len,
    'set': set, 'sorted': sorted, 'sum': sum, 'all': all, 'any': any,
}

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
    ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Call,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
)

_ALLOWED_NAMES = {'a', 'b', 'c'} | set(_ALLOWED_FUNCS)


class UnsafePredicate(ValueError):
    """The guesser's predicate used something outside the whitelist."""


def compile_predicate(expr, funcs=None, variables=('a', 'b', 'c')):
    """Compile a guesser-written boolean expression into a callable.

    Returns a function of the given variables -> bool, or raises
    UnsafePredicate. `funcs` overrides the callable whitelist for simulations
    with a different vocabulary; the AST rules are shared so there is only one
    sandbox to audit.
    """
    funcs = _ALLOWED_FUNCS if funcs is None else funcs
    allowed_names = set(variables) | set(funcs)

    if not expr or not isinstance(expr, str) or len(expr) > 400:
        raise UnsafePredicate("empty or oversized predicate")

    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError as e:
        raise UnsafePredicate(f"syntax error: {e}")

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafePredicate(f"disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise UnsafePredicate(f"disallowed name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
                raise UnsafePredicate("disallowed call")
            if node.keywords:
                raise UnsafePredicate("keyword arguments not allowed")
        # Cap exponents so a**b**c cannot burn the process.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not (isinstance(node.right, ast.Constant)
                    and isinstance(node.right.value, int)
                    and 0 <= node.right.value <= 6):
                raise UnsafePredicate("exponent must be a small integer constant")

    code = compile(tree, '<predicate>', 'eval')

    def fn(*args, **bound):
        # Positional args map onto `variables`; `bound` lets a caller inject
        # message-specific helpers (see norms.py) alongside them.
        scope = dict(zip(variables, args))
        scope.update(funcs)
        scope.update(bound)
        return bool(eval(code, {'__builtins__': {}}, scope))

    return fn


def predicate_labels(fn, triples):
    """Apply a compiled predicate to triples, or return None if it ever errors."""
    out = []
    for t in triples:
        try:
            out.append(bool(fn(*t)))
        except Exception:
            return None
    return out


# ---------------------------------------------------------------------------
# The two judges
# ---------------------------------------------------------------------------

def truth_judge(predicate_expr, history, rule_name, previous_predicate, holdout):
    """Decide the aim's status from evidence, not opinion.

    A hypothesis that disagrees with the keeper on any observation it has
    already seen is refuted — that is a fact, so it returns ABANDON. One that
    also reproduces the true rule on held-out items has genuinely achieved the
    goal. Everything else is still in play.

    Returns (aim_status, detail_dict).
    """
    detail = {"compiled": False, "consistent": None, "holdout_acc": None}

    try:
        fn = compile_predicate(predicate_expr)
    except UnsafePredicate as e:
        detail["error"] = str(e)
        return CONTINUE, detail
    detail["compiled"] = True

    seen = [t for t, _ in history]
    truth = [lab for _, lab in history]
    got = predicate_labels(fn, seen)
    if got is None:
        detail["error"] = "predicate raised on observed evidence"
        return CONTINUE, detail

    consistent = got == truth
    detail["consistent"] = consistent
    if not consistent:
        # Refuted by evidence already in hand.
        detail["contradicts"] = [
            {"triple": list(t), "keeper": lab, "hypothesis": g}
            for (t, lab), g in zip(history, got) if lab != g
        ][:3]
        return ABANDON, detail

    ho_items = [t for t, _ in holdout]
    ho_truth = [lab for _, lab in holdout]
    ho_got = predicate_labels(fn, ho_items)
    if ho_got is not None:
        acc = sum(1 for x, y in zip(ho_got, ho_truth) if x == y) / len(ho_truth)
        detail["holdout_acc"] = round(acc, 3)
        if acc >= 0.99:
            return ACHIEVED, detail

    if previous_predicate is not None and predicate_expr.strip() != previous_predicate.strip():
        return PROGRESS, detail
    return CONTINUE, detail


JUDGE_SYSTEM = """You are a judge reviewing an agent's progress on its current aim.

The agent is trying to identify a hidden rule that accepts or rejects triples of
integers. Its current aim is one hypothesis about that rule. You see the
evidence it has gathered and the hypothesis it currently holds.

Judge the aim, not the agent's manner."""

JUDGE_PROMPT = """Agent's long-range goal: {goal}
Agent's current aim (its working hypothesis): {aim}

Evidence gathered so far, as (triple -> keeper's verdict):
{evidence}

The agent has spent {spent} probes on this aim, out of a {budget} probe budget.

Rate progress on this aim from 1 to 7, and choose an aim_status:
- "continue": the hypothesis is still viable and worth more probes.
- "progress": the hypothesis has been refined or superseded by a better one.
  Give the refined hypothesis as next_aim.
- "achieved": the hypothesis is certainly the hidden rule.
- "abandon": the evidence contradicts the hypothesis; it cannot be the rule.

Judge "abandon" only when some observation above is inconsistent with the
hypothesis as stated. Judge "achieved" only when no other rule could explain
the evidence equally well."""


def llm_judge(goal, aim, history, spent, budget, model, effort):
    """The existing GoalGraph judge, prompted over a probe log instead of chat."""
    prompt = JUDGE_PROMPT.format(
        goal=goal, aim=aim, evidence=fmt_evidence(history),
        spent=spent, budget=budget,
    )
    try:
        raw = llm_service.complete(
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "user", "content": prompt}],
            {"provider": "openai-codex", "model": model, "reasoning_effort": effort,
             "json_schema": JUDGE_SCHEMA, "schema_name": "aim_review", "verbosity": "low"},
        )
        out = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"LLM judge failed: {e}")
        return None

    status = out.get('aim_status')
    if status not in (CONTINUE, PROGRESS, ACHIEVED, ABANDON):
        rating = out.get('rating')
        status = ACHIEVED if isinstance(rating, int) and rating >= 6 else CONTINUE
        out['aim_status'] = status
    if isinstance(out.get('rating'), (int, float)):
        out['rating'] = max(1, min(7, int(out['rating'])))
    return out


CORROBORATE_SCHEMA = {
    "type": "object",
    "properties": {
        "refuted": {"type": "boolean"},
        "reason": {"type": "string"},
        "rival_rule": {"type": ["string", "null"]},
    },
    "required": ["refuted", "reason", "rival_rule"],
    "additionalProperties": False,
}

CORROBORATE_SYSTEM = """You are checking a claim that an agent has finished its aim.

Your job is to refute that claim. Treat it as unproven until the evidence forces
you to accept it, and say so plainly when it does not. Confirming a claim that
later turns out to be wrong is the costly error here; withholding confirmation
from a claim that was right merely costs a little time."""

CORROBORATE_PROMPT = """Goal: {goal}
Claim: the agent's aim below is exactly correct and its goal is achieved.

Aim claimed to be achieved: {aim}

Evidence gathered so far, as (triple -> keeper's verdict):
{evidence}

Two ways this claim can fail:
1. Some observation above is inconsistent with the aim as stated.
2. A different rule explains every observation above equally well, so the
   evidence does not single this one out.

If either holds, set refuted to true and name the rival rule if there is one.
Set refuted to false only if the evidence genuinely admits no other explanation."""


def corroborate_achievement(goal, aim, history, model, effort):
    """Independent adversarial check on a candidate Go.

    A Go edge is not just a record that an aim finished — `find_path_to_goal`
    steers later agents toward it, so a false Go actively misdirects, where a
    false NoGo merely prunes. That asymmetry is why Go is worth a second,
    independently-framed opinion and NoGo is not.
    """
    try:
        raw = llm_service.complete(
            [{"role": "system", "content": CORROBORATE_SYSTEM},
             {"role": "user", "content": CORROBORATE_PROMPT.format(
                 goal=goal, aim=aim, evidence=fmt_evidence(history))}],
            {"provider": "openai-codex", "model": model, "reasoning_effort": effort,
             "json_schema": CORROBORATE_SCHEMA, "schema_name": "corroboration",
             "verbosity": "low"},
        )
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"corroborator failed: {e}")
        # An unreachable corroborator must not silently wave the claim through.
        return {"refuted": True, "reason": f"corroborator unavailable: {e}",
                "rival_rule": None}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def update_graph(graph, current_node, next_node, label, weight=1.0):
    """Add or update an edge. Same contract as agent.update_graph."""
    if current_node not in graph:
        graph.add_node(current_node)
    if next_node not in graph:
        graph.add_node(next_node)
    if graph.has_edge(current_node, next_node):
        graph[current_node][next_node]['label'] = label
        graph[current_node][next_node]['weight'] = weight
    else:
        graph.add_edge(current_node, next_node, label=label, weight=weight)
    return graph


def goalgraph_decision(verdict, previous_rating, spent,
                       patience_min=2, patience_max=5, go_threshold=6):
    """Reproduce agent.py's Go / Progress / NoGo rules exactly.

    GoalGraph does not act on aim_status alone. The 1-7 rating carries
    independent weight, and a low rating fires NoGo even when the judge said
    "continue" — which turns out to be the mechanism doing most of the work,
    because the judge's status field is far less reliable than its rating.
    Simulating the status field alone would misrepresent the system.

    Returns (decision, reason).
    """
    rating = verdict.get('rating')
    status = verdict.get('aim_status')
    next_aim = verdict.get('next_aim')

    if rating is None:
        return CONTINUE, "no rating"

    if rating >= go_threshold or status == ACHIEVED:
        return ACHIEVED, (f"rating={rating}" if rating >= go_threshold
                          else "judge: achieved")

    if status == PROGRESS and next_aim:
        return PROGRESS, "judge: progress"

    # Refutation is ungated: patience protects a struggling aim, not a
    # rejected one. Mirrors the NoGo block in agent.py.
    if status == ABANDON:
        return ABANDON, "judge: abandon"
    if rating <= 2:
        return ABANDON, f"strong failure (rating={rating})"

    if spent >= patience_min:
        if previous_rating is not None and rating < (previous_rating - 1) and rating <= 4:
            return ABANDON, f"regression ({previous_rating} -> {rating})"
        if spent > patience_max:
            return ABANDON, f"exceeded patience ({spent} > {patience_max})"

    return CONTINUE, "continue"


def apply_status(graph, node, aim, status, spent):
    """Walk one judge's verdict onto its graph. Returns the new current node."""
    if status == ACHIEVED:
        update_graph(graph, node, aim, "Go", spent)
        return aim
    if status == PROGRESS:
        update_graph(graph, node, aim, "Progress", spent)
        return aim
    if status == ABANDON:
        update_graph(graph, node, f"{aim}_NoGo", "NoGo", spent)
        return node
    return node


def node_label(hypothesis, limit=60):
    """Display-only label. Never use this for node identity.

    An earlier version of this harness keyed graph nodes on this string, which
    silently merged distinct hypotheses whenever they shared a prefix - and the
    clause that distinguishes two rules is almost always at the end. Identity
    now goes through aim_id(), which keys on the predicate. GoalGraph's own
    agent.py never truncated aim names; this was a defect of the harness only.
    """
    h = " ".join((hypothesis or "unnamed aim").split())
    return h if len(h) <= limit else h[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

GUESSER_PROMPT = """You are playing a rule-induction game.

I am thinking of a hidden rule that either accepts or rejects a triple of three
integers between 1 and 100. Your job is to work out that rule.

Evidence so far:
{evidence}

Probes used: {used} of {budget}.

Reply with:
- hypothesis: your current single best guess at the rule, in one sentence.
- predicate: that same hypothesis as a Python boolean expression over a, b, c.
- action: "probe" to test another triple, or "declare" if you are confident.
- probe: the three integers to test (null if declaring).

The predicate must mean exactly what the hypothesis sentence says — it is how
your aim is checked against the evidence.

Your score depends on whether your rule reproduces mine on unseen triples, not
on how quickly you declare. A rule that fits every example so far may still be
too narrow."""


def fmt_evidence(history):
    return "\n".join(
        f"  {t[0]}, {t[1]}, {t[2]}  ->  {'YES' if lab else 'NO'}" for t, lab in history
    )


def valid_probe(p):
    return (isinstance(p, list) and len(p) == 3
            and all(isinstance(x, int) and R.ITEM_MIN <= x <= R.ITEM_MAX for x in p))


def run_game(rule_name, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, budget=12,
             seed=0, patience_min=2, patience_max=5, verbose=True, retries=2,
             judge_model=None, judge_effort=None, corroborate=True,
             go_threshold=6, memory_mode='none', context_window=None,
             recall_k=4, carried_memory=None, ruleset=None):
    """Play one game, judged twice, building one graph per judge.

    judge_model/judge_effort default to the guesser's. Set them to hold the
    guesser fixed while varying the judge, which is the only way to tell a
    judge failure apart from a guesser failure.
    """
    judge_model = judge_model or model
    judge_effort = judge_effort or effort
    goal = "identify the hidden rule governing which triples of integers are accepted"
    holdout = R.holdout_set(rule_name, n=24, seed=seed)

    # memory_mode picks what the guesser is told about its own past aims:
    #   none        nothing (today's behaviour for this run type)
    #   description the old flat list of failed aim labels, no reasons
    #   graph       structured recall - nearest ruled-out aims, with reasons
    # context_window caps how much raw evidence it sees, which is what makes
    # the memory matter: with the full log in front of it, a guesser has no
    # need of stored aims at all.
    mem = GraphMemory(carried_memory, ruleset=ruleset or rule_name,
                      use_embeddings=False) if memory_mode != 'none' else None

    seed_item = R.SEED_EXAMPLES[rule_name]
    history = [(seed_item, True)]

    G_llm, G_truth = nx.DiGraph(), nx.DiGraph()
    G_llm.add_node('start')
    G_truth.add_node('start')
    node_llm = node_truth = 'start'

    turns = []
    prev_predicate = None
    prev_rating = None
    current_aim = None
    spent_on_aim = 0
    declared = False

    def say(msg):
        if verbose:
            print(f"[{rule_name}] {msg}", flush=True)

    say(f"start — seed {seed_item} -> YES")

    while len(history) - 1 < budget:
        out = None
        for attempt in range(retries + 1):
            try:
                shown = history if not context_window else history[-context_window:]
                elided = len(history) - len(shown)
                evidence = fmt_evidence(shown)
                if elided:
                    evidence = f"  (…{elided} earlier observations no longer in view)\n" + evidence
                recall = ''
                if mem is not None:
                    recall = (mem.render(current_aim or '', k=recall_k)
                              if memory_mode == 'graph'
                              else legacy_nogo_statement(mem.G))
                raw = llm_service.complete(
                    (recall + GUESSER_PROMPT.format(
                        evidence=evidence,
                        used=len(history) - 1, budget=budget,
                    )),
                    {"provider": "openai-codex", "model": model,
                     "reasoning_effort": effort, "json_schema": TURN_SCHEMA,
                     "schema_name": "turn", "verbosity": "low"},
                )
                out = json.loads(raw)
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(f"guesser call failed ({attempt + 1}): {e}")
        if out is None:
            say("guesser unreachable, ending game")
            break

        hypothesis = (out.get('hypothesis') or '').strip()
        predicate = (out.get('predicate') or '').strip()
        aim = aim_id(hypothesis, predicate)

        if current_aim is None or aim != current_aim:
            current_aim = aim
            spent_on_aim = 0
            prev_rating = None

        if out.get('action') == 'declare':
            declared = True
            say(f"declare after {len(history) - 1} probes: {hypothesis}")

        probe = out.get('probe')
        if not declared:
            if not valid_probe(probe):
                say(f"invalid probe {probe!r}, ending game")
                break
            actual = R.label(rule_name, probe)
            history.append((tuple(probe), actual))
            spent_on_aim += 1

        # ---- judge twice on the same evidence ----
        t_status, t_detail = truth_judge(predicate, history, rule_name, prev_predicate, holdout)
        verdict = llm_judge(goal, hypothesis, history, spent_on_aim, budget,
                            judge_model, judge_effort)
        l_status = verdict['aim_status'] if verdict else None

        # What GoalGraph would actually do with that verdict — status plus the
        # rating rules, not the status field alone.
        if verdict:
            l_decision, l_reason = goalgraph_decision(
                verdict, prev_rating, spent_on_aim, patience_min, patience_max,
                go_threshold)
            prev_rating = verdict.get('rating')
        else:
            l_decision, l_reason = None, "judge unreachable"

        # A candidate Go must survive an independent attempt to refute it.
        corrob = None
        if corroborate and l_decision == ACHIEVED:
            corrob = corroborate_achievement(
                goal, hypothesis, history, judge_model, judge_effort)
            if corrob.get('refuted'):
                l_decision = CONTINUE
                l_reason = f"Go withheld: {corrob.get('reason', '')[:70]}"

        if mem is not None:
            why = None
            contra = (t_detail or {}).get('contradicts') or []
            if contra:
                c = contra[0]
                why = (f"{c['triple'][0]}, {c['triple'][1]}, {c['triple'][2]} was "
                       f"{'accepted' if c['keeper'] else 'rejected'} but this rule says "
                       f"{'yes' if c['hypothesis'] else 'no'}")
            mem.record(hypothesis, t_status, predicate=predicate, reason=why,
                       rating=(verdict or {}).get('rating'), turn=len(history) - 1)

        node_truth = apply_status(G_truth, node_truth, aim, t_status, spent_on_aim)
        if l_decision:
            node_llm = apply_status(G_llm, node_llm, aim, l_decision, spent_on_aim)

        turns.append({
            "probe": list(probe) if (probe and not declared) else None,
            "actual": ("yes" if history[-1][1] else "no") if not declared else None,
            "hypothesis": hypothesis,
            "predicate": predicate,
            "truth_status": t_status,
            "truth_detail": t_detail,
            "llm_status": l_status,
            "llm_decision": l_decision,
            "llm_reason": l_reason,
            "llm_rating": (verdict or {}).get('rating'),
            "corroboration": corrob,
            "llm_justification": (verdict or {}).get('justification'),
            "agree": l_decision == t_status,
            "agree_raw_status": l_status == t_status,
        })

        mark = "ok " if l_decision == t_status else "MISS"
        say(f"probe {probe} -> {history[-1][1] and 'YES' or 'NO'} | truth={t_status:<8} "
            f"llm={str(l_decision):<8} {mark} | {l_reason[:26]:<26} | {hypothesis[:44]}")

        prev_predicate = predicate
        if declared or t_status == ACHIEVED:
            break

    # ---- final behavioural score on the last predicate ----
    final = turns[-1] if turns else {}
    final_acc = (final.get('truth_detail') or {}).get('holdout_acc')
    if final_acc is None:
        try:
            fn = compile_predicate(final.get('predicate', ''))
            got = predicate_labels(fn, [t for t, _ in holdout])
            if got is not None:
                ho_truth = [lab for _, lab in holdout]
                final_acc = round(sum(1 for x, y in zip(got, ho_truth) if x == y) / len(ho_truth), 3)
        except UnsafePredicate:
            final_acc = None

    judged = [t for t in turns if t['llm_decision']]
    agree = sum(1 for t in judged if t['agree'])
    false_survival = sum(
        1 for t in judged
        if t['truth_status'] == ABANDON and t['llm_decision'] != ABANDON
    )
    premature = sum(
        1 for t in judged
        if t['truth_status'] in (CONTINUE, PROGRESS) and t['llm_decision'] == ABANDON
    )
    false_go = sum(
        1 for t in judged
        if t['llm_decision'] == ACHIEVED and t['truth_status'] != ACHIEVED
    )
    uncompiled = sum(1 for t in turns if not t['truth_detail'].get('compiled'))

    # Did blocking a Go help or hurt? Ground truth knows.
    withheld = [t for t in turns if t.get('corroboration')
                and t['corroboration'].get('refuted')]
    withheld_right = sum(1 for t in withheld if t['truth_status'] != ACHIEVED)
    withheld_wrong = sum(1 for t in withheld if t['truth_status'] == ACHIEVED)
    go_edges = sum(1 for t in judged if t['llm_decision'] == ACHIEVED)

    result = {
        "rule": rule_name,
        "true_rule": R.describe(rule_name),
        "model": model,
        "effort": effort,
        "judge_model": judge_model,
        "judge_effort": judge_effort,
        "budget": budget,
        "probes": len(history) - 1,
        "declared": declared,
        "final_hypothesis": final.get('hypothesis'),
        "final_predicate": final.get('predicate'),
        "holdout_acc": final_acc,
        "solved": bool(final_acc is not None and final_acc >= 0.9),
        "judge_turns": len(judged),
        "judge_agreement": round(agree / len(judged), 3) if judged else None,
        "raw_status_agreement": (
            round(sum(1 for t in judged if t['agree_raw_status']) / len(judged), 3)
            if judged else None),
        "false_survival": false_survival,
        "premature_prune": premature,
        "false_go": false_go,
        "go_edges": go_edges,
        "go_withheld": len(withheld),
        "go_withheld_right": withheld_right,
        "go_withheld_wrong": withheld_wrong,
        "corroborate": corroborate,
        "memory_mode": memory_mode,
        "context_window": context_window,
        "memory_stats": mem.stats() if mem is not None else None,
        "go_threshold": go_threshold,
        "uncompiled_predicates": uncompiled,
        "turns": turns,
        "graph_llm": nx.node_link_data(G_llm),
        "graph_truth": nx.node_link_data(G_truth),
    }
    say(f"done — holdout {final_acc if final_acc is not None else 'n/a'} "
        f"judge agreement {result['judge_agreement']} "
        f"(false survival {false_survival}, premature prune {premature})")
    return result, G_llm, G_truth
