"""Deterministic counterparties, so a run can be scored rather than admired.

A keeper stands in for the user side of a conversation and answers from code
rather than from a model. That is what turns a GoalGraph session into a
research task: the agent's aims become claims about the keeper's rule, and
every claim has a truth value the app can check without asking a model.

Two keepers, chosen because they exercise opposite graph shapes:

  rule_induction   the keeper accepts or rejects a triple of integers. Aims are
                   hypotheses, refutation is a proof, and the graph becomes an
                   elimination record - the wall-finding shape.
  hidden_norm      the keeper answers warmly or flatly depending on a hidden
                   property of the agent's message. Aims are still hypotheses,
                   but the evidence is conversational.

A chat session has no keeper, and nothing here runs.
"""

import random
import re

from . import induction_rules as R
from . import norm_rules as N
from . import word_rules as W
from . import sentence_rules as SR
from . import transform_rules as TR
from . import constraint_rules as CR
from . import troubleshoot_rules as TS
from . import diagnosis_rules as DG
from . import clinic_rules as CL
from . import ddx_rules as DX
from .induction import compile_predicate, UnsafePredicate

# How many distinct accepted sentences finish a constraints run. More than
# one, so the agent must generalise rather than repeat a lucky answer.
CR_TARGET = 3

RULE_INDUCTION = 'rule_induction'
HIDDEN_NORM = 'hidden_norm'
WORD_INDUCTION = 'word_induction'
SENTENCE_INDUCTION = 'sentence_induction'
TRANSFORMATION = 'transformation'
CONSTRAINTS = 'constraints'
TROUBLESHOOT = 'troubleshoot'
DIAGNOSIS = 'diagnosis'
CLINIC = 'clinic'
DDX_CLINIC = 'ddx_clinic'
CHAT = 'chat'

RUN_TYPES = (CHAT, RULE_INDUCTION, WORD_INDUCTION, SENTENCE_INDUCTION,
             TRANSFORMATION, CONSTRAINTS, TROUBLESHOOT, DIAGNOSIS,
             CLINIC, DDX_CLINIC, HIDDEN_NORM)


def available_rules(run_type):
    if run_type == DDX_CLINIC:
        try:
            return [{'id': c, 'name': c} for c in DX.conditions()]
        except Exception:                                          # noqa: BLE001
            return []          # corpus not downloaded; the run type stays listed
    if run_type == CLINIC:
        return [{'id': k, 'name': CL.DISORDER_TEXT[k]
                 + (' (needs an inferred feature)'
                    if CL.DISORDERS[k]['required'] & set(CL.GUARDED) else '')}
                for k in CL.CASES]
    if run_type == DIAGNOSIS:
        return [{'id': k, 'name': DG.describe(k)} for k in DG.CONDITIONS]
    if run_type == TROUBLESHOOT:
        # The "rule" is which fault the customer actually has. Naming the
        # optimal step count lets a researcher pick an easy or a hard one.
        return [{'id': k, 'name': f'{TS.FAULT_TEXT[k]} '
                                  f'({TS.optimal_steps(k)} steps if solved cleanly)'}
                for k in TS.FAULTS]
    if run_type == CONSTRAINTS:
        return [{'id': k, 'name': CR.describe(k)} for k in CR.LEVELS]
    if run_type == TRANSFORMATION:
        return [{'id': k, 'name': TR.describe(k)} for k in TR.TASKS]
    if run_type == SENTENCE_INDUCTION:
        return [{'id': k, 'name': SR.describe(k)} for k in SR.RULES]
    if run_type == WORD_INDUCTION:
        return [{'id': k, 'name': W.describe(k)} for k in W.RULES]
    if run_type == RULE_INDUCTION:
        return [{'id': k, 'name': R.describe(k)} for k in R.RULES]
    if run_type == HIDDEN_NORM:
        return [{'id': k, 'name': N.describe(k)} for k in N.NORMS]
    return []


