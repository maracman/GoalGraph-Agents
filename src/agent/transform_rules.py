"""A transformation task: get from one sentence to another, one step at a time.

Every game so far has been "guess the rule", which produces a star — a hub of
refuted hypotheses at depth one, with nothing to path through. This one has a
route. The agent must transform a starting sentence into a target sentence by
proposing one small edit at a time, and **every intermediate sentence must
satisfy a hidden invariant**. Illegal states are rejected and the agent stays
where it is.

That gives the decision graph something it has never had here:

  states are places        an intermediate sentence is somewhere you can be,
                           return to, and route through
  accepted edits are edges a transition that worked is reusable, so a Go edge
                           connects rather than terminates
  progress is measurable   distance to the target falls as the agent advances,
                           independently of any judge's opinion
  the invariant is hidden  so there is still a rule to induce, and a wrong
                           belief about it still produces refutations

Two constraints, and only one of them is secret:

  the step rule   public. A proposal may differ from the current sentence by at
                  most `max_edits` word changes, so the agent cannot jump.
  the invariant   hidden. A property every state must satisfy.
"""

import random
import re

from . import sentence_rules as SR

MAX_EDITS = 2


def words(text):
    """Words, plus terminal punctuation as its own token.

    Punctuation has to count as an edit: changing "." to "?" is a real move,
    and on several invariants it is *the* move that reveals the rule. Ignoring
    it made that proposal register as a zero-word change and get rejected as
    not being a move at all, so the agent could never learn from it.
    """
    tokens = SR._words(text)
    end = SR._s(text)[-1:] if SR._s(text) else ""
    if end in ".?!":
        tokens = tokens + [end]
    return tokens


def word_distance(a, b):
    """Levenshtein distance over words — how many edits separate two sentences."""
    x, y = words(a), words(b)
    if not x:
        return len(y)
    if not y:
        return len(x)
    prev = list(range(len(y) + 1))
    for i, xi in enumerate(x, 1):
        cur = [i]
        for j, yj in enumerate(y, 1):
            cur.append(min(prev[j] + 1,          # delete
                           cur[j - 1] + 1,       # insert
                           prev[j - 1] + (xi != yj)))  # substitute
        prev = cur
    return prev[-1]


def is_small_step(current, proposed, max_edits=MAX_EDITS):
    """Is this a legal-sized move, regardless of the hidden invariant?"""
    d = word_distance(current, proposed)
    return 0 < d <= max_edits


# The invariants are borrowed from the sentence rules, so a claim about one is
# checked by machinery that already exists and is already tested.
INVARIANTS = {
    "is_question": SR.RULES["is_question"][0],
    "even_word_count": SR.RULES["even_word_count"][0],
    "starts_with_the": SR.RULES["starts_with_the"][0],
    "contains_long_word": SR.RULES["contains_long_word"][0],
    "even_letter_count": SR.RULES["even_letter_count"][0],
    "last_word_longer_than_first": SR.RULES["last_word_longer_than_first"][0],
}

INVARIANT_TEXT = {k: SR.RULES[k][1] for k in INVARIANTS}


def holds(invariant, sentence):
    return bool(INVARIANTS[invariant](sentence))


def describe(invariant):
    return INVARIANT_TEXT[invariant]


# --- the state space ------------------------------------------------------
# States are built from slots rather than listed, so neighbours can be
# generated instead of searched for. Changing one slot is one word edit, so a
# move of at most `max_edits` slots is a legal step — and because many slots
# can change independently, most states have dozens of neighbours. A listed
# pool gave a corridor with one legal move at each point, which is a path but
# not a graph, and route reuse cannot be tested on a corridor.

SLOTS = {
    # Determiners chosen to avoid a/an agreement: "An visitor" reads as a
    # typo and costs the agent turns arguing with the grammar rather than
    # the rule.
    "det1": ["The", "That", "Each"],
    "subject": ["cat", "engineer", "student", "visitor"],
    "verb": ["watched", "repaired", "counted", "described"],
    "det2": ["the", "that", "three"],
    "object": ["gate", "folder", "parcels", "schedule"],
    "tail": ["", " again", " yesterday", " twice"],
    "punct": [".", "?"],
}
SLOT_ORDER = ["det1", "subject", "verb", "det2", "object", "tail", "punct"]


