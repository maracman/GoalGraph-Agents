"""Norm-inference run type for GoalGraph: two agents, one hidden rule.

A keeper agent silently enforces a norm about the guesser's messages. The norm
decides which *mode* the keeper answers in — engaged or withdrawn — while the
reply text is written by a model, so the dialogue is real while the fact of
whether the norm was met stays in code. The guesser has to infer the norm from
how the keeper's manner shifts.

This exists to test one idea. In the rule-induction run type, ungating NoGo
worked because refutation is decidable from the agent's own evidence: a single
contradicting observation settles it. Go is not decidable that way — finite
evidence never forces a general rule, so an honest judge under-rates real
successes and an adversarial one refuses every claim. Both were measured.

The fix proposed there was to certify Go on evidence the agent did not author.
Here that evidence exists: the guesser commits to a prediction of how the
keeper will respond *before* sending each message, and the keeper's actual
mode either bears it out or does not. An aim that predicts the counterparty
correctly, repeatedly, has earned a Go in a way no amount of re-reading the
transcript can establish.

So each run scores two Go rules against ground truth:

    immediate Go   the judge reads the transcript and rates the aim (today)
    lagged Go      the aim predicted the keeper N times running (proposed)
"""

import json
import logging

import networkx as nx

from . import norm_rules as N
from .induction import (
    CONTINUE, PROGRESS, ACHIEVED, ABANDON,
    UnsafePredicate, compile_predicate, goalgraph_decision,
    node_label, update_graph, apply_status,
)
from .graph_memory import node_id as aim_id
from .llm_service import llm_service

logger = logging.getLogger('norms_logger')

DEFAULT_MODEL = 'gpt-5.4-mini'
DEFAULT_EFFORT = 'low'
GO_STREAK = 3          # correct predictions in a row before a lagged Go
ENGAGED, WITHDRAWN = 'engaged', 'withdrawn'

GUESSER_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {
            "type": "string",
            "description": "Your current best guess at the hidden norm, in one sentence.",
        },
        "predicate": {
            "type": "string",
            "description": "The same guess as a boolean expression over the message you are about to send.",
        },
        "message": {
            "type": "string",
            "description": "The message to send next. One or two sentences.",
        },
        "predicted_mode": {
            "type": "string",
            "enum": [ENGAGED, WITHDRAWN],
            "description": "How you expect the other party to respond to that message.",
        },
    },
    "required": ["hypothesis", "predicate", "message", "predicted_mode"],
    "additionalProperties": False,
}

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

LABEL_SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {"type": "string", "enum": ["yes", "no"]}}},
    "required": ["labels"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# The keeper
# ---------------------------------------------------------------------------

KEEPER_SYSTEM = f"""You are {N.KEEPER_NAME}, talking with a colleague.

You are in one of two moods, which will be given to you each turn. Stay in it.

engaged   - warm and forthcoming. Engage with what they said, add something of
            your own, sound glad to be talking.
withdrawn - flat and incurious. Acknowledge them minimally and offer nothing
            further. Not rude, just closed.

Absolutely never explain, hint at, or allude to why your mood changes. Never
mention moods, rules, patterns, conditions, or what they did. Just talk, in
whichever mood you are in. Keep replies to one or two sentences."""


def keeper_reply(mode, message, history, model, effort):
    """Text from a model, mood from code."""
    convo = "\n".join(
        f"{'Colleague' if r == 'guesser' else N.KEEPER_NAME}: {t}"
        for r, t in history[-6:]
    )
    prompt = (f"Conversation so far:\n{convo or '(nothing yet)'}\n\n"
              f"Colleague just said: {message}\n\n"
              f"Your mood for this reply: {mode}\n\nReply now.")
    try:
        return llm_service.complete(
            [{"role": "system", "content": KEEPER_SYSTEM},
             {"role": "user", "content": prompt}],
            {"provider": "openai-codex", "model": model,
             "reasoning_effort": effort, "verbosity": "low", "max_tokens": 120},
        ).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"keeper failed: {e}")
        return "Mm." if mode == WITHDRAWN else "That's interesting, tell me more."


# ---------------------------------------------------------------------------
# The guesser
# ---------------------------------------------------------------------------

