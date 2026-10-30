import json
from pathlib import Path

import yaml

from projectsync.dify_client import parse_json_answer

ROOT = Path(__file__).resolve().parents[1]


def test_parse_json_answer_with_code_fence():
    parsed = parse_json_answer('```json\n{"intent":"query","reply":"ok"}\n```')
    assert parsed == {"intent": "query", "reply": "ok"}


def test_dify_dsl_yaml_and_graph_shape():
    data = yaml.safe_load((ROOT / "dify" / "projectsync_chatflow.yml").read_text(encoding="utf-8"))
    assert data["kind"] == "app"
    assert data["app"]["mode"] == "advanced-chat"
    graph = data["workflow"]["graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    assert {"start", "llm", "answer"}.issubset(node_ids)
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in graph["edges"])
    assert data["workflow"]["graph"]["nodes"][-1]["data"]["answer"] == "{{#llm.text#}}"
