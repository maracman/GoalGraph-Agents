import logging
import re
import time
import json
import random
import difflib
import networkx as nx
import pandas as pd
from .schemas import (
    json_schemas,
    json_schema_review_goal,
    json_schema_new_subgoal,
    json_schema_response
)
from .llm_service import llm_service
from .graph_intelligence import (
    find_path_to_goal,
    import_graph,
    combine_graphs,
    link_similar_nodes
)

# Set up logging
logger = logging.getLogger('agent_logger')


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def extract_json(response_text):
    """Extract a JSON object from a string that might contain extra text."""
    try:
        start_index = response_text.find('{')
        end_index = response_text.rfind('}') + 1
        if start_index != -1 and end_index > 0:
            return response_text[start_index:end_index]
    except Exception as e:
        logger.error(f"Error extracting JSON: {e}")
    return response_text


def validate_json(response_text, schema):
    """Parse JSON text and validate against a schema (best-effort)."""
    try:
        output = json.loads(response_text)
        # Light validation: check required keys exist
        for key in schema.get("required", []):
            if key not in output:
                logger.warning(f"Missing required key '{key}' in JSON output")
                return None
        return output
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error: {e}")
        # Try extracting JSON from surrounding text
        extracted = extract_json(response_text)
        if extracted != response_text:
            try:
                output = json.loads(extracted)
                for key in schema.get("required", []):
                    if key not in output:
                        return None
                return output
            except json.JSONDecodeError:
                pass
    return None


def is_too_similar(text1, text2, threshold=0.2):
    """Return True if two strings are more similar than the threshold."""
    if not text1 or not text2:
        return False
    similarity = difflib.SequenceMatcher(None, text1, text2).ratio()
    return similarity > threshold


# ---------------------------------------------------------------------------
# LLM helper – sends a prompt through the existing llm_service
# ---------------------------------------------------------------------------

def llm_judge_call(system_prompt, user_prompt, generation_vars):
    """Make a lightweight LLM call for the judge / subgoal generator.

    Uses lower temperature and fewer tokens than the main agent call.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    options = {
        'temperature': 0.5,
        'max_tokens': 400,
        'top_p': 0.9,
    }
    # Carry over provider / model from generation_vars so the judge uses the
    # same backend the agent is configured with.
    for key in ('provider', 'model', 'offline'):
        if key in generation_vars:
            options[key] = generation_vars[key]

    if options.get('offline', False):
        return None  # Cannot judge in offline mode

    try:
        raw = llm_service.complete(messages, options)
        return raw
    except Exception as e:
        logger.error(f"LLM judge call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_go_nogo_nodes(graph):
    """Return lists of Go and NoGo destination nodes from the graph."""
    go_nodes = []
    nogo_nodes = []
    for u, v, data in graph.edges(data=True):
        label = data.get('label', '')
        if label == 'Go':
            go_nodes.append(v)
        elif label == 'NoGo':
            nogo_nodes.append(v)
    return go_nodes, nogo_nodes


def update_graph(graph, current_node, next_node, label, weight=1.0):
    """Add or update an edge in the agent's decision graph."""
    if current_node not in graph:
        graph.add_node(current_node)
    if next_node not in graph:
        graph.add_node(next_node)

    if graph.has_edge(current_node, next_node):
        graph[current_node][next_node]['label'] = label
        graph[current_node][next_node]['weight'] = weight
    else:
        graph.add_edge(current_node, next_node, label=label, weight=weight)

    return graph


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_prompt(history, agent_description, goal, name, user_name,
                  current_aim=None, suggestion=None, last_narration=None):
    """Format the prompt for the agent, including subgoal context."""

    system_prompt = f"""You are {name}, an intelligent agent with the following description:
{agent_description}

Your goal is: {goal}
"""
    if current_aim:
        system_prompt += f"\nYour current subgoal is: {current_aim}\n"
    if suggestion:
        system_prompt += f"Suggested next action: {suggestion}\n"

    system_prompt += """
Always respond in character. Maintain consistent behavior and personality throughout the conversation.
Respond with a JSON object containing:
- "agent_response": your in-character response text
- "narration": (optional) brief narration describing actions, appearances, or behaviors accompanying your response

IMPORTANT: Do NOT repeat previous responses or narration.
Respond ONLY with the JSON object, no other text."""

    conversation = ""
    for speaker, message in history:
        if speaker == "user":
            conversation += f"{user_name}: {message}\n"
        else:
            conversation += f"{speaker}: {message}\n"

    full_prompt = f"{system_prompt}\n\nConversation:\n{conversation}"
    return full_prompt


