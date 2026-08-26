# A Worked Example: an agent that interviews, and remembers what it ruled out

This walkthrough shows what driving GoalGraph feels like, once, from start to finish.

The agent conducts an interview, chooses one question at a time, and records what each answer established or ruled out. The measured capabilities live in [`docs/DEMONSTRATION.md`](DEMONSTRATION.md). This document does not repeat them.

The setting is a clinical intake: an agent working out which of several conditions fits the person in front of it. The same shape appears in support, onboarding, and research. The agent must ask, listen, narrow the possibilities, and avoid returning to ground that has already been settled.

This is a puzzle rather than a clinical instrument. The conditions are simplified past the point of clinical use, and nothing here describes real illness.

---

## The interaction

You talk to the agent. It opens the interview, you answer briefly, and it explains what your answer changed.

The following dialogue illustrates the shape of a run.

> **Dr Ellery**: Hello. Let's start with the practical problem that brought you in.
>
> **You**: My sister made me come. She says I have stopped answering my phone.
>
> **Dr Ellery**: That helps. Stopping answering the phone could go with several patterns, but on its own it rules out very little. Have you been turning down invitations and seeing people less?
>
> **You**: Yes.
>
> **Dr Ellery**: That suggests some withdrawal, which can happen in low mood, anxiety, or exhaustion, so it still does not settle it. Are you worrying about lots of different things on most days?
>
> **You**: No.
>
> **Dr Ellery**: That is useful. Broad day-to-day worry being absent makes generalised anxiety less likely, so I should look more at low mood or exhaustion patterns. Have you been feeling flat most of the day?
>
> **You**: Yes.
>
> **Dr Ellery**: That points more toward a depressive pattern than simple burnout, though I still want one feature that separates them cleanly. Are you sleeping a full night but waking exhausted anyway?
>
> **You**: No.
>
> **Dr Ellery**: That makes burnout-exhaustion less likely. Have you lost interest in things that normally still feel enjoyable?

Three things are worth noticing.

**The opening is a consequence, not a symptom.** "My sister made me come" is not a structured criterion. It is what the problem caused. The agent has to work backwards from ordinary conversation.

**Each answer matters because of what it changes.** "No" to broad worry removes one line of inquiry. "No" to unrefreshing sleep removes another. The graph records those changes rather than treating every utterance as equally important.

**The person answers what they are asked and nothing more.** No one volunteers a complete, structured account. The agent has to choose the next question because it gets one answer at a time.

---

## What the graph recorded

Open the **Graph** tab while the conversation is running. The graph grows as the agent proposes aims and the judge settles them.

Read the graph alongside the conversation:

| In the graph | In the conversation |
|---|---|
| the current aim | what the agent is trying to establish next |
| the judge's verdict | whether the latest exchange advanced, completed, or ruled out that aim |
| a continuing branch | a line of inquiry that remains useful |
| a ruled-out branch | a line that no longer needs attention |
| the current route | the sequence of settled decisions leading to the present position |

The important distinction is between the agent's **aim** and the judge's **verdict**.

The aim states what the agent is trying to learn. The verdict is recorded after the exchange and says what happened to that aim. An answer may settle it, narrow it, or make it irrelevant. The graph keeps that outcome attached to the route that produced it.

Turn on **Hide ruled-out aims** to collapse branches that are no longer active. The remaining view shows the route the conversation is currently following. Turn the option off again to inspect the alternatives that were considered and rejected.

---

## Why a graph rather than the transcript

The transcript is the conversation. The graph is the working state extracted from it.

A transcript preserves every greeting, hedge, clarification, and repeated phrase. That is useful when you need the exact exchange, but awkward when you need to answer a smaller question: what has already been established, what has been ruled out, and what remains worth asking?

The graph gives those decisions stable places to live.

**It separates settled state from conversational wording.** Several differently phrased answers can support the same decision. The graph records the decision without requiring the original wording to remain in the active prompt.

**It keeps abandoned lines visible without keeping them active.** A ruled-out aim remains available for inspection, but it does not need to compete with the current route.

**It can be carried beyond one transcript.** A later session can receive the graph rather than the whole earlier conversation. The next agent sees the reusable structure without pretending that the next person gave the same answers.

The interface exposes four memory modes: `none`, `inline`, `description`, and `graph`. This walkthrough uses `graph`, because the object being inspected and carried is the decision graph itself.

---

## The next person, and the one after

Finish the first interview, then begin another run with the graph available as memory.

The new person is not a continuation of the old person. Their answers can differ immediately. The carried graph is therefore not a stored conclusion and not a template that must be obeyed. It is a record of routes that have previously been tried.

The next session can consult that record while building its own path:

1. The agent begins with a new person and a new hidden rule.
2. The carried graph offers previously recorded aims and routes.
3. The person's answers determine which of those routes remain relevant.
4. Contradictory answers send the session elsewhere.
5. New aims and verdicts extend the graph for a later session.

Repeat the process for another person and the same distinction remains important. The graph carries the interviewer's accumulated decision structure. It does not carry one person's answers forward as facts about someone else.

Switch **Hide ruled-out aims** on and off after several sessions. The filtered view shows the routes still in play. The complete view shows the alternatives that were attempted, settled, or rejected along the way.

---

## Run it yourself

Start the application from the repository root:

```bash
python3 src/app.py
```

Open the application in your browser, then use the **Decision Graph** panel.

1. Choose a task.
2. Choose the hidden rule.
3. Select the `graph` memory mode for this walkthrough.
4. Set a run label so the exported run is easy to identify.
5. Start the run.
6. Talk to the agent. Answer briefly and respond only to what it asks.
7. Watch the current aim as the agent chooses its next step.
8. Watch the judge's verdict after each exchange.
9. Open the **Graph** tab and inspect the route as it grows.
10. Use **Hide ruled-out aims** to move between the active route and the complete decision history.
11. Download the run as CSV when the session is complete.

Try another run with a different hidden rule while carrying the graph. The new conversation will produce its own route through the remembered structure.

The scripted version of this walkthrough is:

```bash
python3 studies/constraints_study.py
```

`studies/constraints_study.py` reads `GOALGRAPH_BASE`. Set that environment variable when the script should target a second application instance rather than the default one.

The measured story is in [`docs/DEMONSTRATION.md`](DEMONSTRATION.md). The design history, including earlier approaches and changes to the apparatus, is in [`docs/DEVELOPMENT_NOTES.md`](DEVELOPMENT_NOTES.md).

---

## What this shows and what it does not

This walkthrough demonstrates the mechanics of conducting a run, watching aims and verdicts, inspecting the graph, carrying it into another session, and exporting the run as CSV.

It does not establish effect sizes or report measured outcomes. For measurements, see [`docs/DEMONSTRATION.md`](DEMONSTRATION.md).