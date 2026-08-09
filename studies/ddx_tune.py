#!/usr/bin/env python3
"""Fill the window grid's middle, then screen the tuning knobs.

Two phases, one resumable queue:

  windows   carried and fresh at window 3, full eight-patient sequences. The
            existing grid has only the corners - window 2 (a floor, where only
            a carried run ever solved) and window 4 (workable, where carrying
            buys reliability). The transition between them is where the
            graph's leverage should peak, and it is unmapped.

  knobs     four-patient carried sequences at window 4, one knob moved at a
            time from its default. This is a coarse screen, not an
            optimisation: four runs per cell can rank configurations and
            catch a knob that is badly wrong, and cannot resolve small
            differences. Anything promising earns a longer run.

              baseline        the defaults as committed
              route_easier    route_min_score 0.40 -> 0.33
              trust_gentler   trust_decay 0.60 -> 0.80 (more second chances)
              abandon_faster  persistence_min 3 -> 2, patience_max 6 -> 4

    python3 studies/ddx_tune.py            # runs both phases
    python3 studies/ddx_tune.py --resume
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
LONG = ['HIV (initial infection)', 'Influenza'] * 4     # eight patients
SHORT = ['HIV (initial infection)', 'Influenza'] * 2    # four, for the screen

KNOB_CONFIGS = {
    'baseline': {},
    'route_easier': {'route_min_score': 0.33},
    'trust_gentler': {'trust_decay': 0.80},
    'abandon_faster': {'persistence_min': 2, 'patience_max': 4},
}


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def graph_shape(path):
    if not os.path.exists(path):
        return {}
    G = nx.read_graphml(path)
    lab = collections.Counter(x.get('label') for _, _, x in G.edges(data=True))
    return {'nodes': G.number_of_nodes(),
            'progress': lab.get('Progress', 0), 'nogo': lab.get('NoGo', 0),
            'go': lab.get('Go', 0)}


def run_one(case, label, window, max_calls, carried_graph, knobs):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    form = dict(run_type='ddx_clinic', keeper_rule=case,
                graph_memory_mode='graph', context_window=str(window),
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
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'chat_cache',
                        'graphs', f'{doc}_graph.graphml')
    saved = s.post(f"{BASE}/api/saved_graphs/from_agent/{doc}",
                   json={'name': label}, timeout=60).json()
    return dict(case=case, solved=int(solved), turns=turns,
                inherited=inherited, input_tokens=tokens,
                graph_path=sources.get('graph_path', 0),
                trust_low=round(trust_low, 3),
                minutes=round((time.time() - t0) / 60, 1),
                graph_id=(saved.get('graph') or {}).get('graph_id', ''),
                **graph_shape(path))


def build_plan():
    plan = []
    for arm in ('carried', 'fresh'):
        for i, case in enumerate(LONG):
            plan.append(dict(phase='w3', arm=arm, config='baseline', window=3,
                             position=i, case=case))
    for config in KNOB_CONFIGS:
        for i, case in enumerate(SHORT):
            plan.append(dict(phase='knobs', arm='carried', config=config,
                             window=4, position=i, case=case))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--out', default='studies/results/ddx_tune.json')
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()

    plan = build_plan()
    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} recorded', flush=True)
    plan = plan[len(rows):]
    print(f'{len(plan)} runs to go\n', flush=True)

    # carried pointers per (phase, arm/config) chain
    carried = {}
    for r in rows:
        key = (r['phase'], r['arm'], r['config'])
        if r['arm'] == 'carried' and r.get('graph_id'):
            carried[key] = r['graph_id']

    for job in plan:
        if not alive():
            sys.exit('app not responding; rerun with --resume')
        key = (job['phase'], job['arm'], job['config'])
        label = f"tune-{job['phase']}-{job['config']}-{job['arm']}-{job['position']}"
        r = run_one(job['case'], label, job['window'], a.max_calls,
                    carried.get(key) if job['arm'] == 'carried' else None,
                    KNOB_CONFIGS[job['config']])
        r.update(job)
        if job['arm'] == 'carried' and r.get('graph_id'):
            carried[key] = r['graph_id']
        rows.append(r)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f"[{job['phase']:<5} {job['config']:<14} {job['arm']:<7} "
              f"{job['position']}] solved={r['solved']} turns={r['turns']:<3} "
              f"route={r['graph_path']:<3} trust_low={r['trust_low']} "
              f"{r['minutes']}min", flush=True)

    print('\n--- window 3 ---')
    for arm in ('carried', 'fresh'):
        rs = [r for r in rows if r['phase'] == 'w3' and r['arm'] == arm]
        sv = [r for r in rs if r['solved']]
        t = round(sum(r['turns'] for r in sv) / len(sv), 1) if sv else None
        print(f"  {arm:<8} solved {len(sv)}/{len(rs)}  turns-when-solved {t}  "
              f"routed {sum(r['graph_path'] for r in rs)}")
    print('--- knob screen (window 4, carried, four patients) ---')
    for config in KNOB_CONFIGS:
        rs = [r for r in rows if r['phase'] == 'knobs' and r['config'] == config]
        sv = [r for r in rs if r['solved']]
        t = round(sum(r['turns'] for r in sv) / len(sv), 1) if sv else None
        print(f"  {config:<15} solved {len(sv)}/{len(rs)}  "
              f"turns-when-solved {t}  routed {sum(r['graph_path'] for r in rs)}  "
              f"min-trust {min((r['trust_low'] for r in rs), default=1.0)}")
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
