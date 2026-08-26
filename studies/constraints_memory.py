#!/usr/bin/env python3
"""Does graph memory pay when the state genuinely exceeds the window?

Three tasks in a row failed to bind memory: ddx state compresses to a
sentence, the Wason rules fall in two hypotheses, and a stateful patient
could not stop the clinician re-carrying facts in its own prose. Constraints
at five_constraints is different, by construction and now by pilot: five
rules must hold at once, rejections do not say which rule broke, and accepted
sentences must share few words with every earlier accepted one - so the state
that matters is the word-sets of every attempt, which neither compresses nor
fits a 250-token message. Pilot at window 3: none arm 29 rejections, 39
re-treads, unsolved; graph arm solved at call 23.

2x2, n=12 per cell:

               window 3                    window 24
  none         memory failures expected    control
  graph        THE TEST                    control (little room expected)

Pre-registered:
  - primary : at window 3, graph solves more than none (Fisher p<0.05)
  - mechanism: at window 3, graph has a lower re-tread rate per proposal
  - at window 24 the gap should shrink or vanish; a same-size gap at both
    windows would say the help is not about the window at all
Engagement gates (a cell that never engaged tested nothing):
  - graph arms: graph_contribution_chars > 0
  - none w3: re-treads occur (the failure the graph is supposed to prevent)

    GOALGRAPH_BASE=http://localhost:5055 python3 studies/constraints_memory.py \\
        --out studies/results/v3_constraints_w3.json --resume
"""

import argparse
import csv
import io
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))
import requests                                                   # noqa: E402

from agent.keeper import make_keeper                              # noqa: E402
from agent import constraint_rules as CR                          # noqa: E402

BASE = os.environ.get('GOALGRAPH_BASE', 'http://localhost:5055')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'src', 'chat_cache')

LEVEL = 'five_constraints'          # overridden by --level
MODEL_TAG = ''                       # set from --model for labels
LLM = None                           # set from --provider/--model
CELLS = [('none', 3), ('graph', 3), ('none', 24), ('graph', 24)]


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def score_transcript(session_id):
    """Attempts, progress and memory failures, via the keeper's own code."""
    path = os.path.join(CACHE, f'{session_id}_state.json')
    if not os.path.exists(path):
        # No transcript, no mechanism metrics - and silently recording Nones
        # would mark the run done so --resume never retried it.
        return None
    with open(path) as f:
        history = json.load(f).get('session_history', [])
    proposers = {s for s, m in history if s != 'keeper'}
    if len(proposers) > 1:
        print(f'  !! two proposers in {session_id} - mute did not hold',
              file=sys.stderr, flush=True)
        return None
    keeper = make_keeper({'run_type': 'constraints', 'keeper_rule': LEVEL})
    accepted, rejected = keeper.attempts_from(history)
    distinct = keeper.distinct_accepted(history)

    # Memory failure 1: proposing something nearly identical to an already
    # rejected sentence AND getting rejected again. An accepted near-match is
    # the opposite of forgetting - it is a deliberate minimal repair - so it
    # is counted separately, not as a failure. is_repeat is the keeper's own
    # test, so the metric matches the feedback the agent actually received.
    # Agent messages only - the keeper echoes candidates back.
    redo = 0
    repaired = 0
    seen_rejected = []
    for speaker, m in history:
        if speaker == 'keeper':
            continue
        mv = keeper.extract_move(m)
        if not mv:
            continue
        near = CR.is_repeat(mv, seen_rejected)
        if CR.accepts(LEVEL, mv):
            if near:
                repaired += 1
        else:
            if near:
                redo += 1
            seen_rejected.append(mv)

    # Memory failure 2: rule-passing sentences that fail only novelty against
    # earlier accepted ones - the rules were cracked, progress still stalled.
    blocked = 0
    kept = [CR.opening_example(LEVEL)]
    for a in accepted:
        if CR.is_novel(a, kept):
            kept.append(a)
        else:
            blocked += 1

    return {'proposals': len(accepted) + len(rejected),
            'accepted': len(accepted), 'rejected': len(rejected),
            'distinct_accepted': len(distinct),
            'redo_rejected': redo, 'repaired_rejected': repaired,
            'novelty_blocked': blocked}


