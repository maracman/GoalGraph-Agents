#!/usr/bin/env python3
"""Two experiments on the DDXPlus clinic, driven over HTTP exactly as the UI is.

  --context   how the graph's contribution changes as the episodic window grows.
              If the graph is doing the job claimed for it - carrying verdicts
              past the horizon - its advantage should be largest at a short
              window and shrink toward zero as the window makes it redundant.

  --model     hold the window at a value where performance is mediocre and vary
              the model instead. Distinguishes "the graph substitutes for
              context" from "the graph substitutes for capability", which are
              different claims and are usually conflated.

Both arms share one horizon by construction: `judge_view` and the agent's
window read the same `context_window`, so the graph is the only thing that can
carry information past it.

    python3 studies/ddx_sweep.py --context --reps 3
    python3 studies/ddx_sweep.py --model --reps 3
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import requests                                                   # noqa: E402
import networkx as nx                                             # noqa: E402

BASE = "http://localhost:5000"
CASES = ['HIV (initial infection)', 'Sarcoidosis', 'Influenza',
         'Pancreatic neoplasm', 'SLE', 'Anaphylaxis']


def graph_shape(path):
    if not os.path.exists(path):
        return {}
    G = nx.read_graphml(path)
    lab = collections.Counter(x.get('label') for _, _, x in G.edges(data=True))
    starts = [n for n in G.nodes if str(n) == 'start'] or \
             [n for n in G.nodes if G.in_degree(n) == 0]
    depth = max((max(nx.single_source_shortest_path_length(G, t).values())
                 for t in starts), default=0)
    return {'nodes': G.number_of_nodes(), 'depth': depth,
            'progress': lab.get('Progress', 0), 'nogo': lab.get('NoGo', 0),
            'go': lab.get('Go', 0)}


def alive(tries=30, gap=10):
    """Wait for the app to answer. A sweep is hours long and the app may be
    restarted under it; losing the whole remaining plan to one refused
    connection wastes more than waiting does."""
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def run_one(case, mode, window, model, max_calls, label):
    """One interview. Fresh session, so nothing carries between runs."""
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    if model:
        s.post(f"{BASE}/update_llm_settings",
               json={'provider': 'openai-codex', 'model': model}, timeout=60)
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='ddx_clinic', keeper_rule=case, graph_memory_mode=mode,
        context_window=str(window), graph_recall_k='5',
        graph_recall_chars='800', nogo_ungated='false',
        run_label=label), timeout=180)
    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)
    s.post(f"{BASE}/submit", data=dict(user_message='', is_user='false',
                                       max_turns=str(max_calls)), timeout=120)

    solved, turns = False, 0
    for i in range(max_calls):
        turns = i + 1
        try:
            r = s.get(f"{BASE}/generate", timeout=300)
        except requests.RequestException as e:
            print(f'  [{label}] {e}', file=sys.stderr)
            break
        if r.status_code != 200:
            print(f'  [{label}] HTTP {r.status_code}', file=sys.stderr)
            break
        if any('Task complete' in str(l) for l in r.json().get('logs', [])):
            solved = True
            break

    try:
        text = s.get(f"{BASE}/export_run_data", timeout=60).text
    except requests.RequestException:
        # The app went away mid-run. Report this run as lost rather than
        # taking the rest of the sweep down with it.
        return dict(case=case, mode=mode, window=window,
                    model=model or 'default', solved=0, turns=turns,
                    input_tokens=0, graph_path=0, carried=0, llm_subgoal=0,
                    lost=1, minutes=round((time.time() - t0) / 60, 1))
    rows = list(csv.DictReader(io.StringIO(text)))
    tokens = 0
    sources = collections.Counter()
    for row in rows:
        try:
            tokens += int(row.get('input_tokens') or 0)
        except ValueError:
            pass
        sources[row.get('aim_source') or 'unset'] += 1

    agents = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    agents = agents if isinstance(agents, list) else agents.get('agents', [])
    shape = {}
    if agents:
        aid = agents[0].get('id') or agents[0].get('agent_id')
        shape = graph_shape(os.path.join(
            os.path.dirname(__file__), '..', 'src', 'chat_cache', 'graphs',
            f'{aid}_graph.graphml'))

    return dict(case=case, mode=mode, window=window, model=model or 'default',
                solved=int(solved), turns=turns, input_tokens=tokens,
                graph_path=sources.get('graph_path', 0),
                carried=sources.get('carried', 0),
                llm_subgoal=sources.get('llm_subgoal', 0),
                minutes=round((time.time() - t0) / 60, 1), **shape)


def summarise(rows, by):
    groups = collections.OrderedDict()
    for r in rows:
        groups.setdefault(tuple(r[k] for k in by), []).append(r)
    out = []
    for key, rs in groups.items():
        solved = [r for r in rs if r['solved']]
        out.append({
            **dict(zip(by, key)),
            'n': len(rs),
            'solved': f"{len(solved)}/{len(rs)}",
            'turns_when_solved': round(st.mean([r['turns'] for r in solved]), 1)
            if solved else None,
            'tokens': round(st.mean([r['input_tokens'] for r in rs])),
            'depth': round(st.mean([r.get('depth', 0) or 0 for r in rs]), 1),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--context', action='store_true')
    ap.add_argument('--model', action='store_true')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--windows', nargs='+', type=int, default=[2, 4, 8, 16, 32])
    ap.add_argument('--models', nargs='+',
                    default=['gpt-5.4-mini', 'gpt-5.4', 'gpt-5.5'])
    ap.add_argument('--hold-window', type=int, default=4)
    ap.add_argument('--out', default='studies/results/ddx_sweep.json')
    ap.add_argument('--skip', type=int, default=0,
                    help='resume: skip the first N runs of the plan')
    ap.add_argument('--resume', action='store_true',
                    help='load --out and skip the runs already recorded')
    a = ap.parse_args()

    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f'GoalGraph is not running at {BASE}')

    plan = []
    if a.context:
        for w in a.windows:
            for mode in ('graph', 'none'):
                for rep in range(a.reps):
                    plan.append(dict(case=CASES[rep % len(CASES)], mode=mode,
                                     window=w, model=None,
                                     label=f'ctx-w{w}-{mode}-r{rep}'))
    if a.model:
        for m in a.models:
            for mode in ('graph', 'none'):
                for rep in range(a.reps):
                    plan.append(dict(case=CASES[rep % len(CASES)], mode=mode,
                                     window=a.hold_window, model=m,
                                     label=f'mdl-{m}-{mode}-r{rep}'))

    rows = []
    done = 0
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        done = len(rows)
        print(f'resuming: {done} runs already recorded', flush=True)
    done = max(done, a.skip)
    plan = plan[done:]
    print(f'{len(plan)} runs to go\n', flush=True)
    for i, job in enumerate(plan):
        label = job.pop('label')
        if not alive():
            sys.exit('app at :5000 is not responding; stopping so the '
                     'remaining plan can be resumed with --resume')
        r = run_one(max_calls=a.max_calls, label=label, **job)
        rows.append(r)
        # A run that recorded no turns at all is not a result - it is the
        # provider having failed. Writing those to the results file is how
        # eleven dead runs once got recorded as data; stop instead.
        if r['input_tokens'] == 0 and r['turns'] > 1:
            dead = sum(1 for x in rows[-3:] if x['input_tokens'] == 0)
            print(f'  !! {label} recorded no tokens - provider failing?',
                  file=sys.stderr, flush=True)
            if dead >= 3:
                sys.exit('three consecutive runs recorded nothing; aborting '
                         'rather than writing dead runs to the results file')
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f'[{i+1}/{len(plan)}] {label:<28} solved={r["solved"]} '
              f'turns={r["turns"]:<3} depth={r.get("depth")} '
              f'tok={r["input_tokens"]:<6} {r["minutes"]}min', flush=True)

    print()
    if a.context:
        print('--- context sweep ---')
        for row in summarise([r for r in rows if r['model'] == 'default'],
                             ['window', 'mode']):
            print(f'  window {row["window"]:<3} {row["mode"]:<6} '
                  f'solved {row["solved"]:<6} turns {row["turns_when_solved"]} '
                  f'depth {row["depth"]} tokens {row["tokens"]}')
    if a.model:
        print('--- model sweep ---')
        for row in summarise([r for r in rows if r['model'] != 'default'],
                             ['model', 'mode']):
            print(f'  {row["model"]:<16} {row["mode"]:<6} '
                  f'solved {row["solved"]:<6} turns {row["turns_when_solved"]} '
                  f'depth {row["depth"]} tokens {row["tokens"]}')
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