GUESSER_PROMPT = f"""You are talking with a colleague called {N.KEEPER_NAME}.

{N.KEEPER_NAME} follows a hidden rule about the messages you send. When your
message satisfies that rule they answer warmly and at length; when it does not,
they answer flatly and offer nothing. They will never tell you the rule, and
never hint at it. Your job is to work out what it is.

The rule depends only on the message you send — its wording, form or content.
It never depends on what {N.KEEPER_NAME} said, or on the topic of conversation.

Conversation so far, with how {N.KEEPER_NAME} actually responded:
{{evidence}}

Messages sent: {{used}} of {{budget}}.

Reply with:
- hypothesis: your current single best guess at the rule, in one sentence.
- predicate: that guess as a boolean expression over the message you are about
  to send.
{N.PREDICATE_VOCAB}
- message: the next thing you say to {N.KEEPER_NAME}. Make it a deliberate test
  of your hypothesis, and keep it natural.
- predicted_mode: whether you expect them to answer "engaged" or "withdrawn".
  Answer from your hypothesis honestly, not from what you would prefer.

You are scored on whether your stated rule is right, not on how fast you
commit. A rule that fits everything so far may still be wrong."""


def fmt_evidence(turns):
    if not turns:
        return "(nothing yet)"
    out = []
    for i, t in enumerate(turns, 1):
        out.append(f"  {i}. You: {t['message']}")
        out.append(f"     {N.KEEPER_NAME} [{t['actual_mode']}]: {t['reply']}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The two judges
# ---------------------------------------------------------------------------

def truth_judge(predicate_expr, turns, previous_predicate, holdout):
    """Status from evidence, exactly as in the induction run type.

    Refuted means the guesser's own predicate disagrees with how the keeper
    actually behaved on some message already sent.
    """
    detail = {"compiled": False, "consistent": None, "holdout_acc": None}
    try:
        fn = compile_predicate(predicate_expr, funcs=N.predicate_helpers(""), variables=())
    except UnsafePredicate as e:
        detail["error"] = str(e)
        return CONTINUE, detail
    detail["compiled"] = True

    got, truth = [], []
    for t in turns:
        try:
            got.append(bool(compile_predicate(
                predicate_expr, funcs=N.predicate_helpers(t['message']), variables=())()))
        except Exception:
            detail["error"] = "predicate raised on observed evidence"
            return CONTINUE, detail
        truth.append(t['actual_mode'] == ENGAGED)

    consistent = got == truth
    detail["consistent"] = consistent
    if not consistent:
        detail["contradicts"] = [
            {"message": t['message'][:70], "keeper": t['actual_mode'], "hypothesis": g}
            for t, lab, g in zip(turns, truth, got) if lab != g
        ][:3]
        return ABANDON, detail

    hits = 0
    for msg, lab in holdout:
        try:
            if bool(compile_predicate(
                    predicate_expr, funcs=N.predicate_helpers(msg), variables=())()) == lab:
                hits += 1
        except Exception:
            return CONTINUE, detail
    acc = hits / len(holdout)
    detail["holdout_acc"] = round(acc, 3)
    if acc >= 0.99:
        return ACHIEVED, detail

    if previous_predicate is not None and predicate_expr.strip() != previous_predicate.strip():
        return PROGRESS, detail
    return CONTINUE, detail


JUDGE_SYSTEM = """You are a judge reviewing an agent's progress on its current aim.

The agent is trying to work out a hidden rule that governs when the other party
in a conversation answers warmly rather than flatly. Its current aim is one
hypothesis about that rule. Judge the aim against the evidence, not the manner."""

JUDGE_PROMPT = """Agent's long-range goal: {goal}
Agent's current aim (its working hypothesis): {aim}

Conversation so far, with how the other party actually responded:
{evidence}

The agent has spent {spent} messages on this aim, out of a {budget} budget.

Rate progress on this aim from 1 to 7 and choose an aim_status:
- "continue": the hypothesis is still viable and worth more testing.
- "progress": it has been refined or superseded; give the refinement as next_aim.
- "achieved": the hypothesis is certainly the hidden rule.
- "abandon": the evidence contradicts it; it cannot be the rule.

Judge "abandon" only when some exchange above is inconsistent with the
hypothesis as stated."""


def llm_judge(goal, aim, turns, spent, budget, model, effort):
    try:
        raw = llm_service.complete(
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "user", "content": JUDGE_PROMPT.format(
                 goal=goal, aim=aim, evidence=fmt_evidence(turns),
                 spent=spent, budget=budget)}],
            {"provider": "openai-codex", "model": model, "reasoning_effort": effort,
             "json_schema": JUDGE_SCHEMA, "schema_name": "aim_review", "verbosity": "low"},
        )
        out = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"LLM judge failed: {e}")
        return None
    if out.get('aim_status') not in (CONTINUE, PROGRESS, ACHIEVED, ABANDON):
        r = out.get('rating')
        out['aim_status'] = ACHIEVED if isinstance(r, int) and r >= 6 else CONTINUE
    if isinstance(out.get('rating'), (int, float)):
        out['rating'] = max(1, min(7, int(out['rating'])))
    return out


