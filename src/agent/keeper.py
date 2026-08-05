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
CHAT = 'chat'

RUN_TYPES = (CHAT, RULE_INDUCTION, WORD_INDUCTION, SENTENCE_INDUCTION,
             TRANSFORMATION, CONSTRAINTS, HIDDEN_NORM)


def available_rules(run_type):
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

    def describe(self):
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

    def is_complete(self, history):
        """Has the task been finished? Only meaningful where there is a target."""
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

    def progress_note(self, history):
        """What advancing looks like from here, so an evolved aim has somewhere to go."""
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

    def agent_goal(self):
        """What the agent is actually trying to do in this run.

        Without this the session keeps whatever persona the chat scenario had,
        and the agent argues about a subscription while the keeper answers
        questions about integers.
        """
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
