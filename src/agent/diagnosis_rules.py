"""A two-agent diagnosis game: a clinician narrows, a patient decides what to say.

This keeps the structure that made troubleshooting work - a hidden answer, moves
that shrink a candidate set, progress decided by counting rather than by
opinion - but both sides are agents with their own goal, so both build a graph
worth looking at, and the two graphs are not the same shape.

  the clinician  narrows nine conditions to one by asking about symptoms, then
                 commits to a diagnosis. Progress is elimination.
  the patient    wants to be diagnosed - so volunteering ordinary symptoms is in
                 their interest - but is guarded about two topics they would
                 rather not raise. Progress is being understood while those stay
                 unsaid; a guarded disclosure is a NoGo.

That tension is the game. Two of the conditions can only be separated by asking
about a guarded topic, so a clinician who is too polite to ask cannot finish,
and a patient who volunteers everything is diagnosed quickly but exposed. Both
of those are real outcomes and both are visible in the graphs.

Nothing here asks a model what happened. Which symptoms have been disclosed is
read from the transcript, and the candidate set follows from the table below.
"""
from . import claims

# --- what can be asked about ---------------------------------------------

SYMPTOMS = (
    'chest_pain', 'breathlessness', 'cough', 'fever', 'fatigue',
    'weight_loss', 'night_sweats', 'palpitations', 'swollen_ankles',
    'heartburn', 'alcohol_use', 'smoking',
)

# Topics a patient will not raise unprompted. They answer honestly when asked
# directly - the game is whether the clinician thinks to ask, not whether the
# patient lies.
GUARDED = frozenset({'alcohol_use', 'smoking'})

# --- the conditions -------------------------------------------------------
# Each condition lists the symptoms it presents with. Everything unlisted is
# absent, so a "no" is as informative as a "yes".

# Two design rules, both checked by tests below rather than assumed:
#
#   no symptom belongs to only one condition, so no single lucky question ends
#   the game - the clinician has to combine answers;
#
#   two pairs differ *only* by a guarded topic, so those conditions cannot be
#   separated without asking something the patient would rather not discuss.
#   That is the game: a clinician too polite to ask cannot finish.
#
#     alcoholic_hepatitis / coeliac_disease   differ only by alcohol_use
#     stable_angina       / muscular_strain   differ only by smoking

CONDITIONS = {
    'stable_angina':       {'chest_pain', 'breathlessness', 'fatigue', 'smoking'},
    'muscular_strain':     {'chest_pain', 'breathlessness', 'fatigue'},
    'pneumonia':           {'cough', 'fever', 'breathlessness', 'fatigue'},
    'asthma':              {'cough', 'breathlessness', 'palpitations'},
    'heart_failure':       {'breathlessness', 'swollen_ankles', 'fatigue',
                            'palpitations'},
    'anaemia':             {'fatigue', 'palpitations', 'breathlessness',
                            'weight_loss'},
    'reflux':              {'heartburn', 'chest_pain', 'cough'},
    'tuberculosis':        {'cough', 'fever', 'night_sweats', 'weight_loss',
                            'fatigue'},
    'alcoholic_hepatitis': {'fatigue', 'weight_loss', 'swollen_ankles',
                            'night_sweats', 'alcohol_use'},
    'coeliac_disease':     {'fatigue', 'weight_loss', 'swollen_ankles',
                            'night_sweats'},
    'copd':                {'cough', 'breathlessness', 'heartburn', 'smoking'},
}

CONDITION_TEXT = {
    'stable_angina': 'stable angina',
    'muscular_strain': 'a muscular chest strain',
    'pneumonia': 'pneumonia',
    'asthma': 'asthma',
    'heart_failure': 'heart failure',
    'anaemia': 'anaemia',
    'reflux': 'acid reflux',
    'tuberculosis': 'tuberculosis',
    'alcoholic_hepatitis': 'alcoholic hepatitis',
    'coeliac_disease': 'coeliac disease',
    'copd': 'COPD',
}

# How a patient describes each symptom when they choose to mention it. Kept here
# so the patient agent has concrete language and the scorer has strings to match.
SYMPTOM_TEXT = {
    'chest_pain': 'a tightness or pain in the chest',
    'breathlessness': 'getting out of breath easily',
    'cough': 'a cough that will not settle',
    'fever': 'running a temperature',
    'fatigue': 'being tired all the time',
    'weight_loss': 'losing weight without trying',
    'night_sweats': 'waking up drenched at night',
    'palpitations': 'the heart racing or thumping',
    'swollen_ankles': 'ankles swelling by the evening',
    'heartburn': 'burning behind the breastbone after eating',
    'alcohol_use': 'drinking well over the recommended limit',
    'smoking': 'smoking regularly',
}


# Words that count as raising a topic. Agents talk in English, not in symptom
# ids, so the scorer has to recognise "short of breath" as breathlessness. Kept
# deliberately narrow: a false match would credit the clinician with knowing
# something nobody said.
KEYWORDS = {
    'chest_pain': ['chest pain', 'chest tightness', 'tightness in the chest',
                   'pain in the chest', 'chest discomfort', 'chest_pain'],
    'breathlessness': ['breathless', 'short of breath', 'shortness of breath',
                       'out of breath', 'winded', 'breathing'],
    'cough': ['cough'],
    'fever': ['fever', 'temperature', 'febrile'],
    'fatigue': ['fatigue', 'tired', 'exhausted', 'no energy', 'worn out'],
    'weight_loss': ['weight loss', 'losing weight', 'lost weight', 'weight_loss'],
    'night_sweats': ['night sweat', 'sweating at night', 'drenched at night',
                     'night_sweats'],
    'palpitations': ['palpitation', 'heart racing', 'racing heart', 'thumping',
                     'heart pounding'],
    'swollen_ankles': ['ankle', 'oedema', 'edema', 'swollen_ankles'],
    'heartburn': ['heartburn', 'burning behind', 'acid', 'reflux', 'indigestion'],
    'alcohol_use': ['alcohol', 'drink', 'drinking', 'units a week', 'booze'],
    'smoking': ['smoke', 'smoking', 'cigarette', 'tobacco', 'vape'],
}