# ---------------------------------------------------------------------------
# Behavioural scoring of the final stated norm
# ---------------------------------------------------------------------------

SCORE_PROMPT = """Below is a rule about messages. Apply it literally and exactly
as written to each message, and say whether the message satisfies it.

Rule: {hypothesis}

Messages:
{items}

Return a "labels" array of "yes"/"no", one per message, in the same order.
Return exactly {n} labels."""


def score_stated_norm(hypothesis, holdout, model, effort):
    """Hand the guesser's own words to a fresh model with no game history."""
    if not hypothesis:
        return None
    items = "\n".join(f"  {i+1}. {m}" for i, (m, _) in enumerate(holdout))
    truth = ["yes" if lab else "no" for _, lab in holdout]
    try:
        raw = llm_service.complete(
            SCORE_PROMPT.format(hypothesis=hypothesis, items=items, n=len(holdout)),
            {"provider": "openai-codex", "model": model, "reasoning_effort": effort,
             "json_schema": LABEL_SCHEMA, "schema_name": "labels", "verbosity": "low"},
        )
        got = json.loads(raw).get('labels', [])[:len(truth)]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scoring failed: {e}")
        return None
    if not got:
        return None
    return round(sum(1 for a, b in zip(got, truth) if a == b) / len(truth), 3)


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

