#!/usr/bin/env python3
"""The constraints study, driven through GoalGraph itself.

Driven over HTTP exactly as the UI drives it, so what it measures is the
product. Three parts, each closing a gap that would otherwise be a caveat:

  sweep        every memory mode at every window, replicated, so the effect has
               an interval rather than a single number
  completion   runs go long enough to finish, so the measure is turns-to-solve
               rather than a rate at an arbitrary cutoff
  reuse        a second agent starts with the first agent's graph, which is the
               only way to show a route being *reused* rather than merely built

Every setting this sets is one you can set by hand in the Decision Graph panel,
and every number it reads comes from the same CSV the panel's download button
produces. It is the UI, scripted - not a private harness with its own
measurements. Run the app, then:

    python3 studies/constraints_study.py --reps 6 --windows 4 --modes none graph
    python3 studies/constraints_study.py --reuse

Results land in studies/results/.
"""

import argparse
import csv
import os
import io
import json
import statistics as st
import sys
import time

import requests

BASE = "http://localhost:5000"


def post(s, path, **form):
    r = s.post(f"{BASE}{path}", data=form, timeout=180)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    return r.json() if ct.startswith("application/json") else {}


def ensure_single_solver(s):
    """Leave exactly one agent working the task.

    A default session carries two agents, and they alternate turns. On a
    conversation that is the point, but `constraints` is solitaire: one agent
    induces a rule against a keeper. Two agents split the turns *and* the
    memory, because each keeps its own decision graph and recalls only from
    that one. So the graph arm was really two half-graphs, each holding half of
    what had been ruled out, which understates exactly the effect this study is
    trying to measure.
    """
    try:
        agents = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
        agents = agents if isinstance(agents, list) else agents.get("agents", [])
        for extra in agents[1:]:
            aid = extra.get("id") or extra.get("agent_id")
            if aid:
                s.post(f"{BASE}/delete_agent", data={"agent_id": aid}, timeout=60)
        if len(agents) > 1:
            print(f"  (single-solver: removed {len(agents) - 1} extra agent)",
                  flush=True)
    except Exception as e:                                         # noqa: BLE001
        print(f"  could not reduce to one agent: {e}", file=sys.stderr)


