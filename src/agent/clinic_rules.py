"""A criteria-based diagnosis game with symptoms that must be inferred.

This is a puzzle, not a clinical instrument. It borrows the *shape* of
criteria-based diagnosis - a disorder needs so many features from a list, for
so long, with certain exclusions - because that shape makes a much better game
than "match this exact symptom set". No diagnostic text is reproduced from any
manual, the conditions are simplified past the point of clinical use, and
nothing here should be read as describing real illness.

What it adds over `diagnosis_rules`, and why:

  thresholds      a disorder needs N of M features, so a single answer rarely
                  settles anything and the clinician has to accumulate.
  distractors     several features appear in most disorders. Asking about one
                  is a proven dead end - it eliminates nothing - which is how
                  the graph gets branches that are wrong rather than merely
                  unexplored.
  guarded facts   some features the patient will not confirm if asked outright.
                  They can still be *established*, because each one has
                  ordinary correlates the patient will talk about happily.

That last one is the point. It puts two routes to the same knowledge in the
graph: the direct question, which is blocked, and a longer detour that works.
A decision graph is worth having exactly when there is more than one way to get
somewhere and they are not equally good.
"""

# --- features -------------------------------------------------------------

FEATURES = {
    # sleep and body
    'early_waking':      'waking at 4am and not getting back to sleep',
    'unrefreshing_sleep': 'sleeping a full night and waking exhausted',
    'appetite_loss':     'not feeling like eating',
    'weight_change':     'clothes fitting differently',
    'morning_nausea':    'feeling sick first thing, settling by midday',
    'tremor':            'hands unsteady in the morning',
    # mood and thought
    'low_mood':          'feeling flat most of the day',
    'anhedonia':         'nothing being enjoyable any more',
    'guilt':             'dwelling on things done wrong',
    'poor_concentration': 'losing the thread of things',
    'racing_thoughts':   'thoughts coming too fast to follow',
    'worry':             'worrying about everything, most days',
    # behaviour and function
    'social_withdrawal': 'turning down invitations',
    'missed_mornings':   'starting work late, or not at all',
    'irritability':      'snapping at people',
    'restlessness':      'not being able to sit still',
    'checking':          'going back to check things repeatedly',
    'avoidance':         'planning routes to avoid certain places',
    # guarded
    'heavy_drinking':    'drinking a great deal more than intended',
    'panic_in_public':   'attacks of panic in shops and on transport',
}

# Features the patient will not confirm on a direct question. They are not
# lying about them - they change the subject, and the clinician has to get
# there another way.
GUARDED = {
    'heavy_drinking': [
        {'morning_nausea', 'tremor', 'missed_mornings'},
        {'morning_nausea', 'unrefreshing_sleep', 'missed_mornings'},
    ],
    'panic_in_public': [
        {'avoidance', 'restlessness', 'worry'},
    ],
}

# Present in most disorders, so asking about one narrows nothing. A clinician
# who leads with these burns turns and the graph records it.
DISTRACTORS = frozenset({'poor_concentration', 'irritability', 'worry'})


# --- disorders ------------------------------------------------------------
# required: every one must be present.
# any_of:   at least `n` of the listed features.
# excludes: if present, this disorder is ruled out.

DISORDERS = {
    'depressive_episode': {
        'required': {'low_mood', 'anhedonia'},
        'any_of': ({'early_waking', 'appetite_loss', 'guilt',
                    'poor_concentration', 'social_withdrawal'}, 3),
        'excludes': {'heavy_drinking', 'racing_thoughts'},
        'weeks': 2,
    },
    'alcohol_related_low_mood': {
        'required': {'low_mood', 'heavy_drinking'},
        'any_of': ({'morning_nausea', 'tremor', 'missed_mornings',
                    'unrefreshing_sleep'}, 2),
        'excludes': set(),
        'weeks': 4,
    },
    # The decoy that makes the guarded feature matter. It shares low mood and
    # tremor with the drinking case, so those cannot separate them; what
    # separates them is morning nausea and missed mornings - which are also
    # exactly the correlates that establish the drinking. The indirect route is
    # therefore not a shortcut, it is the only route.
    'thyroid_disturbance': {
        'required': {'low_mood', 'tremor'},
        'any_of': ({'weight_change', 'unrefreshing_sleep', 'restlessness',
                    'poor_concentration'}, 2),
        'excludes': {'heavy_drinking', 'morning_nausea', 'missed_mornings'},
        'weeks': 8,
    },
    'generalised_anxiety': {
        'required': {'worry', 'restlessness'},
        'any_of': ({'poor_concentration', 'irritability',
                    'unrefreshing_sleep'}, 2),
        # checking excludes this one: the two otherwise overlap completely, and
        # a game where two answers are both correct has no answer.
        'excludes': {'panic_in_public', 'low_mood', 'checking'},
        'weeks': 24,
    },
    'panic_with_avoidance': {
        'required': {'panic_in_public', 'avoidance'},
        'any_of': ({'restlessness', 'worry', 'social_withdrawal'}, 2),
        'excludes': set(),
        'weeks': 4,
    },
    'obsessive_checking': {
        'required': {'checking', 'restlessness'},
        'any_of': ({'worry', 'poor_concentration', 'irritability'}, 2),
        'excludes': {'low_mood'},
        'weeks': 8,
    },
    'burnout_exhaustion': {
        'required': {'unrefreshing_sleep', 'social_withdrawal'},
        'any_of': ({'irritability', 'poor_concentration', 'anhedonia',
                    'missed_mornings'}, 3),
        'excludes': {'heavy_drinking', 'panic_in_public'},
        'weeks': 12,
    },
}