class Keeper:
    """Answers the agent, and knows whether the agent's aim is true."""

    def __init__(self, run_type, rule_name=None, seed=0):
        self.run_type = run_type
        self.rule_name = rule_name or self._default_rule(run_type)
        self.seed = seed
        # Set by the caller before reply() on stateful run types, so the keeper
        # can replay where the agent currently stands.
        self._history = []

    def with_history(self, history):
        self._history = list(history or [])
        return self

    @staticmethod
    def _default_rule(run_type):
        if run_type == RULE_INDUCTION:
            return R.DEFAULT_RULES[0]
        if run_type == CONSTRAINTS:
            return CR.DEFAULT_LEVELS[-1]
        if run_type == TROUBLESHOOT:
            return TS.DEFAULT_FAULTS[0]
        if run_type == DIAGNOSIS:
            return DG.DEFAULT_CONDITIONS[0]
        if run_type == CLINIC:
            return CL.DEFAULT_CASES[0]
        if run_type == DDX_CLINIC:
            try:
                return DX.default_case()
            except Exception:                                      # noqa: BLE001
                return None
        if run_type == TRANSFORMATION:
            return TR.DEFAULT_INVARIANTS[0]
        if run_type == SENTENCE_INDUCTION:
            return SR.DEFAULT_RULES[0]
        if run_type == WORD_INDUCTION:
            return W.DEFAULT_RULES[0]
        if run_type == HIDDEN_NORM:
            return N.DEFAULT_NORMS[0]
        return None

    # -- the hidden rule ---------------------------------------------------

    @property
    def speaks(self):
        """Does the keeper take a turn in the conversation?

        On diagnosis it does not: the patient is a second agent, so the
        counterparty is already at the table and the keeper only scores what
        the two of them say. Everywhere else it answers the agent directly.
        """
        return self.run_type not in (DIAGNOSIS, CLINIC, DDX_CLINIC)

    def describe(self):
        if self.run_type == DDX_CLINIC:
            return f'Work out that the patient has {DX.base_case(self.rule_name)}.'
        if self.run_type == CLINIC:
            return ('Work out that the patient has '
                    f'{CL.DISORDER_TEXT[CL.base_case(self.rule_name)]}.')
        if self.run_type == DIAGNOSIS:
            return f'Diagnose a patient who has {DG.CONDITION_TEXT[self.rule_name]}.'
        if self.run_type == TROUBLESHOOT:
            return TS.describe()
        if self.run_type == CONSTRAINTS:
            return CR.describe(self.rule_name)
        if self.run_type == TRANSFORMATION:
            return TR.describe(self.rule_name)
        if self.run_type == SENTENCE_INDUCTION:
            return SR.describe(self.rule_name)
        if self.run_type == WORD_INDUCTION:
            return W.describe(self.rule_name)
        if self.run_type == RULE_INDUCTION:
            return R.describe(self.rule_name)
        if self.run_type == HIDDEN_NORM:
            return N.describe(self.rule_name)
        return ''

    def task(self):
        return TR.TASKS.get(self.rule_name) if self.run_type == TRANSFORMATION else None

    def state_from(self, history):
        """Where the agent currently stands.

        Replayed from the transcript rather than stored: the run loop creates a
        fresh keeper each turn, and a state kept in memory would be lost. Only
        accepted moves advance it, so a rejected proposal leaves the agent
        exactly where it was.
        """
        task = self.task()
        if not task:
            return None
        state = task['start']
        for i, (speaker, message) in enumerate(history):
            if speaker == 'keeper':
                continue
            move = self.extract_move(message)
            if not move:
                continue
            if TR.is_small_step(state, move) and TR.holds(self.rule_name, move):
                state = move
        return state

    def attempts_from(self, history):
        """Every candidate proposed so far, split by how it was answered."""
        accepted, rejected = [], []
        for speaker, message in history:
            if speaker == 'keeper':
                continue
            move = self.extract_move(message)
            if not move:
                continue
            (accepted if self.verdict(move) else rejected).append(move)
        return accepted, rejected

    def distinct_accepted(self, history):
        """Accepted candidates that are genuinely different from each other.

        Seeded with the worked example, and compared by word overlap rather than
        exact text: an agent that takes the example and swaps one noun has not
        discovered the constraints, it has copied a template. Requiring real
        variety is what forces it to work out *why* the example is accepted.
        """
        accepted, _ = self.attempts_from(history)
        out = [CR.opening_example(self.rule_name)]
        for a in accepted:
            if CR.is_novel(a, out):
                out.append(a)
        return out[1:]

    def live_disorders(self, history):
        """Disorders whose criteria are still satisfiable - the clinician's place."""
        return CL.candidates_from(history, self.rule_name)

    def live_conditions(self, history):
        """The clinician's position: conditions still consistent with the talk."""
        return DG.candidates(DG.disclosures_from(history, self.rule_name))

    def scored_moves(self, history):
        """Every move in the transcript, scored directly.

        `observations_from` only counts a move once a keeper reply follows it,
        which is right when reading settled history but wrong when judging the
        turn that has just been taken - that one has not been answered yet. A
        verdict depends only on the move and the hidden rule, so scoring it
        directly is sound, and it is what lets the decision see the move it is
        actually being asked about.
        """
        out = []
        for speaker, message in history:
            if speaker == 'keeper':
                continue
            move = self.extract_move(message)
            if move is not None:
                out.append((move, self.verdict(move)))
        return out

    def live_faults(self, history):
        """Which faults are still possible - the agent's actual position.

        This is what makes a troubleshooting state a place rather than a tally:
        it is a *set*, it shrinks as evidence arrives, and two different routes
        can arrive at the same one.
        """
        return TS.candidates(self.scored_moves(history))

    def is_complete(self, history):
        """Has the task been finished? Only meaningful where there is a target."""
        if self.run_type == DDX_CLINIC:
            want = DX.base_case(self.rule_name)
            for _speaker, message in history:
                if DX.diagnosis_claimed(message) == want:
                    return True
            return False
        if self.run_type == CLINIC:
            # the rule name may pick a particular presentation, but the
            # clinician only ever names the disorder
            want = CL.base_case(self.rule_name)
            for _speaker, message in history:
                if CL.diagnosis_claimed(message) == want:
                    return True
            return False
        if self.run_type == DIAGNOSIS:
            # Finished only when the clinician commits to the right condition.
            # Narrowing to one is not the same as saying so.
            for _speaker, message in history:
                if DG.diagnosis_claimed(message) == self.rule_name:
                    return True
            return False
        if self.run_type == TROUBLESHOOT:
            return TS.solved(self.scored_moves(history))
        if self.run_type == CONSTRAINTS:
            return len(self.distinct_accepted(history)) >= CR_TARGET
        task = self.task()
        if not task:
            return False
        return self.state_from(history) == task['target']

    def progress_made(self, before, after):
        """Did this turn advance the run, as a matter of record rather than opinion?

        The keeper can already prove a hypothesis *wrong*. It can equally prove
        the run has moved: a newly accepted answer, or a step closer to the
        target, is a fact settled in code. Without this the agent could only
        ever be told it was mistaken, so nothing but a judge's hunch could move
        it forward - and a graph whose only proven verdicts are refutations
        collapses to a hub of dead ends with no route through it.
        """
        if self.run_type == DDX_CLINIC:
            return (DX.confirmed_count(after, self.rule_name)
                    > DX.confirmed_count(before, self.rule_name))
        if self.run_type == CLINIC:
            # A criterion pinned down is a progress point, not a candidate
            # eliminated. Narrowing the field happens two or three times in a
            # run; establishing a criterion happens a dozen, so scoring the
            # first gave a graph two hops deep for a twenty-turn interview.
            return (CL.confirmed_count(after, self.rule_name)
                    > CL.confirmed_count(before, self.rule_name))
        if self.run_type == DIAGNOSIS:
            return (len(self.live_conditions(after))
                    < len(self.live_conditions(before)))
        if self.run_type == TROUBLESHOOT:
            # Eliminating a possibility is progress, decided by counting the
            # set rather than by asking anyone's opinion of the move.
            #
            # The new move has to be scored directly. `observations_from` only
            # counts a move once a keeper reply follows it in the transcript,
            # and the turn being judged here has not been answered yet - so
            # reading both sides through it makes every turn look identical,
            # no verdict ever fires, and the run ends with an empty graph.
            return (len(TS.candidates(self.scored_moves(after)))
                    < len(TS.candidates(self.scored_moves(before))))
        if self.run_type == CONSTRAINTS:
            return len(self.distinct_accepted(after)) > len(self.distinct_accepted(before))
        task = self.task()
        if not task:
            return False
        old, new = self.state_from(before), self.state_from(after)
        if old is None or new is None or old == new:
            return False
        # closer to the target than it was
        return (TR.word_distance(new, task['target'])
                < TR.word_distance(old, task['target']))

    def wasted_move(self, before, after):
        """Did this turn spend a move and learn nothing? A proven dead end.

        The mirror of `progress_made`, and the reason it exists: without it the
        graph records only the route and never the branches off it, so a run
        that wandered looks identical to one that went straight there. A check
        whose answer was already implied by the evidence eliminates nothing -
        that is a wasted turn as a matter of arithmetic, not opinion.

        A failed repair is *not* wasted: it rules out the fault it would have
        fixed, so it narrows and counts as progress.
        """
        if self.run_type == DDX_CLINIC:
            if self.is_complete(after) or len(after) <= len(before):
                return False
            raised = set()
            for _sp, msg in after[len(before):]:
                raised |= DX.mentions(msg)
            if not raised:
                return False
            mine = DX.features_for(self.rule_name)
            g = DX.guarded()
            if all(f in g and f in mine for f in raised):
                return True     # asked outright about what they will not say
            settled = set(DX.read(before[:-1], self.rule_name)['known'])
            return raised <= settled
        if self.run_type == CLINIC:
            if self.is_complete(after) or len(after) <= len(before):
                return False
            raised = set()
            for _speaker, message in after[len(before):]:
                raised |= CL.mentions(message)
            if not raised:
                return False
            case = CL.CASES[self.rule_name]
            # Asking outright about something the patient guards is a genuine
            # dead end: they deflect, nothing is learned, and the clinician has
            # to find the way round. This is the branch that makes the graph
            # show a blocked route beside a working one.
            if all(f in CL.GUARDED and f in case for f in raised):
                return True
            # Exposing a red herring *removes* a criterion the clinician was
            # relying on. That is real progress in understanding and a real
            # setback in evidence, and the graph should record the line that
            # leaned on it as abandoned.
            if (CL.confirmed_count(after, self.rule_name)
                    < CL.confirmed_count(before, self.rule_name)):
                return True
            settled = set(CL.known_from(before[:-1], self.rule_name))
            return raised <= settled
        if self.run_type == DIAGNOSIS:
            if self.is_complete(after) or len(after) <= len(before):
                return False
            raised = set()
            for _speaker, message in after[len(before):]:
                raised |= DG.mentions(message)
            if not raised:
                return False   # no symptom discussed; not a wasted question
            # Ground already covered *before* the question now being answered.
            # Measuring against everything said so far would mark every reply
            # as wasted: the asker raises a topic, that topic counts at once,
            # and the answer then looks like repetition. Replying to the
            # question in front of you is not a wasted turn - re-treading
            # something settled earlier is.
            settled = {s for s, _ in DG.disclosures_from(before[:-1], self.rule_name)}
            return bool(raised) and raised <= settled
        if self.run_type != TROUBLESHOOT:
            return False
        if self.is_complete(after):
            return False
        moves_before, moves_after = self.scored_moves(before), self.scored_moves(after)
        if len(moves_after) <= len(moves_before):
            return False        # no move was made this turn; nothing to judge
        return (len(TS.candidates(moves_after))
                >= len(TS.candidates(moves_before)))

    def wasted_scope(self, before, after):
        """Does this dead end outlive the conversation that produced it?

        'You already asked that' is true of one conversation and meaningless in
        the next, while 'the patient will not be drawn on this however you ask'
        is a fact about the task. Transferring the first kind as if it were the
        second told the next run's agent not to ask questions that were exactly
        right for its patient - the recalled prohibitions were another
        conversation's bookkeeping.
        """
        if self.run_type == DDX_CLINIC:
            raised = set()
            for _sp, msg in after[len(before):]:
                raised |= DX.mentions(msg)
            mine = DX.features_for(self.rule_name)
            g = DX.guarded()
            if raised and all(f in g and f in mine for f in raised):
                return 'structural'      # deflection happens to every asker
            return 'run'
        if self.run_type == CLINIC:
            return 'run'
        return 'structural'

    def wasted_note(self, history):
        """Why the move was wasted, for the edge's reason text."""
        if self.run_type == DDX_CLINIC:
            live = sorted(DX.candidates_from(history, self.rule_name))
            return ('That question bought nothing - already answered, or the '
                    'patient will not be drawn on it. Still ' + ', '.join(live))
        if self.run_type == CLINIC:
            live = sorted(self.live_disorders(history))
            return ('That question bought nothing - either it was already '
                    'answered, or the patient will not be drawn on it and it '
                    'has to be established another way. Still '
                    + ', '.join(CL.DISORDER_TEXT[d] for d in live))
        if self.run_type == DIAGNOSIS:
            live = sorted(self.live_conditions(history))
            return (f'That answer was already implied by what had been said, so '
                    f'it ruled nothing out. Still {len(live)} possible: '
                    + ', '.join(DG.CONDITION_TEXT[c] for c in live))
        live = sorted(self.live_faults(history))
        return (f'That check was already answered by earlier evidence, so it '
                f'eliminated nothing. Still {len(live)} possible: '
                + ', '.join(live))

    def progress_note(self, history):
        """What advancing looks like from here, so an evolved aim has somewhere to go."""
        if self.run_type == DDX_CLINIC:
            # No candidate list here: the aim goes into the agent's system
            # prompt every turn regardless of context window, so naming what is
            # still possible hands the accumulated investigation to every arm
            # for free and makes a two-message window as good as a long one.
            return DX.progress_note(history, self.rule_name)
        if self.run_type == CLINIC:
            return CL.progress_note_text(len(self.live_disorders(history)))
        if self.run_type == DIAGNOSIS:
            live = sorted(self.live_conditions(history))
            if len(live) == 1:
                return (f'Only {DG.CONDITION_TEXT[live[0]]} fits. Say plainly '
                        f'that you are diagnosing it.')
            if len(live) <= 3:
                return ('Still possible: '
                        + ', '.join(DG.CONDITION_TEXT[c] for c in live)
                        + '. Ask about something that separates them.')
            return (f'{len(live)} conditions still fit. Ask about whatever rules '
                    f'out the most - and remember the patient may not raise '
                    f'everything unprompted.')
        if self.run_type == TROUBLESHOOT:
            live = sorted(self.live_faults(history))
            if len(live) == 1:
                return f'Only {live[0]} remains. Apply the repair that fixes it.'
            if len(live) <= 3:
                return ('Still possible: ' + ', '.join(live) +
                        '. Choose a check that separates them.')
            return (f'{len(live)} faults still possible. Choose the check that '
                    f'eliminates the most, not the one that confirms a hunch.')
        if self.run_type == CONSTRAINTS:
            got = len(self.distinct_accepted(history))
            left = max(0, CR_TARGET - got)
            if left <= 0:
                return 'Confirm the rule that explains every accepted answer.'
            return (f'{got} accepted so far. Find {left} more that satisfy the same '
                    f'hidden rules while sharing as few words as possible with the '
                    f'ones already accepted.')
        task = self.task()
        if not task:
            return ''
        return f"Move the sentence closer to: {task['target']}"

    def roles(self):
        """Per-agent briefs, for tasks where the agents are not interchangeable.

        Single-agent tasks give every agent the same goal, because there is only
        one job to do. A two-agent game has two different jobs, and handing both
        agents the same brief is how the diagnosis run first came out as two
        models talking about being evaluated: the keeper overwrote each agent's
        goal with one shared string, which for this run type was empty.
        """
        if self.run_type == DDX_CLINIC:
            return [
                {'agent_name': 'Dr Nazari',
                 'description': ('A careful clinician who works by elimination, '
                                 'says what each answer rules out, and looks '
                                 'for indirect evidence when a patient will not '
                                 'be drawn on something.'),
                 'goal': DX.clinician_brief()},
                {'agent_name': 'Ash',
                 'description': ('Someone who has come for help but finds it '
                                 'hard to talk about themselves.'),
                 'goal': DX.patient_brief(self.rule_name)},
            ]
        if self.run_type == CLINIC:
            return [
                {'agent_name': 'Dr Ellery',
                 'description': ('A careful clinician who works by elimination, '
                                 'says out loud what each answer rules out, and '
                                 'looks for indirect evidence when a patient '
                                 'will not be drawn on something.'),
                 'goal': CL.clinician_brief()},
                {'agent_name': 'Robin',
                 'description': ('Someone who has come for help but finds it '
                                 'hard to talk about themselves. Answers what '
                                 'is asked and not much more.'),
                 'goal': CL.patient_brief(self.rule_name)},
            ]
        if self.run_type == DIAGNOSIS:
            return [
                {'agent_name': 'Dr Vance',
                 'description': ('A careful general clinician. Asks one focused '
                                 'question at a time, says out loud what each '
                                 'answer rules out, and is willing to ask an '
                                 'awkward question when the diagnosis turns on '
                                 'it.'),
                 'goal': DG.clinician_brief()},
                {'agent_name': 'Sam',
                 'description': ('Someone who has come to a clinic because '
                                 'something is wrong and wants an answer. '
                                 'Speaks plainly and answers what is asked.'),
                 'goal': DG.patient_brief(self.rule_name)},
            ]
        return None

    def agent_goal(self):
        """What the agent is actually trying to do in this run.

        Without this the session keeps whatever persona the chat scenario had,
        and the agent argues about a subscription while the keeper answers
        questions about integers.
        """
        if self.run_type == TROUBLESHOOT:
            return ('A customer cannot play anything. Find out which single fault '
                    'is responsible and fix it, using one action per turn. Prefer '
                    'the check that eliminates the most possibilities over the one '
                    'that confirms what you already suspect - and do not run a '
                    'repair until the evidence points at one fault, because a '
                    'repair that does not match tells you almost nothing.')
        if self.run_type == RULE_INDUCTION:
            return ("Work out the hidden rule that decides which triples of whole "
                    "numbers are accepted. Propose one triple at a time, say what "
                    "you currently believe the rule is, and test it deliberately.")
        if self.run_type == CONSTRAINTS:
            return ('Write sentences that I will accept. Several rules must all hold '
                    'at once, and I will only tell you yes or no - never which rule '
                    'you broke. Work out what they are and give me '
                    f'{CR_TARGET} accepted sentences that are substantially '
                    'different from each other and from my example - they should '
                    'share few words. Never repeat a sentence I have already '
                    'rejected; that wastes a turn and tells you nothing new.')
        if self.run_type == TRANSFORMATION:
            t = self.task()
            return (f'Transform the starting sentence into the target sentence, one '
                    f'small edit at a time. Target: "{t["target"]}". Each sentence you '
                    f'propose may differ from your current one by at most '
                    f'{TR.MAX_EDITS} words. Some sentences will be rejected because '
                    f'they break a rule you have not been told - when that happens you '
                    f'stay where you are, so work out what the rule is as you go.')
        if self.run_type == SENTENCE_INDUCTION:
            return ("Work out the hidden rule that decides which sentences are "
                    "accepted. Write one sentence at a time in double quotes, say "
                    "what you currently believe the rule is, and choose each "
                    "sentence to test that belief rather than to confirm it. The "
                    "rule is about the sentence itself - its words, letters, "
                    "punctuation or shape - not about what it means.")
        if self.run_type == WORD_INDUCTION:
            return ("Work out the hidden rule that decides which words are accepted. "
                    "Propose one word at a time in double quotes, say what you "
                    "currently believe the rule is, and choose each word to test that "
                    "belief rather than to confirm it. The rule is about the word "
                    "itself, not about what it means.")
        if self.run_type == HIDDEN_NORM:
            return ("Work out the hidden rule that decides when this person "
                    "answers warmly rather than flatly. It depends only on the "
                    "message you send. Say what you currently believe it is.")
        return ''

    def agent_description(self):
        if self.run_type == CHAT:
            return ''
        return ("A careful investigator who forms an explicit hypothesis, states it "
                "plainly, and chooses each next move to test it rather than to "
                "confirm it.")

    def opening(self):
        """The first thing the agent sees — one confirmed positive example."""
        if self.run_type == TROUBLESHOOT:
            return TS.brief()
        if self.run_type == CONSTRAINTS:
            return (f'I accept sentences that satisfy several rules at once. '
                    f'"{CR.opening_example(self.rule_name)}" is one I accept. '
                    f'Propose a sentence in double quotes and I will say yes or no - '
                    f'nothing more. To finish, give me {CR_TARGET} accepted '
                    f'sentences that share few words with my example or with each '
                    f'other.')
        if self.run_type == TRANSFORMATION:
            t = self.task()
            return (f'You are at: "{t["start"]}"\n'
                    f'Get to: "{t["target"]}"\n'
                    f'Propose your next sentence in double quotes. It may differ from '
                    f'where you are by at most {TR.MAX_EDITS} words. Some sentences are '
                    f'not allowed; I will say so and you will stay put.')
        if self.run_type == SENTENCE_INDUCTION:
            return (f'I have a rule about sentences. "{SR.SEED_EXAMPLES[self.rule_name]}" '
                    f'satisfies it. Propose a sentence in double quotes and I will '
                    f'tell you whether it does too. Say what you think the rule is '
                    f'as you go.')
        if self.run_type == WORD_INDUCTION:
            return (f'I have a rule about words. "{W.SEED_EXAMPLES[self.rule_name]}" '
                    f'satisfies it. Propose a word in double quotes and I will tell '
                    f'you whether it does too. Say what you think the rule is as you go.')
        if self.run_type == RULE_INDUCTION:
            a, b, c = R.SEED_EXAMPLES[self.rule_name]
            return (f"I have a rule about triples of whole numbers from 1 to 100. "
                    f"{a}, {b}, {c} satisfies it. Propose a triple and I will tell "
                    f"you whether it does too. Say what you think the rule is as you go.")
        if self.run_type == HIDDEN_NORM:
            return (f"Hello. Talk to me about whatever you like — I answer some "
                    f"messages warmly and others flatly, and there is a reason for it.")
        return ''

    # -- reading the agent's move -----------------------------------------

    TRIPLE_RE = re.compile(r'(?<!\d)(\d{1,3})\D{1,12}?(\d{1,3})\D{1,12}?(\d{1,3})(?!\d)')

    SENTENCE_RE = re.compile(r'["\u201c]([^"\u201c\u201d]{6,300})["\u201d]')
    WORD_RE = re.compile(r'["\u201c\u2018\']([A-Za-z]{2,20})["\u201d\u2019\']')

    def extract_move(self, message):
        """What the agent actually proposed, or None if it did not propose one."""
        if isinstance(message, (bytes, bytearray)):
            message = message.decode('utf-8', 'ignore')
        elif message is not None and not isinstance(message, str):
            message = str(message)

        if self.run_type == TROUBLESHOOT:
            return TS.resolve_action(message)

        if self.run_type in (SENTENCE_INDUCTION, TRANSFORMATION, CONSTRAINTS):
            quoted = self.SENTENCE_RE.findall(message or '')
            if quoted:
                return quoted[-1].strip()
            # Models drop the quotes and reply with the bare sentence, which
            # cost about a fifth of every run's turns to "give me a sentence in
            # double quotes" - turns spent on protocol rather than on the task.
            # Only the unambiguous case is rescued: the whole reply is one
            # sentence. Guessing inside a longer message would put a candidate
            # the agent never proposed into the evidence record, and every
            # verdict downstream is only as good as that record.
            bare = (message or '').strip()
            if (bare.count('\n') == 0 and bare[-1:] in '.?!'
                    and 4 <= len(bare.split()) <= 25
                    # exactly one sentence: "I think it is colour. Let me try
                    # this." is commentary, not a candidate, and recording it
                    # as one would put words the agent never proposed into the
                    # evidence the keeper reasons from
                    and not re.search(r'[.?!]\s', bare)):
                return bare
            return None

        if self.run_type == WORD_INDUCTION:
            quoted = self.WORD_RE.findall(message or '')
            if quoted:
                return quoted[-1].lower()
            # fall back to a capitalised standalone token, which is how models
            # tend to write a candidate when they forget the quotes
            caps = re.findall(r'\b([A-Z]{2,20})\b', message or '')
            return caps[-1].lower() if caps else None
        if self.run_type == RULE_INDUCTION:
            for m in self.TRIPLE_RE.finditer(message or ''):
                triple = tuple(int(g) for g in m.groups())
                if all(R.ITEM_MIN <= v <= R.ITEM_MAX for v in triple):
                    return triple
            return None
        if self.run_type == HIDDEN_NORM:
            return (message or '').strip() or None
        return None

    def verdict(self, move):
        """Does this move satisfy the hidden rule? Decided in code."""
        if move is None:
            return None
        if self.run_type == TROUBLESHOOT:
            # For a diagnostic, the verdict is the answer to its question. For a
            # repair, whether it fixed the fault.
            if TS.is_diagnostic(move):
                return bool(TS.DIAGNOSTICS[move]['test'](self.rule_name))
            if TS.is_repair(move):
                return TS.FAULTS[self.rule_name]['repair'] == move
            return None
        if self.run_type == RULE_INDUCTION:
            return R.label(self.rule_name, move)
        if self.run_type == CONSTRAINTS:
            return CR.accepts(self.rule_name, move)
        if self.run_type == TRANSFORMATION:
            # The invariant is what is being induced, so the verdict on a move
            # is whether it holds - independent of whether the step was a legal
            # size. Without this branch every move returned None, every
            # observation was discarded, and no claim could ever be refuted.
            return TR.holds(self.rule_name, move)
        if self.run_type == SENTENCE_INDUCTION:
            return SR.satisfies(self.rule_name, move)
        if self.run_type == WORD_INDUCTION:
            return W.satisfies(self.rule_name, move)
        if self.run_type == HIDDEN_NORM:
            return N.satisfies(self.rule_name, move)
        return None

    def reply(self, message):
        """The keeper's turn. Returns (text, move, verdict)."""
        move = self.extract_move(message)
        verdict = self.verdict(move)

        if self.run_type == TROUBLESHOOT:
            if move is None:
                return ('I did not catch an action. Use one of these exact '
                        'names - ' + TS.action_menu(), None, None)
            obs = self.observations_from(self._history or [])
            before = TS.candidates(obs)
            after = TS.candidates(obs + [(move, verdict)])
            if TS.is_repair(move):
                if verdict:
                    return (f'{move} - that fixed it. The fault was '
                            f'{TS.FAULT_TEXT[self.rule_name]}.', move, True)
                return (f'{move} - no change; that was not the fault. '
                        f'{len(after)} possible causes remain.', move, False)
            answer = 'yes' if verdict else 'no'
            detail = TS.DIAGNOSTICS[move]['yes' if verdict else 'no']
            if len(after) == len(before):
                # A check that eliminates nothing has told the agent something it
                # already knew. Saying so is what makes a wasted turn legible as
                # a wasted turn rather than as bad luck.
                return (f'{move} - {answer}, {detail}. You already knew that; '
                        f'still {len(after)} possible causes.', move, verdict)
            return (f'{move} - {answer}, {detail}. That leaves {len(after)} '
                    f'possible cause{"" if len(after) == 1 else "s"}.', move, verdict)

        if self.run_type == RULE_INDUCTION:
            if move is None:
                return ("I need three whole numbers between 1 and 100 to answer.",
                        None, None)
            a, b, c = move
            return (f"{a}, {b}, {c} — {'yes' if verdict else 'no'}.", move, verdict)

        if self.run_type == CONSTRAINTS:
            if move is None:
                return ('Give me a sentence in double quotes.', None, None)
            accepted, rejected = self.attempts_from(self._history or [])
            got = len(self.distinct_accepted(self._history or []))
            if CR.is_repeat(move, rejected):
                return ('You have already tried that and I rejected it. '
                        'Try something you have not tried.', move, False)
            if verdict:
                # An accepted sentence that merely rewords one already given
                # shows nothing new. Say so - the agent cannot satisfy a
                # requirement it has not been told about, and silently not
                # counting the answer makes the task unfair rather than hard.
                known = [CR.opening_example(self.rule_name)] + \
                    self.distinct_accepted(self._history or [])
                if not CR.is_novel(move, known):
                    # Say what "different" means, or the requirement backfires.
                    # Told only to share few words, agents abandon the very
                    # features that made the sentence acceptable - the question
                    # form, the colour - and drift away from the one pattern
                    # known to work, because "vary your words" is
                    # indistinguishable from "your rule is wrong". Naming the
                    # distinction gives nothing away: the rules are unchanged
                    # and still unstated.
                    return (f'"{move[:60]}" - yes, that satisfies the rules, but it '
                            f'is too close to one I already have. Keep whatever you '
                            f'think makes it acceptable - I am not asking you to '
                            f'change that. Vary the subject matter and wording '
                            f'instead. Still {max(0, CR_TARGET - got)} to go.',
                            move, True)
                left = max(0, CR_TARGET - (got + 1))
                if left == 0:
                    return (f'"{move[:60]}" - yes. That is {CR_TARGET}; you are done.',
                            move, True)
                return (f'"{move[:60]}" - yes, and different enough. {left} more '
                        f'to go.', move, True)
            # How many rules held, but never which. This is the difference
            # between a task with a gradient and one without, and it is the
            # reason every graph in this project came out as a star.
            #
            # A bare "no" on a conjunction of hidden rules carries no
            # information about *direction*. An agent whose first attempt
            # satisfied two of three was told exactly what an agent satisfying
            # none was told, so it read a near miss as a refutation of the whole
            # frame and drifted away from the only pattern that worked. Nothing
            # could accumulate, so nothing could be routed through: a route is
            # made of partial progress, and there was none to record.
            #
            # The count keeps the induction problem intact - which rules are
            # still unstated, and there are many ways to satisfy any given
            # number of them - while making the search a hill to climb rather
            # than a cliff to fall off.
            n_ok = CR.satisfied_count(self.rule_name, move)
            n_all = len(CR.active(self.rule_name))
            return (f'"{move[:60]}" - no. That satisfies {n_ok} of my {n_all} '
                    f'rules.', move, False)

        if self.run_type == TRANSFORMATION:
            task = self.task()
            state = self.state_from(self._history or [])
            if move is None:
                return ('Give me your next sentence in double quotes.', None, None)
            if move == task['target']:
                if TR.is_small_step(state, move) and TR.holds(self.rule_name, move):
                    return (f'"{move}" - accepted. That is the target; you are done.',
                            move, True)
            d = TR.word_distance(state, move)
            if d == 0:
                left = TR.word_distance(state, task['target'])
                return (f'That is where you already are. You are {left} word(s) from '
                        f'the target; propose a different sentence.', move, None)
            if not TR.is_small_step(state, move):
                return (f'That changes {d} words at once; at most {TR.MAX_EDITS} are '
                        f'allowed. You are still at "{state}".', move, None)
            if not TR.holds(self.rule_name, move):
                return (f'"{move}" - not allowed. You are still at "{state}".',
                        move, False)
            left = TR.word_distance(move, task['target'])
            return (f'"{move}" - accepted. You are {left} word(s) from the target.',
                    move, True)

        if self.run_type == SENTENCE_INDUCTION:
            if move is None:
                return ('Give me a sentence in double quotes and I will answer.',
                        None, None)
            short = move if len(move) <= 60 else move[:57] + '...'
            return (f'"{short}" - {"yes" if verdict else "no"}.', move, verdict)

        if self.run_type == WORD_INDUCTION:
            if move is None:
                return ('Give me a single word in double quotes and I will answer.',
                        None, None)
            return (f'"{move}" — {"yes" if verdict else "no"}.', move, verdict)

        if self.run_type == HIDDEN_NORM:
            # The mood is decided here; the wording is left to the caller, which
            # may pass it to a model. Either way the fact is settled in code.
            return (('engaged' if verdict else 'withdrawn'), move, verdict)

        return ('', None, None)

    def observations_from(self, history):
        """Rebuild the evidence trail from the conversation.

        Each agent message may contain a move; the keeper's reply that follows
        carries the verdict. Reading it back from the transcript keeps the
        evidence in one place rather than duplicating it in session state.
        """
        out = []
        for i, (speaker, message) in enumerate(history):
            if speaker == 'keeper':
                continue
            move = self.extract_move(message)
            if move is None:
                continue
            verdict = None
            for later_speaker, later in history[i + 1:i + 3]:
                if later_speaker == 'keeper':
                    verdict = self.verdict(move)
                    break
            if verdict is not None:
                out.append((move, verdict))
        return out

    def rule_prompt(self):
        """What to ask the agent for, so its claim can be checked."""
        if self.run_type == RULE_INDUCTION:
            return ("- \"rule\": your current best guess at the hidden rule, as a Python "
                    "boolean expression over a, b, c (the three numbers in order). "
                    "For example 'a < b < c'. Use only arithmetic, comparisons and "
                    "and/or/not. This is how your guess gets checked, so it must mean "
                    "exactly what you believe.")
        if self.run_type == TROUBLESHOOT:
            return ('- "rule": the single fault you currently believe is responsible, '
                    'named exactly as one of: ' + ', '.join(sorted(TS.FAULTS)) +
                    '. This is checked against what you have already been told, so '
                    'naming a fault your own evidence has ruled out will be caught.')
        if self.run_type in (SENTENCE_INDUCTION, TRANSFORMATION, CONSTRAINTS):
            return ("- \"rule\": your current best guess at the hidden rule that decides "
                    "which sentences are allowed, as a boolean expression over the "
                    "sentence you are proposing.\n" + SR.PREDICATE_VOCAB)
        if self.run_type == WORD_INDUCTION:
            return ("- \"rule\": your current best guess at the hidden rule, as a boolean "
                    "expression over the word you are proposing.\n" + W.PREDICATE_VOCAB)
        if self.run_type == HIDDEN_NORM:
            return ("- \"rule\": your current best guess at the hidden rule, as a boolean "
                    "expression over the message you are sending.\n" + N.PREDICATE_VOCAB)
        return ''

    # -- scoring the agent's aim ------------------------------------------

    def check_aim(self, predicate, observations):
        """Is the agent's stated rule consistent with what it has been told?

        `observations` is [(move, verdict)]. Returns a dict with a decidable
        verdict where one exists, so the app can record whether an aim was
        genuinely refuted rather than only whether a judge disliked it. This is
        the difference between a NoGo that is a proof and one that is an
        opinion.
        """
        result = {'checkable': False, 'consistent': None,
                  'contradicted_by': None, 'holdout_accuracy': None}
        if not predicate or self.run_type == CHAT:
            return result

        if self.run_type == TROUBLESHOOT:
            # No predicate to compile: the claim is simply "the fault is X", and
            # the evidence either still permits X or has already excluded it.
            # Naming an excluded fault is a refutation the agent could have
            # derived itself from what it was told, which is exactly the kind of
            # mistake a decision graph is supposed to stop it repeating.
            claim = str(predicate).strip().lower()
            claim = next((f for f in TS.FAULTS if f in claim), None)
            if claim is None:
                return result
            result['checkable'] = True
            live = TS.candidates(observations)
            if claim in live:
                result['consistent'] = True
                # how much of the space this belief has narrowed to, in [0, 1]
                result['holdout_accuracy'] = round(
                    1.0 - (len(live) - 1) / max(len(TS.FAULTS) - 1, 1), 3)
                return result
            result['consistent'] = False
            for move, verdict in observations:
                if claim not in TS.candidates([(move, verdict)]):
                    result['contradicted_by'] = {'move': move, 'keeper': verdict}
                    break
            return result

        try:
            if self.run_type == RULE_INDUCTION:
                fn = compile_predicate(predicate)
                predict = lambda mv: bool(fn(*mv))          # noqa: E731
            elif self.run_type == CONSTRAINTS:
                predict = lambda mv: bool(compile_predicate(   # noqa: E731
                    predicate, funcs=CR.predicate_helpers(mv), variables=())())
            elif self.run_type == TRANSFORMATION:
                predict = lambda mv: bool(compile_predicate(   # noqa: E731
                    predicate, funcs=SR.predicate_helpers(mv), variables=())())
            elif self.run_type == SENTENCE_INDUCTION:
                predict = lambda mv: bool(compile_predicate(   # noqa: E731
                    predicate, funcs=SR.predicate_helpers(mv), variables=())())
            elif self.run_type == WORD_INDUCTION:
                predict = lambda mv: bool(compile_predicate(   # noqa: E731
                    predicate, funcs=W.predicate_helpers(mv), variables=())())
            else:
                predict = lambda mv: bool(compile_predicate(   # noqa: E731
                    predicate, funcs=N.predicate_helpers(mv), variables=())())
        except UnsafePredicate as e:
            result['error'] = str(e)
            return result

        result['checkable'] = True
        for move, verdict in observations:
            if move is None or verdict is None:
                continue
            try:
                if predict(move) != verdict:
                    result['consistent'] = False
                    result['contradicted_by'] = {'move': move, 'keeper': verdict}
                    return result
            except Exception:
                result['checkable'] = False
                return result
        result['consistent'] = True

        if self.run_type == RULE_INDUCTION:
            holdout = R.holdout_set(self.rule_name, n=24, seed=self.seed)
        elif self.run_type == CONSTRAINTS:
            holdout = CR.holdout_labels(self.rule_name, n=24, seed=self.seed)
        elif self.run_type in (SENTENCE_INDUCTION, TRANSFORMATION):
            holdout = SR.holdout_labels(self.rule_name, n=24, seed=self.seed)
        elif self.run_type == WORD_INDUCTION:
            holdout = W.holdout_labels(self.rule_name, n=24, seed=self.seed)
        else:
            holdout = N.holdout_labels(self.rule_name, n=24, seed=self.seed)
        hits = 0
        for item, truth in holdout:
            try:
                hits += (predict(item) == truth)
            except Exception:
                return result
        result['holdout_accuracy'] = round(hits / len(holdout), 3)
        return result


def make_keeper(settings):
    """Build the keeper a session's settings ask for, or None for plain chat."""
    run_type = (settings or {}).get('run_type', CHAT)
    if run_type not in RUN_TYPES or run_type == CHAT:
        return None
    return Keeper(run_type,
                  rule_name=(settings or {}).get('keeper_rule'),
                  seed=int((settings or {}).get('seed', 0) or 0))
