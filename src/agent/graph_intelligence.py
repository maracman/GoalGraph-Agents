"""
Graph intelligence module: embedding-based search, pathfinding, and graph import/merge.

Each agent builds its own decision graph. This module adds the ability to:
1. Embed node labels and find which existing node is closest to a goal
2. Find the shortest weighted path from the current position to that node
3. Import another agent's graph into the current one
4. Combine multiple graphs into a single merged graph
"""

import logging
import networkx as nx
import numpy as np
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger('graph_intelligence')

# ---------------------------------------------------------------------------
# Embedding service – lazy-loaded sentence-transformers
# ---------------------------------------------------------------------------

_embedding_model = None
_embedding_cache: Dict[str, np.ndarray] = {}


def _get_embedding_model():
    """Lazy-load the sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            return None
    return _embedding_model


def get_embedding(text: str) -> Optional[np.ndarray]:
    """Get the embedding for a text string, using cache."""
    if text in _embedding_cache:
        return _embedding_cache[text]

    model = _get_embedding_model()
    if model is None:
        return None

    try:
        embedding = model.encode(text, normalize_embeddings=True)
        _embedding_cache[text] = embedding
        return embedding
    except Exception as e:
        logger.error(f"Error computing embedding: {e}")
        return None


def get_embeddings_batch(texts: List[str]) -> Optional[np.ndarray]:
    """Get embeddings for multiple texts at once (more efficient)."""
    model = _get_embedding_model()
    if model is None:
        return None

    # Split into cached and uncached
    uncached_texts = [t for t in texts if t not in _embedding_cache]

    if uncached_texts:
        try:
            new_embeddings = model.encode(uncached_texts, normalize_embeddings=True)
            for text, emb in zip(uncached_texts, new_embeddings):
                _embedding_cache[text] = emb
        except Exception as e:
            logger.error(f"Error computing batch embeddings: {e}")
            return None

    return np.array([_embedding_cache[t] for t in texts])


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors (already normalized)."""
    return float(np.dot(a, b))


def clear_embedding_cache():
    """Clear the embedding cache (useful after graph merge)."""
    global _embedding_cache
    _embedding_cache.clear()


# ---------------------------------------------------------------------------
# Graph search – find nearest goal node and path to it
# ---------------------------------------------------------------------------

def find_nearest_goal_node(
    graph: nx.DiGraph,
    goal_text: str,
    min_similarity: float = 0.3,
    exclude_nodes: Optional[List[str]] = None
) -> Optional[Tuple[str, float]]:
    """Find the node in the graph whose label is most similar to the goal.

    Args:
        graph: The agent's decision graph.
        goal_text: The agent's ultimate goal text.
        min_similarity: Minimum cosine similarity threshold.
        exclude_nodes: Nodes to skip (e.g. 'start', NoGo nodes).

    Returns:
        (node_name, similarity_score) or None if no good match found.
    """
    exclude = set(exclude_nodes or [])
    exclude.add('start')  # Always skip the start node

    # Filter out NoGo nodes and excluded nodes
    candidate_nodes = [
        n for n in graph.nodes()
        if n not in exclude and not n.endswith('_NoGo')
    ]

    if not candidate_nodes:
        return None

    goal_emb = get_embedding(goal_text)
    if goal_emb is None:
        return None

    node_embs = get_embeddings_batch(candidate_nodes)
    if node_embs is None:
        return None

    # Compute similarities
    similarities = node_embs @ goal_emb  # dot product (normalized = cosine)

    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    if best_score < min_similarity:
        logger.info(
            f"No node similar enough to goal (best: '{candidate_nodes[best_idx]}' "
            f"score={best_score:.3f} < threshold={min_similarity})"
        )
        return None

    best_node = candidate_nodes[best_idx]
    logger.info(f"Found nearest goal node: '{best_node}' (similarity={best_score:.3f})")
    return best_node, best_score


def find_path_to_node(
    graph: nx.DiGraph,
    source: str,
    target: str,
    prefer_go_edges: bool = True
) -> Optional[List[str]]:
    """Find the shortest path from source to target in the graph.

    Args:
        graph: The agent's decision graph.
        source: Current node.
        target: Target node.
        prefer_go_edges: If True, weight NoGo edges much higher to prefer Go paths.

    Returns:
        List of node names forming the path, or None if no path exists.
    """
    if source not in graph or target not in graph:
        return None

    if source == target:
        return [source]

    try:
        if prefer_go_edges:
            # Create a weight function that penalizes NoGo edges
            def edge_weight(u, v, data):
                base_weight = data.get('weight', 1.0)
                if data.get('label') == 'NoGo':
                    return base_weight * 10  # Heavy penalty for failed paths
                return base_weight

            path = nx.shortest_path(
                graph, source=source, target=target, weight=edge_weight
            )
        else:
            path = nx.shortest_path(
                graph, source=source, target=target, weight='weight'
            )

        logger.info(f"Found path: {' -> '.join(path)} (length={len(path)-1})")
        return path

    except nx.NetworkXNoPath:
        logger.info(f"No path from '{source}' to '{target}'")
        return None
    except nx.NodeNotFound as e:
        logger.warning(f"Node not found in graph: {e}")
        return None


