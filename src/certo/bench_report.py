"""Turn a benchmark results folder into `results.md`, `results.csv` and
`cost.json`.

Works from the folder alone (`meta.json` plus `runs/*.json`), so an
interrupted or resumed benchmark can always be reported. Pure: no SDK, no
model.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .model_pricing import is_local_model_id
from .run_summary import effort_label

CSV_FIELDS = (
    "run_id",
    "arm",
    "strategy",
    "models",
    "model_ids",
    "reasoning_efforts",
    "task",
    "repeat",
    "verdict",
    "agent_claimed_done",
    "hidden_status",
    "hidden_passed",
    "fooled",
    "caught",
    "unconfirmed_pass",
    "wall_seconds",
    "tokens_in",
    "tokens_out",
    "tokens_cached",
    "cost",
    "cost_known",
    "retries_used",
    "tool_call_reminders",
    "final_rung",
    "independent_status",
    "error",
)


def _rate(count: int, total: int) -> str:
    return f"{count}/{total} ({count / total:.0%})" if total else "0/0"


# The effort of a model in results written before Certo recorded it.
_NOT_RECORDED = "not recorded"


def _seconds(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{round(seconds)}s"


def _known(record: dict[str, Any]) -> bool:
    """Whether a run's cost is complete. A run on local models only is free:
    older records counted it as unknown."""
    models = record.get("models") or []
    return record["cost_known"] or (
        bool(models) and all(is_local_model_id(m.get("model", "")) for m in models)
    )


def _rung_known(rung: dict[str, Any]) -> bool:
    return rung.get("cost_known", True) or is_local_model_id(rung.get("model", ""))


def _cost(records: list[dict[str, Any]]) -> str:
    total = sum(r["cost"] for r in records)
    if all(_known(r) for r in records):
        return f"${total:.4f}"
    return f"${total:.4f} + unknown"


def cost_summary(meta: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """The benchmark's real, recorded cost: in total, per model, and next to
    the plan's estimate (kept in meta.json when the benchmark started).
    Escalation runs are split by rung, so each model gets what it spent."""
    per_model: dict[tuple[str, str, str | None], dict[str, Any]] = {}

    def add(name: str, model: str, effort: str | None, cost: float, known: bool) -> None:
        row = per_model.setdefault(
            (name, model, effort),
            {
                "name": name,
                "model": model,
                "reasoning_effort": effort,
                "runs": 0,
                "cost": 0.0,
                "complete": True,
            },
        )
        row["runs"] += 1
        row["cost"] += cost
        row["complete"] = row["complete"] and known

    for r in records:
        if r.get("rungs"):
            for rung in r["rungs"]:
                add(
                    rung.get("name", ""),
                    rung.get("model", ""),
                    rung.get("reasoning_effort", _NOT_RECORDED),
                    rung.get("cost", 0.0),
                    _rung_known(rung),
                )
        elif len(r.get("models", [])) == 1:
            m = r["models"][0]
            add(
                m["name"],
                m["model"],
                m.get("reasoning_effort", _NOT_RECORDED),
                r["cost"],
                _known(r),
            )
        elif r["cost"]:
            add("(not attributed)", "", None, r["cost"], _known(r))
    models = sorted(per_model.values(), key=lambda row: (-row["cost"], row["name"]))
    for row in models:
        row["cost"] = round(row["cost"], 6)
        row["average_per_run"] = round(row["cost"] / row["runs"], 6) if row["runs"] else 0.0
    config = meta["config"]
    return {
        "total": round(sum(r["cost"] for r in records), 6),
        "complete": all(_known(r) for r in records),
        "runs_recorded": len(records),
        "runs_planned": len(config["tasks"]) * len(config["arms"]) * config["repeats"],
        "per_model": models,
        "estimate": meta.get("estimate"),
    }


def _money(value: float, complete: bool = True) -> str:
    return f"${value:.4f}" + ("" if complete else " + unknown")


def cost_line(summary: dict[str, Any]) -> str:
    """One line: the real total, and what the plan estimated."""
    line = f"Total cost: {_money(summary['total'], summary['complete'])}"
    estimate = summary.get("estimate")
    if estimate:
        line += f" (the plan estimated at most ~${estimate['at_most']:.2f}"
        if estimate.get("likely") is not None:
            line += f", likely ~${estimate['likely']:.2f}"
        line += ")"
    if summary["runs_recorded"] != summary["runs_planned"]:
        line += f", for {summary['runs_recorded']} of {summary['runs_planned']} runs"
    return line


def _cost_per_solved(records: list[dict[str, Any]]) -> str:
    """Total cost divided by the runs whose hidden tests passed."""
    solved = sum(r["hidden_tests"]["passed"] for r in records)
    if not solved:
        return "-"
    per = sum(r["cost"] for r in records) / solved
    return f"${per:.4f}" + ("" if all(_known(r) for r in records) else " + unknown")


def rung_shares(records: list[dict[str, Any]]) -> str:
    """For an escalate arm: how often each rung gave the final result, for
    example "rung 1 (qwen-local): 4/9, rung 2 (gpt-luna): 5/9"."""
    counts: dict[tuple[int, str], int] = {}
    no_result = 0
    for r in records:
        final = next((g for g in r.get("rungs", []) if g.get("final")), None)
        if final is None:
            no_result += 1
            continue
        key = (final["rung"], final["name"])
        counts[key] = counts.get(key, 0) + 1
    total = len(records)
    parts = [f"rung {n} ({name}): {c}/{total}" for (n, name), c in sorted(counts.items())]
    if no_result:
        parts.append(f"no result (error): {no_result}/{total}")
    return ", ".join(parts) or "-"


def _arm_models(meta: dict[str, Any], arm: dict[str, Any], records: list[dict[str, Any]]) -> str:
    """The models an arm uses. A derived escalate arm shows its ladder (kept
    in meta.json by newer versions), not every active model; an older folder
    without it shows the models its runs really used."""
    models = meta["config"]["models"]

    def named(names: list[str]) -> str:
        return ", ".join(f"{n} (`{models.get(n, '?')}`)" for n in names)

    if arm["strategy"] == "auto":
        started: dict[str, int] = {}
        for r in records:
            if r.get("models"):
                first = r["models"][0]["name"]
                started[first] = started.get(first, 0) + 1
        picks = ", ".join(f"{n} {c}×" for n, c in started.items()) or "none yet"
        return f"auto from {named(meta['config']['arm_models'][arm['name']])}; started on: {picks}"
    derived = arm["strategy"] == "escalate" and arm.get("models") is None
    if not derived:
        return named(meta["config"]["arm_models"][arm["name"]])
    ladder = meta.get("ladders", {}).get(arm["name"])
    if ladder:
        return "derived ladder: " + named(ladder)
    used: list[str] = []
    for r in records:
        for rung in r.get("rungs", []):
            if rung.get("name") and rung["name"] not in used:
                used.append(rung["name"])
    return "derived ladder; used: " + (named(used) if used else "none yet")


def _independent_failed(record: dict[str, Any]) -> bool:
    return (record.get("independent_tests") or {}).get("status") == "failed"


def _independent_columns(mine: list[dict[str, Any]]) -> dict[str, str]:
    """For a benchmark with an independent_tests arm: how often they failed,
    on runs the hidden tests passed (a wrong test, or a bug the hidden tests
    miss) and on runs that fooled Certo."""
    if not any(r.get("independent_tests") for r in mine):
        return {"Independent tests failed": "-", "...hidden passed": "-", "...fooled": "-"}
    passed = [r for r in mine if r["hidden_tests"]["passed"]]
    fooled = [r for r in mine if r["fooled"]]
    return {
        "Independent tests failed": _rate(sum(map(_independent_failed, mine)), len(mine)),
        "...hidden passed": f"{sum(map(_independent_failed, passed))} of {len(passed)}",
        "...fooled": f"{sum(map(_independent_failed, fooled))} of {len(fooled)}",
    }


def arm_rows(meta: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    independent = any(a.get("independent_tests") for a in meta["config"]["arms"])
    for arm in meta["config"]["arms"]:
        mine = [r for r in records if r["arm"] == arm["name"]]
        rows.append(
            {
                "Arm": arm["name"],
                "Strategy": arm["strategy"],
                "Models": _arm_models(meta, arm, mine),
                "Hidden tests passed": _rate(
                    sum(r["hidden_tests"]["passed"] for r in mine), len(mine)
                ),
                "Verified": _rate(sum(r["verdict"] == "verified" for r in mine), len(mine)),
                "Fooled": str(sum(r["fooled"] for r in mine)),
                "Caught": str(sum(r["caught"] for r in mine)),
                "Unconfirmed passes": str(sum(r.get("unconfirmed_pass", False) for r in mine)),
                "Errors": str(sum(r["error"] is not None for r in mine)),
                "Median time": _seconds(statistics.median(r["wall_seconds"] for r in mine))
                if mine
                else "-",
                "Tokens in / out": f"{sum(r['tokens_in'] for r in mine):,} / "
                f"{sum(r['tokens_out'] for r in mine):,}",
                "Tool-call reminders": str(sum(r.get("tool_call_reminders", 0) for r in mine)),
                "Cost": _cost(mine) if mine else "-",
                "Cost per solved task": _cost_per_solved(mine),
                **(_independent_columns(mine) if independent else {}),
            }
        )
    return rows


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _hardware(hint: dict[str, Any]) -> str:
    parts = [hint.get("system", ""), hint.get("machine", ""), hint.get("cpu", "")]
    if hint.get("cpu_count"):
        parts.append(f"{hint['cpu_count']} CPUs")
    if hint.get("memory_gb"):
        parts.append(f"{hint['memory_gb']} GB RAM")
    if hint.get("gpu"):
        parts.append(f"GPU: {hint['gpu']}")
    return ", ".join(p for p in parts if p) or "unknown"


def _short_digest(digest: str) -> str:
    """The first 12 hex digits, as `ollama list` shows them."""
    return digest.removeprefix("sha256:")[:12]


def _model_servers(meta: dict[str, Any]) -> list[str]:
    """One line per Ollama model: its server and the context window."""
    windows = {
        a["name"]: a["context_tokens"] for a in meta["config"]["arms"] if a.get("context_tokens")
    }
    lines = []
    for name, info in meta.get("model_servers", {}).items():
        version = info.get("ollama_version")
        server = f"Ollama {version}" if version else "Ollama, version unknown"
        context = info.get("context_tokens")
        parts = [
            f"{server} at {info.get('server', 'unknown')}",
            f"server window {context:,} tokens" if context else "server window unknown",
        ]
        if info.get("model_digest"):
            parts.append(f"model digest {_short_digest(info['model_digest'])}")
        if info.get("context_tokens_set"):
            parts.append(f"models.yaml sets {info['context_tokens_set']:,}")
        arms = meta["config"].get("arm_models", {})
        parts += [
            f"arm {arm} asks for {tokens:,}"
            for arm, tokens in windows.items()
            if name in arms.get(arm, [])
        ]
        lines.append(f"  - {name} (`{info.get('model', '?')}`): " + ", ".join(parts))
    return ["- Model servers:", *lines] if lines else []


def _per_milestone_lines(config: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    """For tasks whose hidden tests are named by milestone: the hidden tests
    passed per milestone, added up over each arm's runs."""
    lines: list[str] = []
    arms = [a["name"] for a in config["arms"]]
    for task in config["tasks"]:
        mine = [r for r in records if r["task"] == task and r["hidden_tests"].get("by_milestone")]
        if not mine:
            continue
        numbers = sorted({int(n) for r in mine for n in r["hidden_tests"]["by_milestone"]})
        rows = []
        for arm in arms:
            runs = [r for r in mine if r["arm"] == arm]
            if not runs:
                continue
            cells = [arm]
            for n in numbers:
                counts = [r["hidden_tests"]["by_milestone"].get(str(n)) for r in runs]
                passed = sum(c[0] for c in counts if c)
                total = sum(c[1] for c in counts if c)
                cells.append(f"{passed}/{total}" if total else "-")
            rows.append(cells)
        lines += ["", f"## Hidden tests passed per milestone: {task}", ""]
        lines += [
            "Each cell adds up the arm's runs: hidden tests passed / hidden tests run.",
            "",
        ]
        lines += _table(["Arm", *[f"Milestone {n}" for n in numbers]], rows)
    return lines


