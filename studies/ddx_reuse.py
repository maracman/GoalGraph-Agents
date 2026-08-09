#!/usr/bin/env python3
"""Does a carried graph beat starting fresh, on the same patients in the same order?

The context sweep answered a different question - whether recall of ruled-out
aims helps within one interview - and answered it no. Routing never engaged
there because every run began with an empty graph: `find_path_to_goal` had
nothing to search. Routing needs an *accumulated* graph, which means the
comparison that can actually show the architecture working is across patients,
not within one.

Two arms, identical patient sequence:

  carried   the clinician's graph is saved after each patient and loaded into
            the next (trust:False, so inherited aims are marked unverified)
  fresh     every patient starts with an empty graph

The sequence's back half repeats the front half's conditions as different
presentations, so the carried arm's graph has routes worth taking exactly when
the repeats arrive. If the architecture works, the two arms should look alike
on the first half and diverge on the second - and `graph_path` should be
nonzero in the carried arm's later runs, which is the direct evidence routing
engaged at all.

    python3 studies/ddx_reuse.py --max-calls 70
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

# Front half builds the graph; back half repeats the same conditions so the
# carried arm has routes to reuse. Different variants would be better still,
# but the ddx task keys presentations off the condition name alone.
# Only cases that actually solve: across 32 prior runs, HIV solved 9/14 and
# Influenza 5/14, while Sarcoidosis went 1/14 and SLE 0/4. A sequence half
# composed of unwinnable cases drowns any arm difference in shared failure -
# checklist item 2, learned the hard way twice.
SEQUENCE = ['HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza']


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


def run_one(case, label, max_calls, carried_graph, window=4):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='ddx_clinic', keeper_rule=case, graph_memory_mode='graph',
        context_window=str(window), graph_recall_k='5',
        graph_recall_chars='800', nogo_ungated='false',
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

    try:
        text = s.get(f"{BASE}/export_run_data", timeout=60).text
        rows = list(csv.DictReader(io.StringIO(text)))
    except requests.RequestException:
        rows = []
    tokens = 0
    sources = collections.Counter()
    trust_low = 1.0
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
    graph_id = (saved.get('graph') or {}).get('graph_id', '')

    return dict(case=case, label=label, solved=int(solved), turns=turns,
                inherited=inherited, input_tokens=tokens,
                graph_path=sources.get('graph_path', 0),
                carried=sources.get('carried', 0),
                llm_subgoal=sources.get('llm_subgoal', 0),
                trust_low=round(trust_low, 3),
                minutes=round((time.time() - t0) / 60, 1),
                graph_id=graph_id, path=path, **graph_shape(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--window', type=int, default=4)
    ap.add_argument('--out', default='studies/results/ddx_reuse.json')
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()

    plan = [('carried', i, c) for i, c in enumerate(SEQUENCE)] + \
           [('fresh', i, c) for i, c in enumerate(SEQUENCE)]

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} runs already recorded', flush=True)
    plan = plan[len(rows):]
    print(f'{len(plan)} runs to go\n', flush=True)

    # rebuild the carried-graph pointer if resuming mid-arm
    carried = ''
    for r in rows:
        if r['arm'] == 'carried':
            carried = r.get('graph_id') or carried

    for arm, idx, case in plan:
        if not alive():
            sys.exit('app not responding; rerun with --resume')
        label = f'reuse-{arm}-{idx}'
        r = run_one(case, label, a.max_calls,
                    carried if arm == 'carried' else None, window=a.window)
        r['arm'], r['position'] = arm, idx
        if arm == 'carried':
            carried = r.get('graph_id') or carried
        rows.append(r)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f"[{arm:<7} {idx}] {case[:24]:<26} solved={r['solved']} "
              f"turns={r['turns']:<3} in={r['inherited']:<3} "
              f"route={r['graph_path']:<3} trust_low={r['trust_low']} "
              f"nodes={r.get('nodes')} {r['minutes']}min", flush=True)

    # summary: first half vs second half, per arm
    print('\n--- reuse ---')
    for arm in ('carried', 'fresh'):
        for half, lo, hi in (('build ', 0, 4), ('repeat', 4, 8)):
            rs = [r for r in rows if r['arm'] == arm and lo <= r['position'] < hi]
            if not rs:
                continue
            solved = [r for r in rs if r['solved']]
            t = round(sum(r['turns'] for r in solved) / len(solved), 1) if solved else None
            print(f"  {arm:<8} {half}  solved {len(solved)}/{len(rs)}  "
                  f"turns-when-solved {t}  "
                  f"route-aims {sum(r['graph_path'] for r in rs)}")
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