def run_one(mode, window, label, max_calls):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    if LLM:
        # The acting model varies; the judge and keeper are the instrument and
        # stay on the strong model. strict_provider turns a provider hiccup
        # into a lost (retried) run instead of a silent model swap.
        r = s.post(f"{BASE}/update_llm_settings", json=LLM, timeout=60)
        if not r.ok:
            sys.exit(f'update_llm_settings failed: {r.status_code} {r.text[:150]}')
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='constraints', keeper_rule=LEVEL, graph_memory_mode=mode,
        aim_fork_mode='gate', task_variant='', context_window=str(window),
        graph_recall_k='6', graph_recall_chars='1200', nogo_ungated='false',
        judge_delay_seconds='0', run_label=label), timeout=180)

    got = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    if (got.get('graph_memory_mode') != mode
            or int(got.get('context_window') or -1) != window):
        sys.exit(f'server did not accept mode={mode!r}/window={window} '
                 f'(reports {got.get("graph_memory_mode")!r}/'
                 f'{got.get("context_window")!r}). Restart it.')

    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)

    # One proposer. The session ships two agents and both propose, which
    # splits the memory question across two graphs and two windows; muting the
    # second gives one agent, one graph, one window - identically in every
    # cell.
    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    for extra in ags[1:]:
        aid = extra.get('id') or extra.get('agent_id')
        if not aid:
            continue
        # Each run_one is a fresh server session, so every extra agent starts
        # unmuted and one toggle mutes it. The response is asserted rather
        # than trusted: a failed toggle would silently hand the run two
        # proposers, and the transcript check downstream would only catch it
        # after 40 calls were spent.
        resp = s.post(f"{BASE}/toggle_agent_mute", data={'agent_id': aid},
                      timeout=60)
        ok = resp.ok and (resp.json() or {}).get('muted') is True
        if not ok:
            sys.exit(f'could not mute agent {aid} ({resp.status_code} '
                     f'{resp.text[:120]}) - the study needs one proposer.')

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

    session_id = s.get(f"{BASE}/get_session_id", timeout=60).json()['session_id']
    scored = score_transcript(session_id)
    if scored is None:
        lost = 1
        scored = {'proposals': None, 'accepted': None, 'rejected': None,
                  'distinct_accepted': None, 'redo_rejected': None,
                  'repaired_rejected': None, 'novelty_blocked': None}
    return dict(
        mode=mode, window=window, label=label, solved=int(solved), turns=turns,
        recorded_turns=len(rows), lost=lost,
        capped=int(turns >= max_calls and not solved),
        input_tokens=total('input_tokens'), output_tokens=total('output_tokens'),
        graph_contribution_chars=total('graph_contribution_chars'),
        minutes=round((time.time() - t0) / 60, 1),
        **scored)


def cell_name(mode, window):
    return f'{mode:<6} w{window}'