def render(state):
    """A slot assignment as a sentence."""
    return (f'{state["det1"]} {state["subject"]} {state["verb"]} '
            f'{state["det2"]} {state["object"]}{state["tail"]}{state["punct"]}')


def parse(sentence):
    """Best-effort recovery of the slots from a sentence, or None."""
    text = SR._s(sentence)
    punct = "?" if text.endswith("?") else "."
    body = text.rstrip("?.").strip()
    parts = body.split()
    if len(parts) < 5:
        return None
    tail = ""
    if len(parts) >= 6 and (" " + parts[-1].lower()) in SLOTS["tail"]:
        tail = " " + parts[-1].lower()
        parts = parts[:-1]
    if len(parts) != 5:
        return None
    state = {"det1": parts[0], "subject": parts[1].lower(), "verb": parts[2].lower(),
             "det2": parts[3].lower(), "object": parts[4].lower(),
             "tail": tail, "punct": punct}
    for k in SLOT_ORDER:
        if state[k] not in SLOTS[k]:
            return None
    return state


def slot_difference(a, b):
    """How many slots two states differ in."""
    return sum(1 for k in SLOT_ORDER if a[k] != b[k])


def neighbours(state, invariant, max_slots=MAX_EDITS, cap=400):
    """Every legal state within `max_slots` changes, as sentences.

    Capped: the full two-slot neighbourhood of this grammar runs to hundreds of
    states, and nothing needs all of them at once.
    """
    import itertools
    out = []
    for count in range(1, max_slots + 1):
        for keys in itertools.combinations(SLOT_ORDER, count):
            for values in itertools.product(*[SLOTS[k] for k in keys]):
                if all(state[k] == v for k, v in zip(keys, values)):
                    continue
                cand = dict(state)
                for k, v in zip(keys, values):
                    cand[k] = v
                text = render(cand)
                if holds(invariant, text):
                    out.append(text)
                    if len(out) >= cap:
                        return sorted(set(out))
    return sorted(set(out))


def legal_next_states(current, invariant, max_edits=MAX_EDITS):
    """Everywhere you could legally go from here — the routes a graph can cache."""
    state = parse(current)
    if state is None:
        return []
    return neighbours(state, invariant, max_edits)


def plan(start, target, invariant, max_slots=MAX_EDITS, tries=40):
    """A concrete legal route from start to target, or None.

    The slots are independent, so a route is built rather than searched for:
    change up to `max_slots` of the differing slots at a time and check the
    invariant still holds at each intermediate state. Only the *order* matters,
    so a handful of shuffles finds a route when one exists. Breadth-first search
    over this neighbourhood is exponential and was taking minutes.
    """
    a, b = parse(start), parse(target)
    if a is None or b is None:
        return None
    differing = [k for k in SLOT_ORDER if a[k] != b[k]]
    if not differing:
        return []
    rng = random.Random(len(differing) * 7 + len(invariant))
    for _ in range(tries):
        order = differing[:]
        rng.shuffle(order)
        state, route, ok = dict(a), [], True
        for i in range(0, len(order), max_slots):
            for k in order[i:i + max_slots]:
                state[k] = b[k]
            text = render(state)
            if not holds(invariant, text):
                ok = False
                break
            route.append(text)
        if ok and route and route[-1] == render(b):
            return route
    return None


def build_tasks():
    """One start/target pair per invariant, verified solvable and not trivial."""
    rng = random.Random(20260729)
    tasks = {}
    for inv in INVARIANTS:
        pool = []
        for _ in range(300):
            cand = {k: rng.choice(v) for k, v in SLOTS.items()}
            if holds(inv, render(cand)):
                pool.append(cand)
        if len(pool) < 2:
            continue
        best = None
        for _ in range(200):
            a, b = rng.choice(pool), rng.choice(pool)
            diff = slot_difference(a, b)
            if diff < 4:
                continue
            route = plan(render(a), render(b), inv)
            if route and len(route) >= 2 and (best is None or len(route) > best["steps"]):
                best = {"start": render(a), "target": render(b),
                        "slots_apart": diff, "steps": len(route),
                        "example_route": route}
        if best:
            tasks[inv] = best
    return tasks


TASKS = build_tasks()
DEFAULT_INVARIANTS = list(TASKS)
