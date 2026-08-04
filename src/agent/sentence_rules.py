"""Hidden rules over whole sentences.

The number and word games kept failing to produce refutations for the same
reason: the correct rule was the first thing the model guessed. A sentence has
many more candidate properties — length, punctuation, word lengths, repetition,
first letters, digits — so a plausible first hypothesis is usually the wrong
one, and the agent gets contradicted. That is the condition the decision graph
needs in order to accumulate anything.

Every rule is a pure predicate over a sentence string, so a claim about it is
decidable rather than a matter of opinion.
"""

import random
import re

VOWELS = "aeiou"
COLOURS = ("red", "blue", "green", "yellow", "black", "white", "orange",
           "purple", "grey", "gray", "brown", "pink")
TIME_WORDS = ("today", "tomorrow", "yesterday", "morning", "evening", "night",
              "week", "month", "year", "hour", "minute", "monday", "friday")
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten", "eleven", "twelve")


def _s(text):
    """Anything sentence-shaped, coerced to a plain string."""
    if text is None:
        return ""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "ignore")
    elif not isinstance(text, str):
        text = str(text)
    return text.strip()


def _words(text):
    return re.findall(r"[A-Za-z']+", _s(text).lower())


# --- the rules ------------------------------------------------------------

def even_word_count(t):
    return len(_words(t)) % 2 == 0


def exactly_seven_words(t):
    return len(_words(t)) == 7


def starts_with_vowel(t):
    w = _words(t)
    return bool(w) and w[0][0] in VOWELS


def contains_number(t):
    s = _s(t).lower()
    return any(c.isdigit() for c in s) or any(n in _words(t) for n in NUMBER_WORDS)


def last_word_longer_than_first(t):
    w = _words(t)
    return len(w) > 1 and len(w[-1]) > len(w[0])


def has_repeated_word(t):
    w = _words(t)
    return len(w) != len(set(w))


def contains_comma(t):
    return "," in _s(t)


def is_question(t):
    return _s(t).endswith("?")


def no_word_over_five_letters(t):
    w = _words(t)
    return bool(w) and all(len(x) <= 5 for x in w)


def contains_long_word(t):
    return any(len(x) >= 8 for x in _words(t))


def alliteration(t):
    w = _words(t)
    return any(a[0] == b[0] for a, b in zip(w, w[1:]))


def first_and_last_word_share_letter(t):
    w = _words(t)
    return len(w) > 1 and w[0][0] == w[-1][0]


def contains_colour(t):
    return any(c in _words(t) for c in COLOURS)


def mentions_time(t):
    return any(c in _words(t) for c in TIME_WORDS)


def even_letter_count(t):
    return sum(1 for c in _s(t) if c.isalpha()) % 2 == 0


def all_word_lengths_differ(t):
    w = _words(t)
    return len(w) > 1 and len({len(x) for x in w}) == len(w)


def more_vowels_than_half(t):
    letters = [c for c in _s(t).lower() if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c in VOWELS) * 2 > len(letters)


def starts_with_the(t):
    w = _words(t)
    return bool(w) and w[0] == "the"


RULES = {
    "even_word_count": (even_word_count, "the sentence has an even number of words"),
    "exactly_seven_words": (exactly_seven_words, "the sentence has exactly seven words"),
    "starts_with_vowel": (starts_with_vowel, "the first word begins with a vowel"),
    "contains_number": (contains_number, "the sentence mentions a number"),
    "last_word_longer_than_first": (last_word_longer_than_first,
                                    "the last word is longer than the first word"),
    "has_repeated_word": (has_repeated_word, "some word appears more than once"),
    "contains_comma": (contains_comma, "the sentence contains a comma"),
    "is_question": (is_question, "the sentence is a question"),
    "no_word_over_five_letters": (no_word_over_five_letters,
                                  "no word in the sentence is longer than five letters"),
    "contains_long_word": (contains_long_word, "the sentence contains a word of eight or more letters"),
    "alliteration": (alliteration, "two neighbouring words start with the same letter"),
    "first_and_last_word_share_letter": (first_and_last_word_share_letter,
                                         "the first and last words begin with the same letter"),
    "contains_colour": (contains_colour, "the sentence mentions a colour"),
    "mentions_time": (mentions_time, "the sentence mentions a time or a day"),
    "even_letter_count": (even_letter_count, "the sentence has an even number of letters"),
    "all_word_lengths_differ": (all_word_lengths_differ, "no two words have the same length"),
    "starts_with_the": (starts_with_the, 'the sentence begins with the word "the"'),
}

# Ordered hardest-first: these are the ones a model does not guess on sight,
# which is what makes a run produce refutations at all.
DEFAULT_RULES = [
    "even_letter_count",
    "all_word_lengths_differ",
    "first_and_last_word_share_letter",
    "even_word_count",
    "alliteration",
]


