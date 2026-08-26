#!/usr/bin/env python3
"""Is there a context-loss gradient for memory to close? (Phase 1: graph OFF.)

Both window sweeps found the no-memory control flat from a 2-message window to
32. The reason is structural: the patient forgets along with the clinician. It
does not remember having answered, so any fact the window has dropped can be
re-elicited for the price of a turn, and forgetting has no consequence. A task
in that regime cannot test whether anything "carries information past the
window" - there is nothing to carry.

The lever is the environment, not the agent: the ddx 'stateful_patient'
variant gives the patient the full conversation regardless of the session
window, and a standing rule that a question already answered gets "I've
already told you that" and nothing else. A fact outside the clinician's
window is then genuinely gone.

2x2, graph off in every cell (memory mode 'none', fork 'gate', fresh graph):

                 window 3          window 24
  plain          replicates the old null on current code
  stateful       THE TEST          checks the variant leaves the task solvable

Pre-registered outcomes:
  - gradient found:  stateful w3 solves less than stateful w24 (Fisher p<0.05)
                     AND plain shows no such gap. Phase 2 (graph on, inside
                     the stateful regime) is then worth running.
  - no gradient:     stateful w3 ~= stateful w24. The thesis stays untestable
                     on this task even with an unforgiving environment, and
                     that is the finding - phase 2 is cancelled.
  - variant broken:  stateful w24 craters relative to plain w24. The variant
                     made the task unsolvable rather than memory-bound; fix
                     before interpreting anything.

Engagement checks (a cell that never engaged tested nothing):
  - refusals ("I've already told you...") must appear in stateful arms and
    not in plain arms.

    GOALGRAPH_BASE=http://localhost:5055 python3 studies/ddx_gradient.py \\
        --out studies/results/v3_gradient.json --resume
"""

import argparse
import collections
import csv
import io
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))
import requests                                                   # noqa: E402

from agent import ddx_rules as DX                                 # noqa: E402

BASE = os.environ.get('GOALGRAPH_BASE', 'http://localhost:5055')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'src', 'chat_cache')

CLINICIAN = 'Dr Nazari'
PATIENT = 'Ash'

# (variant, window) cells. Window 24 rather than 0 so both poles run through
# the identical windowing code path - 0 would switch judge_view to its
# last-ten default and the poles would differ in more than size.
CELLS = [('', 3), ('', 24), (DX.STATEFUL, 3), (DX.STATEFUL, 24)]

SEQUENCE = ['HIV (initial infection)', 'Influenza']

REFUSAL = re.compile(
    r"already (?:told|said|answered|mentioned|covered|been (?:through|over))"
    r"|told you (?:that|this|before)"
    r"|asked (?:me )?(?:that|this) (?:already|before)"
    r"|we(?:'ve| have)? (?:already )?(?:covered|been over|discussed)", re.I)


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def score_transcript(session_id, case):
    """Commitment, refusals and re-asks, replayed from the stored history."""
    path = os.path.join(CACHE, f'{session_id}_state.json')
    if not os.path.exists(path):
        return {'committed': None, 'claim_last': '', 'claims_n': None,
                'claim_right': None, 'refusals': None, 'reasked_codes': None}
    with open(path) as f:
        history = json.load(f).get('session_history', [])
    want = DX.base_case(case)
    claims = [c for sp, m in history if sp == CLINICIAN
              for c in [DX.diagnosis_claimed(m)] if c]
    # Three kinds of refusal, because they mean three different things.
    #   clean : refused and gave nothing - the lever working as designed
    #   leaky : refusal phrasing but a feature mentioned anyway ("as I already
    #           told you, it's red") - the information still got out
    #   wrong : a refusal answering a question whose features no earlier
    #           clinician message ever raised - the patient over-refusing,
    #           which would fake a memory gradient. The novelty test uses the
    #           same phrase-matching as reasked_codes, so it is a flag to
    #           inspect on, not a verdict.
    refusals = leaky = wrong = 0
    asked_before = set()
    for n, (sp, m) in enumerate(history):
        if sp == CLINICIAN:
            asked_before |= set(DX.mentions(m))
            continue
        if sp != PATIENT or not REFUSAL.search(m):
            continue
        refusals += 1
        if DX.mentions(m):
            leaky += 1
        prev = next((mm for ss, mm in reversed(history[:n]) if ss == CLINICIAN), '')
        prev_codes = set(DX.mentions(prev))
        before = set()
        for ss, mm in history[:n]:
            if ss == CLINICIAN and mm is not prev:
                before |= set(DX.mentions(mm))
        if prev_codes and not (prev_codes & before):
            wrong += 1
    # How often the clinician went back over ground already covered: feature
    # codes appearing in more than one clinician message. A rough proxy - the
    # phrasing needn't re-match - but comparable across cells, which is what
    # a proxy has to be.
    seen = collections.Counter()
    for sp, m in history:
        if sp != CLINICIAN:
            continue
        for code in set(DX.mentions(m)):
            seen[code] += 1
    return {'committed': int(bool(claims)),
            'claim_last': claims[-1] if claims else '',
            'claims_n': len(claims),
            'claim_right': int(bool(claims) and claims[-1] == want),
            'refusals': refusals, 'leaky_refusals': leaky,
            'wrong_refusals': wrong,
            'reasked_codes': sum(1 for v in seen.values() if v > 1)}


