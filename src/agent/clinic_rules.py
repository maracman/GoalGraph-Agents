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
from . import claims

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


# --- what the patient comes in saying -------------------------------------
# The complaint is never a criterion. It is a *consequence* of one or two of
# them, so the clinician starts outside the diagnostic vocabulary entirely and
# has to work backwards to what would produce it. Opening with "I feel low"
# hands over a criterion for free; opening with "I got a written warning"
# does not.

PRESENTATIONS = {
    'alcohol_related_low_mood': {
        'complaint': 'I got a written warning at work last week.',
        'caused_by': {'missed_mornings', 'poor_concentration'},
    },
    'depressive_episode': {
        'complaint': 'My sister made me come. She says I have stopped '
                     'answering my phone.',
        'caused_by': {'social_withdrawal', 'anhedonia'},
    },
    'thyroid_disturbance': {
        'complaint': 'I had to have my wedding ring cut off.',
        'caused_by': {'weight_change', 'tremor'},
    },
    'burnout_exhaustion': {
        'complaint': 'I fell asleep on the train and went four stops past my '
                     'stop. Second time this month.',
        'caused_by': {'unrefreshing_sleep', 'poor_concentration'},
    },
    'generalised_anxiety': {
        'complaint': 'My dentist says I am grinding my teeth down to nothing.',
        'caused_by': {'worry', 'restlessness'},
    },
    'panic_with_avoidance': {
        'complaint': 'I have started paying for taxis I cannot afford.',
        'caused_by': {'avoidance', 'restlessness'},
    },
    'obsessive_checking': {
        'complaint': 'I am late for everything now. My partner has stopped '
                     'waiting for me.',
        'caused_by': {'checking', 'restlessness'},
    },
}

# --- the red herring ------------------------------------------------------
# A feature the patient genuinely has and will report, which is *not* part of
# their illness - it has an ordinary cause. It counts toward the criteria until
# the clinician asks what changed or when it started, at which point it stops
# counting and any reasoning that leaned on it has to be redone.
#
# This is the only mechanic here that can make a clinician wrong rather than
# merely slow, and it is what puts a genuinely mistaken branch in the graph.

SITUATIONAL = {
    'alcohol_related_low_mood': {
        'early_waking': 'there has been building work next door since March, '
                        'it starts at seven',
    },
    'burnout_exhaustion': {
        'appetite_loss': 'the canteen closed and there is nowhere to eat near '
                         'the new office',
    },
    'depressive_episode': {
        'restlessness': 'they gave up smoking eight weeks ago',
    },
    'thyroid_disturbance': {
        'social_withdrawal': 'their closest friend moved abroad in January',
    },
    'generalised_anxiety': {
        'missed_mornings': 'the only bus on their route was rerouted',
    },
}

# --- the second kind of red herring ---------------------------------------
# Features that are genuinely true of the patient and have no ordinary
# explanation to uncover - they simply do not cohere into anything. Each is
# real, each belongs to some disorder's criteria, and no combination of them
# completes a cluster, because the rest of that disorder's requirements are
# absent.
#
# This is a different trap from the situational one and needs to be, because
# they fail differently. A situational symptom is disproved by asking when it
# started. An incidental one is never disproved at all: the clinician has to
# notice that pursuing it cannot complete any diagnosis and drop it. That is
# the harder judgement, and the one that produces a branch the agent has to
# abandon on its own rather than because it was told.
#
# `separable()` checks that none of these accidentally completes a cluster.

INCIDENTAL = {
    'alcohol_related_low_mood': {'checking', 'avoidance'},
    'thyroid_disturbance': {'guilt', 'appetite_loss'},
    'burnout_exhaustion': {'worry', 'racing_thoughts'},
    'depressive_episode': {'checking'},
    'generalised_anxiety': {'guilt'},
    'panic_with_avoidance': {'early_waking'},
    'obsessive_checking': {'appetite_loss'},
}

# Phrasings that count as asking why something is happening, rather than
# whether it is. Discovering the situational cause requires this second kind of
# question, which is the part clinicians skip when they are pattern-matching.
CONTEXT_CUES = (
    'since when', 'how long', 'when did', 'what changed', 'anything change',
    'why do you think', 'what started', 'always been', 'before that',
    'is there a reason', 'what is different', 'around that time',
)


def asks_context(text):
    low = str(text or '').lower()
    return any(cue in low for cue in CONTEXT_CUES)


