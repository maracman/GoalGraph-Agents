#!/usr/bin/env python3
"""The groove as a guard-rail: does enforcing the record beat reciting it?

The weak model re-treads refuted ground with the refutations in its prompt:
recall alone did not reduce re-proposals anywhere it was measured. This study
tests enforcement: when a draft move is a near-repeat of an already-rejected
one, the keeper names it and the draft is regenerated ONCE before the turn is
spent. Mechanical - it cannot fail by "the arbiter did not read the list".

Arms (all scaffolded, 3B acting, gpt-5.4 judging, two_constraints, w24, n=16):

  none    aims on, graph memory off - the bare scaffold
  graph   aims + graph recall - the record recited
  guard   aims + graph recall + move_guard - the record enforced

Pre-registered, continuous primaries (the binary solve rate has flapped
across days all week; rejections and re-treads are per-run counts with real
power):
  primary   guard < graph on redo_rejected per proposal (the mechanism,
            Mann-Whitney) AND guard > graph on distinct_accepted (progress)
  secondary graph vs none on near-dup looping (replication of the scaffold
            study's monotone gradient), solve rate everywhere
  gates     guard arm: move_guard_fired > 0 somewhere (else it never
            engaged); graph arms: contribution > 0 somewhere

Every memory study ablated recall and kept the scaffold: both arms always had
a current aim in the prompt and a judge revising it. The system was born
before any of that mattered for scoring - it was built to stop Llama-2-era
agents looping and drifting off their goals. That claim is about the
SCAFFOLD, and it has never been tested, for any model.

Three arms, weak model (llama-3.2-3b via OpenRouter), strong judge (gpt-5.4),
constraints/two_constraints at window 24, n=12 each:

  off    aim_system off - no aim, no judge, no graph writes. A plain
         conversing agent: the pre-GoalGraph world.
  none   aims on, memory off - the scaffold alone.
  graph  aims on, graph recall on - the full system.

Outcomes: solve rate and turns (the task), then the behavioural metrics the
origin story is actually about - near-duplicate looping, longest loop,
distinct-trigram ratio, re-treads of rejected sentences.

Pre-registered: the origin story predicts off < none on solve and/or looping
(the scaffold pays). The week's memory results predict none ~= graph.
Engagement gates: the off arm must show empty aims throughout; the graph arm
must show non-zero recall in at least some runs.

    GOALGRAPH_BASE=http://localhost:5055 python3 studies/constraints_scaffold.py \\
        --out studies/results/v3_scaffold_w24.json --resume
"""

import argparse
import collections
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

LEVEL = 'two_constraints'
WINDOW = 24
MODEL = 'meta-llama/llama-3.2-3b-instruct'
ARMS = ['none', 'graph', 'guard']
ARM_SETTINGS = {
    'none': dict(aim_system='on', graph_memory_mode='none', move_guard='false'),
    'graph': dict(aim_system='on', graph_memory_mode='graph', move_guard='false'),
    'guard': dict(aim_system='on', graph_memory_mode='graph', move_guard='true'),
}


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def trigrams(text):
    words = ''.join(c.lower() if c.isalnum() or c.isspace() else ' '
                    for c in text).split()
    return set(zip(words, words[1:], words[2:])) if len(words) >= 3 else {tuple(words)}