def run_one(case, variant, window, label, salt, max_calls):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='ddx_clinic', keeper_rule=case, graph_memory_mode='none',
        aim_fork_mode='gate', task_variant=variant,
        context_window=str(window), nogo_ungated='false',
        order_salt=salt, judge_delay_seconds='0', run_label=label), timeout=180)

    got = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    if (got.get('task_variant') != variant
            or int(got.get('context_window') or -1) != window):
        sys.exit(f'server did not accept task_variant={variant!r} / '
                 f'context_window={window} (it reports '
                 f'{got.get("task_variant")!r} / {got.get("context_window")!r})'
                 f' - it is running code that predates them. Restart it.')

    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)
    s.post(f"{BASE}/submit", data=dict(user_message='', is_user='false',
                                       max_turns=str(max_calls)), timeout=120)
    solved, turns, lost = False, 0, 0
    for i in range(max_calls):
        turns = i + 1
        try:
            resp = s.get(f"{BASE}/generate", timeout=300)
        except requests.RequestException as e:
            print(f'  [{label}] {e}', file=sys.stderr)
            lost = 1
            break
        if resp.status_code != 200:
            print(f'  [{label}] HTTP {resp.status_code}', file=sys.stderr)
            lost = 1
            break
        if any('Task complete' in str(x) for x in resp.json().get('logs', [])):
            solved = True
            break

    try:
        rows = list(csv.DictReader(io.StringIO(
            s.get(f"{BASE}/export_run_data", timeout=60).text)))
    except requests.RequestException:
        rows = []

    def total(col):
        n = 0
        for row in rows:
            try:
                n += int(row.get(col) or 0)
            except ValueError:
                pass
        return n

    contrib = total('graph_contribution_chars')
    session_id = s.get(f"{BASE}/get_session_id", timeout=60).json()['session_id']
    return dict(
        case=case, variant=variant, window=window, label=label, salt=salt,
        solved=int(solved), turns=turns, recorded_turns=len(rows), lost=lost,
        capped=int(turns >= max_calls and not solved),
        input_tokens=total('input_tokens'), output_tokens=total('output_tokens'),
        graph_contribution_chars=contrib,
        minutes=round((time.time() - t0) / 60, 1),
        **score_transcript(session_id, case))


def cell_name(variant, window):
    return f"{'stateful' if variant else 'plain':<9} w{window}"