def mentions(text):
    """Which symptoms this message raises, by name or in plain English."""
    low = str(text or '').lower()
    return {s for s, words in KEYWORDS.items() if any(w in low for w in words)}


def disclosures_from(history, condition):
    """What the clinician has actually learned, as [(symptom, present)].

    A topic counts from the moment it is raised. The patient answers honestly,
    so the truth follows from the condition once the subject is on the table -
    and crediting the turn that *raised* it is what puts the progress on the
    graph of whoever asked the good question. Waiting for the reply instead
    credited the patient for the clinician's reasoning.

    This is what makes the guarded topics bite. The patient's brief tells them
    not to raise alcohol or smoking unprompted, so those enter the record only
    when the clinician thinks to ask - and two pairs of conditions cannot be
    separated any other way.
    """
    out, seen = [], set()
    for _speaker, message in history:
        for symptom in mentions(message):
            if symptom in seen:
                continue
            seen.add(symptom)
            out.append((symptom, has(condition, symptom)))
    return out


def diagnosis_claimed(text):
    """The condition a clinician has committed to, if any.

    The commitment test lives in claims.claimed_label; this supplies only the
    wording particular to this task. This one was the loosest of the three -
    it also accepted the bare phrase 'it is ' as evidence of a diagnosis.
    """
    return claims.claimed_label(
        text,
        {name: claims.aliases_for(name) + [str(pretty).lower()]
         for name, pretty in CONDITION_TEXT.items()})


def has(condition, symptom):
    return symptom in CONDITIONS[condition]


def candidates(disclosed):
    """Conditions consistent with everything disclosed so far.

    `disclosed` is [(symptom, present)]. This is the clinician's position: a
    set, which shrinks, and which two different lines of questioning can reach
    by different routes.
    """
    live = set(CONDITIONS)
    for symptom, present in disclosed:
        if symptom not in SYMPTOMS:
            continue
        live = {c for c in live if has(c, symptom) == bool(present)}
    return live


def narrowed(before, after):
    return len(after) < len(before)


def guarded_disclosed(disclosed):
    """Guarded topics the patient has ended up admitting to."""
    return {s for s, present in disclosed if s in GUARDED and present}


def optimal_questions(condition):
    """Fewest questions that isolate this condition, greedily. For scoring."""
    live, asked, steps = set(CONDITIONS), set(), 0
    while len(live) > 1:
        best, best_size = None, len(live)
        for s in SYMPTOMS:
            if s in asked:
                continue
            answer = has(condition, s)
            remaining = {c for c in live if has(c, s) == answer}
            if len(remaining) < best_size:
                best, best_size = s, len(remaining)
        if best is None:
            break
        asked.add(best)
        live = {c for c in live if has(c, best) == has(condition, best)}
        steps += 1
    return steps


def needs_guarded(condition):
    """Can this condition be isolated without asking about a guarded topic?"""
    live = set(CONDITIONS)
    for s in SYMPTOMS:
        if s in GUARDED:
            continue
        live = {c for c in live if has(c, s) == has(condition, s)}
    return len(live) > 1


def separable():
    """Every condition must be distinguishable, or the game is unfair."""
    seen, clashes = {}, []
    for name, symptoms in CONDITIONS.items():
        key = tuple(sorted(symptoms))
        if key in seen:
            clashes.append((seen[key], name))
        seen[key] = name
    return clashes


DEFAULT_CONDITIONS = list(CONDITIONS)


def describe(condition):
    guarded = ' (needs a guarded question)' if needs_guarded(condition) else ''
    return (f'{CONDITION_TEXT[condition]} - '
            f'{optimal_questions(condition)} questions if asked well{guarded}')


def clinician_brief():
    return (
        'A patient has come to you. Exactly one of these conditions is the '
        'answer:\n  '
        + '\n  '.join(f'{k} - {v}' for k, v in CONDITION_TEXT.items())
        + '\n\nWork out which, then say plainly that you are diagnosing it. '
          'Do not name a condition that is not on this list.\n\n'
        'You may ask about any of these:\n  '
        + '\n  '.join(f'{s} - {SYMPTOM_TEXT[s]}' for s in SYMPTOMS)
        + '\n\nAsk about one thing at a time, and choose the question that rules '
          'out the most, not the one that confirms what you already suspect. '
          'Some patients will not raise everything unprompted. When you are '
          'sure, write: I diagnose <condition>.')


def patient_brief(condition):
    present = sorted(CONDITIONS[condition])
    guarded = [s for s in present if s in GUARDED]
    open_ = [s for s in present if s not in GUARDED]
    lines = [
        'You are a patient seeing a clinician. You want to be diagnosed and '
        'helped, so answer honestly and do not invent symptoms.',
        '',
        'What is actually true of you:',
    ]
    lines += [f'  - {SYMPTOM_TEXT[s]}' for s in open_]
    if guarded:
        lines += [f'  - {SYMPTOM_TEXT[s]} (you would rather not bring this up)'
                  for s in guarded]
    lines += [
        '',
        'Anything not listed above is not true of you; say so if asked.',
        '',
        'You may mention the ordinary symptoms freely - it helps you get seen. '
        'The last items you would rather keep to yourself, and you will not '
        'raise them unprompted. If you are asked about one directly, answer '
        'honestly rather than lying.',
    ]
    return '\n'.join(lines)
