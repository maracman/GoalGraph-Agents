"""
JSON schema definitions for validating agent and session data.
"""

# Schema for the LLM judge that reviews subgoal progress
json_schema_review_goal = {
    "type": "object",
    "properties": {
        "rating": {"type": "integer", "minimum": 1, "maximum": 7},
        "justification": {"type": "string"},
        "suggestion": {"type": "string"},
        "aim_status": {
            "type": "string",
            "enum": ["continue", "progress", "achieved", "abandon"]
        },
        "next_aim": {"type": ["string", "null"]}
    },
    "required": ["rating", "justification", "suggestion"]
}

# Schema for the route-or-invent fork, where the agent reads its own scratchpad
# and either takes a place the graph offers or names one that is not on it yet.
# `choice` is 0 for "none of these fit", so a reply that rejects every option is
# a decision rather than a parse failure.
json_schema_aim_choice = {
    "type": "object",
    "properties": {
        "choice": {"type": "integer", "minimum": 0},
        "new_aim": {"type": ["string", "null"]},
        "why": {"type": "string"}
    },
    "required": ["choice"]
}

# Schema for generating new subgoals
json_schema_new_subgoal = {
    "type": "object",
    "properties": {
        "new_subgoal": {"type": "string"},
        "planned_action": {"type": "string"}
    },
    "required": ["new_subgoal", "planned_action"]
}

# Schema for agent responses with optional narration
json_schema_response = {
    "type": "object",
    "properties": {
        "agent_response": {"type": "string"},
        "narration": {"type": "string"},
        # On keeper runs the agent states its current claim in a checkable
        # form, so refutation becomes a fact rather than a judgement.
        "rule": {"type": "string"},
        # With aim_scratchpad on, the agent keeps a running note of where the
        # investigation stands. It is read back at the route-or-invent fork,
        # where it decides which place on the graph to go to next, or that none
        # of them fit and the aim has to be a new one.
        "notes": {"type": "string"}
    },
    "required": ["agent_response"]
}

json_schemas = {
    "agent": {
        "type": "object",
        "required": ["agent_id", "agent_name", "description", "goal"],
        "properties": {
            "agent_id": {"type": "string"},
            "agent_name": {"type": "string"},
            "description": {"type": "string"},
            "goal": {"type": "string"},
            "target_impression": {"type": "string"},
            "muted": {"type": "boolean"},
            "environment": {"type": "string"},
            "graph_file_path": {"type": "string"},
            "persistance_count": {"type": "integer"},
            "persistance_score": {"type": ["number", "null"]},
            "patience": {"type": "integer"},
            "persistance": {"type": "integer"},
            "last_response": {"type": "string"},
            "last_narration": {"type": "string"},
            "current_aim": {"type": ["string", "null"]},
            "suggestion": {"type": "string"},
            "current_node_location": {"type": "string"},
            "personal_history": {
                "type": "array",
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": [
                        {"type": "string"},
                        {"type": "string"}
                    ]
                }
            },
            "is_agent_generation_variables": {"type": "boolean"},
            "generation_variables": {
                "type": "object",
                "properties": {
                    "seed": {"type": "integer"},
                    "temperature": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                    "top_p": {"type": "number"},
                    "use_gpu": {"type": "boolean"},
                    "llm": {"type": ["object", "null"]}
                }
            },
            "impression_of_others": {"type": "string"},
            "environment_changes": {"type": "string"},
            "new_information": {"type": "string"}
        }
    },
    
    "session": {
        "type": "object",
        "required": ["session_id", "user_name", "agents_df", "session_history", "settings"],
        "properties": {
            "session_id": {"type": "string"},
            "user_name": {"type": "string"},
            "agent_mutes": {
                "type": "array",
                "items": {"type": "boolean"}
            },
            "agents_df": {
                "type": "array",
                "items": {"$ref": "#/agent"}
            },
            "session_history": {
                "type": "array",
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": [
                        {"type": "string"},
                        {"type": "string"}
                    ]
                }
            },
            "len_last_history": {"type": "integer"},
            "settings": {
                "type": "object",
                "properties": {
                    "temperature": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                    "top_p": {"type": "number"},
                    "seed": {"type": "integer"},
                    "top_k": {"type": "integer"},
                    "repetition_penalty": {"type": "number"},
                    "use_gpu": {"type": "boolean"},
                    "llm": {"type": ["object", "null"]},
                    # How the decision graph feeds back into aim generation.
                    # "description" is the original behaviour: every ruled-out
                    # aim label, dumped whole. "graph" retrieves only the
                    # nearest few and includes why each was ruled out.
                    "graph_memory_mode": {
                        "type": "string",
                        "enum": ["none", "inline", "description", "graph"]
                    },
                    "graph_recall_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    "graph_recall_chars": {"type": "integer", "minimum": 100, "maximum": 4000},
                    # A keeper turns the counterparty into code, so the
                    # agent's claims can be checked rather than judged.
                    "run_type": {
                        "type": "string",
                        "enum": ["chat", "rule_induction", "word_induction", "sentence_induction",
                                 "transformation", "constraints", "troubleshoot",
                                 "diagnosis", "clinic", "ddx_clinic",
                                 "hidden_norm"]
                    },
                    "keeper_rule": {"type": "string"},
                    # Most recent messages an agent may see. 0 means all of
                    # them. A short window is what makes stored aims worth more
                    # than raw history.
                    "context_window": {"type": "integer", "minimum": 0, "maximum": 200},
                    # Whether a refuted aim can be abandoned before it has been
                    # held for patience_min turns.
                    "nogo_ungated": {"type": "boolean"},
                    # Whether a candidate Go must survive an independent
                    # attempt to refute it.
                    "go_corroborate": {"type": "boolean"},
                    # Who arbitrates the route-or-invent fork.
                    #   gate       similarity * trust >= route_min_score
                    #   judgement  the agent picks from the same candidates,
                    #              with only the conversation to go on
                    #   scratchpad as judgement, plus its own running note
                    # judgement exists to separate "let the agent decide" from
                    # "let the agent decide with a persistent note": without
                    # it, any difference could be the extra reasoning step
                    # rather than the memory, and the study would need running
                    # again to find out which.
                    "aim_fork_mode": {
                        "type": "string",
                        "enum": ["gate", "judgement", "scratchpad"]
                    },
                    # Whether the aim scaffold runs at all. 'off' is the
                    # ablation of the original design: no aim, no judge, no
                    # graph writes - a plain conversing agent.
                    "aim_system": {"type": "string", "enum": ["on", "off"]},
                    # A named variation of the task's rules, interpreted by
                    # the task's own rule module (e.g. ddx 'stateful_patient':
                    # the patient keeps full history and never repeats an
                    # answer). Empty = the task as shipped.
                    "task_variant": {"type": "string"},
                    # Pins this run's candidate ordering so paired arms face an
                    # identical list. Unset, the order is salted per session and
                    # varies run to run.
                    "order_salt": {"type": "string"}
                }
            },
            "play": {"type": "boolean"},
            "is_user": {"type": "boolean"},
            "max_generations": {"type": "integer"},
            "current_generation": {"type": "integer"},
            "user_message": {"type": "string"},
            "number_of_agents": {"type": "integer"}
        }
    }
}
