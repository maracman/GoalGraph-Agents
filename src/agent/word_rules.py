"""Hidden rules over single words, for the word-induction keeper.

Chosen deliberately to be *orthographic* — about the letters — while the words
themselves are ordinary nouns from mixed semantic fields. That combination is
what makes the game produce refutations: a model looking at ANIMAL, BOTTLE and
LETTER reaches for a meaning-based rule long before it counts letters, so it
states hypotheses that are wrong and gets contradicted. The triples game failed
to produce refutations because its correct rule was the first thing the model
guessed.

Every rule is a pure predicate over a lowercase word, so a claim about it is
decidable rather than a matter of opinion.
"""

import random
import re

VOWELS = "aeiou"


def _w(word):
    """Normalise anything word-shaped to bare lowercase letters.

    Coerces bytes and non-strings explicitly: a bytes value reaches .lower()
    happily and then fails on a string regex pattern, which surfaces far from
    the cause.
    """
    if word is None:
        return ""
    if isinstance(word, (bytes, bytearray)):
        word = word.decode("utf-8", "ignore")
    elif not isinstance(word, str):
        word = str(word)
    return re.sub(r"[^a-z]", "", word.lower())


def has_double_letter(word):
    w = _w(word)
    return any(a == b for a, b in zip(w, w[1:]))


def length_six(word):
    return len(_w(word)) == 6


def starts_and_ends_same(word):
    w = _w(word)
    return len(w) > 1 and w[0] == w[-1]


def contains_no_e(word):
    return "e" not in _w(word)


def three_or_more_vowels(word):
    return sum(1 for c in _w(word) if c in VOWELS) >= 3

def second_letter_vowel(word):
    w = _w(word)
    return len(w) > 1 and w[1] in VOWELS


def letters_ascending(word):
    w = _w(word)
    return len(w) > 1 and all(a <= b for a, b in zip(w, w[1:]))


def more_consonants_than_vowels(word):
    w = _w(word)
    v = sum(1 for c in w if c in VOWELS)
    return (len(w) - v) > v


RULES = {
    "has_double_letter": (has_double_letter, "the word contains a doubled letter"),
    "length_six": (length_six, "the word is exactly six letters long"),
    "starts_and_ends_same": (starts_and_ends_same, "the word starts and ends with the same letter"),
    "contains_no_e": (contains_no_e, "the word contains no letter E"),
    "three_or_more_vowels": (three_or_more_vowels, "the word has three or more vowels"),
    "second_letter_vowel": (second_letter_vowel, "the second letter of the word is a vowel"),
    "letters_ascending": (letters_ascending, "the word's letters are in alphabetical order"),
    "more_consonants_than_vowels": (more_consonants_than_vowels,
                                    "the word has more consonants than vowels"),
}

DEFAULT_RULES = [
    "has_double_letter",
    "second_letter_vowel",
    "contains_no_e",
    "length_six",
    "three_or_more_vowels",
]

# One accepted example to open with, chosen so it is also semantically
# unremarkable - an opening word that shared a topic with the rule would hand
# the game away.
SEED_EXAMPLES = {
    "has_double_letter": "bottle",
    "length_six": "garden",
    "starts_and_ends_same": "level",
    "contains_no_e": "curtain",
    "three_or_more_vowels": "animal",
    "second_letter_vowel": "camera",
    "letters_ascending": "almost",
    "more_consonants_than_vowels": "strand",
}

# A fixed vocabulary spanning the feature space, so scoring is possible and the
# keeper can answer about any word the agent proposes.
WORDS = [
    "bottle", "garden", "level", "curtain", "animal", "camera", "almost", "strand",
    "letter", "puzzle", "kettle", "yellow", "mirror", "summer", "rabbit", "ribbon",
    "candle", "flower", "silver", "marble", "planet", "forest", "castle", "window",
    "cat", "dog", "bird", "fish", "tree", "star", "moon", "rain",
    "orange", "purple", "banana", "guitar", "orbit", "ocean", "eagle", "opera",
    "rhythm", "crypt", "lymph", "myth", "glyph", "syntax", "crown", "brush",
    "aback", "abhor", "chintz", "bijoux", "effort", "accept", "arrow", "berry",
    "noon", "deed", "gag", "tot", "solos", "rotor", "kayak", "radar",
]


def satisfies(rule_name, word):
    fn, _ = RULES[rule_name]
    return bool(fn(word))


def describe(rule_name):
    return RULES[rule_name][1]


def holdout_labels(rule_name, n=24, seed=0):
    """A balanced (word, satisfies) set, so chance is 50%."""
    rng = random.Random(seed ^ (hash(rule_name) & 0xFFFF))
    pos = [w for w in WORDS if satisfies(rule_name, w)]
    neg = [w for w in WORDS if not satisfies(rule_name, w)]
    rng.shuffle(pos)
    rng.shuffle(neg)
    k = min(n // 2, len(pos), len(neg))
    items = [(w, True) for w in pos[:k]] + [(w, False) for w in neg[:k]]
    rng.shuffle(items)
    return items


def predicate_helpers(word):
    """The vocabulary a stated rule may use, bound to one word.

    Deliberately letter-level rather than string methods: the sandbox forbids
    attribute access, and naming the operations makes the hypothesis space the
    agent is reaching into explicit.
    """
    w = _w(word)
    return {
        "wl": lambda: len(w),
        "has": lambda s: str(s).lower() in w,
        "starts": lambda s: w.startswith(str(s).lower()),
        "ends": lambda s: w.endswith(str(s).lower()),
        "count": lambda s: w.count(str(s).lower()),
        "vowels": lambda: sum(1 for c in w if c in VOWELS),
        "consonants": lambda: sum(1 for c in w if c.isalpha() and c not in VOWELS),
        "doubles": lambda: any(a == b for a, b in zip(w, w[1:])),
        "ascending": lambda: len(w) > 1 and all(a <= b for a, b in zip(w, w[1:])),
        "letter": lambda i: w[int(i)] if 0 <= int(i) < len(w) else "",
        "is_vowel": lambda c: str(c).lower() in VOWELS,
        "len": len, "abs": abs, "min": min, "max": max, "any": any, "all": all,
    }


PREDICATE_VOCAB = """You may use only these, combined with and/or/not, comparisons and arithmetic:
  wl()              - how many letters the word has
  has("x")          - is "x" somewhere in the word
  starts("x") / ends("x")
  count("x")        - how many times "x" appears
  vowels() / consonants()   - how many of each
  doubles()         - does the word contain a doubled letter
  ascending()       - are the letters in alphabetical order
  letter(i)         - the letter at position i, counting from 0
  is_vowel("a")     - is that letter a vowel
Examples: 'doubles()', 'wl() == 6', 'is_vowel(letter(1))', 'not has("e")'"""
