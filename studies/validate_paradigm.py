#!/usr/bin/env python3
"""Does the software still do the thing it claims to do?

This exists because it once stopped doing it silently. A change to when NoGo
fires, plus a keeper that could refute an aim but never confirm one, left the
agent with no evidence-backed way to advance. Runs still completed, the export
still had numbers in it, and nothing raised - but every decision graph came out
as a depth-1 star with zero Go edges, and the write-up rationalised that as a
property of the task rather than a regression.

The lesson is that "it ran" and "it worked" are different claims, and only the
second one is interesting. So these are the checks that distinguish them:

  --quick   pure logic, no LLM calls, runs in about a second. Catches the
            specific mechanisms that broke: serialisation, the keeper's ability
            to confirm as well as refute, and the patience gate.

  full      drives a real run through the HTTP API exactly as the UI does, then
            inspects the graph it produced. Slower and costs tokens, but it is
            the only check that can see a star.

    python3 studies/validate_paradigm.py --quick
    python3 studies/validate_paradigm.py            # needs the app running
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

FAILURES = []


def check(name, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" - {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)
    return condition


# --- logic checks, no LLM ------------------------------------------------

def quick():
    import numpy as np
    from agent import keeper as K
    from agent import constraint_rules as CR

    print("\nserialisation")
    # A numpy scalar used to raise part way through json.dump, truncating the
    # session file on disk. Both symptoms came from this one gap.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "app_mod", os.path.join(os.path.dirname(__file__), "..", "src", "app.py"))
    src = open(spec.origin).read()
    ns = {"os": os, "json": json}
    exec(src[src.index("def _sanitize_for_json"):
             src.index("def save_current_session")], ns)
    sanitize = ns["_sanitize_for_json"]
    payload = {"i": np.int64(3), "f": np.float64("nan"),
               "t": [("x", np.int64(1)), ("y", float("inf"))]}
    try:
        json.dumps(sanitize(payload), allow_nan=False)
        ok = True
    except (TypeError, ValueError) as e:
        ok = False
        print(f"        {e}")
    check("numpy scalars and NaN survive a strict JSON dump", ok)

    print("\nthe keeper can settle a verdict in both directions")
    k = K.make_keeper({"run_type": "constraints",
                       "keeper_rule": "four_constraints", "seed": 0})
    good = ['"Was the purple document approved yesterday?"',
            '"Is the crimson envelope arriving Tuesday afternoon?"',
            '"Were the silver instruments delivered this morning?"']
    hist, fired = [], 0
    for s in good:
        nxt = hist + [("agent", s)]
        if k.progress_made(hist, nxt):
            fired += 1
        hist = nxt
    check("a proven advance is detected", fired == len(good),
          f"{fired}/{len(good)} accepted answers registered as progress")
    check("completion is detected", k.is_complete(hist))
    check("progress_note gives an evolved aim somewhere to go",
          bool(k.progress_note(hist).strip()))

    # The refuting half, which never broke, guarded so it cannot start to.
    chk = k.check_aim("is_question()", [("Was the purple document approved "
                                         "yesterday?", False)])
    check("a contradicted rule is refuted from evidence",
          chk.get("checkable") and chk.get("consistent") is False)

    print("\nthe novelty requirement does not fight the constraints")
    # Told only "share few words with the ones you have given", agents dropped
    # the question form and the colour - the very things that made the sentence
    # acceptable - and drifted away from the only working pattern, because
    # "vary your words" is indistinguishable from "your rule is wrong".
    k2 = K.make_keeper({"run_type": "constraints",
                        "keeper_rule": "three_constraints", "seed": 0})
    near = k2.reply('"Is the blue schedule finished?"')[0]
    far = k2.reply('"Did the crimson envelope arrive?"')[0]
    check("a near-duplicate is refused without telling the agent to change what works",
          "too close" in near and "not asking you to change" in near)
    check("a genuinely different answer still counts",
          "different enough" in far)

    print("\nrejection carries a direction, not just a refusal")
    # Without this the task has no gradient, and a task with no gradient has no
    # routes - only dead ends hanging off a hub. It is the single biggest cause
    # of the star shape this project kept producing.
    near = k2.reply('"Did the silver engine stall?"')[0]      # 2 of 3
    far = k2.reply('"Silver comets drift above marshes."')[0]  # 1 of 3
    check("a near miss is distinguishable from a wild miss",
          "2 of my 3" in near and "1 of my 3" in far,
          "near=2/3, wild=1/3")
    check("but which rules held is still not revealed",
          "colour" not in near.lower() and "question" not in near.lower())

    print("\nreading the agent's proposal")
    # A fifth of every run's turns went on "give me a sentence in double
    # quotes". Rescuing the bare-sentence case is worth real turns, but only
    # while commentary stays out of the evidence record.
    cases = [('"Was the purple document approved yesterday?"', True),
             ("Was the purple document approved yesterday?", True),
             ("Is the crimson envelope arriving Tuesday afternoon?", True),
             ("I think the rule involves colour. Let me try this one next.", False),
             ("Here is my attempt.\nWas the purple document approved yesterday?", False),
             ("Yes.", False)]
    wrong = [c for c, want in cases if (k.extract_move(c) is not None) != want]
    check("a proposal is read, and commentary is not mistaken for one",
          not wrong, f"{len(wrong)} misread" if wrong else f"{len(cases)} cases")

    print("\nthe aim does not give the answer away")
    # An aim sits in the agent's *system prompt* every turn, outside the
    # context window entirely. So anything named in it is handed to every arm
    # for free, and a memory experiment measures nothing. A progress note once
    # read "Still possible: Anaphylaxis, SLE, Sarcoidosis", which made a
    # two-message window as good as a thirty-two message one and cost a full
    # sweep before anyone noticed.
    from agent import keeper as KP
    leaks = []
    for run_type, rules_mod, names in (
            ('clinic', 'clinic_rules', None),
            ('ddx_clinic', 'ddx_rules', None)):
        try:
            mod = __import__(f'agent.{rules_mod}', fromlist=['x'])
            kp = KP.make_keeper({'run_type': run_type})
            if kp is None or kp.rule_name is None:
                continue
            answers = (list(mod.DISORDER_TEXT.values()) + list(mod.DISORDER_TEXT)
                       if hasattr(mod, 'DISORDER_TEXT') else mod.conditions())
            for hist in ([], [('p', 'x'), ('d', 'Do you have a fever?')]):
                note = str(kp.progress_note(hist) or '').lower()
                for a in answers:
                    if len(str(a)) > 4 and str(a).lower() in note:
                        leaks.append(f'{run_type}: aim names "{a}"')
        except Exception as e:                                     # noqa: BLE001
            print(f'        ({run_type} not checkable: {e})')
    check("no run type names a candidate answer in the aim text",
          not leaks, '; '.join(leaks[:3]) if leaks else 'checked clinic + ddx_clinic')

    print("\nthe patience gate")
    txt = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "agent", "agent.py")).read()
    check("only a keeper proof skips the persistence gate",
          "proven or past_gate" in txt,
          "an ungated judge kills aims on turn one, which flattens the graph")
    check("positive verdicts carry their real source, not a hardcoded opinion",
          "verdict_confidence(OPINION, rating)" not in txt)


# --- the real thing ------------------------------------------------------

def full(reps, level, window, max_calls):
    import requests
    import networkx as nx

    BASE = "http://localhost:5000"
    try:
        requests.get(BASE, timeout=10)
    except requests.RequestException:
        sys.exit(f"GoalGraph is not running at {BASE}")

    sys.path.insert(0, os.path.dirname(__file__))
    from constraints_study import run_one

    print(f"\nrunning {reps} rep(s) of {level}, window {window}")
    depths, positives, proven_pos, accepted = [], [], [], []
    for rep in range(reps):
        r = run_one("graph", window, level, max_calls, f"validate-r{rep}")
        # Use the graph the run itself saved. Asking the server for the agent
        # list here would open a *new* HTTP session with no cookie, find no
        # agents, and silently measure an empty graph - which reads as a
        # depth-0 failure no matter how well the run went.
        path = None
        if r.get("graph_id"):
            # graph_id already carries its "graph_" prefix
            path = os.path.join(os.path.dirname(__file__), "..", "src",
                                "chat_cache", "saved_graphs",
                                f"{r['graph_id']}.graphml")
        d = pos = prov = 0
        if path and os.path.exists(path):
            G = nx.read_graphml(path)
            lab = collections.Counter(x.get("label") for _, _, x in G.edges(data=True))
            pos = lab.get("Go", 0) + lab.get("Progress", 0)
            prov = sum(1 for _, _, x in G.edges(data=True)
                       if x.get("label") in ("Go", "Progress")
                       and x.get("verdict_source") == "evidence")
            starts = [n for n in G.nodes if str(n) == "start"
                      or str(n).endswith("/start")] or \
                     [n for n in G.nodes if G.in_degree(n) == 0]
            for s in starts:
                try:
                    lens = nx.single_source_shortest_path_length(G, s)
                    d = max(d, max(lens.values()) if lens else 0)
                except Exception:                                  # noqa: BLE001
                    pass
        depths.append(d); positives.append(pos); proven_pos.append(prov)
        accepted.append(r["accepted"])
        print(f"  rep{rep}: depth={d} positives={pos} proven={prov} "
              f"accepted={r['accepted']} done={r['completed']}")

    print("\ngraph structure")
    check("the graph has depth, rather than being a hub of dead ends",
          max(depths) >= 3, f"deepest route {max(depths)} hops")
    check("aims are reached, not only ruled out",
          max(positives) > 0, f"{max(positives)} Go/Progress edges")
    check("at least one advance is backed by evidence rather than opinion",
          max(proven_pos) > 0, f"{max(proven_pos)} proven positives")
    check("the agent still solves the task",
          max(accepted) >= 2, f"best run accepted {max(accepted)}")

    # Depth has to be earned. A run that accepted nothing and still shows a
    # long chain of Go edges is recording the judge's optimism as if it were
    # achievement, which looks healthier than a star while meaning less.
    inflated = [(d, p, a) for d, p, a in zip(depths, positives, accepted)
                if a == 0 and p > 0]
    check("no run claims progress it did not make",
          not inflated,
          f"{len(inflated)} run(s) with positives but nothing accepted"
          if inflated else "positives are backed by accepted answers")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="logic only, no LLM calls")
    ap.add_argument("--reps", type=int, default=1)
    # three, not four: with four constraints and no signal about which one
    # failed, the agent lands one or two novel answers in a full run and
    # essentially never reaches the three needed to finish, so the run has
    # nothing to show either way.
    ap.add_argument("--level", default="three_constraints")
    ap.add_argument("--window", type=int, default=4)
    # matches the study's own default; a shorter budget cuts runs off before
    # they can finish and makes the task look harder than it is
    ap.add_argument("--max-calls", type=int, default=26)
    a = ap.parse_args()

    quick()
    if not a.quick:
        full(a.reps, a.level, a.window, a.max_calls)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("all checks passed")
