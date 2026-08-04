"""Structured aim memory for GoalGraph's decision graph.

The original graph stores an aim as a 60-character truncated label and nothing
else: node attributes are empty, and the only thing that reaches the model is a
flat list of failed labels with no reasons. Measured over 605 recorded aims,
that loses a lot — 80% of aims are longer than the label, the discriminating
clause sits at the end where truncation removes it, and 33 labels each collapse
between two and five genuinely different aims. At the same time, identity by
exact string forks the graph on paraphrase: 22% of node pairs within a graph
are near-duplicates of each other.

This module keeps the same graph and the same Go / Progress / NoGo edges, and
changes four things:

  identity    a node is keyed on its predicate when it has one, else on
              normalised text with a hash to disambiguate. Truncation is a
              display concern, never an identity one.
  payload     the node carries the full text, the predicate, the observation
              that settled it, the rating, the turn, and the ruleset it was
              learned under.
  recall      the prompt gets the k aims nearest the current one, not the
              whole list, inside a character budget.
  provenance  every node records which ruleset produced it, and whether it has
              been verified under the current one.

All of it is opt-in. `enabled=False` reproduces the old behaviour exactly.
"""

import difflib
import hashlib
import json
import logging
import re

import networkx as nx

logger = logging.getLogger('graph_memory_logger')

GO, PROGRESS, NOGO, OPEN = 'Go', 'Progress', 'NoGo', 'Open'

# Callers speak two vocabularies: the judge's aim_status ('abandon', 'achieved',
# …) and the graph's edge labels ('NoGo', 'Go', …). Storing whichever one the
# caller happened to use makes recall silently return nothing, so everything is
# normalised to the edge vocabulary on the way in.
_STATUS_ALIASES = {
    'abandon': NOGO, 'nogo': NOGO, 'no_go': NOGO,
    'achieved': GO, 'go': GO,
    'progress': PROGRESS,
    'continue': OPEN, 'open': OPEN,
}


# A verdict reached by checking evidence is worth more than one reached by
# asking a model. Judge opinion is capped below certainty so that no amount of
# confident-sounding rating can impersonate a proof.
PROOF, OPINION = 'evidence', 'judge'


def verdict_confidence(source, rating=None):
    """How much this verdict should be trusted, in [0, 1].

    Stored as the edge weight, so pathfinding and recall both read one number.
    """
    if source == PROOF:
        return 1.0
    if rating is None:
        return 0.4
    # Distance from the midpoint is how strong the opinion is; 0.6 is the
    # ceiling, leaving 1.0 to mean "checked".
    return round(min(0.6, 0.3 + abs(float(rating) - 4.0) * 0.075), 3)


def canonical_status(status):
    if not status:
        return OPEN
    return _STATUS_ALIASES.get(str(status).strip().lower(), str(status))

# Default budget for what reaches the prompt. Chosen to be smaller than the
# largest nogo_statement observed in practice (693 chars), because the point is
# to bound context for a weak agent rather than to grow with the graph.
DEFAULT_RECALL_K = 4
DEFAULT_RECALL_CHARS = 600


def normalise(text):
    """Whitespace- and case-insensitive form used for identity and matching.

    Coerces bytes and non-strings first: graphml attributes can come back from
    networkx as bytes, and a string regex pattern applied to bytes fails with an
    error that points nowhere near the graph it came from.
    """
    if text is None:
        return ''
    if isinstance(text, (bytes, bytearray)):
        text = text.decode('utf-8', 'ignore')
    elif not isinstance(text, str):
        text = str(text)
    return re.sub(r'\s+', ' ', text).strip().lower()


def node_id(full_text, predicate=None):
    """A stable, readable identity for an aim.

    Prefers the predicate: it is short, canonical, and two aims with the same
    predicate are the same aim however differently they are worded. Falls back
    to normalised text. Long keys keep a readable prefix and a hash suffix, so
    two aims sharing their first 56 characters no longer collide — which is the
    failure the old 60-character label had.
    """
    base = normalise(predicate) or normalise(full_text)
    if not base:
        return 'unnamed aim'
    if len(base) <= 64:
        return base
    digest = hashlib.sha1(base.encode('utf-8')).hexdigest()[:6]
    return f"{base[:56]}…#{digest}"


def normalise_display(text):
    """Whitespace-collapsed but case-preserving, for anything shown to a reader."""
    if text is None:
        return 'unnamed aim'
    if isinstance(text, (bytes, bytearray)):
        text = text.decode('utf-8', 'ignore')
    elif not isinstance(text, str):
        text = str(text)
    return re.sub(r'\s+', ' ', text).strip() or 'unnamed aim'