def _build_corpus():
    """Sentences composed so every feature varies roughly independently."""
    rng = random.Random(20260729)
    subjects = ["the cat", "an engineer", "our neighbour", "the kettle",
                "every visitor", "a quiet student", "the orange lamp", "eleven birds"]
    verbs = ["watched", "repaired", "questioned", "ignored", "counted", "described"]
    objects = ["the broken gate", "a yellow folder", "three parcels",
               "the morning schedule", "an unusual pattern", "everything",
               "the silver kettle", "seven letters"]
    tails = ["", " again", " yesterday", " without complaint", ", apparently",
             " twice", " on Monday", " carefully"]
    out, seen = [], set()
    combos = [(s, v, o, t) for s in subjects for v in verbs for o in objects for t in tails]
    rng.shuffle(combos)
    for s, v, o, t in combos[:180]:
        body = f"{s} {v} {o}{t}"
        text = body[0].upper() + body[1:]
        text += "?" if rng.random() < 0.3 else "."
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


# Hand-written additions covering features the generator cannot reach: short
# words only, alliteration, and vowel-heavy text. Without these the
# corresponding rules have no positives and so cannot be scored at all.
_EXTRA = [
    "The big dog sat on my bed.",
    "She saw ten cats and a fox.",
    "We must not lose our last key?",
    "He put his hat on the desk.",
    "Ask them why they went away.",
    "Sally sold seven silver shells.",
    "Brian brought bright blue boxes.",
    "Cold clouds crossed the county.",
    "Peter packed plenty of parcels?",
    "Many merry members met Monday.",
    "Aoife area idea?",
    "Ohio audio Iowa.",
    "Eau aioli oui.",
    "A queue idea, aye?",
    "Tiny toy top.",
    "Our aim is a idea?",
]

SENTENCES = _build_corpus() + [s for s in _EXTRA]

SEED_EXAMPLES = {}
for _name in RULES:
    _hit = next((s for s in SENTENCES if RULES[_name][0](s)), None)
    SEED_EXAMPLES[_name] = _hit or SENTENCES[0]


def satisfies(rule_name, sentence):
    fn, _ = RULES[rule_name]
    return bool(fn(sentence))


def describe(rule_name):
    return RULES[rule_name][1]


def holdout_labels(rule_name, n=24, seed=0):
    """A balanced (sentence, satisfies) set, so chance is 50%."""
    rng = random.Random(seed ^ (hash(rule_name) & 0xFFFF))
    pos = [s for s in SENTENCES if satisfies(rule_name, s)]
    neg = [s for s in SENTENCES if not satisfies(rule_name, s)]
    rng.shuffle(pos)
    rng.shuffle(neg)
    k = min(n // 2, len(pos), len(neg))
    items = [(s, True) for s in pos[:k]] + [(s, False) for s in neg[:k]]
    rng.shuffle(items)
    return items


def predicate_helpers(sentence):
    """The vocabulary a stated rule may use, bound to one sentence."""
    s = _s(sentence)
    w = _words(s)
    letters = [c for c in s.lower() if c.isalpha()]
    return {
        "wc": lambda: len(w),
        "letters": lambda: len(letters),
        "word": lambda i: w[int(i)] if 0 <= int(i) < len(w) else "",
        "wlen": lambda i: len(w[int(i)]) if 0 <= int(i) < len(w) else 0,
        "longest": lambda: max((len(x) for x in w), default=0),
        "shortest": lambda: min((len(x) for x in w), default=0),
        "has": lambda x: str(x).lower() in s.lower(),
        "has_char": lambda x: str(x) in s,
        "has_digit": lambda: any(c.isdigit() for c in s),
        "is_question": lambda: s.endswith("?"),
        "vowels": lambda: sum(1 for c in letters if c in VOWELS),
        "repeated_word": lambda: len(w) != len(set(w)),
        "alliterates": lambda: any(a[0] == b[0] for a, b in zip(w, w[1:])),
        "distinct_lengths": lambda: len({len(x) for x in w}),
        "first_letter": lambda i: (w[int(i)][0] if 0 <= int(i) < len(w) else ""),
        "len": len, "abs": abs, "min": min, "max": max,
        "any": any, "all": all, "sum": sum, "set": set, "sorted": sorted,
    }


PREDICATE_VOCAB = """You may use only these, combined with and/or/not, comparisons and arithmetic:
  wc()                - how many words
  letters()           - how many letters in total
  word(i) / wlen(i)   - the i-th word, and its length, counting from 0
  longest() / shortest()      - longest and shortest word length
  has("x")            - is "x" anywhere in the sentence
  has_char(",")       - is that character present
  has_digit()         - does it contain a digit
  is_question()       - does it end in a question mark
  vowels()            - how many vowels
  repeated_word()     - does any word appear twice
  alliterates()       - do two neighbouring words share a first letter
  distinct_lengths()  - how many different word lengths there are
  first_letter(i)     - first letter of the i-th word
Examples: 'letters() % 2 == 0', 'wc() == 7', 'first_letter(0) == first_letter(wc()-1)'"""
