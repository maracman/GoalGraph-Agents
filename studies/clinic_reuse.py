#!/usr/bin/env python3
"""Sixteen clinic patients, one carried graph - the paper's long sequence.

Patients cycle the seven hand-authored disorders in interleaved order, with
repeats of a disorder appearing as different presentations (the `#k` variant
suffix). The report's per-condition table - first presentation versus later -
comes from this run, as does the accumulated-graph figure.

    python3 studies/clinic_reuse.py
    python3 studies/clinic_reuse.py --resume
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
SEQUENCE = [
    'alcohol_related_low_mood#0', 'thyroid_disturbance#0',
    'burnout_exhaustion#0', 'depressive_episode#0',
    'generalised_anxiety#0', 'alcohol_related_low_mood#1',
    'panic_with_avoidance#0', 'obsessive_checking#0',
    'thyroid_disturbance#4', 'depressive_episode#7',
    'burnout_exhaustion#2', 'alcohol_related_low_mood#2',
    'panic_with_avoidance#1', 'generalised_anxiety#2',
    'obsessive_checking#2', 'depressive_episode#12',
]


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
    contested = sum(1 for _, _, x in G.edges(data=True) if x.get('contested'))
    revisited = sum(1 for _, _, x in G.edges(data=True)
                    if int(x.get('visits') or 1) > 1)
    starts = [n for n in G.nodes if str(n) == 'start'] or \
             [n for n in G.nodes if G.in_degree(n) == 0]
    depth = max((max(nx.single_source_shortest_path_length(G, t).values())
                 for t in starts), default=0)
    return {'nodes': G.number_of_nodes(), 'depth': depth,
            'progress': lab.get('Progress', 0), 'nogo': lab.get('NoGo', 0),
            'go': lab.get('Go', 0), 'contested': contested,
            'revisited': revisited}


def run_one(rule, label, max_calls, carried_graph):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='clinic', keeper_rule=rule, graph_memory_mode='graph',
        context_window='8', graph_recall_k='5', graph_recall_chars='800',
        nogo_ungated='false', judge_delay_seconds='0',
        run_label=label), timeout=180)
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
    trust_low = 1.0
    sources = collections.Counter()
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
    return dict(rule=rule, solved=int(solved), turns=turns,
                inherited=inherited, input_tokens=tokens,
                graph_path=sources.get('graph_path', 0),
                trust_low=round(trust_low, 3),
                minutes=round((time.time() - t0) / 60, 1),
                graph_id=(saved.get('graph') or {}).get('graph_id', ''),
                path=path, **graph_shape(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--out', default='studies/results/final_clinic16.json')
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} recorded', flush=True)
    plan = SEQUENCE[len(rows):]
    print(f'{len(plan)} runs to go\n', flush=True)

    carried = ''
    for r in rows:
        carried = r.get('graph_id') or carried

    for i, rule in enumerate(plan, start=len(rows)):
        if not alive():
            sys.exit('app not responding; rerun with --resume')
        r = run_one(rule, f'clinic16-{i}', a.max_calls, carried)
        r['position'] = i
        carried = r.get('graph_id') or carried
        rows.append(r)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f"[{i+1}/16] {rule:<30} solved={r['solved']} turns={r['turns']:<3} "
              f"in={r['inherited']:<3} route={r['graph_path']:<3} "
              f"trust_low={r['trust_low']} nodes={r.get('nodes')} "
              f"{r['minutes']}min", flush=True)

    base = lambda ru: ru.split('#')[0]                             # noqa: E731
    print('\n--- per condition, first presentation -> later ---')
    seen = collections.defaultdict(list)
    for r in rows:
        seen[base(r['rule'])].append(
            f"{r['turns']}{'' if r['solved'] else '(cap)'}")
    for c, v in seen.items():
        print(f"  {c:<28} {' -> '.join(v)}")
    sv = [r for r in rows if r['solved']]
    print(f"\nsolved {len(sv)}/16; first half "
          f"{sum(r['solved'] for r in rows[:8])}/8, "
          f"second half {sum(r['solved'] for r in rows[8:])}/8")
    print(f'written to {a.out}')


if __name__ == '__main__':
    main()