def find_path_to_goal(
    graph: nx.DiGraph,
    current_node: str,
    goal_text: str,
    min_similarity: float = 0.3
) -> Optional[Tuple[List[str], str, float]]:
    """Find the best path from current position toward the goal.

    Combines embedding search (find nearest goal node) with pathfinding.

    Returns:
        (path, target_node, similarity_score) or None if no viable path.
    """
    result = find_nearest_goal_node(graph, goal_text, min_similarity)
    if result is None:
        return None

    target_node, similarity = result

    path = find_path_to_node(graph, current_node, target_node)
    if path is None or len(path) < 2:
        # No path or already at the target
        return None

    return path, target_node, similarity


# ---------------------------------------------------------------------------
# Graph import and merge
# ---------------------------------------------------------------------------

def import_graph(
    target: nx.DiGraph,
    source: nx.DiGraph,
    namespace: Optional[str] = None
) -> nx.DiGraph:
    """Import nodes and edges from a source graph into the target graph.

    Args:
        target: The graph to import into (modified in place and returned).
        source: The graph to import from (not modified).
        namespace: Optional prefix for source node names to avoid collisions.
                   If None, nodes with the same name are merged.

    Returns:
        The target graph with imported nodes/edges.
    """
    def _rename(node_name):
        if namespace:
            return f"{namespace}/{node_name}"
        return node_name

    # Import nodes
    for node in source.nodes():
        new_name = _rename(node)
        if new_name not in target:
            target.add_node(new_name)

    # Import edges
    for u, v, data in source.edges(data=True):
        new_u = _rename(u)
        new_v = _rename(v)

        if target.has_edge(new_u, new_v):
            # Edge already exists – keep the one with lower weight (fewer attempts)
            existing_weight = target[new_u][new_v].get('weight', float('inf'))
            new_weight = data.get('weight', float('inf'))
            if new_weight < existing_weight:
                target[new_u][new_v].update(data)
        else:
            target.add_edge(new_u, new_v, **data)

    logger.info(
        f"Imported graph: {source.number_of_nodes()} nodes, "
        f"{source.number_of_edges()} edges "
        f"(namespace={'None' if not namespace else namespace})"
    )
    return target


def combine_graphs(
    graphs: List[nx.DiGraph],
    namespaces: Optional[List[str]] = None
) -> nx.DiGraph:
    """Combine multiple graphs into a single merged graph.

    Args:
        graphs: List of graphs to combine.
        namespaces: Optional list of prefixes for each graph's nodes.
                    If None, nodes with the same name across graphs are merged.

    Returns:
        A new combined graph.
    """
    combined = nx.DiGraph()
    combined.add_node('start')

    for i, graph in enumerate(graphs):
        ns = namespaces[i] if namespaces and i < len(namespaces) else None
        import_graph(combined, graph, namespace=ns)

    logger.info(
        f"Combined {len(graphs)} graphs: "
        f"{combined.number_of_nodes()} nodes, {combined.number_of_edges()} edges"
    )
    return combined


def link_similar_nodes(
    graph: nx.DiGraph,
    similarity_threshold: float = 0.8,
    link_weight: float = 0.1
) -> nx.DiGraph:
    """Add zero-cost edges between semantically similar nodes in the graph.

    This connects subgraphs that describe similar subgoals, enabling pathfinding
    across imported graphs even when node names don't exactly match.

    Args:
        graph: The graph to add links to (modified in place).
        similarity_threshold: Min cosine similarity to create a link.
        link_weight: Weight for the new edges (low = easy to traverse).

    Returns:
        The graph with new similarity edges added.
    """
    # Get all non-special nodes
    nodes = [
        n for n in graph.nodes()
        if n != 'start' and not n.endswith('_NoGo')
    ]

    if len(nodes) < 2:
        return graph

    embeddings = get_embeddings_batch(nodes)
    if embeddings is None:
        return graph

    # Compute pairwise similarities
    sim_matrix = embeddings @ embeddings.T
    links_added = 0

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if sim_matrix[i, j] >= similarity_threshold:
                # Add bidirectional edges if they don't already exist
                for u, v in [(nodes[i], nodes[j]), (nodes[j], nodes[i])]:
                    if not graph.has_edge(u, v):
                        graph.add_edge(
                            u, v,
                            label='Similar',
                            weight=link_weight,
                            similarity=float(sim_matrix[i, j])
                        )
                        links_added += 1

    if links_added > 0:
        logger.info(f"Added {links_added} similarity links (threshold={similarity_threshold})")

    return graph
