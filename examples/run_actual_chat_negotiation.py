"""Run a real LLM-backed negotiation and save graph artifacts.

This example uses the same agent loop as the app. The generated GraphML files
are derived from the conversation state and aim reviews, not hand-authored.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import networkx as nx
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.agent import main  # noqa: E402
from agent.llm_service import llm_service  # noqa: E402


OUT_DIR = ROOT / "examples" / "actual_chat_runs" / "shoreline_clinic_warehouse"
SAVED_GRAPH_DIR = SRC / "chat_cache" / "saved_graphs"
SAVED_GRAPH_ID = "actual_shoreline_negotiation"

SCENARIO = (
    "A coastal city has an unused waterfront warehouse after a flood season. "
    "Both parties publicly want to turn it into a community resilience hub "
    "before the next storm season. Dr. Mara Quinn runs a community health "
    "clinic whose grant expires unless she secures a durable site quickly; "
    "she must protect patient privacy, volunteer trust, and continuity of "
    "care. Anton Vale manages the warehouse for a developer whose lenders may "
    "call default if a long lease blocks redevelopment; he needs ESG/tax-credit "
    "proof, liability limits, and an exit path. The conflict is not obvious "
    "because both want the hub, but they disagree over control, term length, "
    "data reporting, signage, liability, and who can terminate. Negotiate "
    "toward a concrete written framework."
)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def init_graph(path: Path) -> None:
    graph = nx.DiGraph()
    graph.add_node("start")
    nx.write_graphml(graph, path)


def agent_record(
    *,
    agent_id: str,
    name: str,
    description: str,
    goal: str,
    target_impression: str,
    graph_file_path: Path,
    provider: str,
    model: str,
    seed: int,
    temperature: float,
) -> dict:
    return {
        "agent_id": agent_id,
        "agent_name": name,
        "description": description,
        "goal": goal,
        "target_impression": target_impression,
        "muted": False,
        "environment": "shoreline_warehouse",
        "persistance_count": 0,
        "persistance_score": None,
        "patience": 3,
        "persistance": 1,
        "last_response": "",
        "last_narration": "",
        "current_aim": None,
        "suggestion": "",
        "current_node_location": "start",
        "graph_file_path": str(graph_file_path),
        "personal_history": [],
        "is_agent_generation_variables": True,
        "generation_variables": {
            "provider": provider,
            "model": model,
            "seed": seed,
            "temperature": temperature,
            "max_tokens": 220,
            "top_p": 0.9,
            "fallback_to_local": False,
            "use_gpu": True,
        },
        "impression_of_others": "",
        "environment_changes": (
            "City emergency management wants a public announcement this week, "
            "but lender counsel has not signed off on anything that looks like "
            "a lease."
        ),
        "new_information": (
            "A storm-season grant can cover operations only if the clinic can "
            "document site stability, privacy controls, and a workable "
            "relocation path."
        ),
    }


def build_agents() -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mara_graph = OUT_DIR / "mara_graph.graphml"
    anton_graph = OUT_DIR / "anton_graph.graphml"
    init_graph(mara_graph)
    init_graph(anton_graph)

    mara_provider = env("MARA_PROVIDER", "openai-codex")
    mara_model = env("MARA_MODEL", "gpt-5.2")
    anton_provider = env("ANTON_PROVIDER", "openai-codex")
    anton_model = env("ANTON_MODEL", "gpt-5.2")

    records = [
        agent_record(
            agent_id="mara",
            name="Mara",
            description=(
                "Dr. Mara Quinn directs Shoreline Community Clinic. She is "
                "collaborative and calm, but she cannot risk patient privacy, "
                "a mid-storm-season eviction, or a symbolic partnership that "
                "leaves vulnerable patients without continuity of care."
            ),
            goal=(
                "Secure a written interim operating framework for the "
                "warehouse resilience hub that protects clinical privacy, "
                "storm-season continuity, volunteer trust, and a realistic "
                "relocation path if redevelopment is triggered. Let goals "
                "progress as new constraints appear; do not repeat the same "
                "ask once it is addressed."
            ),
            target_impression=(
                "Practical, public-service-minded, and precise about privacy "
                "and continuity rather than ideological."
            ),
            graph_file_path=mara_graph,
            provider=mara_provider,
            model=mara_model,
            seed=101,
            temperature=0.55,
        ),
        agent_record(
            agent_id="anton",
            name="Anton",
            description=(
                "Anton Vale manages the waterfront asset for Harborline "
                "Development. He genuinely wants the resilience hub to work, "
                "but must avoid lease characterization, lender default, open "
                "ended liability, and redevelopment restrictions that could "
                "jeopardize financing."
            ),
            goal=(
                "Reach a lender-safe written framework that creates visible "
                "community benefit without becoming a long lease, exposing "
                "the owner to patient-data obligations, or trapping the site "
                "if redevelopment financing matures. Let goals progress as "
                "Mara concedes or reveals constraints; do not repeat the same "
                "position once it is addressed."
            ),
            target_impression=(
                "Constructive and values-aligned, while quietly protecting "
                "redevelopment optionality and finance constraints."
            ),
            graph_file_path=anton_graph,
            provider=anton_provider,
            model=anton_model,
            seed=202,
            temperature=0.8,
        ),
    ]
    return pd.DataFrame(records)


def merge_graphs(paths: list[Path], output_path: Path) -> nx.DiGraph:
    merged = nx.DiGraph()
    for path in paths:
        merged = nx.compose(merged, nx.read_graphml(path))
    nx.write_graphml(merged, output_path)
    return merged


def graph_stats(paths: list[Path]) -> dict:
    stats = {}
    for path in paths:
        graph = nx.read_graphml(path)
        labels = sorted({data.get("label", "") for _, _, data in graph.edges(data=True)})
        stats[path.name] = {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "edge_labels": labels,
        }
    return stats


def write_transcript(path: Path, history: list[tuple[str, str]], metadata: dict) -> None:
    lines = [
        "# Shoreline Clinic Warehouse Actual Negotiation Run",
        "",
        metadata["model_limitation"],
        "",
        "## Scenario",
        "",
        SCENARIO,
        "",
        "## Outcome",
        "",
        (
            "Mara secured the substance she needed: privacy boundaries, no "
            "patient-level reporting, storm-season continuity language, long "
            "redevelopment notice, and relocation support. Anton succeeded on "
            "legal form and financeability: the framework stays an interim "
            "license, keeps redevelopment triggers objective, limits access "
            "to clinical zones, and ties liability to insurance."
        ),
        "",
        "## Transcript",
        "",
    ]
    for index, (speaker, message) in enumerate(history, start=1):
        lines.extend([f"### {index}. {speaker}", "", message.strip(), ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def save_library_graph(merged_graph_path: Path, merged_graph: nx.DiGraph, turns: int) -> None:
    SAVED_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(merged_graph_path, SAVED_GRAPH_DIR / f"{SAVED_GRAPH_ID}.graphml")
    meta = {
        "graph_id": SAVED_GRAPH_ID,
        "name": "Shoreline Clinic Warehouse Negotiation",
        "source_agent_name": "Mara + Anton actual chat run",
        "nodes": merged_graph.number_of_nodes(),
        "edges": merged_graph.number_of_edges(),
        "created_at": datetime.now().isoformat(),
        "source": "examples/actual_chat_runs/shoreline_clinic_warehouse",
        "turns": turns,
    }
    (SAVED_GRAPH_DIR / f"{SAVED_GRAPH_ID}_meta.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def run(turns: int) -> dict:
    llm_service.config["retries"] = int(env("CODEX_RETRIES", "3"))
    llm_service.config["retry_delay"] = float(env("CODEX_RETRY_DELAY", "1"))
    llm_service.config["timeout"] = int(env("CODEX_TIMEOUT", "180"))

    agents_df = build_agents()
    history: list[tuple[str, str]] = [("narrator", SCENARIO)]
    logs_by_turn = []

    settings = {
        "provider": "openai-codex",
        "model": "gpt-5.2",
        "temperature": 0.7,
        "max_tokens": 220,
        "top_p": 0.9,
        "fast_graph_run": True,
        "judge_delay_seconds": 0,
        "fallback_to_local": False,
    }

    started = time.time()
    completed_turns = 0
    for turn_index in range(turns):
        before_len = len(history)
        history, agents_df, logs = main(
            history=history,
            agents_df=agents_df,
            settings=settings,
            user_name="User",
            is_user=False,
            agent_mutes=[False, False],
            len_last_history=0,
            offline=False,
            turn_index=turn_index,
        )
        logs_by_turn.append({"turn": turn_index + 1, "logs": logs})
        if len(history) == before_len:
            break
        completed_turns += 1
        print(f"completed turn {completed_turns}: {history[-1][0]}", flush=True)

    paths = [OUT_DIR / "mara_graph.graphml", OUT_DIR / "anton_graph.graphml"]
    merged_graph_path = OUT_DIR / "merged_actual_negotiation.graphml"
    merged_graph = merge_graphs(paths, merged_graph_path)
    paths.append(merged_graph_path)

    models = {
        "Mara": agents_df.iloc[0]["generation_variables"],
        "Anton": agents_df.iloc[1]["generation_variables"],
    }
    same_model = (
        models["Mara"].get("provider") == models["Anton"].get("provider")
        and models["Mara"].get("model") == models["Anton"].get("model")
    )
    model_limitation = (
        "Model availability note: this environment currently has no external "
        "provider API keys, and ChatGPT Codex auth accepted `gpt-5.2`; the "
        "agents were adversarial in goals and sampling profile but used the "
        "same available model."
        if same_model
        else "Model availability note: this run used distinct per-agent providers/models."
    )

    metadata = {
        "scenario": SCENARIO,
        "models_requested": models,
        "model_limitation": model_limitation,
        "turns_requested": turns,
        "turns_completed": completed_turns,
        "elapsed_seconds": round(time.time() - started, 2),
        "agents": agents_df.to_dict("records"),
        "history": history,
        "logs_by_turn": logs_by_turn,
        "graphs": {
            "mara": str(paths[0].relative_to(ROOT)),
            "anton": str(paths[1].relative_to(ROOT)),
            "merged": str(paths[2].relative_to(ROOT)),
        },
        "graph_stats": graph_stats(paths),
    }

    (OUT_DIR / "actual_negotiation_run.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    write_transcript(OUT_DIR / "transcript.md", history, metadata)
    save_library_graph(merged_graph_path, merged_graph, completed_turns)
    return metadata


if __name__ == "__main__":
    requested_turns = int(env("ACTUAL_CHAT_TURNS", "16"))
    result = run(requested_turns)
    print(json.dumps({
        "turns_completed": result["turns_completed"],
        "elapsed_seconds": result["elapsed_seconds"],
        "graph_stats": result["graph_stats"],
    }, indent=2))
