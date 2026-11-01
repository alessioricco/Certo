"""The shared core under Certo's interfaces: the command line, `certo-server`
and the MCP server call these functions instead of each building a run its own
way (DECISIONS.md, "The MCP server: every command, on a shared core").

Nothing here prints or asks: problems are raised as `ConfigError` (a setting
or a file is wrong) or `UsageError` (the options don't go together), with a
message the interface shows as it is. Options are named the way each interface
spells them through `spell`, so the command line says `--model` and the server
says `model`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace

from .config import (
    Config,
    ConfigError,
    defer_llm_check,
    ensure_llm_configured,
    override_llm,
    resolve_project_dir,
)
from .escalation import ResolvedLadder, load_ladder

Spell = Callable[[str], str]


class UsageError(ValueError):
    """Options that don't go together. The message is user-facing."""


def _plain(name: str) -> str:
    return name


@dataclass(frozen=True)
class RunOptions:
    """What a caller asks for, before any setting is read.

    `escalate` is None for no ladder, "" for the default ladder, or a ladder's
    name. `independent_tests` None keeps the setting; True or False sets it.
    """

    project: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    escalate: str | None = None
    auto_model: bool = False
    execution: str | None = None
    interactive: bool = False
    independent_tests: bool | None = None
    independent_tests_strict: bool = False
    verbose: bool = False
    agents_md: str | None = None


def resolve_config(
    options: RunOptions,
    *,
    load: Callable[[], Config],
    spell: Spell = _plain,
) -> Config:
    """The settings a run uses: `load()` (the settings files and environment),
    then `options` on top. The project folder is resolved but not created:
    `prepare_workspace` does that, once every check that can refuse is done."""
    if options.agents_md is not None and options.project is None:
        raise UsageError(f"{spell('agents_md')} requires {spell('project')}")
    if options.escalate is not None and (options.auto_model or options.model is not None):
        others = spell("model")
        if options.auto_model:
            others = f"{spell('auto_model')} or {others}"
        raise UsageError(
            f"{spell('escalate')} can't be combined with {others}: the ladder decides which "
            "models run"
        )

    # The overrides go on before the required-field checks, so they alone
    # can satisfy them (issue #11).
    with defer_llm_check():
        cfg = load()
    if (
        options.model is not None
        or options.api_key is not None
        or options.base_url is not None
        or options.reasoning_effort is not None
    ):
        cfg = override_llm(
            cfg,
            model=options.model,
            api_key=options.api_key,
            base_url=options.base_url,
            reasoning_effort=options.reasoning_effort,
        )
    # With a ladder or --auto-model the model files name every model and its
    # key, so CERTO_LLM_MODEL isn't needed (DECISIONS.md).
    if options.escalate is None and not options.auto_model and cfg.model_selection == "manual":
        cfg = ensure_llm_configured(cfg)

    if options.execution is not None:
        cfg = replace(cfg, execution=options.execution)
    if options.interactive:
        cfg = replace(cfg, interactive=True)
    if options.independent_tests is not None:
        cfg = replace(cfg, independent_tests=options.independent_tests)
        if not options.independent_tests:
            cfg = replace(cfg, independent_tests_strict=False)
    if options.independent_tests_strict:
        cfg = replace(cfg, independent_tests=True, independent_tests_strict=True)
    if options.verbose:
        cfg = replace(cfg, verbose=True)

    if options.escalate is not None:
        cfg = replace(cfg, model_selection="escalate", escalation_ladder=options.escalate)
    elif options.auto_model:
        cfg = replace(cfg, model_selection="auto")
    elif cfg.model_selection == "escalate" and options.model is not None:
        raise UsageError(
            f"{spell('model')} can't be used while CERTO_MODEL_SELECTION=escalate: the "
            "ladder decides which models run"
        )

    if options.project is not None:
        cfg = replace(cfg, workspace=resolve_project_dir(cfg.projects_dir, options.project))
    return cfg


def load_run_ladder(
    cfg: Config, on_warning: Callable[[str], None] | None = None
) -> ResolvedLadder | None:
    """The ladder an escalation climbs, or None when `cfg` doesn't escalate.
    With --auto-model, checks the model files the same way, so a broken file
    is refused before the run starts."""
    if cfg.model_selection == "escalate":
        return load_ladder(
            cfg.models_file,
            cfg.models_list_file,
            cfg.escalation_ladder or None,
            escalation_file=cfg.escalation_file,
            task_profiles_file=cfg.task_profiles_file,
            on_warning=on_warning,
        )
    if cfg.model_selection == "auto":
        from .catalog_check import load_checked_catalog

        load_checked_catalog(
            cfg.models_file,
            cfg.models_list_file,
            task_profiles_file=cfg.task_profiles_file,
            escalation_file=cfg.escalation_file,
            mode="auto",
        )
    return None


def prepare_workspace(cfg: Config, options: RunOptions) -> bool:
    """Make the project folder ready for a run: refuse OpenHands plugins from
    outside it (plugins.py), create a named project and remember that Certo
    created it, and write `agents_md`. Returns whether the folder was created
    now."""
    if cfg.execution == "local":
        from .plugins import foreign_plugins, refusal

        found = foreign_plugins(cfg.workspace, cfg.projects_dir)
        if found:
            raise ConfigError(refusal(found))
    created = False
    if options.project is not None:
        from .worktree import record_created_project

        created = not os.path.exists(cfg.workspace)
        os.makedirs(cfg.workspace, exist_ok=True)
        if created:
            record_created_project(cfg.projects_dir, options.project)
    if options.agents_md is not None:
        from .skills import write_project_context

        write_project_context(cfg.workspace, options.agents_md)
    return created