def score_transcript(session_id):
    """Task metrics via the keeper's code, looping metrics via trigrams."""
    path = os.path.join(CACHE, f'{session_id}_state.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        history = json.load(f).get('session_history', [])
    proposers = {s for s, m in history if s != 'keeper'}
    if len(proposers) > 1:
        print(f'  !! two proposers in {session_id}', file=sys.stderr, flush=True)
        return None
    keeper = make_keeper({'run_type': 'constraints', 'keeper_rule': LEVEL})
    accepted, rejected = keeper.attempts_from(history)
    distinct = keeper.distinct_accepted(history)

    redo = 0
    seen_rejected = []
    for speaker, m in history:
        if speaker == 'keeper':
            continue
        mv = keeper.extract_move(m)
        if not mv:
            continue
        if CR.accepts(LEVEL, mv):
            continue
        if CR.is_repeat(mv, seen_rejected):
            redo += 1
        seen_rejected.append(mv)

    msgs = [m for s, m in history if s != 'keeper']
    near_dup = best = streak = 0
    grams = [trigrams(m) for m in msgs]
    for i in range(1, len(msgs)):
        sims = [len(grams[i] & grams[j]) / max(len(grams[i] | grams[j]), 1)
                for j in range(i)]
        if sims and max(sims) >= 0.6:
            near_dup += 1
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    tri = collections.Counter()
    for g in grams:
        tri.update(g)
    return {'proposals': len(accepted) + len(rejected),
            'accepted': len(accepted), 'rejected': len(rejected),
            'distinct_accepted': len(distinct), 'redo_rejected': redo,
            'near_dup_rate': round(near_dup / max(len(msgs) - 1, 1), 3),
            'longest_loop': best,
            'distinct_tri': round(len(tri) / max(sum(tri.values()), 1), 3)}


def run_one(arm, label, max_calls):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    r = s.post(f"{BASE}/update_llm_settings", json=dict(
        provider='openai', model=MODEL, max_tokens=250,
        strict_provider=True, fallback_to_local=False,
        judge_provider='openai-codex', judge_model='gpt-5.4'), timeout=60)
    if not r.ok:
        sys.exit(f'update_llm_settings failed: {r.status_code}')
    cfg = ARM_SETTINGS[arm]
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='constraints', keeper_rule=LEVEL,
        graph_memory_mode=cfg['graph_memory_mode'],
        aim_system=cfg['aim_system'], move_guard=cfg['move_guard'],
        aim_fork_mode='gate', task_variant='',
        context_window=str(WINDOW), graph_recall_k='6',
        graph_recall_chars='1200', judge_delay_seconds='0',
        run_label=label), timeout=180)
    got = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    want_guard = cfg['move_guard'] == 'true'
    if (got.get('graph_memory_mode') != cfg['graph_memory_mode']
            or bool(got.get('move_guard', False)) != want_guard):
        sys.exit(f'server did not accept arm {arm!r} (reports '
                 f'{got.get("graph_memory_mode")!r}/'
                 f'move_guard={got.get("move_guard")!r})')

    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)
    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    for extra in ags[1:]:
        aid = extra.get('id') or extra.get('agent_id')
        if not aid:
            continue
        resp = s.post(f"{BASE}/toggle_agent_mute", data={'agent_id': aid},
                      timeout=60)
        if not (resp.ok and (resp.json() or {}).get('muted') is True):
            sys.exit(f'could not mute agent {aid}')

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

    aims_seen = sum(1 for r in rows if (r.get('aim') or '').strip())
    guard_fired = sum(1 for r in rows if (r.get('move_guard_fired') or '') == '1')
    session_id = s.get(f"{BASE}/get_session_id", timeout=60).json()['session_id']
    scored = score_transcript(session_id)
    if scored is None:
        lost = 1
        scored = {k: None for k in
                  ('proposals', 'accepted', 'rejected', 'distinct_accepted',
                   'redo_rejected', 'near_dup_rate', 'longest_loop',
                   'distinct_tri')}
    return dict(
        arm=arm, label=label, solved=int(solved), turns=turns,
        recorded_turns=len(rows), lost=lost,
        capped=int(turns >= max_calls and not solved),
        aims_seen=aims_seen, guard_fired=guard_fired,
        input_tokens=total('input_tokens'), output_tokens=total('output_tokens'),
        graph_contribution_chars=total('graph_contribution_chars'),
        minutes=round((time.time() - t0) / 60, 1), **scored)


