"""docs_source.py: where `certo ask` reads the docs. No network: the
download is a fake."""

from __future__ import annotations

import io
import os
import urllib.error
import zipfile

import pytest

from certo import docs_source
from certo.docs_source import (
    DocsUnavailable,
    build_docs_zip,
    extract,
    find_docs,
    is_user_page,
    release_url,
)


@pytest.mark.parametrize(
    ("path", "user"),
    [
        ("README.md", True),
        ("guides/resume-a-run.md", True),
        ("reference/commands.md", True),
        ("concepts/how-verification-works.md", True),
        ("benchmark/baseline-0.1.23.md", False),
        ("launch/release-notes-v0.2.3.md", False),
        ("history/SPEC.md", False),
        ("guides/deep/x.md", False),
        ("../secret.md", False),
        ("guides/notes.txt", False),
    ],
)
def test_user_pages_are_the_top_pages_and_three_folders(path, user):
    assert is_user_page(path) is user


def _docs(tmp_path):
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "benchmark").mkdir()
    (docs / "README.md").write_text("# Docs\n")
    (docs / "guides" / "a.md").write_text("# A\n\n## One\ntext\n")
    (docs / "benchmark" / "b.md").write_text("# Bench\n")
    return docs


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """Certo as installed: no checkout docs, an empty cache folder."""
    monkeypatch.setattr(docs_source, "checkout_docs", lambda: None)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def test_the_release_zip_is_downloaded_once_then_read_from_the_cache(tmp_path, installed):
    zipped = tmp_path / "docs.zip"
    assert build_docs_zip(str(_docs(tmp_path)), str(zipped)) == 2
    urls = []

    def download(url):
        urls.append(url)
        return zipped.read_bytes()

    first = find_docs("0.2.4", download=download)
    assert first.where == "downloaded"
    assert first.folder == str(tmp_path / "cache" / "certo" / "docs" / "0.2.4")
    assert sorted(os.listdir(first.folder)) == ["README.md", "guides"]
    again = find_docs("0.2.4", download=download)
    assert again.where == "cache"
    assert urls == [release_url("0.2.4")]
    assert urls[0] == "https://github.com/alessioricco/certo/releases/download/v0.2.4/docs.zip"


def test_a_version_with_no_docs_zip_says_where_to_read_them(installed):
    def download(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    with pytest.raises(DocsUnavailable, match="has no docs to download"):
        find_docs("0.2.3", download=download)


def test_offline_with_no_cached_copy_says_so(installed):
    def download(url):
        raise urllib.error.URLError("no network")

    with pytest.raises(DocsUnavailable, match="try again when you are online"):
        find_docs("0.2.4", download=download)


def test_extract_writes_only_user_pages_inside_the_target(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docs/README.md", "# ok\n")
        archive.writestr("docs/../evil.md", "x")
        archive.writestr("/abs.md", "x")
        archive.writestr("docs/benchmark/b.md", "x")
        archive.writestr("other/README.md", "x")
    target = tmp_path / "cache" / "0.2.4"
    assert extract(buffer.getvalue(), str(target)) == 1
    assert os.listdir(target) == ["README.md"]
    assert not (tmp_path / "evil.md").exists() and not (tmp_path / "cache" / "evil.md").exists()


def test_a_broken_download_leaves_no_folder(tmp_path):
    target = tmp_path / "cache" / "0.2.4"
    with pytest.raises(DocsUnavailable, match="can't be read"):
        extract(b"not a zip", str(target))
    assert not target.exists()
    assert os.listdir(tmp_path / "cache") == []


def test_links_are_files_in_a_checkout_and_github_pages_at_the_tag_otherwise(tmp_path):
    checkout = docs_source.Docs(str(tmp_path), "checkout", "0.2.4")
    assert checkout.link("guides/a.md", "one") == str(tmp_path / "guides" / "a.md") + "#one"
    cached = docs_source.Docs(str(tmp_path), "cache", "0.2.4")
    assert cached.link("guides/a.md", "one") == (
        "https://github.com/alessioricco/certo/blob/v0.2.4/docs/guides/a.md#one"
    )


def test_this_checkout_reads_its_own_docs():
    found = find_docs("0.0.0", download=lambda url: pytest.fail("no download in a checkout"))
    assert found.where == "checkout"
    assert os.path.isfile(os.path.join(found.folder, "reference", "commands.md"))
