#!/usr/bin/env python3
"""Two follow-ups the tuning screen earned: confirm the gate, exercise the trust.

  gate    the screen suggested easing the routing gate (0.40 -> 0.33)
          increases engagement, on four runs. Confirmed or refuted here with a
          full eight-patient carried sequence at window three - the window
          where routing does the most work - against the already-recorded
          window-three baseline (5/8, 39.8 turns when solved, 71 routed).

  shift   the trust mechanism has never fired: minimum trust was 1.0 across
          every run of every study, because routes built on the same two
          conditions the runs tested rarely fail outright. This arm builds the
          graph on HIV and influenza for four patients, then switches to
          anaphylaxis and pancreatic neoplasm - conditions the graph knows
          nothing about, whose inherited routes should now mislead. If the
          design is right, routed aims fail, trust_low drops below 1.0 for the
          first time, and the agent falls back to the judge rather than being
          dragged down the wrong route. A fresh arm on the same shifted
          sequence is the control.

Primary endpoint for `shift` is mechanism (does trust engage), not outcome:
the shifted conditions have one prior solved run each, so their difficulty is
poorly known and solve counts there carry wide error bars.

    python3 studies/ddx_confirm.py
    python3 studies/ddx_confirm.py --resume
"""

import argparse
import collections
import csv
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import requests                                                   # noqa: E402
import networkx as nx                                             # noqa: E402

BASE = "http://localhost:5000"
GATE_SEQ = ['HIV (initial infection)', 'Influenza'] * 4
# The first shift test used anaphylaxis and pancreatic neoplasm on one prior
# solve each - they turned out easy (fresh went 4/4 in ~26 turns), so nothing
# ever punished a wrong inherited route and trust had nothing to react to.
# Sarcoidosis is hard (9/25 across prior runs) without being demonstrated
# impossible, and its feature profile overlaps HIV enough that inherited
# HIV routes should genuinely mislead. The fresh arm on the same sequence
# controls for its difficulty.
SHIFT_SEQ = ['HIV (initial infection)', 'Influenza',
             'HIV (initial infection)', 'Influenza',
             'Sarcoidosis', 'Sarcoidosis',
             'Sarcoidosis', 'Sarcoidosis']
WINDOW = 3


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def run_one(case, label, max_calls, carried_graph, knobs):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    form = dict(run_type='ddx_clinic', keeper_rule=case,
                graph_memory_mode='graph', context_window=str(WINDOW),
                graph_recall_k='5', graph_recall_chars='800',
                nogo_ungated='false', run_label=label)
    form.update({k: str(v) for k, v in knobs.items()})
    s.post(f"{BASE}/update_user_settings", data=form, timeout=180)
    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)

    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    doc = ags[0].get('id') or ags[0].get('agent_id')
    inherited = 0
    if carried_graph:
        r = s.post(f"{BASE}/api/saved_graphs/{carried_graph}/load_into/{doc}",
                   json={'trust': False}, timeout=180).json()
        inherited = r.get('nodes') or 0

    s.post(f"{BASE}/submit", data=dict(user_message='', is_user='false',
                                       max_turns=str(max_calls)), timeout=120)
    solved, turns = False, 0
    for i in range(max_calls):
        turns = i + 1
        try:
            r = s.get(f"{BASE}/generate", timeout=300)
        except requests.RequestException:
            break
        if r.status_code != 200:
            break
        if any('Task complete' in str(l) for l in r.json().get('logs', [])):
            solved = True
            break

    tokens = 0
    sources = collections.Counter()
    trust_low = 1.0
    try:
        rows = list(csv.DictReader(io.StringIO(
            s.get(f"{BASE}/export_run_data", timeout=60).text)))
    except requests.RequestException:
        rows = []
    for row in rows:
        try:
            tokens += int(row.get('input_tokens') or 0)
        except ValueError:
            pass
        sources[row.get('aim_source') or 'unset'] += 1
        try:
            trust_low = min(trust_low, float(row.get('graph_trust') or 1.0))
        except ValueError:
            pass

    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    doc = ags[0].get('id') or ags[0].get('agent_id')
    saved = s.post(f"{BASE}/api/saved_graphs/from_agent/{doc}",
                   json={'name': label}, timeout=60).json()
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'chat_cache',
                        'graphs', f'{doc}_graph.graphml')
    return dict(case=case, solved=int(solved), turns=turns,
                inherited=inherited, input_tokens=tokens,
                graph_path=sources.get('graph_path', 0),
                trust_low=round(trust_low, 3),
                minutes=round((time.time() - t0) / 60, 1),
                graph_id=(saved.get('graph') or {}).get('graph_id', ''),
                path=path)