def report(rows):
    rows = [r for r in rows if not r.get('lost')]
    if not rows:
        print('\nno completed runs to report')
        return
    print(f'\n{len(rows)} runs, constraints/{LEVEL}\n')
    print(f"{'cell':<12}{'solved':<9}{'turns/solve':<13}{'capped':<8}"
          f"{'accepted':<10}{'rejected':<10}{'redo/prop':<11}{'repaired':<10}"
          f"{'blocked':<9}{'in tok/turn':<12}")
    for mode, window in CELLS:
        rs = [r for r in rows if r['mode'] == mode and r['window'] == window]
        if not rs:
            continue
        sv = [r for r in rs if r['solved']]
        turns = sum(r['recorded_turns'] for r in rs) or 1
        solve_cell = f'{len(sv)}/{len(rs)}'
        when = round(st.mean([r['turns'] for r in sv]), 1) if sv else '-'
        def m(k):
            xs = [r[k] for r in rs if r.get(k) is not None]
            return round(st.mean(xs), 1) if xs else '-'
        props = sum(r['proposals'] or 0 for r in rs)
        redo = sum(r['redo_rejected'] or 0 for r in rs)
        rate = f'{redo}/{props}' if props else '-'
        cap_cell = f"{sum(r['capped'] for r in rs)}/{len(rs)}"
        print(f"{cell_name(mode, window):<12}{solve_cell:<9}{str(when):<13}"
              f"{cap_cell:<8}{str(m('accepted')):<10}{str(m('rejected')):<10}"
              f"{rate:<11}{str(m('repaired_rejected')):<10}"
              f"{str(m('novelty_blocked')):<9}"
              f"{round(sum(r['input_tokens'] for r in rs) / turns):<12}")

    for mode, window in CELLS:
        rs = [r for r in rows if r['mode'] == mode and r['window'] == window]
        if not rs:
            continue
        if mode == 'graph' and not any(r['graph_contribution_chars'] for r in rs):
            print(f'\n!! {cell_name(mode, window)}: memory never reached the '
                  f'prompt. This cell tested nothing.')
        if mode == 'none' and any(r['graph_contribution_chars'] for r in rs):
            print(f'\n!! {cell_name(mode, window)}: graph text reached a '
                  f'graph-off prompt. The control is contaminated.')
    w3none = [r for r in rows if r['mode'] == 'none' and r['window'] == 3]
    if w3none and not any(r.get('redo_rejected') for r in w3none):
        print('\n!! none w3 shows no re-treads: the failure the graph is '
              'supposed to prevent did not occur, and the primary contrast '
              'has nothing to measure.')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--max-calls', type=int, default=40)
    ap.add_argument('--replicates', type=int, default=12)
    ap.add_argument('--level', default='five_constraints')
    ap.add_argument('--provider', default='',
                    help='acting model provider (e.g. openai for an '
                         'OpenAI-compatible host); judge stays on codex')
    ap.add_argument('--model', default='')
    ap.add_argument('--out', default='studies/results/v3_constraints_w3.json')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--report-only', action='store_true')
    a = ap.parse_args()

    global LEVEL, MODEL_TAG, LLM
    LEVEL = a.level
    if a.provider:
        MODEL_TAG = (a.model.split('/')[-1] or a.provider)[:24]
        LLM = dict(provider=a.provider, model=a.model, max_tokens=250,
                   strict_provider=True, fallback_to_local=False,
                   judge_provider='openai-codex', judge_model='gpt-5.4')

    if a.report_only:
        with open(a.out) as f:
            report(json.load(f))
        return

    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f'GoalGraph is not running at {BASE}')

    # One replicate = the four cells adjacently, rotated so no cell always
    # goes first; drift lands on all cells alike.
    plan = []
    for rep in range(a.replicates):
        cells = list(CELLS)
        shift = rep % len(cells)
        cells = cells[shift:] + cells[:shift]
        for mode, window in cells:
            plan.append((rep, mode, window))

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} runs already recorded', flush=True)

    def label_for(step):
        rep, mode, window = step
        tag = f'-{MODEL_TAG}' if MODEL_TAG else ''
        return f'con{tag}-{mode}-w{window}-r{rep}'

    lost = [r for r in rows if r.get('lost')]
    if lost:
        print(f'{len(lost)} lost run(s) will be retried', flush=True)
        rows = [r for r in rows if not r.get('lost')]
    done = {r.get('label') for r in rows}
    plan = [step for step in plan if label_for(step) not in done]
    print(f'{len(plan)} runs to go\n', flush=True)

    for i, step in enumerate(plan):
        rep, mode, window = step
        if not alive():
            sys.exit(f'app at {BASE} is not responding; rerun with --resume')
        r = run_one(mode, window, label_for(step), a.max_calls)
        r['replicate'] = rep
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
        print(f"[{i+1}/{len(plan)}] {cell_name(mode, window):<12} r{rep} "
              f"solved={r['solved']} turns={r['turns']:<3} "
              f"acc={r['accepted']} rej={r['rejected']} "
              f"redo={r['redo_rejected']} blocked={r['novelty_blocked']} "
              f"{r['minutes']}min", flush=True)

    report(rows)
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