def format_chat_messages(history, agent_description, goal, name, user_name,
                         current_aim=None, suggestion=None):
    """Format as chat messages for providers that support it."""
    messages = []

    system_content = f"""You are {name}, an intelligent agent with the following description:
{agent_description}

Your goal is: {goal}
"""
    if current_aim:
        system_content += f"\nYour current subgoal is: {current_aim}\n"
    if suggestion:
        system_content += f"Suggested next action: {suggestion}\n"

    system_content += """
Always respond in character. Respond with a JSON object containing:
- "agent_response": your in-character response text
- "narration": (optional) brief narration of actions/behaviors

Respond ONLY with the JSON object."""

    messages.append({"role": "system", "content": system_content})

    for speaker, message in history:
        role = "user" if speaker == "user" else "assistant"
        messages.append({"role": role, "content": message})

    return messages


# ---------------------------------------------------------------------------
# Subgoal management
# ---------------------------------------------------------------------------

def review_subgoal(history, agent, generation_vars, graph):
    """Use the LLM to judge whether the current subgoal has been achieved.

    Returns (rating, justification, suggestion) or (None, None, None) on failure.
    """
    agent_name = agent['agent_name']
    current_aim = agent['current_aim']
    previous_score = agent['persistance_score'] if agent['persistance_score'] is not None else 4

    recent_exchanges = "\n".join(
        [f"{m[0]}: {m[1]}" for m in history[-10:]]
    )

    system_prompt = "You are an impartial evaluator. Always respond with valid JSON only."

    user_prompt = f"""This is the current conversation:
{recent_exchanges}

Based on this chat, has {agent_name} achieved the below goal?
Goal: "{current_aim}"

Answer using the following scale:
1 = Strongly disagree, 2 = Disagree, 3 = Slightly disagree,
4 = Neither agree nor disagree, 5 = Slightly agree, 6 = Agree, 7 = Strongly agree.

Justify your response, then provide a suggestion (to guide {agent_name}'s next action) that
increases their chances at achieving this goal.

Respond with JSON: {{"rating": <int 1-7>, "justification": "<text>", "suggestion": "<text>"}}"""

    raw = llm_judge_call(system_prompt, user_prompt, generation_vars)
    if raw is None:
        return None, None, None

    output = validate_json(raw, json_schema_review_goal)
    if output is None:
        logger.warning(f"Failed to parse review_subgoal response: {raw[:200]}")
        return None, None, None

    rating = output.get('rating')
    justification = output.get('justification', '')
    suggestion = output.get('suggestion', '')

    # Clamp rating to valid range
    if isinstance(rating, (int, float)):
        rating = max(1, min(7, int(rating)))
    else:
        return None, None, None

    logger.info(f"Subgoal review for '{current_aim}': rating={rating}, justification={justification[:80]}")
    return rating, justification, suggestion


def generate_new_subgoal(history, agent, generation_vars, graph):
    """Use the LLM to generate a new subgoal for the agent.

    Returns (new_subgoal, planned_action) or (None, None) on failure.
    """
    agent_name = agent['agent_name']
    goal = agent['goal']
    description = agent['description']
    target_impression = agent.get('target_impression', '')
    environment_changes = agent.get('environment_changes', '')
    new_information = agent.get('new_information', '')

    recent_exchanges = "\n".join(
        [f"{m[0]}: {m[1]}" for m in history[-10:]]
    )

    # Get failed approaches from graph
    _, nogo_nodes = get_go_nogo_nodes(graph)
    nogo_statement = ""
    if nogo_nodes:
        # Strip _NoGo suffix for readability
        clean_nodes = [n.replace('_NoGo', '') for n in nogo_nodes]
        nogo_list = "\n".join([f" - {node}" for node in clean_nodes])
        nogo_statement = f"The following approaches at achieving the goal were unsuccessful:\n{nogo_list}\n\n"

    environment_info = ""
    if environment_changes:
        environment_info += f"Recent environment changes: {environment_changes}\n"
    if new_information:
        environment_info += f"New information: {new_information}\n"

    system_prompt = "You are a strategic planner. Always respond with valid JSON only."

    user_prompt = f"""Current Context:
Recent chat: {recent_exchanges}
{environment_info}
{agent_name} description: {description}
{agent_name} goal: {goal}
{nogo_statement}
Consider the current situation and provide {agent_name} with an achievable subgoal that aligns
with their character and represents a significant NEXT STEP toward completing their main goal.
Additionally, detail the specific action they should take to achieve this subgoal.

Respond with JSON: {{"new_subgoal": "<subgoal text>", "planned_action": "<action text>"}}"""

    raw = llm_judge_call(system_prompt, user_prompt, generation_vars)
    if raw is None:
        # Offline fallback: generate a simple subgoal
        return f"Work toward: {goal}", "Continue the conversation naturally."

    output = validate_json(raw, json_schema_new_subgoal)
    if output is None:
        logger.warning(f"Failed to parse new_subgoal response: {raw[:200]}")
        return f"Work toward: {goal}", "Continue the conversation naturally."

    new_subgoal = output.get('new_subgoal', '')
    planned_action = output.get('planned_action', '')
    logger.info(f"New subgoal for {agent_name}: '{new_subgoal}' / action: '{planned_action}'")
    return new_subgoal, planned_action