def build_plan():
    plan = []
    for i, case in enumerate(GATE_SEQ):
        plan.append(dict(phase='gate', arm='carried', position=i, case=case,
                         knobs={'route_min_score': 0.33}))
    for arm in ('carried', 'fresh'):
        for i, case in enumerate(SHIFT_SEQ):
            plan.append(dict(phase='shift', arm=arm, position=i, case=case,
                             knobs={}))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--out', default='studies/results/ddx_confirm.json')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--shift-only', action='store_true',
                    help='skip the gate phase (already settled: 0.40 stays)')
    a = ap.parse_args()

    plan = build_plan()
    if a.shift_only:
        plan = [j for j in plan if j['phase'] == 'shift']
    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} recorded', flush=True)
    plan = plan[len(rows):]
    print(f'{len(plan)} runs to go\n', flush=True)

    carried = {}
    for r in rows:
        if r['arm'] == 'carried' and r.get('graph_id'):
            carried[r['phase']] = r['graph_id']

    for job in plan:
        if not alive():
            sys.exit('app not responding; rerun with --resume')
        label = f"confirm-{job['phase']}-{job['arm']}-{job['position']}"
        r = run_one(job['case'], label, a.max_calls,
                    carried.get(job['phase']) if job['arm'] == 'carried' else None,
                    job['knobs'])
        r.update({k: v for k, v in job.items() if k != 'knobs'})
        if job['arm'] == 'carried' and r.get('graph_id'):
            carried[job['phase']] = r['graph_id']
        rows.append(r)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f"[{job['phase']:<5} {job['arm']:<7} {job['position']}] "
              f"{job['case'][:22]:<24} solved={r['solved']} turns={r['turns']:<3} "
              f"route={r['graph_path']:<3} trust_low={r['trust_low']} "
              f"{r['minutes']}min", flush=True)

    print('\n--- gate confirmation (window 3, carried, route gate 0.33) ---')
    rs = [r for r in rows if r['phase'] == 'gate']
    sv = [r for r in rs if r['solved']]
    t = round(sum(r['turns'] for r in sv) / len(sv), 1) if sv else None
    print(f"  route_easier  solved {len(sv)}/{len(rs)}  turns-when-solved {t}  "
          f"routed {sum(r['graph_path'] for r in rs)}")
    print("  (baseline from ddx_tune: 5/8, 39.8 turns, 71 routed)")

    print('--- distribution shift (window 3, gate 0.40) ---')
    for arm in ('carried', 'fresh'):
        for half, lo, hi in (('familiar', 0, 4), ('shifted ', 4, 8)):
            rs = [r for r in rows if r['phase'] == 'shift' and r['arm'] == arm
                  and lo <= r['position'] < hi]
            if not rs:
                continue
            sv = [r for r in rs if r['solved']]
            t = round(sum(r['turns'] for r in sv) / len(sv), 1) if sv else None
            print(f"  {arm:<8} {half}  solved {len(sv)}/{len(rs)}  "
                  f"turns {t}  routed {sum(r['graph_path'] for r in rs)}  "
                  f"min-trust {min((r['trust_low'] for r in rs), default=1.0)}")
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
