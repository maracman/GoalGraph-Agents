# Studies

Scripted versions of experiments you can also run by hand in the app.

| file | what it does |
|---|---|
| `constraints_study.py` | the toy research project: memory modes across context windows, replicated, plus the route-reuse test |
| `ddx_fork.py` | who arbitrates the route-or-invent fork: the trust gate, the agent, or the agent with a scratchpad. Fixed inherited graph, three arms |
| `ddx_gradient.py` | is there a context-loss gradient for memory to close? Stateful-patient variant, 2x2 window x variant, graph off |
| `constraints_memory.py` | graph memory where state genuinely exceeds the window: none/graph x window, five simultaneous hidden rules |
| `constraints_scaffold.py` | the origin-story ablation: no aims / aims / aims+graph, weak model, strong judge |
| `constraints_transfer.py` | does a proven path transfer to an adjacent goal? fresh/same/adjacent/mismatched donors |

These are **the UI scripted**, not a separate measurement path. Every setting
they send goes through `/update_user_settings`, exactly as the Decision Graph
panel does; every number they read comes from `/export_run_data`, exactly what
the panel's **Download this run as CSV** button produces. If a script and the
panel ever disagree, the script is wrong.

Start the app first, then:

```bash
# memory modes across context windows
python3 studies/constraints_study.py --level four_constraints \
        --reps 5 --windows 4 --modes none inline graph --max-calls 24

# does a fresh agent benefit from inheriting an earlier agent's graph?
python3 studies/constraints_study.py --level four_constraints --reuse --reps 3

# who should arbitrate the aim fork? (fixed inherited graph, three arms)
GOALGRAPH_BASE=http://localhost:5055 \
  python3 studies/ddx_fork.py --out studies/results/v3_fork_w3.json --resume
```

The ddx and constraints studies read `GOALGRAPH_BASE` rather than hardcoding
`:5000`, so they can be pointed at a second app instance and cannot collide
with whatever is running on the usual port. The capabilities these scripts demonstrate are written up in
`docs/DEMONSTRATION.md`.

Results are written to `studies/results/`, one row per run, with the settings
that produced it repeated on every row so files from different arms concatenate
and group without reshaping.

See [../docs/DEMONSTRATION.md](../docs/DEMONSTRATION.md) for what the numbers
mean, and [../docs/WALKTHROUGH.md](../docs/WALKTHROUGH.md) for driving the
same machinery by hand.
