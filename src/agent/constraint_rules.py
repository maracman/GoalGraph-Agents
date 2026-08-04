"""A constraint-accumulation task: satisfy every hidden rule at once.

The earlier tasks all failed to make the decision graph *necessary*. Guessing a
single rule produced a hub of dead ends with nothing to route through, and the
transformation task was solved just as easily with no memory at all — which is
a null result about the software, not a demonstration of it.

This task is built so that forgetting has a price you can measure.

The keeper holds several independent constraints at once and accepts a
candidate only if **all** of them hold. A rejection says only "no": it does not
say which constraint failed. So the agent has to accumulate evidence across
many attempts, and the number of things it must hold in mind grows with every
discovery.

Two properties make the graph matter here, and neither held before:

  more to remember than fits    with five active constraints the evidence for
                               the first is far out of a short window by the
                               time the fifth is found

  forgetting is measurable     re-proposing a candidate already rejected is a
                               repeat failure, countable without asking a judge

That second one is the point. `repeat_violations` is a direct measure of memory
failure, so an arm with no memory should visibly re-tread ground an arm with a
graph does not.
"""

import random
import re

from . import sentence_rules as SR

# Constraints are borrowed from the sentence rules, so a claim about any of
# them is checked by machinery that is already tested.
CONSTRAINTS = {
    "is_question": SR.RULES["is_question"][0],
    "even_word_count": SR.RULES["even_word_count"][0],
    "contains_colour": SR.RULES["contains_colour"][0],
    "contains_long_word": SR.RULES["contains_long_word"][0],
    "starts_with_the": SR.RULES["starts_with_the"][0],
    "mentions_time": SR.RULES["mentions_time"][0],
    "contains_number": SR.RULES["contains_number"][0],
    "has_repeated_word": SR.RULES["has_repeated_word"][0],
    "contains_comma": SR.RULES["contains_comma"][0],
}

CONSTRAINT_TEXT = {k: SR.RULES[k][1] for k in CONSTRAINTS}

# Named difficulty levels: how many constraints must hold at once. The count is
# the dial that decides whether a memory is needed - at two, anyone can hold it
# in their head; at five, a short window cannot.
LEVELS = {
    "two_constraints": ["is_question", "contains_colour"],
    "three_constraints": ["is_question", "contains_colour", "contains_long_word"],
    # starts_with_the is deliberately absent. Combined with is_question it
    # forces the tag-question form ("The X ..., did it not?"), so every valid
    # answer looks the same and "give me a different one" becomes impossible
    # rather than hard. contains_comma constrains punctuation instead, which is
    # orthogonal to sentence shape.
    "four_constraints": ["is_question", "contains_colour", "contains_long_word",
                         "mentions_time"],
    "five_constraints": ["is_question", "contains_colour", "contains_long_word",
                         "mentions_time", "contains_comma"],
}

DEFAULT_LEVELS = list(LEVELS)


def active(level):
    return LEVELS[level]


def describe(level):
    parts = [CONSTRAINT_TEXT[c] for c in LEVELS[level]]
    return f"{len(parts)} rules at once: " + "; ".join(parts)


def accepts(level, sentence):
    """A candidate is valid only if every active constraint holds."""
    return all(CONSTRAINTS[c](sentence) for c in LEVELS[level])


def violated(level, sentence):
    """Which constraints this candidate breaks. For scoring, never shown."""
    return [c for c in LEVELS[level] if not CONSTRAINTS[c](sentence)]


def satisfied_count(level, sentence):
    return len(LEVELS[level]) - len(violated(level, sentence))


def normalise(sentence):
    """For deciding whether two attempts are the same attempt."""
    return " ".join(re.findall(r"[a-z0-9']+", SR._s(sentence).lower()))


def overlap(a, b):
    """Word-set overlap between two candidates, 0 to 1."""
    x, y = set(normalise(a).split()), set(normalise(b).split())
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def is_novel(sentence, previous, threshold=0.6):
    """Is this a genuinely different answer, or the same one reworded?

    A stricter bar than `is_repeat`, because the two questions differ. Retrying
    a rejected candidate only wastes a turn if it is nearly identical. But an
    *accepted* candidate sharing two thirds of its words with one already
    accepted shows nothing new - the agent copied a template rather than
    working out why the template is accepted.
    """
    return all(overlap(sentence, old) < threshold for old in previous)


def is_repeat(sentence, previous):
    """Has this candidate already been tried?

    Exact repeats after normalisation, and near-repeats by word overlap - an
    agent that changes one word of a rejected candidate without addressing why
    it was rejected is re-treading the same ground.
    """
    target = normalise(sentence)
    if not target:
        return False
    words = set(target.split())
    for old in previous:
        prior = normalise(old)
        if prior == target:
            return True
        prior_words = set(prior.split())
        if not prior_words or not words:
            continue
        overlap = len(words & prior_words) / max(len(words | prior_words), 1)
        if overlap >= 0.85:
            return True
    return False


# A worked example per level, so a task is never impossible and the run can be
# scored against something known to exist.
EXAMPLES = {
    "two_constraints": "Is the yellow folder ready?",
    "three_constraints": "Is the yellow schedule finished?",
    "four_constraints": "Was the yellow schedule finished yesterday?",
    "five_constraints": "Was the yellow schedule finished yesterday, or not?",
}


def verify_examples():
    """Every level must have at least one valid answer, or it is not a task."""
    return {lvl: accepts(lvl, ex) for lvl, ex in EXAMPLES.items()}


def opening_example(level):
    """One accepted candidate, so the agent starts with a positive."""
    return EXAMPLES[level]


def holdout_labels(level, n=24, seed=0):
    """A balanced set of candidates for scoring a stated rule."""
    rng = random.Random(seed ^ (hash(level) & 0xFFFF))
    pos = [s for s in SR.SENTENCES if accepts(level, s)]
    neg = [s for s in SR.SENTENCES if not accepts(level, s)]
    # The corpus rarely satisfies four or five at once, so valid candidates are
    # composed rather than found.
    pos = pos + [EXAMPLES[level]]
    rng.shuffle(pos)
    rng.shuffle(neg)
    k = min(n // 2, len(pos), len(neg))
    items = [(s, True) for s in pos[:k]] + [(s, False) for s in neg[:k]]
    rng.shuffle(items)
    return items


PREDICATE_VOCAB = SR.PREDICATE_VOCAB
predicate_helpers = SR.predicate_helpers