def run_one(mode, window, level, max_calls, label, prior_graph=None, verbose=False):
    """One arm. Returns a dict of what happened."""
    s = requests.Session()
    s.get(BASE, timeout=60)
    post(s, "/update_user_settings",
         run_type="constraints", keeper_rule=level,
         graph_memory_mode=mode, context_window=str(window),
         graph_recall_k="4", graph_recall_chars="600",
         nogo_ungated="false", run_label=label)
    post(s, "/reset_run_trail", run_label=label)
    ensure_single_solver(s)

    if prior_graph:
        # Hand this agent the earlier run's graph before it starts, so any
        # advantage it shows comes from inherited knowledge rather than luck.
        # /import_graph only merges two agents inside one session, which is no
        # use across runs; this loads a saved graph into a fresh agent.
        try:
            agents = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
            agents = agents if isinstance(agents, list) else agents.get("agents", [])
            if agents:
                aid = agents[0].get("id") or agents[0].get("agent_id")
                resp = s.post(
                    f"{BASE}/api/saved_graphs/{prior_graph}/load_into/{aid}",
                    json={"trust": True}, timeout=120).json()
                if not resp.get("success"):
                    print(f"  [{label}] load failed: {resp.get('error')}", file=sys.stderr)
                else:
                    print(f"  [{label}] inherited {resp.get('nodes')} nodes",
                          flush=True)
        except Exception as e:                                     # noqa: BLE001
            print(f"  [{label}] could not load prior graph: {e}", file=sys.stderr)

    # max_turns caps the run server-side; without it the session defaults to 12
    # generations and every arm stops at the same turn regardless of the task.
    post(s, "/submit", user_message="", is_user="false",
         max_turns=str(max_calls))

    accepted = repeats = calls = 0
    completed_at = None
    for i in range(max_calls):
        calls += 1
        try:
            r = s.get(f"{BASE}/generate", timeout=300)
        except requests.RequestException as e:
            print(f"  [{label}] {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            print(f"  [{label}] HTTP {r.status_code}", file=sys.stderr)
            break
        d = r.json()
        hist = d.get("history", [])
        if hist and hist[-1][0] == "keeper":
            msg = str(hist[-1][1])
            if "already tried" in msg:
                repeats += 1
            # Count only answers the keeper counts. "- yes, but too close to one
            # I already have" is a refusal to count it, and it also contains
            # "- yes" - so the obvious substring inflated this figure with
            # near-duplicates the task explicitly does not accept.
            if "different enough" in msg or "you are done" in msg:
                accepted += 1
        if any("Task complete" in str(l) for l in d.get("logs", [])):
            completed_at = calls
            break

    rows = list(csv.DictReader(io.StringIO(
        s.get(f"{BASE}/export_run_data", timeout=60).text)))

    def total(col):
        t = 0
        for r in rows:
            try:
                t += int(r.get(col) or 0)
            except ValueError:
                pass
        return t

    # keep this arm's graph so a later run can inherit it
    graph_id = None
    try:
        agents = s.get(f"{BASE}/get_agent_graphs", timeout=60).json()
        agents = agents if isinstance(agents, list) else agents.get("agents", [])
        if agents:
            aid = agents[0].get("id") or agents[0].get("agent_id")
            saved = s.post(f"{BASE}/api/saved_graphs/from_agent/{aid}",
                           json={"name": label}, timeout=60).json()
            # the id is nested under "graph"; reading it from the top level
            # silently yields None and the reuse arm then inherits nothing
            graph_id = (saved.get("graph") or {}).get("graph_id")
    except Exception:                                              # noqa: BLE001
        pass

    return {
        "label": label, "mode": mode, "window": window, "level": level,
        "turns": len(rows), "calls": calls,
        "accepted": accepted, "repeats": repeats,
        "completed": int(completed_at is not None),
        "completed_at": completed_at or "",
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "recall_chars": round(st.mean([int(r.get("graph_contribution_chars") or 0)
                                       for r in rows]), 1) if rows else 0,
        "graph_nodes": max([int(r.get("graph_nodes") or 0) for r in rows], default=0),
        "graph_id": graph_id or "",
    }


def interval(values):
    """Mean with a 95% interval, or a plain mean when there are too few."""
    if not values:
        return "n/a"
    m = st.mean(values)
    if len(values) < 3:
        return f"{m:.1f}"
    half = 1.96 * st.stdev(values) / (len(values) ** 0.5)
    return f"{m:.1f} ±{half:.1f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", default="five_constraints")
    ap.add_argument("--modes", nargs="+", default=["none", "inline", "graph"])
    ap.add_argument("--windows", nargs="+", type=int, default=[0, 4, 8])
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-calls", type=int, default=26)
    ap.add_argument("--reuse", action="store_true",
                    help="run the route-reuse test instead of the sweep")
    ap.add_argument("--out", default="studies/results/study.csv")
    args = ap.parse_args()

    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f"GoalGraph is not running at {BASE}")

    results = []

    if args.reuse:
        # A cold agent, then an agent starting from the cold agent's graph.
        print("=== route reuse: does inheriting a graph help a fresh agent? ===\n")
        for rep in range(args.reps):
            first = run_one("graph", 4, args.level, args.max_calls,
                            f"reuse-first-{rep}")
            results.append({**first, "arm": "first pass"})
            print(f"  rep{rep} first pass  accepted={first['accepted']:<3} "
                  f"complete={first['completed']} nodes={first['graph_nodes']}", flush=True)

            warm = run_one("graph", 4, args.level, args.max_calls,
                           f"reuse-warm-{rep}", prior_graph=first["graph_id"])
            results.append({**warm, "arm": "inherited graph"})
            print(f"  rep{rep} inherited   accepted={warm['accepted']:<3} "
                  f"complete={warm['completed']} nodes={warm['graph_nodes']}", flush=True)

            cold = run_one("none", 4, args.level, args.max_calls, f"reuse-cold-{rep}")
            results.append({**cold, "arm": "no graph"})
            print(f"  rep{rep} no graph    accepted={cold['accepted']:<3} "
                  f"complete={cold['completed']}", flush=True)
    else:
        for window in args.windows:
            for mode in args.modes:
                for rep in range(args.reps):
                    label = f"{args.level}-{mode}-w{window}-r{rep}"
                    print(f"=== {mode} | window {window} | rep {rep} ===", flush=True)
                    r = run_one(mode, window, args.level, args.max_calls, label)
                    r["arm"] = f"{mode}-w{window}"
                    results.append(r)
                    print(f"  accepted={r['accepted']:<3} repeats={r['repeats']} "
                          f"complete={r['completed']} turns={r['turns']} "
                          f"tokens={r['input_tokens']}", flush=True)

    if results:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]))
            w.writeheader()
            w.writerows(results)

    arms = {}
    for r in results:
        arms.setdefault(r["arm"], []).append(r)
    print(f"\n{'arm':<20}{'n':>3}{'accepted':>16}{'completed':>11}"
          f"{'turns':>14}{'in tokens':>12}")
    print("-" * 78)
    for arm, rs in arms.items():
        comp = sum(r["completed"] for r in rs)
        print(f"{arm:<20}{len(rs):>3}{interval([r['accepted'] for r in rs]):>16}"
              f"{f'{comp}/{len(rs)}':>11}"
              f"{interval([r['turns'] for r in rs]):>14}"
              f"{st.mean([r['input_tokens'] for r in rs]):>12.0f}")
    print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