# What counts as raising a topic. Agents talk in English, not feature ids.
KEYWORDS = {
    'early_waking': ['early wak', 'wake early', '4am', 'four in the morning',
                     'waking early', 'early_waking'],
    'unrefreshing_sleep': ['unrefresh', 'wake exhausted', 'sleep does not help',
                           'still tired after', 'unrefreshing_sleep'],
    'appetite_loss': ['appetite', 'not eating', 'off your food', 'appetite_loss'],
    'weight_change': ['weight', 'clothes fit', 'weight_change'],
    'morning_nausea': ['nausea', 'sick in the morning', 'queasy', 'morning_nausea'],
    'tremor': ['tremor', 'shak', 'unsteady', 'hands trembl'],
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


def split_rule(rule_name):
    """`alcohol_related_low_mood#2` -> ('alcohol_related_low_mood', 2).

    A rule name can name a specific presentation of a disorder, so a long run
    can see many different patients with the same diagnosis without any of
    them looking alike.
    """
    text = str(rule_name or '')
    if '#' in text:
        base, k = text.split('#', 1)
        try:
            return base, int(k)
        except ValueError:
            return base, None
    return text, None


def base_case(rule_name):
    return split_rule(rule_name)[0]


def features_for(rule_name):
    """The features true of this particular patient."""
    base, k = split_rule(rule_name)
    if k is None:
        return set(CASES[base])
    v = variants(base)
    return set(v[k % len(v)])


def reported(case):
    """Everything the patient will say yes to - the illness plus its red herring.

    The situational feature has to be in here or it is not a trap at all: the
    patient would simply deny it, and a clinician could never be misled by
    something nobody mentioned.
    """
    base = base_case(case)
    return (features_for(case) | set(SITUATIONAL.get(base, {}))
            | INCIDENTAL.get(base, set()))


def read(history, case):
    """Everything the clinician has established, and how.

    Returns a dict with:
      known       {feature: bool} - answered one way or the other
      situational features reported present but revealed to have an ordinary
                  cause, so they no longer count toward any criteria
      inferred    guarded features established through their correlates
      confirmed   features that actually count: present, not situational

    `confirmed` is the score that matters. Each new entry is one criterion
    pinned down, and that is a progress point - which is what gives the graph
    a step per symptom rather than a step per candidate eliminated. Narrowing
    the field happens a handful of times in a run; establishing a criterion
    happens a dozen.
    """
    known, situational = {}, set()
    herrings = SITUATIONAL.get(base_case(case), {})
    for _speaker, message in history:
        raised = mentions(message)
        if asks_context(message):
            # a "why" question about anything already on the table exposes any
            # ordinary cause behind it
            for feature in (raised or set(known)) & set(herrings):
                situational.add(feature)
        for feature in raised:
            if feature in known:
                continue
            if feature in GUARDED and feature in features_for(case):
                continue                      # deflected; nothing learned
            known[feature] = feature in reported(case)

    present = {f for f, v in known.items() if v}
    inferred = set()
    for guarded, routes in GUARDED.items():
        if guarded not in present and any(r <= present for r in routes):
            inferred.add(guarded)

    established_now = (present | inferred) - situational
    # Only features some surviving diagnosis actually cares about count as
    # progress. Without this, confirming an incidental symptom scores exactly
    # like confirming a real criterion - the agent is rewarded for chasing
    # something that cannot complete any cluster, which is the opposite of
    # what the trap is for.
    live = _satisfiable(known, situational)
    relevant = set()
    for name in live:
        d = DISORDERS[name]
        relevant |= d['required'] | d['any_of'][0]
    confirmed = established_now & relevant
    return {'known': known, 'situational': situational, 'inferred': inferred,
            'confirmed': confirmed, 'established': established_now,
            'incidental': established_now - relevant, 'live': live}


def _satisfiable(known, situational=frozenset()):
    """Disorders whose criteria could still be met, discounting situational."""
    adjusted = dict(known)
    for f in situational:
        adjusted[f] = False
    return candidates(adjusted)


def confirmed_count(history, case):
    return len(read(history, case)['confirmed'])


def candidates_from(history, case):
    """Disorders still satisfiable, with situational features discounted."""
    r = read(history, case)
    known = dict(r['known'])
    for f in r['situational']:
        known[f] = False              # reported, but not part of the illness
    return candidates(known)


def presenting_complaint(case):
    return PRESENTATIONS[base_case(case)]['complaint']


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
            if feature in GUARDED and feature in features_for(case):
                continue        # deflected; nothing learned
            known[feature] = feature in CASES[case]
    return known


def diagnosis_claimed(text):
    """The disorder a clinician has committed to, if any.

    The commitment test lives in claims.claimed_label; this supplies only the
    wording particular to this task. Previously any message containing
    'diagnos' counted, and the disorder returned was the first in dict order
    that appeared anywhere in it rather than the one being committed to.
    """
    return claims.claimed_label(
        text,
        {name: claims.aliases_for(name) + [str(pretty).lower()]
         for name, pretty in DISORDER_TEXT.items()})


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


# --- a bank of patients ---------------------------------------------------
# Variants generated from the criteria rather than written by hand, so a long
# reuse run sees many different presentations of the same disorders. Each
# variant keeps enough features to satisfy its disorder and drops the rest,
# and carries its own red herrings - so two patients with the same diagnosis
# do not look alike, and a graph that memorised one will not fit the next.

def variants(case, seed=0):
    """Every distinct patient this disorder can present as, hardest first."""
    import itertools
    d = DISORDERS[case]
    pool, n = d['any_of']
    base = d['required']
    have = CASES[case] & pool
    out = []
    for k in range(n, len(have) + 1):
        for combo in itertools.combinations(sorted(have), k):
            feats = base | set(combo) | (CASES[case] - pool - base)
            if meets(case, feats) and diagnosable(case, feats):
                out.append(frozenset(feats))
    # fewest features first: those are the patients who give least away
    return sorted(set(out), key=lambda f: (len(f), sorted(f)))


def diagnosable(case, feats):
    """Could a clinician actually establish this patient's diagnosis?

    Satisfying the criteria on paper is not enough. Where a *required* feature
    is one the patient will not confirm, it can only be established through its
    correlates - so if this presentation happens to lack a complete correlate
    set, the required feature can never be shown and the case is unwinnable no
    matter how well the clinician reasons.

    Two of the twelve patients in the first long run were impossible for
    exactly this reason, and they read as the agent failing rather than as the
    case being unfair.
    """
    for guarded, routes in GUARDED.items():
        if guarded not in DISORDERS[case]['required']:
            continue
        if guarded not in feats:
            continue
        if not any(route <= feats for route in routes):
            return False
    return True


def case_bank(limit_per_case=3, seed=0):
    """A list of (case, features) patients across every disorder."""
    bank = []
    for case in CASES:
        for feats in variants(case, seed)[:limit_per_case]:
            bank.append((case, set(feats)))
    return bank


def bank_summary():
    out = []
    for case in CASES:
        v = variants(case)
        out.append(f'{case:<26} {len(v):>3} distinct presentations')
    return '\n'.join(out)


def progress_note_text(live_count):
    """Direction without state - see the note in ddx_rules.progress_note."""
    if live_count == 1:
        return ('One disorder now accounts for everything established. Say '
                'plainly that you are diagnosing it.')
    return ('Ask about whatever best separates the disorders you have not '
            'ruled out. If the patient will not be drawn on something, look '
            'for what would show it indirectly.')


def clinician_brief():
    return (
        'A patient has come to you. Exactly one of these fits them:\n  '
        + '\n  '.join(f'{k} - {v}' for k, v in DISORDER_TEXT.items())
        + '\n\nYou may ask about any of these:\n  '
        + '\n  '.join(f'{k} - {v}' for k, v in FEATURES.items())
        + '\n\nThe patient will open with what actually brought them in, which '
          'will be a consequence of their symptoms rather than a symptom - '
          'something that went wrong at work, or at home. Work backwards from '
          'it.\n\nAsk about one thing per turn. Three of these features appear '
          'in nearly every case and will tell you almost nothing on their own. '
          'And not everything a patient reports is part of what is wrong with '
          'them. Two kinds of thing will mislead you.\n'
          '  Some symptoms have an ordinary cause - a change at home, a new '
          'job, a noisy street. Those do not count toward any diagnosis, and '
          'the only way to find them is to ask when a symptom started and what '
          'changed around then.\n'
          '  Others are simply true and lead nowhere: real, but not part of '
          'any pattern that completes. If a line of questioning cannot finish '
          'a diagnosis no matter what the answers are, drop it and say so '
          'rather than collecting more of it. '
          'Some patients will not be drawn on a subject however directly you '
          'ask - if that happens, do not keep asking; work out what else would '
          'show it, and ask about that instead. When you are sure, write: '
          'I diagnose <name>.')


def patient_brief(case):
    present = sorted(reported(case))
    guarded = [f for f in present if f in GUARDED]
    open_ = [f for f in present if f not in GUARDED]
    lines = [
        'You are a patient seeing a clinician. Something has been wrong for a '
        'while and you want help, but you find it hard to talk about yourself.',
        '',
        'Open the conversation with exactly this, and nothing more:',
        f'  "{PRESENTATIONS[base_case(case)]["complaint"]}"',
        '',
        'That is what made you come. It is not a symptom - it is what your '
        'symptoms have caused. Do not explain it unless you are asked.',
        '',
        'This is what is true of you:',
    ]
    herrings = SITUATIONAL.get(base_case(case), {})
    for f in open_:
        if f in herrings:
            lines.append(f'  - {FEATURES[f]}  (this one is only because '
                         f'{herrings[f]} - it is not why you are here, but you '
                         f'will not volunteer that unless asked when it started '
                         f'or what changed)')
        else:
            lines.append(f'  - {FEATURES[f]}')
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
        '  If you are asked when something started or what changed around '
        'then, answer honestly - including when the honest answer is that it '
        'has an ordinary cause and nothing to do with why you are here.',
        '  You never bring up the thing you are ashamed of, and if you are '
        'asked about it directly you change the subject or answer vaguely. You '
        'do not lie about anything else, so if the clinician asks about '
        'something related you answer that honestly.',
    ]
    return '\n'.join(lines)
