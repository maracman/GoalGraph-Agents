#!/usr/bin/env python3
"""Who should arbitrate the route-or-invent fork?

A first pass (studies/results/v2_scratchpad_w3.json) found the scratchpad arm
routing a third as much as the gate, and solving more often - but it could not
support either claim. Four things were wrong with it, and each is fixed here,
because each on its own would force the study to be run again:

  1. The graph was an OUTCOME of the arm. Each arm carried its own lineage, so
     the arm that ran longer built a bigger graph and had more to route through:
     the gate arm inherited 175 nodes across the study against the scratchpad's
     122. The primary metric was confounded with run length. Here every run
     inherits the SAME fixed graph, so the graph is an input.

  2. It could not tell "let the agent decide" from "let the agent decide with a
     note". The treatment got an extra reasoning step the control never had, so
     any difference might have been the call rather than the memory. The
     judgement arm gets the identical fork with no scratchpad, isolating it.

  3. A decline was uninterpretable, and the fork was usually offered nothing to
     decline. Measured on the fixed graph below: the nearest-goal node is found
     easily (similarity 0.515), but a directed path to it exists from only 6 of
     53 nodes - and on the 43-node graph the runs inherit, a walkable path is
     offered from 1 sampled node in 14 - because the graph accumulates as a
     near-tree and find_path_to_goal
     wants that node to be a DESCENDANT of wherever the agent stands. Offering
     only path candidates left the fork with nothing to choose between on nine
     turns in ten. It now also sees the most relevant live aims anywhere in the
     graph, and records which kind it took, so taking a walkable path stays
     countable separately and comparable with every earlier result.

  4. It was underpowered and unpaired. 4/8 vs 7/8 is p=0.28. Here three arms
     see the same patients under the same pinned candidate ordering, replicated,
     which both raises n and removes candidate-order variance from the contrast.

Arms, differing only in who settles the fork:

  gate        similarity * trust >= route_min_score, as shipped
  judgement   the agent picks from the same candidates, conversation only
  scratchpad  as judgement, plus its own running note

Primary metric is routed aims. Then the decline rate given a real route, solve
rate, turns-when-solved, never-commit, and tokens.

    GOALGRAPH_BASE=http://localhost:5055 python3 studies/ddx_fork.py \\
        --out studies/results/v3_fork_w3.json --resume
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
import networkx as nx                                             # noqa: E402

from agent import ddx_rules as DX                                 # noqa: E402

BASE = os.environ.get('GOALGRAPH_BASE', 'http://localhost:5055')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'src', 'chat_cache')

ARMS = ('gate', 'judgement', 'scratchpad')
CLINICIAN = 'Dr Nazari'

SEQUENCE = ['HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza',
            'HIV (initial infection)', 'Influenza']

# fork-gate-7: 54 nodes as saved, built by the unmodified gate over a full
# eight-patient sequence. Chosen deliberately - it is the richest route
# structure on hand, and being gate-built it is the control's own habitat, so
# it favours the arm expected to route most. A graph offering nothing to route
# through would make every arm look identical and prove nothing.
#
# Every run actually inherits 43 of those nodes: prune_for_transfer drops the
# 11 run-scoped NoGo aims on any transfer, before the cap is consulted, because
# 'you already asked that' is a fact about one conversation. It is deterministic
# and identical for all three arms. It also means graph recall starts each run
# with nothing and accumulates its own refutations, so an early
# graph_contribution_chars of 0 is expected rather than a failure.
FIXED_GRAPH = 'graph_4a8002e6-3937-4283-bffd-269a888068a3'


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
    return {'nodes': G.number_of_nodes(), 'edges': G.number_of_edges(),
            'progress': lab.get('Progress', 0), 'nogo': lab.get('NoGo', 0),
            'go': lab.get('Go', 0)}


def score_history(history, case):
    """Every claim the clinician made, not just the first.

    Recording only the first mislabels a run that commits wrongly and then
    corrects itself - which happened in the first pass, where a solved run had
    claimed Influenza twice before reaching HIV.
    """
    want = DX.base_case(case)
    claims = [c for speaker, message in history if speaker == CLINICIAN
              for c in [DX.diagnosis_claimed(message)] if c]
    if not claims:
        return {'committed': 0, 'claim_first': '', 'claim_last': '',
                'claims_n': 0, 'claim_right': 0, 'wrong_first': 0}
    return {'committed': 1, 'claim_first': claims[0], 'claim_last': claims[-1],
            'claims_n': len(claims), 'claim_right': int(claims[-1] == want),
            'wrong_first': int(claims[0] != want)}


def commitment(session_id, case):
    path = os.path.join(CACHE, f'{session_id}_state.json')
    if not os.path.exists(path):
        return {'committed': None, 'claim_first': '', 'claim_last': '',
                'claims_n': None, 'claim_right': None, 'wrong_first': None}
    with open(path) as f:
        return score_history(json.load(f).get('session_history', []), case)


def run_one(case, arm, label, salt, max_calls, window, recall_k, recall_chars):
    t0 = time.time()
    s = requests.Session()
    s.get(BASE, timeout=60)
    s.post(f"{BASE}/update_user_settings", data=dict(
        run_type='ddx_clinic', keeper_rule=case, graph_memory_mode='graph',
        context_window=str(window), graph_recall_k=str(recall_k),
        graph_recall_chars=str(recall_chars), nogo_ungated='false',
        aim_fork_mode=arm, order_salt=salt, judge_delay_seconds='0',
        run_label=label), timeout=180)

    # A mode the server does not know is ignored, and the run silently becomes
    # another copy of whatever was set last. That looks like a result and is
    # not one, so it stops the study rather than being written to the file.
    got = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    if got.get('aim_fork_mode') != arm or got.get('order_salt') != salt:
        sys.exit(f'server did not accept aim_fork_mode={arm!r} / order_salt='
                 f'{salt!r} (it reports {got.get("aim_fork_mode")!r} / '
                 f'{got.get("order_salt")!r}) - it is running code that '
                 f'predates them. Restart it.')

    s.post(f"{BASE}/reset_run_trail", data={'run_label': label}, timeout=60)

    ags = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
    ags = ags if isinstance(ags, list) else ags.get('agents', [])
    doc = ags[0].get('id') or ags[0].get('agent_id')
    # prune_to defaults to 40 on the server, which would silently hand every
    # run a different graph from the one whose reachability was measured.
    r = s.post(f"{BASE}/api/saved_graphs/{FIXED_GRAPH}/load_into/{doc}",
               json={'trust': False, 'prune_to': 500}, timeout=180).json()
    inherited = r.get('nodes') or 0
    if not inherited:
        sys.exit(f'the fixed graph {FIXED_GRAPH} loaded 0 nodes into {label}. '
                 f'Every run would start empty and nothing could route.')

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

    sources = collections.Counter(r.get('aim_source') or 'unset' for r in rows)
    forks = [r for r in rows if (r.get('fork_outcome') or '')]
    outcome = collections.Counter(r['fork_outcome'] for r in forks)

    def as_int(row, col):
        try:
            return int(row.get(col) or 0)
        except ValueError:
            return 0

    # The decline rate only means something where a real route was offered.
    # A directed path to the goal-like node exists from about a ninth of the
    # graph, so most forks are choosing among aims the graph knows but cannot
    # walk to. Counted separately: taking a genuine path is the narrow sense of
    # routing, directly comparable to the gate and to every prior result.
    with_path = [r for r in forks if as_int(r, 'fork_path_offered') == 1]
    took_with_path = sum(1 for r in with_path if r['fork_outcome'] == 'graph_path')
    kinds = collections.Counter(r.get('fork_choice_kind') or ''
                                for r in forks if r['fork_outcome'] == 'graph_path')

    contrib = [as_int(r, 'graph_contribution_chars') for r in rows]

    trust = []
    for row in rows:
        if row.get('agent') != CLINICIAN:
            continue
        try:
            trust.append(float(row.get('graph_trust')))
        except (TypeError, ValueError):
            pass
    trust = [t for t in trust if t == t]

    session_id = s.get(f"{BASE}/get_session_id", timeout=60).json()['session_id']
    # Re-read: candidate_order is decided server-side inside /generate, so the
    # settings fetched before the run never carry it.
    after = s.get(f"{BASE}/get_session_settings", timeout=60).json()['settings']
    order = (after.get('candidate_order') or [])
    path = os.path.join(CACHE, 'graphs', f'{doc}_graph.graphml')

    return dict(
        case=case, arm=arm, label=label, salt=salt, solved=int(solved),
        turns=turns, recorded_turns=len(rows), lost=lost, inherited=inherited,
        capped=int(turns >= max_calls and not solved),
        routed=sources.get('graph_path', 0),
        carried=sources.get('carried', 0),
        llm_subgoal=sources.get('llm_subgoal', 0),
        fork_ran=len(forks),
        fork_routed=outcome.get('graph_path', 0),
        fork_invented=outcome.get('carried', 0),
        fork_fell_through=outcome.get('fell_through', 0),
        fork_with_path=len(with_path),
        fork_took_with_path=took_with_path,
        took_path=kinds.get('path', 0),
        took_neighbour=kinds.get('neighbour', 0),
        took_similar=kinds.get('similar', 0),
        fork_candidates_mean=(round(st.mean([as_int(r, 'fork_candidates')
                                             for r in forks]), 2)
                              if forks else 0),
        fork_chars=total('fork_context_chars'),
        input_tokens=total('input_tokens'), output_tokens=total('output_tokens'),
        contrib_mean=round(st.mean(contrib), 1) if contrib else 0,
        trust_low=round(min(trust), 3) if trust else None,
        trust_latched=int(bool(trust) and min(trust) < 1.0),
        minutes=round((time.time() - t0) / 60, 1),
        candidate_first=(order[0] if order else ''),
        **commitment(session_id, case), **graph_shape(path))


def report(rows):
    rows = [r for r in rows if not r.get('lost')]
    if not rows:
        print('\nno completed runs to report')
        return
    sizes = {r['inherited'] for r in rows}
    print(f'\n{len(rows)} runs, every one starting from the same '
          f'{sizes.pop() if len(sizes) == 1 else sorted(sizes)}-node graph\n')
    print(f"{'arm':<12}{'ROUTED':<9}{'solved':<9}{'turns/solve':<13}"
          f"{'capped':<9}{'never commit':<14}{'in tok/turn':<13}"
          f"{'out tok/turn':<14}{'mem chars/turn':<15}")
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if not rs:
            continue
        solved = [r for r in rs if r['solved']]
        turns = sum(r['recorded_turns'] for r in rs) or 1
        routed = sum(r['routed'] for r in rs)
        solve_cell = f'{len(solved)}/{len(rs)}'
        when = round(st.mean([r['turns'] for r in solved]), 1) if solved else '-'
        cap_cell = f'{sum(r["capped"] for r in rs)}/{len(rs)}'
        silent_cell = f'{sum(1 for r in rs if not r.get("committed"))}/{len(rs)}'
        tok_in = round(sum(r['input_tokens'] for r in rs) / turns)
        tok_out = round(sum(r['output_tokens'] for r in rs) / turns)
        mem = round(st.mean([r['contrib_mean'] for r in rs]), 1)
        print(f"{arm:<12}{routed:<9}{solve_cell:<9}{str(when):<13}"
              f"{cap_cell:<9}{silent_cell:<14}{tok_in:<13}{tok_out:<14}{mem:<15}")

    print('\nwhat the fork did — and what it did when a real route was on offer')
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if not rs or arm == 'gate':
            continue
        ran = sum(r['fork_ran'] for r in rs)
        wp = sum(r['fork_with_path'] for r in rs)
        took = sum(r['fork_took_with_path'] for r in rs)
        fell = sum(r['fork_fell_through'] for r in rs)
        cand = round(st.mean([r['fork_candidates_mean'] for r in rs]), 2)
        print(f"  {arm:<12} ran {ran} (fell back {fell}), candidates/fork {cand}")
        # Two different questions, and conflating them inverts the reading.
        # 'took something' says the fork used the graph at all; 'took the path'
        # says it chose the one candidate the gate is capable of offering.
        p_any = (100.0 * took / wp) if wp else 0
        took_path = sum(r['took_path'] for r in rs)
        p_path = (100.0 * took_path / wp) if wp else 0
        print(f"  {'':<12} a walkable path was on offer {wp} times: it took some "
              f"graph aim {took} ({p_any:.0f}%), and the path ITSELF "
              f"{took_path} ({p_path:.0f}%)")
        print(f"  {'':<12} everything it took: {took_path} walkable path, "
              f"{sum(r['took_neighbour'] for r in rs)} reached-from-here, "
              f"{sum(r['took_similar'] for r in rs)} known-but-unwalkable "
              f"(the gate can only ever offer the first)")

    print('\ntrust trajectory (clinician rows only)')
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        lows = [r['trust_low'] for r in rs if r.get('trust_low') is not None]
        if lows:
            print(f"  {arm:<12} latched {sum(1 for x in lows if x < 1.0)}/{len(lows)}, "
                  f"lowest seen {min(lows)}")

    print('\ncommitment')
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if not rs:
            continue
        print(f"  {arm:<12} committed {sum(r.get('committed') or 0 for r in rs)}/{len(rs)}, "
              f"ended right {sum(r.get('claim_right') or 0 for r in rs)}/{len(rs)}, "
              f"wrong first {sum(r.get('wrong_first') or 0 for r in rs)}, "
              f"claims/run {round(st.mean([r.get('claims_n') or 0 for r in rs]), 1)}")

    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        if rs and st.mean([r['contrib_mean'] for r in rs]) == 0:
            print(f"\n!! {arm}: nothing reached the prompt. This arm tested nothing.")
        if rs and arm != 'gate' and sum(r['fork_ran'] for r in rs) == 0:
            print(f"\n!! {arm}: the fork never ran. This arm is the gate under "
                  f"another name.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--window', type=int, default=3)
    ap.add_argument('--max-calls', type=int, default=70)
    ap.add_argument('--recall-k', type=int, default=5)
    ap.add_argument('--recall-chars', type=int, default=800)
    ap.add_argument('--replicates', type=int, default=3,
                    help='repeats of the 8-patient sequence per arm')
    ap.add_argument('--patients', type=int, default=None)
    ap.add_argument('--arms', nargs='+', default=list(ARMS))
    ap.add_argument('--out', default='studies/results/v3_fork_w3.json')
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

    seq = SEQUENCE[:a.patients] if a.patients else SEQUENCE
    # Blocked by (replicate, patient) with the arms adjacent inside each block:
    # the three arms then face the same patient under the same pinned candidate
    # ordering, minutes apart, so drift over the hours this takes cannot land on
    # one arm more than another.
    # Blocked by (replicate, patient), arms adjacent inside each block so the
    # three face the same patient minutes apart. The order WITHIN a block is
    # rotated by block index rather than fixed: a fixed gate -> judgement ->
    # scratchpad order would give one arm the freshest provider state in every
    # block for the whole study, which is an arm-aligned artefact and free to
    # remove.
    plan = []
    for rep in range(a.replicates):
        for pos, case in enumerate(seq):
            block = list(a.arms)
            shift = (rep * len(seq) + pos) % len(block)
            block = block[shift:] + block[:shift]
            for arm in block:
                plan.append((rep, pos, case, arm))

    rows = []
    if a.resume and os.path.exists(a.out):
        with open(a.out) as f:
            rows = json.load(f)
        print(f'resuming: {len(rows)} runs already recorded', flush=True)

    # Resume by label, not by count. A run that was lost to a dropped
    # connection is still appended - it carries lost=1 - so slicing the plan by
    # len(rows) would silently shift every remaining run onto the wrong arm and
    # the whole tail of the study would be mislabelled.
    done = {r.get('label') for r in rows}
    plan = [step for step in plan
            if f'fork3-{step[3]}-r{step[0]}p{step[1]}' not in done]
    lost = [r.get('label') for r in rows if r.get('lost')]
    if lost:
        print(f'{len(lost)} earlier run(s) were lost and are NOT retried: '
              f'{", ".join(lost[:4])}', flush=True)
    print(f'{len(plan)} runs to go\n', flush=True)

    for i, (rep, pos, case, arm) in enumerate(plan):
        if not alive():
            sys.exit(f'app at {BASE} is not responding; rerun with --resume')
        salt = f'blk-{rep}-{pos}'
        r = run_one(case, arm, f'fork3-{arm}-r{rep}p{pos}', salt, a.max_calls,
                    a.window, a.recall_k, a.recall_chars)
        if r.get('lost'):
            print(f'  !! {r["label"]} was lost mid-run; recorded and skipped '
                  f'on resume', file=sys.stderr, flush=True)
        r['replicate'] = rep
        r['position'] = pos
        rows.append(r)

        if r['input_tokens'] == 0 and r['turns'] > 1:
            print(f'  !! {r["label"]} recorded no tokens - provider failing?',
                  file=sys.stderr, flush=True)
            if sum(1 for x in rows[-3:] if x['input_tokens'] == 0) >= 3:
                sys.exit('three consecutive runs recorded nothing; aborting '
                         'rather than writing dead runs to the results file')

        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(rows, f, indent=1)
        print(f"[{i+1}/{len(plan)}] r{rep} p{pos} {arm:<11} {case[:18]:<20} "
              f"solved={r['solved']} turns={r['turns']:<3} "
              f"routed={r['routed']:<3} fork={r['fork_ran']:<3} "
              f"path_offered={r['fork_with_path']:<3} took={r['fork_took_with_path']:<3} "
              f"trust_low={r['trust_low']} {r['minutes']}min", flush=True)

    report(rows)
    print(f'\nwritten to {a.out}')


if __name__ == '__main__':
    main()
