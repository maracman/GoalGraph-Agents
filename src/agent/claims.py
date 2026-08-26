"""Deciding whether a speaker actually committed to a label.

Every task whose counterparty is another agent has the same problem: the
agent's conclusion arrives as prose, and something has to decide whether a
conclusion was reached and which one it was. Each task answered it separately,
and all three answers were the same two mistakes -

  * they accepted the substring 'diagnos' as evidence of a commitment, so
    "nothing here is diagnostic of HIV yet" counted as diagnosing HIV; and
  * they returned the first label in their own list order that appeared
    anywhere in the message, so a sentence ruling one condition out in favour
    of another was scored as claiming the one being ruled out.

Measured over 311 stored transcripts, 16 of 175 completions - 9% - fired on a
message that asserted nothing. Every one truncated its run and scored it
solved, so the error inflated solve counts and deflated turns-to-solve at the
same time.

This module holds only the general rule: a claim needs an assertion, the label
is whatever that assertion points at, and anything else is not a claim. The
vocabulary stays with each task, which is where it belongs - a caller passes
its own labels in.

It fails closed on purpose. A missed commitment scores a solved run as
unsolved, which is visible and recoverable; a false one silently manufactures
a success.
"""
import re

# What committing actually sounds like. The clinical briefs instruct the agent
# to write "I diagnose <x>", so that form leads; the rest are the paraphrases
# that show up in practice.
_ASSERTION = re.compile(
    r'\bi (?:now |would |will )?diagnose\b'
    r'|\bi am diagnosing\b'
    r'|\b(?:my|the|final|working) diagnosis is\b'
    # "diagnosis:" commits; "differential diagnosis:" enumerates. The bare
    # form matched inside the differential one, which scored a clinician
    # LISTING candidates as committing to whichever came first.
    r'|(?<!differential )\bdiagnosis\s*:',
    re.I)

# Hedges and refusals that precede the assertion rather than complete it:
# "I cannot diagnose", "before I diagnose", "I am not ready to diagnose".
_HEDGE = re.compile(
    r'\b(?:not|never|cannot|can\'?t|won\'?t|unable|before|until|rather than|'
    r'without|ready|able|enough|yet|hesitate|reluctant)\b'
    r'[^.]{0,24}$',
    re.I)


def claimed_label(text, labels):
    """The label the speaker committed to in `text`, or None.

    `labels` maps a key to the strings that name it in prose. The key is
    returned, so a caller gets back its own identifier rather than whatever
    wording the agent happened to use.
    """
    body = str(text or '')
    if not body or not labels:
        return None

    for assertion in _ASSERTION.finditer(body):
        # An assertion that is itself negated is not a commitment.
        if _HEDGE.search(body[:assertion.start()]):
            continue
        tail = body[assertion.end():].lower()
        if not tail.strip():
            continue
        # The label is the one the assertion points at - nearest first - not
        # the first in the caller's list order. That distinction is the whole
        # bug: "I diagnose Influenza" in a message that also mentions HIV was
        # scored as HIV purely because HIV sorts earlier.
        # Only look inside the sentence the assertion starts; text past the
        # full stop is discussion, not the commitment.
        sentence_end = tail.find('.')
        span = tail if sentence_end < 0 else tail[:sentence_end + 1]
        best, best_at, named = None, len(span) + 1, set()
        for key, aliases in labels.items():
            for alias in aliases:
                alias = str(alias or '').strip().lower()
                if not alias:
                    continue
                at = span.find(alias)
                if at >= 0:
                    named.add(key)
                    if at < best_at:
                        best, best_at = key, at
        # Naming several conditions in the committing sentence is a list, not
        # a commitment - "diagnosis: HIV, influenza or SLE" commits to none
        # of them, and scoring the nearest was inventing a choice the speaker
        # did not make.
        if best is not None and len(named) == 1:
            return best
    return None


def aliases_for(name):
    """The usual ways a label written as a canonical name appears in prose."""
    name = str(name or '')
    out = {name, name.replace('_', ' ')}
    head = name.split('(')[0].strip()
    if head:
        out.add(head)
        out.add(head.replace('_', ' '))
    return [a.lower() for a in out if a]
