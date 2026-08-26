#!/usr/bin/env python3
"""Existence proof: proven options must pay where they are necessary.

five_constraints floors the 3B - zero solves in every configuration ever run.
gpt-5.4 solves it, and its solved runs now stamp each PROOF-verified node
with the move that proved it (the accepted sentence). If the goal-graph
concept works anywhere it must work here: proven options are necessary (the
rider is floored without them), sufficient (three distinct accepted
sentences ARE the solve), and delivered at the rider's level.

Arms (3B acting, gpt-5.4 judging/arbitrating, five_constraints, w24, n=16):
  fresh     no donor - the known floor
  abstract  the same donor with proof_move STRIPPED - the architecture control
  concrete  the donor with proofs

Pre-registered:
  primary   concrete > fresh on solve (Fisher p<0.05)
  second    concrete > abstract (concreteness is the variable)
  mech      rode_proof > 0 in concrete solves
  gates     donor arms inherit; fresh floor holds

The goal-graph framing (docs/FINDINGS.md) says the graph's job is to remove
friction along a path proven in the past. All reuse measured so far was
same-conditions. This study asks whether a path proven by a STRONG model on
one goal removes friction for a WEAK model on an adjacent one - the
paved-once, ridden-many economics the design implies.

Target: two_constraints (fresh 3B solves ~half the time - room both ways).
Donors, built by gpt-5.4 across chained solved runs:

  fresh      no inherited graph
  same       donor proven on two_constraints itself (positive control - if
             THIS does not beat fresh, the design cannot detect transfer and
             the adjacent result is uninterpretable)
  adjacent   donor proven on three_constraints - a superset: both of the
             target's rules plus one more. The claim under test.
  mismatch   a real graph from a different task family (ddx clinic) - same
             structure, wrong content. Separates "proven path helps" from
             "any graph-shaped text helps".

All arms: llama-3.2-3b acting, gpt-5.4 judging and arbitrating the fork
(aim_fork_mode='judgement' - on near-tree graphs the gate fork almost never
fires, so the fork's candidate list is how a paved path physically reaches
the agent), graph memory on, window 24, n=12, arm order rotated per block.

Pre-registered:
  primary    adjacent vs fresh on solve rate (Fisher)
  gate       same vs fresh must show a positive direction for the primary to
             be interpretable
  placebo    mismatch vs fresh (expected ~0)
  mechanism  donor-node uptake: fraction of the run's aims that are donor
             nodes, per arm - transfer without uptake is luck, uptake without
             transfer is friction that wasn't there.

    GOALGRAPH_BASE=http://localhost:5055 python3 studies/constraints_transfer.py \\
        --donor-same <graph_id> --donor-adjacent <graph_id> \\
        --out studies/results/v3_transfer_two.json --resume
"""

import argparse
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
import networkx as nx                                             # noqa: E402

from agent.keeper import make_keeper                              # noqa: E402
from agent import constraint_rules as CR                          # noqa: E402

BASE = os.environ.get('GOALGRAPH_BASE', 'http://localhost:5055')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'src', 'chat_cache')

LEVEL = 'five_constraints'
WINDOW = 24
MODEL = 'meta-llama/llama-3.2-3b-instruct'
ARMS = ['fresh', 'abstract', 'concrete']
DONORS = {}          # arm -> graph_id, filled from CLI
DONOR_NODES = {}     # arm -> normalised node-label set, for uptake scoring


def alive(tries=30, gap=10):
    for _ in range(tries):
        try:
            requests.get(BASE, timeout=15)
            return True
        except requests.RequestException:
            time.sleep(gap)
    return False


def norm(text):
    return re.sub(r'\s+', ' ', str(text or '').strip().lower())


def load_donor_nodes(arm, graph_id):
    path = os.path.join(CACHE, 'saved_graphs', f'{graph_id}.graphml')
    G = nx.read_graphml(path)
    labels = set()
    for n, d in G.nodes(data=True):
        if str(n) == 'start':
            continue
        labels.add(norm(d.get('full_text') or n))
        labels.add(norm(n))
    DONOR_NODES[arm] = labels
    return G.number_of_nodes()


PROOFS = []          # donor proof sentences, for rode_proof scoring


