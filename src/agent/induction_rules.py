"""Rule bank for GoalGraph's rule-induction run type.

An item is a triple of integers in [1, 100]. A rule is a pure predicate over
that triple. The keeper is code, not a model, so it never leaks, never hedges
and never gets its own rule wrong.
"""

import random

ITEM_MIN, ITEM_MAX = 1, 100


def _ascending(t):
    a, b, c = t
    return a < b < c


def _same_parity(t):
    return len({x % 2 for x in t}) == 1


def _c_eq_a_plus_b(t):
    a, b, c = t
    return c == a + b


def _spread_gt_20(t):
    return max(t) - min(t) > 20


def _middle_between(t):
    a, b, c = t
    return a < b < c or a > b > c


def _contains_repeat(t):
    return len(set(t)) < 3


def _sum_div_3(t):
    return sum(t) % 3 == 0


def _any_triple(t):
    return True


RULES = {
    # The classic Wason 2-4-6 trap. The seed example 2,4,6 invites "+2 each",
    # and only a negative test can kill that hypothesis.
    "ascending": (_ascending, "the three numbers are in strictly increasing order"),
    "same_parity": (_same_parity, "all three numbers have the same parity"),
    "c_eq_a_plus_b": (_c_eq_a_plus_b, "the third number is the sum of the first two"),
    "spread_gt_20": (_spread_gt_20, "the largest minus the smallest is more than 20"),
    "middle_between": (_middle_between, "the second number lies strictly between the first and the third"),
    "contains_repeat": (_contains_repeat, "at least two of the numbers are equal"),
    "sum_div_3": (_sum_div_3, "the sum of the three numbers is divisible by 3"),
    # Devious: everything is positive. Punishes any guesser that never runs a
    # negative test, because it will never see a "no".
    "any_triple": (_any_triple, "every triple satisfies the rule"),
}

DEFAULT_RULES = [
    "ascending",
    "same_parity",
    "c_eq_a_plus_b",
    "spread_gt_20",
    "middle_between",
]

# A positive triple shown to the guesser at the start of each game, so the game
# always opens the way Wason's does: with one confirming example.
SEED_EXAMPLES = {
    "ascending": (2, 4, 6),
    "same_parity": (2, 4, 6),
    "c_eq_a_plus_b": (2, 4, 6),
    "spread_gt_20": (2, 40, 6),
    "middle_between": (2, 4, 6),
    "contains_repeat": (2, 4, 4),
    "sum_div_3": (2, 4, 6),
    "any_triple": (2, 4, 6),
}


def label(rule_name, triple):
    fn, _ = RULES[rule_name]
    return bool(fn(tuple(triple)))


def describe(rule_name):
    return RULES[rule_name][1]


def _random_triple(rng):
    return tuple(rng.randint(ITEM_MIN, ITEM_MAX) for _ in range(3))


def holdout_set(rule_name, n=24, seed=0):
    """Balanced held-out items for behavioural scoring of the guesser's rule.

    Returns [(triple, bool)]. Sampling is rejection-based and seeded, so the
    same rule always yields the same held-out set across runs.

    Some rules are rare under uniform sampling (c == a + b), so positives are
    also drawn from a constructive sampler. If a rule admits no negatives
    (any_triple) the set is all-positive; a guesser with a too-narrow rule
    still scores badly, which is the behaviour we want.
    """
    rng = random.Random(seed ^ (hash(rule_name) & 0xFFFF))
    want = n // 2
    pos, neg = [], []
    constructive = _CONSTRUCTIVE.get(rule_name)

    for _ in range(200_000):
        if len(pos) >= want and len(neg) >= want:
            break
        if constructive and len(pos) < want and rng.random() < 0.5:
            t = constructive(rng)
        else:
            t = _random_triple(rng)
        if label(rule_name, t):
            if len(pos) < want and t not in pos:
                pos.append(t)
        else:
            if len(neg) < want and t not in neg:
                neg.append(t)

    items = [(t, True) for t in pos] + [(t, False) for t in neg]
    rng.shuffle(items)
    return items


def _c_sum(rng):
    a = rng.randint(1, 49)
    b = rng.randint(1, 100 - a)
    return (a, b, a + b)


def _c_asc(rng):
    xs = sorted(rng.sample(range(ITEM_MIN, ITEM_MAX + 1), 3))
    return tuple(xs)


def _c_parity(rng):
    p = rng.randint(0, 1)
    pool = [x for x in range(ITEM_MIN, ITEM_MAX + 1) if x % 2 == p]
    return tuple(rng.choice(pool) for _ in range(3))


def _c_mid(rng):
    xs = sorted(rng.sample(range(ITEM_MIN, ITEM_MAX + 1), 3))
    return tuple(xs) if rng.random() < 0.5 else tuple(reversed(xs))


def _c_repeat(rng):
    a = rng.randint(ITEM_MIN, ITEM_MAX)
    return (a, a, rng.randint(ITEM_MIN, ITEM_MAX))


_CONSTRUCTIVE = {
    "c_eq_a_plus_b": _c_sum,
    "ascending": _c_asc,
    "same_parity": _c_parity,
    "middle_between": _c_mid,
    "contains_repeat": _c_repeat,
}