DISORDER_TEXT = {
    'depressive_episode': 'a depressive episode',
    'alcohol_related_low_mood': 'low mood related to drinking',
    'generalised_anxiety': 'generalised anxiety',
    'panic_with_avoidance': 'panic with avoidance',
    'obsessive_checking': 'obsessive checking',
    'burnout_exhaustion': 'burnout exhaustion',
    'thyroid_disturbance': 'a thyroid disturbance',
}


# --- the patient's record -------------------------------------------------
# Which features are actually true of a patient with a given disorder. Built
# from the criteria so a case always satisfies its own definition.

CASES = {
    'depressive_episode': {
        'low_mood', 'anhedonia', 'early_waking', 'appetite_loss', 'guilt',
        'poor_concentration', 'social_withdrawal',
    },
    'alcohol_related_low_mood': {
        'low_mood', 'heavy_drinking', 'morning_nausea', 'tremor',
        'missed_mornings', 'unrefreshing_sleep', 'poor_concentration',
        'irritability',
    },
    'thyroid_disturbance': {
        'low_mood', 'tremor', 'weight_change', 'unrefreshing_sleep',
        'restlessness', 'poor_concentration',
    },
    'generalised_anxiety': {
        'worry', 'restlessness', 'poor_concentration', 'irritability',
        'unrefreshing_sleep',
    },
    'panic_with_avoidance': {
        'panic_in_public', 'avoidance', 'restlessness', 'worry',
        'social_withdrawal', 'poor_concentration',
    },
    'obsessive_checking': {
        'checking', 'restlessness', 'worry', 'poor_concentration',
        'irritability',
    },
    'burnout_exhaustion': {
        'unrefreshing_sleep', 'social_withdrawal', 'irritability',
        'poor_concentration', 'anhedonia', 'missed_mornings',
    },
}


# What counts as raising a topic. Agents talk in English, not feature ids.
KEYWORDS = {
    'early_waking': ['early wak', 'wake early', '4am', 'four in the morning',
                     'waking early', 'early_waking'],
    'unrefreshing_sleep': ['unrefresh', 'wake exhausted', 'sleep does not help',
                           'still tired after', 'unrefreshing_sleep'],
    'appetite_loss': ['appetite', 'not eating', 'off your food', 'appetite_loss'],
    'weight_change': ['weight', 'clothes fit', 'weight_change'],
    'morning_nausea': ['nausea', 'sick in the morning', 'queasy', 'morning_nausea'],
    'tremor': ['tremor', 'shak', 'unsteady hand', 'hands trembl'],
    'low_mood': ['low mood', 'mood', 'flat', 'depressed', 'low_mood'],
    'anhedonia': ['anhedonia', 'enjoy', 'pleasure', 'interest in things'],
    'guilt': ['guilt', 'blame yourself', 'dwelling on things'],
    'poor_concentration': ['concentrat', 'lose the thread', 'focus'],
    'racing_thoughts': ['racing thought', 'thoughts too fast', 'racing_thoughts'],
    'worry': ['worry', 'worrie', 'anxious about everything'],
    'social_withdrawal': ['withdraw', 'seeing people', 'invitation', 'social'],
    'missed_mornings': ['late for work', 'missed work', 'missing morning',
                        'missed_mornings', 'getting to work'],
    'irritability': ['irritab', 'snapping', 'short tempered', 'temper'],
    'restlessness': ['restless', 'sit still', 'on edge'],
    'checking': ['checking', 'check things', 'go back to check'],
    'avoidance': ['avoid', 'route around', 'stay away from'],
    'heavy_drinking': ['drink', 'alcohol', 'units', 'booze'],
    'panic_in_public': ['panic', 'panic attack'],
}


def mentions(text):
    """Which features this message raises."""
    low = str(text or '').lower()
    return {f for f, words in KEYWORDS.items() if any(w in low for w in words)}