def score_transcript(session_id):
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
    rode = sum(1 for a in accepted
               if any(CR.overlap(a, p) >= 0.85 for p in PROOFS))
    return {'proposals': len(accepted) + len(rejected),
            'accepted': len(accepted), 'rejected': len(rejected),
            'distinct_accepted': len(keeper.distinct_accepted(history)),
            'rode_proof': rode}


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
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='constraints', keeper_rule=LEVEL, graph_memory_mode='graph',
        aim_system='on', aim_fork_mode='judgement', task_variant='',
        context_window=str(WINDOW), graph_recall_k='6',
        graph_recall_chars='1200', judge_delay_seconds='0',
        run_label=label), timeout=180)
    got = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    if (got.get('aim_fork_mode') != 'judgement'
            or got.get('graph_memory_mode') != 'graph'):
        sys.exit(f'server did not accept the treatment config (reports '
                 f'{got.get("aim_fork_mode")!r}/{got.get("graph_memory_mode")!r})')

    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)
    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    doc = ags[0].get('id') or ags[0].get('agent_id')
    for extra in ags[1:]:
        aid = extra.get('id') or extra.get('agent_id')
        if not aid:
            continue
        resp = s.post(f"{BASE}/toggle_agent_mute", data={'agent_id': aid},
                      timeout=60)
        if not (resp.ok and (resp.json() or {}).get('muted') is True):
            sys.exit(f'could not mute agent {aid}')

    inherited = 0
    if arm in DONORS:
        r = s.post(f"{BASE}/api/saved_graphs/{DONORS[arm]}/load_into/{doc}",
                   json={'trust': False, 'prune_to': 500}, timeout=180).json()
        inherited = r.get('nodes') or 0
        if not inherited:
            sys.exit(f'donor {DONORS[arm]} loaded 0 nodes into {label}')

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

    donor_labels = DONOR_NODES.get(arm, set())
    aims = {norm(r.get('aim')) for r in rows if (r.get('aim') or '').strip()}
    donor_aims = sum(1 for a in aims if a in donor_labels)
    forks = [r for r in rows if (r.get('fork_outcome') or '')]

    session_id = s.get(f"{BASE}/get_session_id", timeout=60).json()['session_id']
    scored = score_transcript(session_id)
    if scored is None:
        lost = 1
        scored = {k: None for k in ('proposals', 'accepted', 'rejected',
                                    'distinct_accepted', 'rode_proof')}
    return dict(
        arm=arm, label=label, solved=int(solved), turns=turns,
        recorded_turns=len(rows), lost=lost,
        capped=int(turns >= max_calls and not solved),
        inherited=inherited, distinct_aims=len(aims), donor_aims=donor_aims,
        fork_ran=len(forks),
        fork_graph=sum(1 for r in forks if r['fork_outcome'] == 'graph_path'),
        input_tokens=total('input_tokens'), output_tokens=total('output_tokens'),
        graph_contribution_chars=total('graph_contribution_chars'),
        minutes=round((time.time() - t0) / 60, 1), **scored)


def report(rows):
    rows = [r for r in rows if not r.get('lost')]
    if not rows:
        print('\nno completed runs to report')
        return
    print(f'\n{len(rows)} runs: {MODEL} on {LEVEL}, window {WINDOW}, '
          f'judgement fork, strong judge\n')
    print(f"{'arm':<10}{'solved':<9}{'turns/solve':<13}{'capped':<8}"
          f"{'inherited':<11}{'donor aims':<12}{'fork->graph':<13}"
          f"{'contrib/run':<12}")
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if not rs:
            continue
        sv = [r for r in rs if r['solved']]
        solve_cell = f'{len(sv)}/{len(rs)}'
        when = round(st.mean([r['turns'] for r in sv]), 1) if sv else '-'
        cap = f"{sum(r['capped'] for r in rs)}/{len(rs)}"
        inh = round(st.mean([r['inherited'] for r in rs]), 1)
        da = round(st.mean([r['donor_aims'] for r in rs]), 1)
        fg = sum(r['fork_graph'] for r in rs)
        fr = sum(r['fork_ran'] for r in rs)
        contrib = round(st.mean([r['graph_contribution_chars'] for r in rs]))
        print(f"{arm:<10}{solve_cell:<9}{str(when):<13}{cap:<8}"
              f"{inh:<11}{da:<12}{f'{fg}/{fr}':<13}{contrib:<12}")

    for arm in ('same', 'adjacent', 'mismatch'):
        rs = [r for r in rows if r['arm'] == arm]
        if rs and not any(r['inherited'] for r in rs):
            print(f'\n!! {arm}: nothing was ever inherited.')
    sa = [r for r in rows if r['arm'] == 'same']
    ad = [r for r in rows if r['arm'] == 'adjacent']
    if sa and ad:
        if not any(r['donor_aims'] for r in sa + ad):
            print('\n!! no donor node was ever adopted as an aim in the donor '
                  'arms - the paved path never reached the road.')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--max-calls', type=int, default=40)
    ap.add_argument('--replicates', type=int, default=16)
    ap.add_argument('--arms', nargs='+', default=list(ARMS))
    ap.add_argument('--donor-concrete', required=True)
    ap.add_argument('--donor-abstract', required=True)
    ap.add_argument('--out', default='studies/results/v3_concrete.json')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--report-only', action='store_true')
    a = ap.parse_args()

    if a.report_only:
        with open(a.out) as f:
            report(json.load(f))
        return

    DONORS['concrete'] = a.donor_concrete
    DONORS['abstract'] = a.donor_abstract
    for arm, gid in DONORS.items():
        n = load_donor_nodes(arm, gid)
        print(f'donor {arm:<9} {gid[:24]:<26} {n} nodes', flush=True)
    import networkx as _nx
    _G = _nx.read_graphml(os.path.join(
        CACHE, 'saved_graphs', f'{a.donor_concrete}.graphml'))
    PROOFS.extend(str(d['proof_move']) for _n, d in _G.nodes(data=True)
                  if d.get('proof_move'))
    print(f'{len(PROOFS)} proof sentences loaded for rode_proof', flush=True)

    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f'GoalGraph is not running at {BASE}')

    plan = []
    for rep in range(a.replicates):
        arms = [x for x in ARMS if x in a.arms]
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
        return f'cx-{arm}-r{rep}'

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
        print(f"[{i+1}/{len(plan)}] {arm:<9} r{rep} solved={r['solved']} "
              f"turns={r['turns']:<3} inh={r['inherited']:<4} "
              f"donor_aims={r['donor_aims']} fork_graph={r['fork_graph']} "
              f"{r['minutes']}min", flush=True)

    report(rows)
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