# ---------------------------------------------------------------------------
# Agent response generation
# ---------------------------------------------------------------------------

def get_agent_response(prompt, agent_name, generation_vars, last_narration=''):
    """Generate a response from the agent using the configured LLM.

    Returns (response_text, narration).
    """

    try:
        # Offline mode: simulated response
        if generation_vars.get('offline', False):
            sim_response = (
                f"This is a simulated response from {agent_name}. "
                f"In production, this would be generated by the AI model."
            )
            return sim_response, ""

        provider = generation_vars.get('provider', 'local')
        model = generation_vars.get('model')
        temperature = generation_vars.get('temperature', 0.7)
        max_tokens = generation_vars.get('max_tokens', 150)
        top_p = generation_vars.get('top_p', 0.9)
        fallback_to_local = generation_vars.get('fallback_to_local', True)

        llm_service.set_provider(provider)

        options = {
            'model': model,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'top_p': top_p,
            'fallback_to_local': fallback_to_local,
            'offline_allowed': True
        }

        # For providers that support chat format, convert the prompt
        if provider in ('openai', 'anthropic') and isinstance(prompt, str):
            sections = prompt.split("\n\nConversation:\n")
            if len(sections) == 2:
                system_prompt_text = sections[0]
                conversation = sections[1]

                messages = [{"role": "system", "content": system_prompt_text}]
                for line in conversation.split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        speaker, content = parts[0].strip(), parts[1].strip()
                        role = "user" if speaker not in (agent_name,) else "assistant"
                        messages.append({"role": role, "content": content})

                prompt = messages

        logger.info(f"Generating response using {provider} provider")
        raw = llm_service.complete(prompt, options)
        raw = raw.strip()

        # Try to parse as structured JSON response
        output = validate_json(raw, json_schema_response)
        if output:
            agent_response = output.get('agent_response', raw)
            narration = output.get('narration', '')

            # Suppress narration if too similar to previous
            if narration and is_too_similar(narration, last_narration):
                narration = ''

            return agent_response, narration

        # Fallback: treat entire response as plain text
        return raw, ""

    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        return f"I apologize, but I encountered an error: {str(e)}", ""


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def offline_main(history, agents_df, settings, user_name, is_user, agent_mutes, len_last_history):
    """Main function for offline mode (without real LLM)."""
    return main(history, agents_df, settings, user_name, is_user, agent_mutes, len_last_history, offline=True)


