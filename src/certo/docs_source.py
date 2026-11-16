"""Where `certo ask` reads Certo's docs: the user pages of the docs of this
Certo's own version (DECISIONS.md, "certo ask", 2026-11-14).

- Run from a checkout, the `docs/` folder next to the source.
- Installed, the `docs.zip` the release workflow attaches to the version's
  GitHub Release, downloaded on first use and kept in
  `~/.cache/certo/docs/<version>/` (or under `$XDG_CACHE_HOME`): offline
  afterwards. Not `main`: it documents flags this version doesn't have.
  GitHub sees the version, never the question.

User pages only: `docs/*.md` and the `guides/`, `reference/` and
`concepts/` folders; benchmark records, release notes and history are
left out, as they are from `docs.zip` (`build_docs_zip`, which the
release workflow runs through scripts/build_docs_zip.py). Stdlib only.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

USER_DIRS = ("guides", "reference", "concepts")
DOCS_ZIP = "docs.zip"
RELEASES = "https://github.com/alessioricco/certo/releases/download"
BLOB = "https://github.com/alessioricco/certo/blob"
_FETCH_TIMEOUT_SECONDS = 20
_MAX_ZIP_BYTES = 20 * 1024 * 1024


class DocsUnavailable(Exception):
    """No docs to read. The message says why and what to do."""


@dataclass(frozen=True)
class Docs:
    folder: str  # the folder holding the pages, by their paths under docs/
    where: str  # "checkout", "cache" or "downloaded"
    version: str

    def link(self, page: str, anchor: str = "") -> str:
        """Where a reader opens a page: the file in a checkout, else the page
        on GitHub at this version's tag."""
        tail = f"#{anchor}" if anchor else ""
        if self.where == "checkout":
            return os.path.join(self.folder, *page.split("/")) + tail
        return f"{BLOB}/v{self.version}/docs/{page}{tail}"


def is_user_page(relpath: str) -> bool:
    """A page under docs/ (forward slashes) that `certo ask` reads."""
    parts = relpath.split("/")
    if not relpath.endswith(".md") or any(p in ("", ".", "..") for p in parts):
        return False
    return len(parts) == 1 or (len(parts) == 2 and parts[0] in USER_DIRS)


def user_pages(folder: str) -> list[tuple[str, str]]:
    """(path under docs/, text) for each user page in `folder`, sorted."""
    pages = []
    root = Path(folder)
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if is_user_page(rel):
            pages.append((rel, path.read_text(encoding="utf-8")))
    return pages


def checkout_docs() -> str | None:
    """`docs/` of the source checkout this Certo runs from, or None when it
    is installed (no `docs/` beside `src/`)."""
    root = Path(__file__).resolve().parents[2]
    docs = root / "docs"
    if (root / "pyproject.toml").is_file() and (docs / "README.md").is_file():
        return str(docs)
    return None


def cache_folder(version: str, environ: dict[str, str] | None = None) -> str:
    environ = dict(os.environ) if environ is None else environ
    xdg = (environ.get("XDG_CACHE_HOME") or "").strip()
    base = xdg if os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "certo", "docs", version)


def release_url(version: str) -> str:
    return f"{RELEASES}/v{version}/{DOCS_ZIP}"


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "certo"})
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        data = response.read(_MAX_ZIP_BYTES + 1)
    if len(data) > _MAX_ZIP_BYTES:
        raise DocsUnavailable(f"{url} is larger than {_MAX_ZIP_BYTES // (1024 * 1024)} MB.")
    return data


def extract(data: bytes, target: str) -> int:
    """Put the user pages of a `docs.zip` into `target` (replaced as a
    whole, so a broken download never leaves half a folder). Only
    `docs/<user page>` members are written; any other path is skipped.
    Returns how many pages were written."""
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".docs-", dir=parent)
    count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                name = member.filename
                if member.is_dir() or not name.startswith("docs/"):
                    continue
                rel = name[len("docs/") :]
                if not is_user_page(rel):
                    continue
                path = os.path.join(staging, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(archive.read(member))
                count += 1
        if count == 0:
            raise DocsUnavailable("the docs archive holds no page.")
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.replace(staging, target)
        return count
    except zipfile.BadZipFile as exc:
        raise DocsUnavailable(f"the docs archive can't be read ({exc}).") from exc
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def find_docs(version: str, *, download=_download) -> Docs:
    """The docs for this version. Raises DocsUnavailable when there are none
    on this computer and they can't be downloaded."""
    checkout = checkout_docs()
    if checkout is not None:
        return Docs(checkout, "checkout", version)
    folder = cache_folder(version)
    if os.path.isfile(os.path.join(folder, "README.md")):
        return Docs(folder, "cache", version)
    url = release_url(version)
    try:
        data = download(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise DocsUnavailable(
                f"Certo {version} has no docs to download ({url} isn't there: a version "
                "that isn't released, or one from before 0.2.4). Read them on "
                "https://github.com/alessioricco/certo/tree/main/docs instead."
            ) from exc
        raise DocsUnavailable(f"Couldn't download Certo's docs ({url}: {exc}).") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise DocsUnavailable(
            f"Couldn't download Certo's docs ({url}: {exc}). They are downloaded once, "
            f"then kept in {folder}; try again when you are online."
        ) from exc
    extract(data, folder)
    return Docs(folder, "downloaded", version)


def build_docs_zip(docs_folder: str, out_path: str) -> int:
    """`docs.zip` for a release: the user pages under `docs/`. Returns how
    many pages it holds."""
    pages = user_pages(docs_folder)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, text in pages:
            info = zipfile.ZipInfo(f"docs/{rel}", date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text)
    return len(pages)
