# Studies

Scripted versions of experiments you can also run by hand in the app.

| file | what it does |
|---|---|
| `constraints_study.py` | the toy research project: memory modes across context windows, replicated, plus the route-reuse test |

These are **the UI scripted**, not a separate measurement path. Every setting
they send goes through `/update_user_settings`, exactly as the Decision Graph
panel does; every number they read comes from `/export_run_data`, exactly what
the panel's **Download this run as CSV** button produces. If a script and the
panel ever disagree, the script is wrong.

Start the app first, then:

```bash
# the headline comparison
python3 studies/constraints_study.py --level four_constraints \
        --reps 5 --windows 4 --modes none inline graph --max-calls 24

# does a fresh agent benefit from inheriting an earlier agent's graph?
python3 studies/constraints_study.py --level four_constraints --reuse --reps 3
```

Results are written to `studies/results/`, one row per run, with the settings
that produced it repeated on every row so files from different arms concatenate
and group without reshaping.

See [../docs/TOY_RESEARCH_PROJECT.md](../docs/TOY_RESEARCH_PROJECT.md) for what
the numbers mean and what they do not.