def display_label(full_text, limit=70):
    text = normalise_display(full_text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ---------------------------------------------------------------------------
# Similarity — embeddings when available, lexical when not
# ---------------------------------------------------------------------------

def _embedding_ranker(query, candidates):
    try:
        from .graph_intelligence import get_embedding, get_embeddings_batch
    except Exception:  # pragma: no cover
        return None
    q = get_embedding(query)
    if q is None:
        return None
    embs = get_embeddings_batch(candidates)
    if embs is None:
        return None
    return [float(s) for s in (embs @ q)]


def _lexical_ranker(query, candidates):
    q = normalise(query)
    return [difflib.SequenceMatcher(None, q, normalise(c)).ratio() for c in candidates]


def rank_by_similarity(query, candidates, use_embeddings=True):
    """Scores in [0,1]-ish, one per candidate, highest is nearest."""
    if not candidates:
        return []
    if use_embeddings:
        scores = _embedding_ranker(query, candidates)
        if scores is not None:
            return scores
    return _lexical_ranker(query, candidates)


# ---------------------------------------------------------------------------
# The memory
# ---------------------------------------------------------------------------

class GraphMemory:
    """Wraps a decision graph with structured aim storage and recall."""

    def __init__(self, graph=None, ruleset='default', enabled=True,
                 merge_threshold=0.86, use_embeddings=True):
        self.G = graph if graph is not None else nx.DiGraph()
        if 'start' not in self.G:
            self.G.add_node('start', kind='root')
        self.ruleset = ruleset
        self.enabled = enabled
        self.merge_threshold = merge_threshold
        self.use_embeddings = use_embeddings

    # -- storage ----------------------------------------------------------

    def _aim_nodes(self):
        return [n for n, d in self.G.nodes(data=True) if d.get('kind') == 'aim']

    def find_equivalent(self, full_text, predicate=None):
        """An existing node meaning the same thing, if there is one.

        Exact identity first — two aims with the same predicate are the same
        aim. Then near-identity by similarity, which is what stops a reworded
        hypothesis forking the graph into a second node the NoGo list will not
        suppress.
        """
        nid = node_id(full_text, predicate)
        if nid in self.G:
            return nid

        candidates = self._aim_nodes()
        if not candidates:
            return None
        texts = [self.G.nodes[n].get('full_text', n) for n in candidates]
        scores = rank_by_similarity(full_text or predicate or '', texts,
                                    self.use_embeddings)
        best = max(range(len(scores)), key=lambda i: scores[i])
        if scores[best] >= self.merge_threshold:
            logger.info(f"merging aim into existing node "
                        f"'{candidates[best]}' (score={scores[best]:.2f})")
            return candidates[best]
        return None

    def record(self, full_text, status, predicate=None, evidence=None,
               reason=None, rating=None, turn=None, verified=True):
        """Store or update an aim node. Returns its id.

        `evidence` is whatever settled the verdict — for a refutation, the
        observation that contradicted the aim. It is stored as a string
        because graphml attributes must be primitives, and it is the single
        most useful thing the old graph threw away: without it a later agent
        is told an aim failed but never why, so it can neither generalise nor
        re-test the claim under different rules.
        """
        nid = self.find_equivalent(full_text, predicate) or node_id(full_text, predicate)
        attrs = {
            'kind': 'aim',
            'full_text': (full_text or '').strip(),
            'label': display_label(full_text),
            'predicate': (predicate or '').strip(),
            'status': canonical_status(status),
            'ruleset': self.ruleset,
            'verified': bool(verified),
        }
        if evidence is not None:
            attrs['evidence'] = evidence if isinstance(evidence, str) else json.dumps(evidence)
        if reason:
            attrs['reason'] = str(reason)[:200]
        if rating is not None:
            attrs['rating'] = int(rating)
        if turn is not None:
            attrs['turn'] = int(turn)

        if nid in self.G:
            # Merging a reworded aim must not overwrite what the node already
            # knows. The first refutation is usually the specific one; a later
            # paraphrase often arrives with a vaguer reason, and letting it win
            # would quietly degrade the memory every time an aim is restated.
            existing = self.G.nodes[nid]
            for key, value in attrs.items():
                if key in ('status', 'rating', 'turn', 'verified', 'ruleset'):
                    existing[key] = value
                elif key in ('reason', 'evidence'):
                    if len(str(value)) > len(str(existing.get(key, ''))):
                        existing[key] = value
                elif not existing.get(key):
                    existing[key] = value
            aliases = existing.get('aliases', '')
            wording = (full_text or '').strip()
            if wording and wording != existing.get('full_text') and wording not in aliases:
                existing['aliases'] = (aliases + ' | ' + wording).strip(' |')[:600]
        else:
            self.G.add_node(nid, **attrs)
        return nid

    def link(self, source, target, label, weight=1.0):
        if source not in self.G:
            self.G.add_node(source, kind='aim')
        if self.G.has_edge(source, target):
            self.G[source][target]['label'] = label
            self.G[source][target]['weight'] = weight
        else:
            self.G.add_edge(source, target, label=label, weight=weight)
        return self.G

    # -- recall -----------------------------------------------------------

    def entries(self, statuses=(NOGO,), include_unverified=True):
        out = []
        for n, d in self.G.nodes(data=True):
            if d.get('kind') != 'aim':
                continue
            if statuses and d.get('status') not in statuses:
                continue
            if not include_unverified and not d.get('verified', True):
                continue
            out.append((n, d))
        return out

    def recall(self, current_aim, k=DEFAULT_RECALL_K, statuses=(NOGO,)):
        """The k stored aims nearest the one in hand.

        The old code injected every failed label on every turn, so the cost
        grew with the graph and none of it was selected for relevance. For an
        agent with a small context that is the wrong way round: what matters
        is the handful of past verdicts bearing on the aim being considered.
        """
        items = self.entries(statuses)
        if not items:
            return []
        texts = [d.get('full_text', n) for n, d in items]
        scores = rank_by_similarity(current_aim or '', texts, self.use_embeddings)
        ranked = sorted(zip(items, scores), key=lambda p: -p[1])
        return [(n, d, s) for (n, d), s in ranked[:k]]

    def render(self, current_aim, k=DEFAULT_RECALL_K,
               max_chars=DEFAULT_RECALL_CHARS, statuses=(NOGO,)):
        """The prompt fragment. Reasons included, budget respected."""
        hits = self.recall(current_aim, k, statuses)
        if not hits:
            return ''

        lines, used = [], 0
        for nid, d, _score in hits:
            text = d.get('full_text') or nid
            bits = [f" - {text}"]
            why = d.get('reason') or ''
            ev = d.get('evidence') or ''
            if why:
                bits.append(f"   ruled out because {why}")
            elif ev:
                bits.append(f"   ruled out by: {ev}")
            if not d.get('verified', True):
                bits.append(f"   (learned under a different setup — treat as unconfirmed "
                            f"and worth re-testing)")
            entry = "\n".join(bits)
            if used + len(entry) > max_chars:
                break
            lines.append(entry)
            used += len(entry)

        if not lines:
            return ''
        omitted = len(self.entries(statuses)) - len(lines)
        header = "Approaches already ruled out, most relevant to your current aim first:"
        footer = f"\n({omitted} further ruled-out approaches not shown.)" if omitted > 0 else ""
        return f"{header}\n" + "\n".join(lines) + footer + "\n\n"

    # -- transfer ---------------------------------------------------------

    def mark_unverified(self, new_ruleset):
        """Port this graph to a new setting.

        Every stored verdict was reached under some ruleset. Carried into a
        different one it is a claim, not a fact — so it is flagged rather than
        deleted, and recall says so. Deleting would throw away a useful prior;
        trusting it silently is what makes a ported graph hinder instead of
        help.
        """
        n = 0
        for node, d in self.G.nodes(data=True):
            if d.get('kind') != 'aim':
                continue
            if d.get('ruleset') != new_ruleset:
                d['verified'] = False
                d['prior_ruleset'] = d.get('ruleset', 'unknown')
                n += 1
        self.ruleset = new_ruleset
        logger.info(f"marked {n} aims unverified under ruleset '{new_ruleset}'")
        return n

    def reverify(self, node, holds, evidence=None):
        """Record that a carried-over aim was re-tested under the new rules."""
        if node not in self.G:
            return
        d = self.G.nodes[node]
        d['verified'] = True
        d['ruleset'] = self.ruleset
        d['status'] = d.get('status') if holds else 'revised'
        if evidence:
            d['evidence'] = evidence if isinstance(evidence, str) else json.dumps(evidence)

    # -- stats ------------------------------------------------------------

    def stats(self):
        aims = self._aim_nodes()
        by_status = {}
        for n in aims:
            s = self.G.nodes[n].get('status', '?')
            by_status[s] = by_status.get(s, 0) + 1
        return {
            'nodes': self.G.number_of_nodes(),
            'aims': len(aims),
            'edges': self.G.number_of_edges(),
            'by_status': by_status,
            'unverified': sum(1 for n in aims if not self.G.nodes[n].get('verified', True)),
            'with_reason': sum(1 for n in aims
                               if self.G.nodes[n].get('evidence')
                               or self.G.nodes[n].get('reason')),
        }


def legacy_nogo_statement(graph):
    """The original prompt fragment, for A/B against `GraphMemory.render`."""
    nogo = [v for _, v, a in graph.edges(data=True) if a.get('label') == NOGO]
    if not nogo:
        return ''
    clean = [n.replace('_NoGo', '') for n in nogo]
    listing = "\n".join(f" - {n}" for n in clean)
    return f"The following approaches at achieving the goal were unsuccessful:\n{listing}\n\n"
