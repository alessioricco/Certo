"""Build `docs.zip`, the user pages of `docs/`, for a GitHub Release.

`certo ask` downloads it for its own version (src/certo/docs_source.py,
which decides what a user page is). Run by .github/workflows/release.yml:

    python3 scripts/build_docs_zip.py docs.zip

Stdlib only: it imports docs_source.py from src/ by path, with no install.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: build_docs_zip.py OUT.zip", file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location(
        "docs_source", ROOT / "src" / "certo" / "docs_source.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look themselves up there
    spec.loader.exec_module(module)
    count = module.build_docs_zip(str(ROOT / "docs"), argv[0])
    print(f"{argv[0]}: {count} pages")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
