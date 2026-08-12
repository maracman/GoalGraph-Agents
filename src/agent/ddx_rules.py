"""A clinic task whose content comes from DDXPlus rather than from us.

Same game as `clinic_rules` - an agent interviews a person, narrows a field of
conditions, and has to reach one fact indirectly because the person will not
say it outright. The difference is where the content comes from. Conditions,
symptoms, which facts are awkward and what they can be inferred *from* are all
read off a public corpus. See `ddx_import` for how each is derived.

Built lazily and cached: the corpus is tens of megabytes and most sessions
never touch this run type.
"""

import functools

from . import claims
from . import ddx_import as DX

TARGET = 'HIV (initial infection)'


@functools.lru_cache(maxsize=4)
def task(target=TARGET):
    return DX.build_task(target=target)


def attribution():
    return task()['attribution']


# --- the vocabulary -------------------------------------------------------

def questions():
    return task()['questions']


def feature_text(code):
    """The corpus's own wording, trimmed of the interrogative framing."""
    q = questions().get(code, code).strip()
    return q[:-1] if q.endswith('?') else q


def conditions():
    return list(task()['conditions'])


def condition_text(name):
    return name


def profile(name):
    return set(task()['profiles'][name])


GUARDED_CACHE = {}


def guarded():
    """Facts the person will not confirm outright, and how to get there anyway."""
    if not GUARDED_CACHE:
        for code, routes in task()['guarded'].items():
            GUARDED_CACHE[code] = [set(r) for r in routes]
    return GUARDED_CACHE


def distractors():
    return set(task()['distractors'])


# --- cases ----------------------------------------------------------------

def base_case(rule_name):
    return str(rule_name or '').split('#')[0]


def features_for(rule_name):
    return profile(base_case(rule_name))


def reported(rule_name):
    return features_for(rule_name)


# The corpus has no presenting-complaint field, so these are authored - the
# one place in this module where content is not derived. They deliberately name
# no symptom at all: a complaint is what the illness *cost* the person, and
# handing over a symptom in the first line would skip the part of the interview
# worth watching. Assigned by condition so a run is reproducible.
COMPLAINTS = (
    'My sister made me come. She says I have not been myself for months.',
    'I have taken four days off this month. My manager wants a letter.',
    'I got sent home from work on Tuesday and told not to come back until I '
    'had seen someone.',
    'My partner has started doing all the driving.',
    'I had to cancel a holiday we had been saving for.',
    'I stopped going to five-a-side. The lads keep asking why.',
    'I have been putting this off since Christmas, if I am honest.',
)


def presenting_complaint(rule_name):
    """What brought them in - a consequence, never a symptom."""
    name = base_case(rule_name)
    order = conditions()
    idx = order.index(name) if name in order else 0
    return COMPLAINTS[idx % len(COMPLAINTS)]


# --- reading the conversation ---------------------------------------------