def report(rows):
    rows = [r for r in rows if not r.get('lost')]
    if not rows:
        print('\nno completed runs to report')
        return
    print(f'\n{len(rows)} runs, {MODEL} on {LEVEL} at window {WINDOW}\n')
    print(f"{'arm':<7}{'solved':<9}{'turns/solve':<13}{'capped':<8}"
          f"{'acc':<6}{'rej':<6}{'redo':<6}{'guardfires':<11}{'near-dup':<10}"
          f"{'distinct':<9}{'in tok/turn':<12}")
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if not rs:
            continue
        sv = [r for r in rs if r['solved']]
        turns = sum(r['recorded_turns'] for r in rs) or 1
        def m(k, digits=1):
            xs = [r[k] for r in rs if r.get(k) is not None]
            return round(st.mean(xs), digits) if xs else '-'
        solve_cell = f'{len(sv)}/{len(rs)}'
        when = round(st.mean([r['turns'] for r in sv]), 1) if sv else '-'
        cap = f"{sum(r['capped'] for r in rs)}/{len(rs)}"
        print(f"{arm:<7}{solve_cell:<9}{str(when):<13}{cap:<8}"
              f"{str(m('accepted')):<6}{str(m('rejected')):<6}"
              f"{str(m('redo_rejected')):<6}{str(m('guard_fired')):<11}"
              f"{str(m('near_dup_rate', 3)):<10}"
              f"{str(m('distinct_accepted')):<9}"
              f"{round(sum(r['input_tokens'] for r in rs) / turns):<12}")

    gu = [r for r in rows if r['arm'] == 'guard']
    if gu and not any(r['guard_fired'] for r in gu):
        print('\n!! guard: the move guard never fired - either no re-treads '
              'happened (check redo in the other arms) or the guard is dead.')
    ng = [r for r in rows if r['arm'] != 'guard' and r.get('guard_fired')]
    if any(r['guard_fired'] for r in ng):
        print('\n!! a non-guard arm recorded guard fires - contamination.')
    for arm in ('graph', 'guard'):
        rs = [r for r in rows if r['arm'] == arm]
        if rs and not any(r['graph_contribution_chars'] for r in rs):
            print(f'\n!! {arm}: recall never reached the prompt in any run.')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--max-calls', type=int, default=40)
    ap.add_argument('--replicates', type=int, default=16)
    ap.add_argument('--out', default='studies/results/v3_guard.json')
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

    plan = []
    for rep in range(a.replicates):
        arms = list(ARMS)
        shift = rep % len(arms)
        arms = arms[shift:] + arms[:shift]
        for arm in arms:
            plan.append((rep, arm))

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} runs already recorded', flush=True)

    def label_for(step):
        rep, arm = step
        return f'guard-{arm}-r{rep}'

    lost = [r for r in rows if r.get('lost')]
    if lost:
        print(f'{len(lost)} lost run(s) will be retried', flush=True)
        rows = [r for r in rows if not r.get('lost')]
    done = {r.get('label') for r in rows}
    plan = [step for step in plan if label_for(step) not in done]
    print(f'{len(plan)} runs to go\n', flush=True)

    for i, step in enumerate(plan):
        rep, arm = step
        if not alive():
            sys.exit(f'app at {BASE} is not responding; rerun with --resume')
        r = run_one(arm, label_for(step), a.max_calls)
        r['replicate'] = rep
        rows.append(r)

        if r['input_tokens'] == 0 and r['turns'] > 1:
            print(f'  !! {r["label"]} recorded no tokens', file=sys.stderr,
                  flush=True)
            if sum(1 for x in rows[-3:] if x['input_tokens'] == 0) >= 3:
                sys.exit('three consecutive dead runs; aborting')

        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        tmp = a.out + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(rows, f, indent=1)
        os.replace(tmp, a.out)
        print(f"[{i+1}/{len(plan)}] {arm:<6} r{rep} solved={r['solved']} "
              f"turns={r['turns']:<3} acc={r['accepted']} rej={r['rejected']} "
              f"neardup={r['near_dup_rate']} aims={r['aims_seen']} "
              f"{r['minutes']}min", flush=True)

    report(rows)
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