def known_from(history, case):
    """What the clinician has actually been told, as {feature: bool}.

    A guarded feature is *not* recorded when asked about directly - the patient
    deflects, so the question buys nothing. That is what makes asking it a real
    dead end rather than a missing branch, and what forces the detour.
    """
    known = {}
    for _speaker, message in history:
        for feature in mentions(message):
            if feature in known:
                continue
            if feature in GUARDED and feature in CASES[case]:
                continue        # deflected; nothing learned
            known[feature] = feature in CASES[case]
    return known


def diagnosis_claimed(text):
    """The disorder a clinician has committed to, if any."""
    low = str(text or '').lower()
    if 'diagnos' not in low:
        return None
    for name, pretty in DISORDER_TEXT.items():
        if name in low or name.replace('_', ' ') in low or pretty.lower() in low:
            return name
    return None


def meets(disorder, present):
    """Does this set of features satisfy the disorder's criteria?"""
    d = DISORDERS[disorder]
    if not d['required'] <= present:
        return False
    pool, n = d['any_of']
    if len(pool & present) < n:
        return False
    if d['excludes'] & present:
        return False
    return True


def established(known):
    """Features the clinician can take as true, including inferred ones.

    `known` is {feature: bool} for everything answered so far. A guarded
    feature is never answered directly, but counts as established once all of
    its correlates have been confirmed - which is the whole point: there is a
    way round, it just costs more questions.
    """
    present = {f for f, v in known.items() if v}
    for guarded, routes in GUARDED.items():
        if guarded in present:
            continue
        if any(route <= present for route in routes):
            present = present | {guarded}
    return present


def candidates(known):
    """Disorders whose criteria could still be met by this patient.

    Judged against the criteria rather than against the stored case, which
    matters: comparing to the case made any feature unique to one disorder an
    instant giveaway, collapsing seven candidates to one on a single answer.
    Asking whether the criteria are still *satisfiable* narrows the way a
    clinician actually narrows - a bit at a time, and never on one symptom.
    """
    present = established(known)
    absent = {f for f, v in known.items() if not v}
    out = set()
    for name, d in DISORDERS.items():
        if d['required'] & absent:
            continue                       # something it requires is ruled out
        if d['excludes'] & present:
            continue                       # something that excludes it is present
        pool, n = d['any_of']
        if len(pool - absent) < n:
            continue                       # the threshold can no longer be reached
        out.add(name)
    return out


def answerable(feature, case):
    """Would the patient answer a direct question about this?"""
    return not (feature in GUARDED and feature in CASES[case])


def inferable_routes(feature):
    return GUARDED.get(feature, [])


def is_distractor(feature):
    return feature in DISTRACTORS


def separable():
    """Every case must satisfy its own disorder and no other."""
    problems = []
    for name, case in CASES.items():
        if not meets(name, case):
            problems.append((name, 'does not meet its own criteria'))
        others = [o for o in DISORDERS if o != name and meets(o, case)]
        if others:
            problems.append((name, f'also meets {others}'))
    return problems


DEFAULT_CASES = list(CASES)


def clinician_brief():
    return (
        'A patient has come to you. Exactly one of these fits them:\n  '
        + '\n  '.join(f'{k} - {v}' for k, v in DISORDER_TEXT.items())
        + '\n\nYou may ask about any of these:\n  '
        + '\n  '.join(f'{k} - {v}' for k, v in FEATURES.items())
        + '\n\nAsk about one thing per turn. Three of these features appear in '
          'nearly every case and will tell you almost nothing on their own. '
          'Some patients will not be drawn on a subject however directly you '
          'ask - if that happens, do not keep asking; work out what else would '
          'show it, and ask about that instead. When you are sure, write: '
          'I diagnose <name>.')


def patient_brief(case):
    present = sorted(CASES[case])
    guarded = [f for f in present if f in GUARDED]
    open_ = [f for f in present if f not in GUARDED]
    lines = [
        'You are a patient seeing a clinician. Something has been wrong for a '
        'while and you want help, but you find it hard to talk about yourself.',
        '',
        'This is what is true of you:',
    ]
    lines += [f'  - {FEATURES[f]}' for f in open_]
    if guarded:
        lines += [f'  - {FEATURES[f]}  <-- you are ashamed of this'
                  for f in guarded]
    lines += [
        '',
        'Anything not on that list is not true of you; say so plainly if asked.',
        '',
        'How you talk:',
        '  You answer the question you were asked and little else. You do not '
        'run through your symptoms unprompted - it would not occur to you that '
        'the rest is relevant until someone asks.',
        '  You never bring up the thing you are ashamed of, and if you are '
        'asked about it directly you change the subject or answer vaguely. You '
        'do not lie about anything else, so if the clinician asks about '
        'something related you answer that honestly.',
    ]
    return '\n'.join(lines)