def main(history, agents_df, settings, user_name, is_user, agent_mutes, len_last_history, offline=False):
    """Main function for agent processing.

    Implements the full loop:
    1. Pick an unmuted agent
    2. If no current subgoal, generate one via LLM
    3. Generate agent response (with subgoal context)
    4. Review subgoal progress via LLM judge
    5. Go/NoGo decision updates the graph
    """

    logger.info(f"Agent processing started with {len(agents_df)} agents, is_user={is_user}")

    if is_user:
        logger.info("User turn, not generating agent responses")
        return history, agents_df, []

    if len(history) == len_last_history:
        logger.info("History unchanged, not generating new responses")
        return history, agents_df, []

    logs = []

    # Pick an unmuted agent
    unmuted_agents = [i for i, muted in enumerate(agent_mutes) if not muted]
    if not unmuted_agents:
        logger.warning("All agents are muted, no responses generated")
        return history, agents_df, ["All agents are muted"]

    agent_idx = random.choice(unmuted_agents)
    agent = agents_df.iloc[agent_idx]

    # Build generation vars
    generation_vars = (
        agent['generation_variables'].copy()
        if agent['is_agent_generation_variables']
        else settings.copy()
    )
    if offline:
        generation_vars['offline'] = True

    # Load the agent's graph
    graph_path = agent['graph_file_path']
    try:
        G = nx.read_graphml(graph_path)
    except Exception as e:
        logger.error(f"Error reading graph, creating new one: {e}")
        G = nx.DiGraph()
        G.add_node('start')

    agent_name = agent['agent_name']
    current_aim = agent['current_aim']
    suggestion = agent['suggestion']
    persistence_count = agent['persistance_count']
    persistence_score = agent['persistance_score']
    current_node = agent['current_node_location']
    patience_min = agent.get('persistance', 3)      # min turns before NoGo
    patience_max = agent.get('patience', 6)          # max turns (impatience)
    last_narration = agent.get('last_narration', '')

    # ------------------------------------------------------------------
    # Step 1: If no active subgoal, try graph-guided path first, then LLM
    # ------------------------------------------------------------------
    guided_path = None  # Will hold the path if graph search finds one

    if current_aim is None:
        # First: check if the graph already has a node close to our goal
        # and a viable path to it
        goal_text = agent['goal']
        path_result = find_path_to_goal(G, current_node, goal_text)

        if path_result is not None:
            path, target_node, similarity = path_result
            # The next node on the path becomes our subgoal
            next_step = path[1]  # path[0] is current_node
            current_aim = next_step
            suggestion = (
                f"Follow known path toward '{target_node}' "
                f"(similarity={similarity:.2f}). "
                f"Path: {' -> '.join(path)}"
            )
            guided_path = path
            persistence_count = 0
            persistence_score = None
            logs.append(
                f"Graph-guided subgoal for {agent_name}: '{current_aim}' "
                f"(path to '{target_node}', similarity={similarity:.2f})"
            )
        else:
            # No useful path found – ask the LLM to generate a new subgoal
            new_subgoal, planned_action = generate_new_subgoal(
                history, agent, generation_vars, G
            )
            current_aim = new_subgoal
            suggestion = planned_action
            persistence_count = 0
            persistence_score = None
            logs.append(f"New subgoal for {agent_name}: {current_aim}")

    # ------------------------------------------------------------------
    # Step 2: Generate agent response with subgoal context
    # ------------------------------------------------------------------
    prompt = format_prompt(
        history,
        agent['description'],
        agent['goal'],
        agent_name,
        user_name,
        current_aim=current_aim,
        suggestion=suggestion,
        last_narration=last_narration
    )

    logger.info(f"Generating response for {agent_name}")
    response_text, narration = get_agent_response(
        prompt, agent_name, generation_vars, last_narration
    )
    logs.append(f"Generated response for {agent_name}")

    # Combine response with narration for display
    display_response = response_text
    if narration:
        display_response = f"{response_text}\n\n{narration}"

    # Increment persistence count
    persistence_count += 1

    # ------------------------------------------------------------------
    # Step 3: Review subgoal progress (only after enough history)
    # ------------------------------------------------------------------
    if len(history) > 2 and current_aim:
        rating, justification, new_suggestion = review_subgoal(
            history + [(agent_name, response_text)],
            agent, generation_vars, G
        )

        if rating is not None:
            previous_score = persistence_score if persistence_score is not None else 4
            persistence_score = rating

            if new_suggestion:
                suggestion = new_suggestion

            # GO: rating >= 6 means subgoal achieved
            if rating >= 6:
                logger.info(f"GO: {agent_name} achieved subgoal '{current_aim}' (rating={rating})")
                new_node = current_aim
                G = update_graph(G, current_node, new_node, "Go", persistence_count)
                current_node = new_node
                current_aim = None
                suggestion = ''
                persistence_count = 0
                logs.append(f"GO: subgoal achieved -> {new_node}")

            # NOGO checks (only after minimum persistence)
            elif persistence_count >= patience_min:
                nogo = False

                # Strong failure
                if rating <= 2:
                    nogo = True
                    logs.append(f"NOGO: strong failure (rating={rating})")

                # Regression
                elif (rating < (previous_score - 1)) and rating <= 4:
                    nogo = True
                    logs.append(f"NOGO: regression (rating={rating}, prev={previous_score})")

                # Exceeded patience
                elif persistence_count > patience_max:
                    nogo = True
                    logs.append(f"NOGO: exceeded patience ({persistence_count} > {patience_max})")

                if nogo:
                    logger.info(f"NOGO: {agent_name} abandoning subgoal '{current_aim}'")
                    nogo_node = f"{current_aim}_NoGo"
                    G = update_graph(G, current_node, nogo_node, "NoGo", persistence_count)
                    current_aim = None
                    suggestion = ''
                    persistence_count = 0

    # ------------------------------------------------------------------
    # Step 4: Save updated state back to the DataFrame
    # ------------------------------------------------------------------
    # Save graph
    nx.write_graphml(G, graph_path)

    agent_df = pd.DataFrame(agents_df)
    agent_df.at[agent_idx, 'current_aim'] = current_aim
    agent_df.at[agent_idx, 'suggestion'] = suggestion
    agent_df.at[agent_idx, 'persistance_count'] = persistence_count
    agent_df.at[agent_idx, 'persistance_score'] = persistence_score
    agent_df.at[agent_idx, 'current_node_location'] = current_node
    agent_df.at[agent_idx, 'last_response'] = response_text
    agent_df.at[agent_idx, 'last_narration'] = narration
    agent_df.at[agent_idx, 'personal_history'] = history + [(agent_name, display_response)]

    # Add the response to the conversation history
    new_history = history + [(agent_name, display_response)]

    logger.info(
        f"Agent processing completed. "
        f"Subgoal: {current_aim}, Node: {current_node}, "
        f"Persistence: {persistence_count}, Score: {persistence_score}"
    )

    return new_history, agent_df, logs
