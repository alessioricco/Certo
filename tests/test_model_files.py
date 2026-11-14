"""Finding the model files (model_files.py): the two optional ones."""

from __future__ import annotations

import pytest

from certo.model_catalog import ModelCatalogError
from certo.model_files import resolve_optional


def test_the_optional_files_are_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Certo's own task profiles are always there; no ladder file.
    profiles, escalation = resolve_optional()
    assert profiles.endswith("task_profiles.yaml.example")
    assert escalation is None


def test_the_optional_files_are_found_in_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task_profiles.yaml").write_text("task_profiles: {}\n")
    (tmp_path / "escalation.yaml").write_text("escalation: {}\n")

    profiles, escalation = resolve_optional()

    assert profiles.endswith("task_profiles.yaml")
    assert escalation.endswith("escalation.yaml")


@pytest.mark.parametrize(
    ("kwargs", "setting"),
    [
        ({"task_profiles_file": "nope.yaml"}, "CERTO_TASK_PROFILES_FILE"),
        ({"escalation_file": "nope.yaml"}, "CERTO_ESCALATION_FILE"),
    ],
)
def test_a_named_optional_file_must_exist(tmp_path, monkeypatch, kwargs, setting):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ModelCatalogError, match=f"{setting} names nope.yaml, which doesn't exist"):
        resolve_optional(**kwargs)
