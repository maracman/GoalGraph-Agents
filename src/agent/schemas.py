"""
JSON schema definitions for validating agent and session data.
"""

# Schema for the LLM judge that reviews subgoal progress
json_schema_review_goal = {
    "type": "object",
    "properties": {
        "rating": {"type": "integer", "minimum": 1, "maximum": 7},
        "justification": {"type": "string"},
        "suggestion": {"type": "string"}
    },
    "required": ["rating", "justification", "suggestion"]
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
        "narration": {"type": "string"}
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
                    "llm": {"type": ["object", "null"]}
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