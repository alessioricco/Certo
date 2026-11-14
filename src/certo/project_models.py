"""A project's own model choice, `certo-models.yaml` at its top (written by
`certo models choose`): the models it may use, by name (keys stay in the
user's models.yaml), its strategy, and the task profiles and escalation
ladder proposed for those models.

A run in that project reads the file as its task profiles and escalation
file (unless a setting names others), and the strategy becomes the run's
model selection, unless a flag or CERTO_MODEL_SELECTION chose one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace

from .config import Config, ConfigError
from .model_catalog import PROJECT_FILE, STRATEGIES, ModelCatalogError, _read_mapping


def project_file(folder: str) -> str | None:
    path = os.path.join(folder, PROJECT_FILE)
    return path if os.path.isfile(path) else None


def read_strategy(path: str) -> str | None:
    """The file's `strategy:`, or None when it has none."""
    try:
        raw = _read_mapping(path)
    except ModelCatalogError as exc:
        raise ConfigError(str(exc)) from exc
    strategy = raw.get("strategy")
    if strategy is None:
        return None
    if strategy not in STRATEGIES:
        raise ConfigError(
            f"{path}: 'strategy' must be one of {', '.join(STRATEGIES)}, got {strategy!r}."
        )
    return str(strategy)


def apply_project_models(
    cfg: Config,
    folder: str,
    *,
    mode_chosen: bool,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """`cfg` with the project's file in `folder` applied: as the task
    profiles and escalation file where no setting names one, and its
    strategy as the model selection unless `mode_chosen` (a flag) or
    CERTO_MODEL_SELECTION already chose. Unchanged without the file."""
    path = project_file(folder)
    if path is None:
        return cfg
    environ = os.environ if environ is None else environ
    changes: dict[str, str] = {}
    if not cfg.task_profiles_file:
        changes["task_profiles_file"] = path
    if not cfg.escalation_file:
        changes["escalation_file"] = path
    strategy = read_strategy(path)
    if strategy and not mode_chosen and not (environ.get("CERTO_MODEL_SELECTION") or "").strip():
        changes["model_selection"] = strategy
    return replace(cfg, **changes) if changes else cfg
