"""Build `src/certo/data/model_data.json`: third-party scores and prices for
every model LMArena or Epoch AI rates (src/certo/model_data.py).

Run by a maintainer before a release, then review the diff:

    uv run --with pyarrow python scripts/build_model_data.py

It downloads LMArena's leaderboard tables (parquet, hence pyarrow, which
Certo itself doesn't need), Epoch AI's benchmark ZIP and LiteLLM's price
list into a temporary folder, or reads them from `--from DIR` (the same
file names; `--keep DIR` saves a download there). It prints what to
review: Certo's own models the sources don't rate, and how their ratings
would change.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from certo.model_data import LMARENA_TABLES, build, dumps, parse  # noqa: E402
from certo.ratings import rate  # noqa: E402

LMARENA = (
    "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/"
    "{table}/latest-00000-of-00001.parquet"
)
EPOCH = "https://epoch.ai/data/benchmark_data.zip"
LITELLM = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
ECI_FILE = "epoch_capabilities_index/eci_scores.csv"


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "certo-model-data"})
    with urllib.request.urlopen(request, timeout=120) as response:
        path.write_bytes(response.read())


def fetch(folder: Path) -> None:
    for table in LMARENA_TABLES:
        _download(LMARENA.format(table=table), folder / f"lmarena_{table}.parquet")
    _download(EPOCH, folder / "epoch_benchmark_data.zip")
    _download(LITELLM, folder / "litellm_prices.json")


def read(folder: Path) -> tuple[dict, list, dict]:
    import pyarrow.parquet as pq

    lmarena = {
        table: pq.read_table(folder / f"lmarena_{table}.parquet").to_pylist()
        for table in LMARENA_TABLES
    }
    with zipfile.ZipFile(folder / "epoch_benchmark_data.zip") as z:
        names = [n for n in z.namelist() if n.endswith(ECI_FILE)]
        if not names:
            raise SystemExit(f"Epoch's ZIP has no {ECI_FILE}: its layout changed.")
        eci = list(csv.DictReader(io.TextIOWrapper(z.open(names[0]), encoding="utf-8")))
    prices = json.loads((folder / "litellm_prices.json").read_text(encoding="utf-8"))
    return lmarena, eci, prices


def review(data: dict, out: Path) -> None:
    """What a person checks before committing the file."""
    models = data["models"]
    rated = parse(dumps(data))
    print(
        f"Models: {len(models)}; with a list price: {sum(bool(m['litellm']) for m in models.values())}"
    )
    for source in (
        "lmarena_webdev",
        "lmarena_text_factuality",
        "lmarena_creative_writing",
        "epoch_eci",
    ):
        print(f"  {source}: {sum(source in m['scores'] for m in models.values())}")
    print(f"  cost per agent task: {sum(m['cost_per_task'] is not None for m in models.values())}")

    catalog = yaml.safe_load((ROOT / "src/certo/data/models_list.yaml").read_text(encoding="utf-8"))
    no_data, changed = [], []
    for entry in catalog["models"]:
        local = entry["model"].startswith("ollama/")
        found = rated.lookup(entry["model"], local=local)
        result = rate(found, rated.anchors) if found is not None else None
        if result is None or result.no_data:
            no_data.append(entry["name"])
            continue
        moves = [
            f"{axis} {entry['ratings'][axis]} -> {value}"
            for axis, value in result.ratings.items()
            if axis in entry["ratings"] and abs(entry["ratings"][axis] - value) >= 1
        ]
        if moves:
            changed.append(f"{entry['name']}: " + ", ".join(moves))
    print(f"\nCerto's models with no data ({len(no_data)}): {', '.join(no_data) or 'none'}")
    print(f"Ratings that would move by a point or more ({len(changed)}):")
    for line in changed:
        print(f"  {line}")
    print(f"\nWrote {out}. Review the diff before committing.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="source", help="read the downloaded files from DIR")
    parser.add_argument("--keep", help="save the downloaded files in DIR")
    parser.add_argument("--out", default=str(ROOT / "src/certo/data/model_data.json"))
    args = parser.parse_args(argv)

    aliases = yaml.safe_load((ROOT / "scripts/model_data_aliases.yaml").read_text(encoding="utf-8"))
    if args.source:
        folder = Path(args.source)
        lmarena, eci, prices = read(folder)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(args.keep) if args.keep else Path(tmp)
            folder.mkdir(parents=True, exist_ok=True)
            fetch(folder)
            lmarena, eci, prices = read(folder)

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    data = build(lmarena, eci, prices, aliases or {}, generated)
    out = Path(args.out)
    out.write_text(dumps(data), encoding="utf-8")
    review(data, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
