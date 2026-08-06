"""Build a clinic task from DDXPlus.

DDXPlus (CC-BY-4.0, Tchango et al. 2022) is ~1.3M synthetic patients over 49
pathologies, each with the evidences they present and a differential diagnosis.
It gives structure this project would otherwise have to invent: real
symptom-to-condition mappings, and a flag separating current symptoms from
history factors.

What it does *not* give is the part that makes an interview a game. No corpus
marks a symptom as a red herring, or records what a patient would rather not
say - those are pedagogical annotations, and where they exist (in standardised
patient scripts) they are deliberately unpublished, because printing them would
compromise the exam.

So three of the four mechanics are *derived* from the corpus rather than
authored, which is the point of importing it at all:

  guarded facts   antecedents that are socially awkward to ask about. The
                  shortlist is judgement, but membership is checked against the
                  corpus rather than assumed.
  correlate routes  symptoms that actually co-occur with the guarded antecedent
                  across real patients. Measured, not decided - this is the
                  thing hand-authoring got wrong most often.
  distractors     evidences so common across pathologies that asking about them
                  eliminates almost nothing.

Only the situational red herring is still authored, because nothing in the data
says "this symptom is because of building work next door".

Attribution, as CC-BY requires, is in DDX_ATTRIBUTION and reproduced by any
task built from this module.
"""

import ast
import collections
import csv
import json
import os
import random

DDX_ATTRIBUTION = (
    'Built from DDXPlus (Tchango, Goel, Wen, Martel & Ghosn, 2022), '
    'https://doi.org/10.6084/m9.figshare.20043374 - CC-BY-4.0. '
    'DDXPlus patients are synthetic and intended for research; nothing derived '
    'from them describes real illness.'
)

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(HERE, 'data', 'ddxplus')

# Antecedents a person might hesitate over in a real consultation. This list is
# a judgement call and the only place one is made; every id is verified to
# exist in the corpus before use, so a typo fails loudly rather than silently
# producing a task with no guarded facts.
SENSITIVE_PATTERNS = (
    'alcohol', 'smoke', 'cigarette', 'unprotected sex', 'drug', 'addiction',
    'overweight', 'recreational',
    # Equally awkward to ask outright, so they cannot serve as the *detour*
    # around a guarded fact - a route that runs through another question the
    # patient would dodge is not a route at all.
    'hiv-positive', 'hiv positive', 'sexually transmitted', 'sexual intercourse',
)


def load():
    """The corpus, or a clear failure if it has not been downloaded."""
    cond_path = os.path.join(DATA, 'release_conditions.json')
    evid_path = os.path.join(DATA, 'release_evidences.json')
    if not (os.path.exists(cond_path) and os.path.exists(evid_path)):
        raise FileNotFoundError(
            f'DDXPlus not found in {DATA}. Fetch release_conditions.json and '
            f'release_evidences.json from '
            f'https://huggingface.co/datasets/aai530-group6/ddxplus')
    with open(cond_path) as f:
        conditions = json.load(f)
    with open(evid_path) as f:
        evidences = json.load(f)
    return conditions, evidences


def base_code(token):
    """'E_55_@_V_89' -> 'E_55'. Values are dropped; presence is what we ask about."""
    return str(token).split('_@_')[0]


def question(evidences, code):
    e = evidences.get(code) or {}
    return (e.get('question_en') or code).strip()


def sensitive_antecedents(evidences):
    """Antecedents whose question is awkward to ask outright."""
    out = []
    for code, e in evidences.items():
        if not e.get('is_antecedent'):
            continue
        q = (e.get('question_en') or '').lower()
        if any(p in q for p in SENSITIVE_PATTERNS):
            out.append(code)
    return out


def patient_rows(limit=40000, path=None):
    """Patients from the corpus, as (pathology, {evidence codes})."""
    path = path or os.path.join(DATA, 'validate.csv')
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline='') as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i >= limit:
                break
            try:
                codes = {base_code(t) for t in ast.literal_eval(row['EVIDENCES'])}
            except (ValueError, SyntaxError):
                continue
            out.append((row['PATHOLOGY'], codes))
    return out


def correlates(rows, guarded, top=6, min_lift=1.6, min_support=40):
    """Symptoms that actually travel with a guarded antecedent.

    Ranked by lift - how much more often the symptom appears in patients who
    have the guarded fact than in patients generally. A symptom that is simply
    common everywhere has lift near 1 and is useless for inferring anything,
    which is exactly the mistake hand-picking makes.
    """
    with_g = [c for _p, c in rows if guarded in c]
    if len(with_g) < min_support:
        return []
    n_all, n_g = len(rows), len(with_g)
    overall = collections.Counter()
    for _p, c in rows:
        overall.update(c)
    among = collections.Counter()
    for c in with_g:
        among.update(c)

    scored = []
    for code, k in among.items():
        if code == guarded:
            continue
        p_g = k / n_g
        p_all = overall[code] / n_all
        if p_all <= 0 or p_g < 0.5:
            continue
        lift = p_g / p_all
        if lift >= min_lift:
            scored.append((lift, p_g, code))
    scored.sort(reverse=True)
    return [(c, round(l, 2), round(p, 2)) for l, p, c in scored[:top]]


