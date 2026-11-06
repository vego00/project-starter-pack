"""Runs one journey step in its own process, so tests can prove state outlives a process.

Usage: journey_driver.py DATABASE_URL JOURNEY_ID start|resume JSON_PAYLOAD
"""

import json
import sys
from uuid import UUID

from app.journey.graph import build_graph, journey_config, journey_input
from app.journey.nodes import resume_command
from app.journey.persistence import open_checkpointer
from app.journey.state import ProjectSpec
from app.registry.loader import load_registry


def main(database_url: str, journey_id: str, command: str, payload: str) -> None:
    journey = UUID(journey_id)
    config = journey_config(journey)
    with open_checkpointer(database_url) as saver:
        graph = build_graph(load_registry(), checkpointer=saver)
        data = json.loads(payload)
        graph_input = (
            journey_input(journey, ProjectSpec(**data))
            if command == "start"
            else resume_command(data)
        )
        result = graph.invoke(graph_input, config)
        values = graph.get_state(config).values
    interrupts = result.get("__interrupt__")
    prompt = interrupts[0].value if interrupts else None
    print(
        json.dumps(
            {
                "card_id": prompt["card"]["card_id"] if prompt and "card" in prompt else None,
                "decisions": sorted(values.get("decisions", {})),
                "status": values.get("status"),
            }
        )
    )


if __name__ == "__main__":
    main(*sys.argv[1:5])