def mentions(text):
    """Which features a message raises.

    Matched on content words from the corpus's own question text. The corpus
    phrases everything as a question, so the interesting words are the nouns
    left after the interrogative scaffolding is stripped.
    """
    low = str(text or '').lower()
    hit = set()
    for code, q in questions().items():
        words = [w for w in _content_words(q) if len(w) > 4]
        if not words:
            continue
        # Most content words must appear, not a third of them. A looser bar
        # credited the agent with three findings from one question, because
        # corpus questions share so much vocabulary.
        need = len(words) if len(words) <= 2 else max(2, (len(words) * 2) // 3)
        if sum(1 for w in words if w in low) >= need:
            hit.add(code)
    return hit


STOP = {'have', 'you', 'your', 'do', 'does', 'did', 'are', 'is', 'the', 'a',
        'an', 'in', 'on', 'of', 'or', 'and', 'to', 'with', 'that', 'this',
        'been', 'ever', 'any', 'more', 'than', 'last', 'past', 'currently',
        'recently', 'feel', 'felt', 'take', 'taking', 'had', 'has', 'been',
        'what', 'where', 'how', 'which', 'been', 'about', 'from', 'for'}


def _content_words(q):
    import re
    return [w for w in re.findall(r"[a-z']+", str(q).lower()) if w not in STOP]


def read(history, rule_name):
    """What the agent has established, and what it can infer."""
    case = base_case(rule_name)
    mine = profile(case)
    g = guarded()
    known = {}
    for _speaker, message in history:
        for code in mentions(message):
            if code in known:
                continue
            if code in g and code in mine:
                continue                 # deflected; nothing learned
            known[code] = code in mine

    present = {c for c, v in known.items() if v}
    inferred = {gc for gc, routes in g.items()
                if gc not in present and any(r <= present for r in routes)}
    established = present | inferred
    live = _live(known, established)
    relevant = set()
    for name in live:
        relevant |= profile(name)
    return {'known': known, 'inferred': inferred, 'established': established,
            'confirmed': established & relevant,
            'incidental': established - relevant, 'live': live}


def _live(known, established):
    """Conditions that could still explain everything established.

    A condition is out once something confirmed present is not in its profile:
    it would have no account of that finding. This is the crisp version of
    differential reasoning, and it is what makes the field shrink.
    """
    out = set()
    for name in conditions():
        p = profile(name)
        if established - p:
            continue
        out.add(name)
    return out or set(conditions())


def candidates_from(history, rule_name):
    return read(history, rule_name)['live']


def confirmed_count(history, rule_name):
    return len(read(history, rule_name)['confirmed'])


def diagnosis_claimed(text):
    """The condition the clinician has committed to, if any.

    Delegates the "is this a commitment" question to claims.claimed_label and
    supplies only this task's vocabulary. It used to accept any message
    containing 'diagnos' and return the first condition named anywhere in it,
    which scored "nothing here is diagnostic of HIV yet" as a diagnosis of HIV
    - and, because HIV sorts first here, scored it that way preferentially.
    """
    return claims.claimed_label(
        text, {name: claims.aliases_for(name) for name in conditions()})


# --- briefs ---------------------------------------------------------------

def progress_note(history, rule_name):
    """Direction for an evolved aim, carrying no state.

    This must not name what is still possible. The aim goes into the agent's
    system prompt every turn regardless of the context window, so enumerating
    the live candidate set here hands the whole accumulated investigation to
    both arms for free - which is exactly the state the graph is supposed to be
    tested on carrying. It made a two-message window as good as a thirty-two
    message one, and the sweep measured nothing.
    """
    live = candidates_from(history, rule_name)
    if len(live) == 1:
        return ('One condition now accounts for everything established. Name '
                'it as your diagnosis.')
    return ('Ask about whatever best separates the possibilities you have not '
            'ruled out. If the patient will not be drawn on something, work '
            'out what would show it indirectly.')


def clinician_brief():
    lines = ['A patient has come to you. Exactly one of these fits them:']
    lines += [f'  {c}' for c in conditions()]
    lines.append('')
    lines.append('You may ask about any of these:')
    for code in sorted(set().union(*[profile(c) for c in conditions()])):
        lines.append(f'  {feature_text(code)}')
    lines += [
        '',
        'The patient opens with what made them come, which is a consequence '
        'rather than a symptom. Work backwards from it.',
        'Ask about one thing per turn. Some of these appear in nearly every '
        'condition and will tell you almost nothing on their own.',
        'Some patients will not be drawn on a subject however directly you '
        'ask. If that happens, do not keep asking - work out what else would '
        'show it, and ask about that instead.',
        'When you are sure, write: I diagnose <condition>.',
    ]
    return '\n'.join(lines)


def patient_brief(rule_name):
    case = base_case(rule_name)
    mine = sorted(profile(case))
    g = guarded()
    open_ = [c for c in mine if c not in g]
    hidden = [c for c in mine if c in g]
    lines = [
        'You are a patient seeing a clinician. Something has been wrong for a '
        'while and you want help, but you find it hard to talk about yourself.',
        '',
        'Open with exactly this, and nothing more:',
        f'  "{presenting_complaint(rule_name)}"',
        '',
        'This is what is true of you:',
    ]
    lines += [f'  - {feature_text(c)}' for c in open_]
    if hidden:
        lines.append('')
        lines.append('And these, which you are ashamed of and will not raise:')
        lines += [f'  - {feature_text(c)}' for c in hidden]
    lines += [
        '',
        'Anything not listed is not true of you; say so plainly if asked.',
        '',
        'How you talk:',
        '  You answer the question you were asked and little else. You do not '
        'run through your symptoms unprompted.',
        '  You never raise the things you are ashamed of. Asked about one '
        'directly, you change the subject or answer vaguely - but you answer '
        'everything else honestly, including things that happen to be related.',
    ]
    return '\n'.join(lines)


def default_case():
    return conditions()[0]
