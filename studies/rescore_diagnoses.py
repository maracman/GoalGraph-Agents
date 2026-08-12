#!/usr/bin/env python3
"""Re-derive solve outcomes for the clinical tasks from stored transcripts.

The completion check accepted any message containing 'diagnos' and returned the
first condition named anywhere in it, so sentences that asserted nothing -
"nothing here is diagnostic of HIV yet" - ended runs and scored them solved.
Every transcript is on disk, so the corrected outcome can be recovered without
re-running anything.

Three buckets, not two. A run that was stopped early by a false completion
cannot simply be relabelled unsolved: it was cut off mid-investigation and
might have gone on to commit correctly. Its outcome is unknown, and calling it
a failure would trade an error that inflates for one that deflates. It is
reported as CENSORED and belongs in neither numerator nor denominator.

    python3 studies/rescore_diagnoses.py
    python3 studies/rescore_diagnoses.py --json out.json
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))

from agent import ddx_rules as DX, clinic_rules as CL, diagnosis_rules as DG  # noqa: E402

RULES = {'ddx_clinic': DX, 'clinic': CL, 'diagnosis': DG}


# --- what the old check did, kept verbatim so the difference is measurable ---

def _legacy_ddx(text):
    low = str(text or '').lower()
    if 'diagnos' not in low:
        return None
    for name in DX.conditions():
        if name.lower() in low:
            return name
        head = name.split('(')[0].strip().lower()
        if head and head in low:
            return name
    return None


def _legacy_named(text, table, also_bare=False):
    low = str(text or '').lower()
    if 'diagnos' not in low and not (also_bare and 'it is ' in low):
        return None
    for name, pretty in table.items():
        if name in low or name.replace('_', ' ') in low or str(pretty).lower() in low:
            return name
    return None


def legacy_claim(run_type, text):
    if run_type == 'ddx_clinic':
        return _legacy_ddx(text)
    if run_type == 'clinic':
        return _legacy_named(text, CL.DISORDER_TEXT)
    return _legacy_named(text, DG.CONDITION_TEXT, also_bare=True)


def target_for(run_type, rule_name):
    if run_type == 'ddx_clinic':
        return DX.base_case(rule_name)
    if run_type == 'clinic':
        return CL.base_case(rule_name)
    return rule_name


def answer_position(settings):
    """Where the true answer sat in this run's candidate list, 1-based.

    None for runs made before the list was shuffled and recorded - those all
    used one fixed order, so position is a constant there and cannot be
    separated from which condition it was.
    """
    order = settings.get('candidate_order') or []
    answer = str(settings.get('keeper_rule') or '').strip()
    if not order or not answer:
        return None
    if answer in order:
        return order.index(answer) + 1
    head = answer.split('(')[0].strip().lower()
    for i, name in enumerate(order):
        if head and str(name).lower().startswith(head):
            return i + 1
    return None


def outcome(run_type, history, rule_name):
    """(old_solved, new_solved, stopped_at_old, stopped_at_new)."""
    want = target_for(run_type, rule_name)
    mod = RULES[run_type]
    old_at = new_at = None
    for i, (_speaker, message) in enumerate(history):
        if old_at is None and legacy_claim(run_type, message) == want:
            old_at = i
        if new_at is None and mod.diagnosis_claimed(message) == want:
            new_at = i
        if old_at is not None and new_at is not None:
            break
    return old_at is not None, new_at is not None, old_at, new_at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default='src/chat_cache')
    ap.add_argument('--json', dest='out')
    a = ap.parse_args()

    rows = []
    for path in sorted(glob.glob(os.path.join(a.cache, '*_state.json'))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        s = d.get('settings', {})
        rt = str(s.get('run_type', ''))
        if rt not in RULES:
            continue
        h = d.get('session_history', [])
        rule = str(s.get('keeper_rule', '')).strip()
        if not h or not rule:
            continue
        old, new, old_at, new_at = outcome(rt, h, rule)
        # Stopped early on a claim that was never made: the rest of the run
        # does not exist, so the true outcome is unknown rather than negative.
        censored = old and not new
        rows.append({
            'session': os.path.basename(path).replace('_state.json', ''),
            'run_type': rt, 'run_label': str(s.get('run_label', '')),
            'case': rule, 'context_window': s.get('context_window'),
            'messages': len(h),
            'old_solved': bool(old), 'new_solved': bool(new),
            'censored': bool(censored),
            'old_stop': old_at, 'new_stop': new_at,
            'answer_position': answer_position(s),
        })

    if not rows:
        print('no clinical transcripts found', file=sys.stderr)
        return 1

    by = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        c = by[r['run_type']]
        c['runs'] += 1
        c['old'] += r['old_solved']
        c['new'] += r['new_solved']
        c['censored'] += r['censored']

    print(f"{'run_type':13s} {'runs':>5s} {'old solved':>11s} {'now solved':>11s} "
          f"{'censored':>9s} {'clean rate':>11s}")
    for rt, c in sorted(by.items(), key=lambda kv: -kv[1]['runs']):
        clean = c['runs'] - c['censored']
        rate = f"{c['new']/clean:.0%}" if clean else '-'
        print(f"{rt:13s} {c['runs']:5d} {c['old']:11d} {c['new']:11d} "
              f"{c['censored']:9d} {rate:>11s}")

    tot = collections.Counter()
    for c in by.values():
        tot.update(c)
    print(f"\n{tot['censored']} of {tot['runs']} runs were stopped by a completion that "
          f"was never asserted.\nThose are unknown outcomes, not failures - they were cut "
          f"off before they could finish.")

    # Same split per case, since the old bug favoured whichever condition sorted
    # first and that was not evenly spread across cases.
    per = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        c = per[r['case']]
        c['runs'] += 1
        c['old'] += r['old_solved']
        c['new'] += r['new_solved']
        c['censored'] += r['censored']
    print(f"\n{'case':28s} {'runs':>5s} {'old':>5s} {'now':>5s} {'censored':>9s}")
    for case, c in sorted(per.items(), key=lambda kv: -kv[1]['runs']):
        if c['runs'] < 3:
            continue
        print(f"{case:28s} {c['runs']:5d} {c['old']:5d} {c['new']:5d} {c['censored']:9d}")

    # Was being listed first worth anything? Only answerable for runs made
    # after the order started being shuffled and recorded; before that every
    # run used the same order, so position is confounded with condition.
    positioned = [r for r in rows if r['answer_position']]
    print(f"\nruns with a recorded candidate order: {len(positioned)} of {len(rows)}")
    if positioned:
        pos = collections.defaultdict(collections.Counter)
        for r in positioned:
            c = pos[r['answer_position']]
            c['runs'] += 1
            c['solved'] += r['new_solved']
            c['censored'] += r['censored']
        print(f"\n{'answer listed at':>17s} {'runs':>5s} {'solved':>7s} {'rate':>6s}")
        for p in sorted(pos):
            c = pos[p]
            clean = c['runs'] - c['censored']
            rate = f"{c['solved']/clean:.0%}" if clean else '-'
            print(f"{p:>17} {c['runs']:5d} {c['solved']:7d} {rate:>6s}")
    else:
        print('  (none yet - every run so far used the one fixed order, so '
              'position cannot be told apart from which condition it was)')

    if a.out:
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f'\nper-run detail written to {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
