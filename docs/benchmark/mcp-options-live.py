"""The live check of 72ebcd9 (docs/benchmark/mcp-options-0.2.4.md): `run_task`
over MCP, in process, with the `mcp` package's client, then `run_events` and
`run_status` until the run ends.

    python mcp-options-live.py PROJECTS_DIR PROJECT MINUTES TASK_FILE

TASK_FILE must be inside PROJECTS_DIR. The model and key come from the
settings, as for any run (CERTO_LLM_MODEL, CERTO_LLM_API_KEY).
"""

import json
import sys

import anyio
from mcp import Client

from certo.config import load_config
from certo.mcp_server import Folders, build_server
from certo.runs import RunManager


async def main(projects: str, project: str, minutes: int, task_file: str) -> None:
    server = build_server(RunManager(load=load_config), Folders(projects, []), load=load_config)
    async with Client(server) as client:
        reply = await client.call_tool(
            "run_task",
            {
                "task_file": task_file,
                "project": project,
                "make_milestones": True,
                "max_minutes": minutes,
                "require_verification": True,
            },
        )
        started = reply.structured_content or json.loads(reply.content[0].text)
        run_id, seen = started["run_id"], 0
        while True:
            events = (
                await client.call_tool("run_events", {"run_id": run_id, "since": seen})
            ).structured_content
            for event in events["events"]:
                if event["kind"] == "notice":
                    print("notice:", event["text"])
            seen = events["next"]
            if events["state"] != "running":
                break
            await anyio.sleep(3)
        status = (await client.call_tool("run_status", {"run_id": run_id})).structured_content
        result = status["result"] or {}
        print("state:", status["state"], "verdict:", status["verdict"], "passed:", status["passed"])
        for m in result.get("milestones") or []:
            print("milestone:", m["number"], m["title"], m["verdict"])
        usage = result.get("usage") or {}
        print("seconds:", usage.get("duration_seconds"), "cost:", usage.get("cost"))


if __name__ == "__main__":
    anyio.run(main, sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])