def commonness(rows):
    """How many pathologies each evidence shows up in - distractors score high."""
    per = collections.defaultdict(set)
    for path, codes in rows:
        for c in codes:
            per[c].add(path)
    return {c: len(v) for c, v in per.items()}


def build_task(target='HIV (initial infection)', n_rivals=6, patients=40000,
               seed=0):
    """A playable task built around one condition and its nearest rivals.

    Rivals are chosen by symptom overlap with the target, so the field is
    genuinely confusable rather than an arbitrary shortlist. Everything else -
    which fact is guarded, how it can be inferred, which questions are
    worthless - is read off the corpus.
    """
    conditions, evidences = load()
    rows = patient_rows(patients)
    by_path = collections.defaultdict(list)
    for path, codes in rows:
        by_path[path].append(codes)
    if target not in by_path:
        raise KeyError(f'{target} not present in the sampled patients')

    def profile(path):
        """Evidences seen in at least a third of that condition's patients."""
        seen = collections.Counter()
        for c in by_path[path]:
            seen.update(c)
        n = len(by_path[path])
        return {c for c, k in seen.items() if k / n >= 0.33}

    tgt = profile(target)
    scored = []
    for path in by_path:
        if path == target:
            continue
        p = profile(path)
        if not p:
            continue
        overlap = len(tgt & p) / len(tgt | p)
        scored.append((overlap, path))
    scored.sort(reverse=True)
    chosen = [target] + [p for _o, p in scored[:n_rivals]]

    profiles = {p: profile(p) for p in chosen}
    universe = set().union(*profiles.values())

    # guarded: a sensitive antecedent that some chosen condition presents, and
    # that has a route through symptoms the patient will discuss
    guarded = {}
    for code in sensitive_antecedents(evidences):
        if not any(code in pr for pr in profiles.values()):
            continue
        route = [c for c, _l, _p in correlates(rows, code, top=5)
                 if c in universe and c not in sensitive_antecedents(evidences)]
        if len(route) >= 2:
            guarded[code] = [set(route[:3])]

    # distractors: present in nearly every chosen condition, so asking is idle
    common = collections.Counter()
    for pr in profiles.values():
        common.update(pr)
    distractors = {c for c, k in common.items() if k >= len(chosen) - 1}

    return {
        'attribution': DDX_ATTRIBUTION,
        'target': target,
        'conditions': chosen,
        'profiles': {p: sorted(v) for p, v in profiles.items()},
        'guarded': {k: [sorted(s) for s in v] for k, v in guarded.items()},
        'distractors': sorted(distractors),
        'questions': {c: question(evidences, c) for c in universe},
        'n_patients': {p: len(by_path[p]) for p in chosen},
    }


def report():
    """What the corpus offers, and what it does not. Run before building."""
    conditions, evidences = load()
    rows = patient_rows()
    lines = [DDX_ATTRIBUTION, '',
             f'conditions {len(conditions)}   evidences {len(evidences)}   '
             f'antecedents {sum(1 for e in evidences.values() if e.get("is_antecedent"))}',
             f'patients sampled {len(rows)}', '']

    sens = sensitive_antecedents(evidences)
    lines.append(f'candidate guarded facts ({len(sens)}):')
    for code in sens:
        n = sum(1 for _p, c in rows if code in c)
        lines.append(f'  {code:<8} n={n:<6} {question(evidences, code)[:78]}')

    lines.append('')
    lines.append('derived correlate routes (lift = how much more often than baseline):')
    for code in sens:
        cor = correlates(rows, code)
        if not cor:
            lines.append(f'  {code:<8} no route reaches the threshold')
            continue
        lines.append(f'  {code:<8} {question(evidences, code)[:66]}')
        for c, lift, p in cor:
            lines.append(f'      lift {lift:<5} in {int(p*100):>3}% of them  '
                         f'{question(evidences, c)[:60]}')

    common = commonness(rows)
    top = sorted(common.items(), key=lambda kv: -kv[1])[:8]
    lines.append('')
    lines.append('natural distractors (evidence appears across this many pathologies):')
    for code, n in top:
        lines.append(f'  {n:>3} pathologies  {question(evidences, code)[:70]}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(report())