def render_markdown(meta: dict[str, Any], records: list[dict[str, Any]]) -> str:
    config = meta["config"]
    planned = len(config["tasks"]) * len(config["arms"]) * config["repeats"]
    task_set = meta["task_set"]
    lines = [
        "# Certo benchmark results",
        "",
        f"- Date: {meta['date']}",
        f"- Certo: {meta['certo_version']}",
        f"- Task set: version {task_set['version']} (`{task_set['hash']}`, {task_set['source']})",
        f"- Hardware: {_hardware(meta.get('hardware', {}))}",
        *_model_servers(meta),
        f"- Tasks: {len(config['tasks'])} · arms: {len(config['arms'])} · repeats: "
        f"{config['repeats']} · runs recorded: {len(records)} of {planned}"
        + ("" if len(records) == planned else " (incomplete)"),
        "",
        (
            f"Small samples: {len(config['tasks']) * config['repeats']} runs per arm, so a "
            "difference of a few runs between arms can be chance."
        ),
        "",
        "## Arms",
        "",
    ]
    rows = arm_rows(meta, records)
    header = list(rows[0]) if rows else []
    lines += _table(header, [list(r.values()) for r in rows])

    arms = [a["name"] for a in config["arms"]]
    lines += ["", "## Hidden tests passed, per task", ""]
    task_rows = []
    for task in config["tasks"]:
        cells = [task]
        for arm in arms:
            mine = [r for r in records if r["arm"] == arm and r["task"] == task]
            passed = sum(r["hidden_tests"]["passed"] for r in mine)
            cells.append(f"{passed}/{len(mine)}" if mine else "-")
        task_rows.append(cells)
    lines += _table(["Task", *arms], task_rows)

    lines += _per_milestone_lines(config, records)

    escalate_arms = [a["name"] for a in config["arms"] if a["strategy"] == "escalate"]
    if escalate_arms:
        lines += ["", "## Which rung produced the final result", ""]
        for arm in escalate_arms:
            mine = [r for r in records if r["arm"] == arm]
            lines.append(f"- **{arm}:** {rung_shares(mine)}")

    summary = cost_summary(meta, records)
    lines += ["", "## Cost", "", cost_line(summary) + ".", ""]
    lines += _table(
        ["Model", "Model id", "Effort", "Runs", "Cost", "Average per run"],
        [
            [
                row["name"],
                f"`{row['model']}`" if row["model"] else "-",
                effort_label(row.get("reasoning_effort")) if row["model"] else "-",
                str(row["runs"]),
                _money(row["cost"], row["complete"]),
                _money(row["average_per_run"], row["complete"]),
            ]
            for row in summary["per_model"]
        ],
    )

    lines += [
        "",
        "## What the columns mean",
        "",
        (
            "- **Hidden tests passed:** the task's hidden tests, which the agent never saw, "
            "passed. This is the score."
        ),
        "- **Verified:** Certo's verdict was `verified`.",
        "- **Fooled:** Certo said `verified`, but the hidden tests failed.",
        (
            "- **Caught:** the agent finished and claimed it was done, but Certo did not say "
            "`verified`."
        ),
        (
            "- **Unconfirmed passes:** Certo did not say `verified`, but the hidden tests passed "
            "(for example, nothing to check, or a check Certo couldn't run)."
        ),
        "- **Errors:** the run stopped with an error (for example, the provider failed).",
        "- **Median time:** wall time of one run, including Certo's checks and retries.",
        (
            "- **Tool-call reminders:** how many times the agent wrote a tool call as text "
            "instead of making it, and Certo sent it back (`CERTO_TOOL_CALL_REMINDERS`), "
            "added up over the arm's runs. An escalation run counts every rung's own."
        ),
        "- **Cost:** from LiteLLM's prices; `+ unknown` when a model has no price.",
        (
            "- **Effort:** the reasoning effort the model ran at; `default` when none was "
            f"set, `{_NOT_RECORDED}` in results from before Certo 0.1.22."
        ),
        (
            "- **Cost per model:** what each model spent; an escalation run is split by "
            "rung. A run counts once per model it used."
        ),
        (
            "- **Cost per solved task:** the arm's total cost divided by the runs whose hidden "
            "tests passed."
        ),
        (
            "- **Which rung produced the final result** (escalate arms): the rung whose "
            "verdict ended the run, counted over the arm's runs."
        ),
        (
            "- **Independent tests failed** (arms with `independent_tests: true`): runs where "
            "most sets of independent tests failed. Report only: the verdict doesn't change. "
            "**...hidden passed:** of the runs whose hidden tests passed (a wrong independent "
            "test, or a bug the hidden tests miss). **...fooled:** of the runs that fooled "
            "Certo (caught)."
        ),
        "",
    ]
    return "\n".join(lines)


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    **{k: r.get(k) for k in CSV_FIELDS if k in r},
                    "models": ";".join(m["name"] for m in r["models"]),
                    "model_ids": ";".join(m["model"] for m in r["models"]),
                    "reasoning_efforts": ";".join(
                        effort_label(m.get("reasoning_effort", _NOT_RECORDED)) for m in r["models"]
                    ),
                    "hidden_status": r["hidden_tests"]["status"],
                    "hidden_passed": r["hidden_tests"]["passed"],
                    "unconfirmed_pass": r.get("unconfirmed_pass", False),
                    "independent_status": (r.get("independent_tests") or {}).get("status"),
                }
            )


def write_report(out_dir: Path) -> Path:
    """Write results.md and results.csv; return the path of results.md."""
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    records = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((out_dir / "runs").glob("*.json"))
    ]
    order = {name: i for i, name in enumerate(a["name"] for a in meta["config"]["arms"])}
    records.sort(key=lambda r: (r["repeat"], r["task"], order.get(r["arm"], 0)))
    markdown = out_dir / "results.md"
    markdown.write_text(render_markdown(meta, records), encoding="utf-8")
    write_csv(out_dir / "results.csv", records)
    (out_dir / "cost.json").write_text(
        json.dumps(cost_summary(meta, records), indent=2) + "\n", encoding="utf-8"
    )
    return markdown