def run_game(norm_name, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, budget=12,
             seed=0, patience_min=2, patience_max=5, verbose=True, retries=2,
             judge_model=None, judge_effort=None, go_streak=GO_STREAK,
             go_both_modes=True):
    judge_model = judge_model or model
    judge_effort = judge_effort or effort
    goal = "work out the hidden rule governing when the other party answers warmly"
    holdout = N.holdout_labels(norm_name, n=24, seed=seed)

    G_now, G_lag = nx.DiGraph(), nx.DiGraph()
    G_now.add_node('start')
    G_lag.add_node('start')
    node_now = node_lag = 'start'

    convo, turns = [], []
    prev_predicate = prev_rating = None
    current_aim, spent_on_aim, streak = None, 0, 0

    def say(msg):
        if verbose:
            print(f"[{norm_name}] {msg}", flush=True)

    while len(turns) < budget:
        out = None
        for _ in range(retries + 1):
            try:
                raw = llm_service.complete(
                    GUESSER_PROMPT.format(evidence=fmt_evidence(turns),
                                          used=len(turns), budget=budget),
                    {"provider": "openai-codex", "model": model,
                     "reasoning_effort": effort, "json_schema": GUESSER_SCHEMA,
                     "schema_name": "turn", "verbosity": "low"},
                )
                out = json.loads(raw)
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(f"guesser failed: {e}")
        if out is None:
            say("guesser unreachable, ending game")
            break

        hypothesis = (out.get('hypothesis') or '').strip()
        predicate = (out.get('predicate') or '').strip()
        message = (out.get('message') or '').strip()
        predicted = out.get('predicted_mode')
        if not message:
            say("empty message, ending game")
            break

        aim = aim_id(hypothesis, predicate)
        if current_aim is None or aim != current_aim:
            current_aim, spent_on_aim, prev_rating = aim, 0, None

        # The keeper's mode is decided by code, then dressed in model prose.
        actual_mode = ENGAGED if N.satisfies(norm_name, message) else WITHDRAWN
        reply = keeper_reply(actual_mode, message, convo, model, effort)
        convo.append(('guesser', message))
        convo.append(('keeper', reply))
        spent_on_aim += 1

        # Evidence the guesser did not author: did its aim predict the
        # counterparty? This is what the lagged Go is certified on.
        correct = (predicted == actual_mode)
        streak = streak + 1 if correct else 0

        turns.append({
            "message": message, "reply": reply, "actual_mode": actual_mode,
            "predicted_mode": predicted, "prediction_correct": correct,
            "streak": streak, "hypothesis": hypothesis, "predicate": predicate,
        })

        t_status, t_detail = truth_judge(predicate, turns, prev_predicate, holdout)
        verdict = llm_judge(goal, hypothesis, turns, spent_on_aim, budget,
                            judge_model, judge_effort)

        if verdict:
            now_decision, now_reason = goalgraph_decision(
                verdict, prev_rating, spent_on_aim, patience_min, patience_max)
            prev_rating = verdict.get('rating')
        else:
            now_decision, now_reason = None, "judge unreachable"

        # Lagged Go: identical to the current rule except that ACHIEVED is
        # earned by predicting the counterparty, never by the judge's reading.
        lag_decision, lag_reason = now_decision, now_reason
        if now_decision == ACHIEVED:
            lag_decision, lag_reason = CONTINUE, "Go not yet earned by prediction"
        # A streak only counts if it spans both modes. Predicting engagement
        # five times running says nothing about an aim that cannot also
        # anticipate withdrawal — the same trap the induction guessers fell
        # into, where every probe confirmed and none could have refuted.
        window = turns[-streak:] if streak else []
        spans_both = len({w['actual_mode'] for w in window}) == 2
        if streak >= go_streak and (spans_both or not go_both_modes):
            lag_decision = ACHIEVED
            lag_reason = (f"predicted the counterparty {streak} times running, "
                          f"across both modes" if spans_both else
                          f"predicted the counterparty {streak} times running")
        elif streak >= go_streak:
            lag_reason = f"streak of {streak} but only one mode seen"

        node_now = apply_status(G_now, node_now, aim, now_decision, spent_on_aim) \
            if now_decision else node_now
        node_lag = apply_status(G_lag, node_lag, aim, lag_decision, spent_on_aim) \
            if lag_decision else node_lag

        turns[-1].update({
            "truth_status": t_status, "truth_detail": t_detail,
            "llm_status": verdict['aim_status'] if verdict else None,
            "llm_rating": (verdict or {}).get('rating'),
            "now_decision": now_decision, "now_reason": now_reason,
            "lag_decision": lag_decision, "lag_reason": lag_reason,
        })

        say(f"{len(turns):>2}. pred={predicted:<9} actual={actual_mode:<9} "
            f"{'ok ' if correct else 'X  '} streak={streak} | truth={t_status:<8} "
            f"now={str(now_decision):<8} lag={str(lag_decision):<8} | {hypothesis[:40]}")

        prev_predicate = predicate
        if lag_decision == ACHIEVED and now_decision == ACHIEVED:
            break

    final = turns[-1] if turns else {}
    stated_acc = score_stated_norm(final.get('hypothesis'), holdout, judge_model, judge_effort)
    pred_acc = (final.get('truth_detail') or {}).get('holdout_acc')
    genuinely_right = bool(pred_acc is not None and pred_acc >= 0.9)

    judged = [t for t in turns if t.get('now_decision')]
    now_gos = [t for t in judged if t['now_decision'] == ACHIEVED]
    lag_gos = [t for t in judged if t['lag_decision'] == ACHIEVED]

    def go_quality(gos):
        right = sum(1 for t in gos if t['truth_status'] == ACHIEVED)
        return len(gos), right, len(gos) - right

    now_n, now_ok, now_bad = go_quality(now_gos)
    lag_n, lag_ok, lag_bad = go_quality(lag_gos)

    result = {
        "norm": norm_name,
        "true_norm": N.describe(norm_name),
        "model": model, "effort": effort,
        "judge_model": judge_model, "judge_effort": judge_effort,
        "budget": budget, "messages": len(turns),
        "final_hypothesis": final.get('hypothesis'),
        "final_predicate": final.get('predicate'),
        "predicate_holdout_acc": pred_acc,
        "stated_norm_acc": stated_acc,
        "solved": genuinely_right,
        "prediction_acc": (round(sum(1 for t in turns if t['prediction_correct']) / len(turns), 3)
                           if turns else None),
        "best_streak": max((t['streak'] for t in turns), default=0),
        "go_both_modes": go_both_modes,
        "judge_turns": len(judged),
        "judge_agreement": (round(sum(1 for t in judged if t['now_decision'] == t['truth_status'])
                                  / len(judged), 3) if judged else None),
        "now_go": now_n, "now_go_right": now_ok, "now_go_wrong": now_bad,
        "lag_go": lag_n, "lag_go_right": lag_ok, "lag_go_wrong": lag_bad,
        "turns": turns,
        "graph_now": nx.node_link_data(G_now),
        "graph_lag": nx.node_link_data(G_lag),
    }
    say(f"done — predicate {pred_acc} stated {stated_acc} | "
        f"immediate Go {now_ok}/{now_n} right, lagged Go {lag_ok}/{lag_n} right")
    return result, G_now, G_lag