def report(rows):
    rows = [r for r in rows if not r.get('lost')]
    if not rows:
        print('\nno completed runs to report')
        return
    print(f'\n{len(rows)} runs, graph off in every cell\n')
    print(f"{'cell':<14}{'solved':<9}{'turns/solve':<13}{'capped':<9}"
          f"{'refusals/run':<14}{'re-asked':<10}{'in tok/turn':<13}{'commit':<8}")
    for variant, window in CELLS:
        rs = [r for r in rows if r['variant'] == variant and r['window'] == window]
        if not rs:
            continue
        sv = [r for r in rs if r['solved']]
        turns = sum(r['recorded_turns'] for r in rs) or 1
        refus = [r['refusals'] for r in rs if r['refusals'] is not None]
        reask = [r['reasked_codes'] for r in rs if r['reasked_codes'] is not None]
        solve_cell = f'{len(sv)}/{len(rs)}'
        when = round(st.mean([r['turns'] for r in sv]), 1) if sv else '-'
        cap_cell = f"{sum(r['capped'] for r in rs)}/{len(rs)}"
        print(f"{cell_name(variant, window):<14}{solve_cell:<9}{str(when):<13}"
              f"{cap_cell:<9}"
              f"{str(round(st.mean(refus), 1) if refus else '-'):<14}"
              f"{str(round(st.mean(reask), 1) if reask else '-'):<10}"
              f"{round(sum(r['input_tokens'] for r in rs) / turns):<13}"
              f"{sum(r.get('committed') or 0 for r in rs):<8}")

    # Engagement: the lever must fire where it is on and nowhere else.
    on = [r for r in rows if r['variant'] and r['refusals'] is not None]
    off = [r for r in rows if not r['variant'] and r['refusals'] is not None]
    if on and not any(r['refusals'] for r in on):
        print('\n!! stateful arms recorded zero refusals: the patient never '
              'enforced the rule, and the variant tested nothing.')
    if off and sum(r['refusals'] for r in off) > len(off):
        print('\n!! plain arms are full of refusal phrasing - the detector is '
              'matching something else; do not read the refusal column.')
    grams = [r for r in rows if r['graph_contribution_chars']]
    if grams:
        print(f'\n!! {len(grams)} run(s) show non-zero graph contribution in a '
              f'graph-off study - the control is contaminated.')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--replicates', type=int, default=6,
                    help='repeats of the HIV/Influenza pair per cell; 6 gives '
                         'n=12 per cell, where Fisher can see an 8/12-vs-2/12 '
                         'gap (p=0.036) - the audit showed n=8 only detects '
                         'near-binary effects')
    ap.add_argument('--out', default='studies/results/v3_gradient.json')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--report-only', action='store_true')
    a = ap.parse_args()

    if a.report_only:
        with open(a.out) as f:
            report(json.load(f))
        return

    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f'GoalGraph is not running at {BASE}')

    # Blocked by (replicate, patient); the four cells run adjacently inside a
    # block, rotated so no cell always goes first, under one pinned candidate
    # order - drift lands on all cells alike.
    plan = []
    for rep in range(a.replicates):
        for pos, case in enumerate(SEQUENCE):
            cells = list(CELLS)
            shift = (rep * len(SEQUENCE) + pos) % len(cells)
            cells = cells[shift:] + cells[:shift]
            for variant, window in cells:
                plan.append((rep, pos, case, variant, window))

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} runs already recorded', flush=True)

    def label_for(step):
        rep, pos, case, variant, window = step
        return f"grad-{'sp' if variant else 'pl'}-w{window}-r{rep}p{pos}"

    # A lost run is retried, not skipped: keeping its row while also leaving
    # its label in the plan would double-count, so drop the dead row and run
    # the step again.
    lost = [r for r in rows if r.get('lost')]
    if lost:
        print(f'{len(lost)} lost run(s) will be retried: '
              f'{", ".join(r["label"] for r in lost[:6])}', flush=True)
        rows = [r for r in rows if not r.get('lost')]
    done = {r.get('label') for r in rows}
    plan = [step for step in plan if label_for(step) not in done]
    print(f'{len(plan)} runs to go\n', flush=True)

    for i, step in enumerate(plan):
        rep, pos, case, variant, window = step
        if not alive():
            sys.exit(f'app at {BASE} is not responding; rerun with --resume')
        r = run_one(case, variant, window, label_for(step),
                    f'gblk-{rep}-{pos}', a.max_calls)
        r['replicate'] = rep
        r['position'] = pos
        rows.append(r)

        if r['input_tokens'] == 0 and r['turns'] > 1:
            print(f'  !! {r["label"]} recorded no tokens - provider failing?',
                  file=sys.stderr, flush=True)
            if sum(1 for x in rows[-3:] if x['input_tokens'] == 0) >= 3:
                sys.exit('three consecutive dead runs; aborting')

        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        tmp = a.out + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(rows, f, indent=1)
        os.replace(tmp, a.out)
        print(f"[{i+1}/{len(plan)}] {cell_name(variant, window):<14} r{rep}p{pos} "
              f"{case[:16]:<18} solved={r['solved']} turns={r['turns']:<3} "
              f"refusals={r['refusals']} reasked={r['reasked_codes']} "
              f"{r['minutes']}min", flush=True)

    report(rows)
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
