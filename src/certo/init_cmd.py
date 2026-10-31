"""`certo init [FOLDER]`: a ready-to-use workspace in one command.

Writes a minimal `.env`, a `.gitignore`, the sample tasks and a short
README into FOLDER. The provider presets and default models live in
`starter/providers.toml`, the only place they are kept.

On a terminal it asks only what `.env` needs: provider, model, and the API
key (hidden) or the Ollama address. Flags skip their question. With no
terminal and no flags, nothing is asked and every preset is written
commented out. There is no `--api-key` flag: a key on the command line ends
up in shell history, so a key comes from the hidden prompt or from the
provider's own environment variable, never from argv. The key is never
printed or logged.
"""

from __future__ import annotations
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import TextIO

from . import menus as _menus
from .catalog_report import print_catalog_report, print_task_routing
from .config import (
    ConfigError,
    SettingSource,
    load_config,
    load_settings_files,
    user_settings_path,
)
from .llm_check import check_tool_calling, detail_lines, explain

DEFAULT_FOLDER = "certo-workspace"
# Where `certo init` saves the settings.
USER_SCOPE = "user"
FOLDER_SCOPE = "folder"
README_TITLE = "# Certo workspace"

_STARTER = resources.files("certo").joinpath("starter")
_OLLAMA_TIMEOUT_SECONDS = 5
# Generous: a local model may have to load into memory on the first call.
CHECK_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    model: str | None = None
    key_env: str | None = None
    key_url: str | None = None
    base_url: str | None = None
    small_model: str | None = None
    # Written as CERTO_LLM_TIMEOUT_SECONDS when the provider is chosen.
    llm_timeout_seconds: int | None = None


def load_providers() -> list[Provider]:
    data = tomllib.loads(_STARTER.joinpath("providers.toml").read_text(encoding="utf-8"))
    fields = Provider.__dataclass_fields__
    return [Provider(**{k: v for k, v in p.items() if k in fields}) for p in data["provider"]]


@dataclass(frozen=True)
class Settings:
    """What `.env` will select. `api_key` is never shown in a repr."""

    provider: Provider
    model: str
    api_key: str | None = field(default=None, repr=False)
    # Set instead of api_key: `.env` then refers to this variable, so the
    # key is read from the environment and never copied into the file.
    key_env: str | None = None
    base_url: str | None = None

    @property
    def has_key(self) -> bool:
        return bool(self.api_key or self.key_env)


def _quote(value: str) -> str:
    """Single-quoted for python-dotenv: literal, no `${...}` expansion."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _preset_lines(provider: Provider) -> list[str]:
    """The two commented-out lines that select `provider`."""
    if provider.model is None:
        return []
    second = (
        f"# CERTO_LLM_BASE_URL={provider.base_url}" if provider.base_url else "# CERTO_LLM_API_KEY="
    )
    return [f"# {provider.label}", f"# CERTO_LLM_MODEL={provider.model}", second]


def _active_lines(settings: Settings) -> list[str]:
    lines = [f"# Your model: {settings.provider.label}", f"CERTO_LLM_MODEL={settings.model}"]
    if settings.key_env:
        lines += [
            f"# Read from {settings.key_env} in your environment each time Certo starts.",
            f"CERTO_LLM_API_KEY=${{{settings.key_env}}}",
        ]
    elif settings.api_key:
        lines.append(f"CERTO_LLM_API_KEY={_quote(settings.api_key)}")
    elif settings.provider.key_env or (settings.provider.id == "other" and not settings.base_url):
        where = f" (get one at {settings.provider.key_url})" if settings.provider.key_url else ""
        lines += [f"# Paste your API key after the ={where}.", "CERTO_LLM_API_KEY="]
    if settings.base_url:
        lines.append(f"CERTO_LLM_BASE_URL={settings.base_url}")
    if settings.provider.llm_timeout_seconds:
        lines += [
            "# How long one answer may take, in seconds: a local model can need",
            "# more than the default 300 to think.",
            f"CERTO_LLM_TIMEOUT_SECONDS={settings.provider.llm_timeout_seconds}",
        ]
    return lines


def render_env(providers: list[Provider], settings: Settings | None = None) -> str:
    """The `.env` text: the chosen settings, then the other providers'
    presets commented out. With no settings, every preset is commented out
    for the user to fill in."""
    lines = ["# Certo settings, written by `certo init`. Keep this file private."]
    if settings is None:
        lines += [
            "# Nothing is set yet: uncomment the two lines for your provider,",
            "# add your API key (not needed for Ollama), then run: certo check",
            "",
        ]
        others = providers
    else:
        lines += [
            "",
            *_active_lines(settings),
            "",
            "# To switch provider, comment out the lines above and uncomment",
            "# the two lines of the provider you want.",
            "",
        ]
        others = [p for p in providers if p.id != settings.provider.id]
    for provider in others:
        preset = _preset_lines(provider)
        if preset:
            lines += [*preset, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


# --- Questions ------------------------------------------------------------------


class Cancelled(Exception):
    """The user stopped answering (Ctrl-C / Ctrl-D)."""


class Prompter:
    """Terminal questions. Injected functions keep it testable. On a real
    terminal (the default input and output), `choose` and `confirm` are
    arrow-key menus (menus.py); otherwise numbered questions."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        secret_fn: Callable[[str], str] = getpass.getpass,
        out: TextIO | None = None,
        menus: bool | None = None,
    ) -> None:
        self._input = input_fn
        self._secret = secret_fn
        self.out = out or sys.stdout
        if menus is None:
            menus = input_fn is input and out is None and _menus.available()
        self.menus = menus

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def _read(self, fn: Callable[[str], str], prompt: str) -> str:
        try:
            return fn(prompt).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise Cancelled from exc

    def ask(self, question: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        answer = self._read(self._input, f"{question}{suffix}: ")
        return answer or (default or "")

    def confirm(self, question: str) -> bool:
        if self.menus:
            try:
                return _menus.confirm(question)
            except (KeyboardInterrupt, EOFError) as exc:
                raise Cancelled from exc
        while True:
            answer = self._read(self._input, f"{question} [Y/n]: ").lower()
            if answer in ("", "y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.say("Please answer y or n.")

    def choose(self, question: str, options: list[str], default: int = 0) -> int:
        if self.menus:
            try:
                return _menus.choose(question, options, default)
            except (KeyboardInterrupt, EOFError) as exc:
                raise Cancelled from exc
        self.say(question)
        for i, option in enumerate(options, start=1):
            self.say(f"  {i}. {option}")
        while True:
            answer = self.ask("Choice", str(default + 1))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.say(f"Please enter a number from 1 to {len(options)}.")

    def secret(self, question: str) -> str:
        return self._read(self._secret, f"{question}: ")


def normalize_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    return url


def fetch_ollama_models(base_url: str, timeout: float = _OLLAMA_TIMEOUT_SECONDS) -> list[str]:
    """Names of the models installed on an Ollama server (`/api/tags`).
    Raises OSError (URLError included) when the server can't be reached."""
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m["name"] for m in data.get("models", []) if m.get("name")]


def _provider_for_model(providers: list[Provider], model: str) -> Provider:
    prefix = model.split("/", 1)[0] if "/" in model else ""
    if prefix == "ollama_chat":
        prefix = "ollama"
    by_id = {p.id: p for p in providers}
    return by_id.get(prefix) or by_id["other"]


def _with_prefix(provider: Provider, model: str) -> str:
    """`claude-sonnet-5-5` typed for Anthropic means `anthropic/claude-sonnet-5-5`."""
    if provider.id == "other" or "/" in model:
        return model
    return f"{provider.id}/{model}"


def _ollama_name(model: str | None) -> str:
    return (model or "").split("/", 1)[-1]


def _ask_ollama(
    provider: Provider,
    args: argparse.Namespace,
    prompter: Prompter,
    ask: bool,
    fetch_models: Callable[[str], list[str]],
) -> Settings:
    default_url = provider.base_url or "http://localhost:11434"
    base_url = args.base_url or (
        prompter.ask("Ollama address", default_url) if ask else default_url
    )
    base_url = normalize_base_url(base_url)
    if args.model:
        return Settings(provider, _with_prefix(provider, args.model), base_url=base_url)

    try:
        installed = fetch_models(base_url)
    except (OSError, ValueError):
        prompter.say(
            f"Couldn't reach Ollama at {base_url}. Check that Ollama is running and "
            "that the address is right. If it runs on another machine, start it "
            "there with OLLAMA_HOST=0.0.0.0 so it accepts connections from this one."
        )
        installed = None
    if installed == []:
        prompter.say("This Ollama server has no models yet. Pull one, then run: certo check")
        prompter.say(f"  ollama pull {_ollama_name(provider.model)}")
        if provider.small_model:
            prompter.say(
                f"  ollama pull {_ollama_name(provider.small_model)}"
                "   (smaller, for machines with less memory)"
            )
    if not installed:
        model = prompter.ask("Model", provider.model) if ask else provider.model
        return Settings(provider, _with_prefix(provider, model or ""), base_url=base_url)

    preferred = _preferred_installed(provider, installed)
    if not ask:
        return Settings(provider, f"ollama/{installed[preferred]}", base_url=base_url)
    options = [*installed, "Another model (type its name)"]
    index = prompter.choose("Which installed model?", options, preferred)
    if index == len(installed):
        name = prompter.ask("Model name, as Ollama knows it", _ollama_name(provider.model))
        return Settings(provider, _with_prefix(provider, name), base_url=base_url)
    return Settings(provider, f"ollama/{installed[index]}", base_url=base_url)


def _preferred_installed(provider: Provider, installed: list[str]) -> int:
    """The installed model to offer first: the recommended one, then the
    smaller one, then any coder model, else the first."""
    for wanted in (provider.model, provider.small_model):
        if wanted and _ollama_name(wanted) in installed:
            return installed.index(_ollama_name(wanted))
    return next((i for i, name in enumerate(installed) if "coder" in name.lower()), 0)


def gather_settings(
    args: argparse.Namespace,
    prompter: Prompter,
    *,
    providers: list[Provider],
    env: Mapping[str, str],
    interactive: bool,
    fetch_models: Callable[[str], list[str]] = fetch_ollama_models,
) -> Settings | None:
    """Ask what `.env` needs. None means "write every preset commented out"."""
    if not interactive and not (args.yes or args.provider or args.model):
        return None
    ask = interactive and not args.yes
    if ask:
        prompter.say("Certo setup. Press Enter to accept the default in [brackets].\n")

    by_id = {p.id: p for p in providers}
    if args.provider:
        provider = by_id[args.provider]
    elif args.model:
        provider = _provider_for_model(providers, args.model)
    else:
        found = next((p for p in providers if p.key_env and env.get(p.key_env)), None)
        default = providers.index(found) if found else 0
        index = (
            prompter.choose(
                "Which model provider do you want to use?", [p.label for p in providers], default
            )
            if ask
            else default
        )
        provider = providers[index]
        prompter.say()

    if provider.id == "ollama":
        return _ask_ollama(provider, args, prompter, ask, fetch_models)

    if provider.id == "other":
        model = args.model or ""
        while not model:
            if not ask:
                raise ValueError("--provider other needs --model (any LiteLLM model id).")
            model = prompter.ask("LiteLLM model id (for example deepseek/deepseek-chat)")
        api_key = prompter.secret("API key (hidden, Enter to skip)") if ask else ""
        base_url = args.base_url or (prompter.ask("Base URL (Enter to skip)") if ask else "")
        return Settings(
            provider,
            model,
            api_key=api_key or None,
            base_url=normalize_base_url(base_url) if base_url else None,
        )

    model = args.model or (prompter.ask("Model", provider.model) if ask else provider.model)
    model = _with_prefix(provider, model or "")
    base_url = normalize_base_url(args.base_url) if args.base_url else None
    found = provider.key_env and env.get(provider.key_env)
    if found and (
        not ask or prompter.confirm(f"Found {provider.key_env} in your environment. Use it?")
    ):
        return Settings(provider, model, key_env=provider.key_env, base_url=base_url)
    api_key = prompter.secret("API key (hidden)") if ask else ""
    return Settings(provider, model, api_key=api_key or None, base_url=base_url)


def _folder_has_files(folder: str) -> bool:
    return os.path.isdir(folder) and any(os.scandir(folder))


def _write_private(path: str, text: str) -> None:
    """Write `path` readable by the owner only (600), even if it existed."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def _merge_gitignore(path: str, template: str) -> None:
    """Write the template, or append its missing entries to an existing file."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(template)
        return
    with open(path, encoding="utf-8") as f:
        existing = f.read()
    have = {line.strip() for line in existing.splitlines()}
    missing = [
        line
        for line in template.splitlines()
        if line.strip() and not line.startswith("#") and line.strip() not in have
    ]
    if missing:
        with open(path, "a", encoding="utf-8") as f:
            f.write(("" if existing.endswith("\n") or not existing else "\n") + "\n".join(missing))
            f.write("\n")


def write_workspace(folder: str, env_text: str | None, settings_file: str = "`.env`") -> list[str]:
    """Create FOLDER's files. Returns notes about files kept as they were.

    `env_text` None writes no `.env`: the settings live in the user file,
    which `settings_file` then names in the README. The caller has already
    decided overwriting is allowed. A README.md that isn't one `certo init`
    wrote is kept, since FOLDER may be an existing repo; `.gitignore` only
    gains the entries it lacks.
    """
    notes = []
    os.makedirs(os.path.join(folder, "tasks"), exist_ok=True)
    if env_text is not None:
        _write_private(os.path.join(folder, ".env"), env_text)
    _merge_gitignore(
        os.path.join(folder, ".gitignore"),
        _STARTER.joinpath("gitignore").read_text(encoding="utf-8"),
    )
    for task in sorted(_STARTER.joinpath("tasks").iterdir(), key=lambda t: t.name):
        if task.name.endswith(".md"):
            with open(os.path.join(folder, "tasks", task.name), "w", encoding="utf-8") as f:
                f.write(task.read_text(encoding="utf-8"))
    readme = os.path.join(folder, "README.md")
    if os.path.exists(readme):
        with open(readme, encoding="utf-8") as f:
            ours = f.readline().strip() == README_TITLE
        if not ours:
            notes.append("Kept your existing README.md; Certo's notes were not written.")
            return notes
    text = _STARTER.joinpath("README.md").read_text(encoding="utf-8")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(text.replace("SETTINGS_FILE", settings_file))
    return notes


def write_user_settings(path: str, env_text: str) -> None:
    """Write the user settings file (600), creating its folder."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_private(path, env_text)


def describe_settings_file(path: str) -> str:
    """'Anthropic (Claude), model anthropic/x' for an existing settings
    file. Reads only the model line: the key is never read or shown."""
    from dotenv import dotenv_values

    model = (dotenv_values(path, interpolate=False).get("CERTO_LLM_MODEL") or "").strip()
    if not model:
        return "no model set"
    provider = _provider_for_model(load_providers(), model)
    label = provider.label if provider.id != "other" else "another provider"
    return f"{label}, model {model}"


def _provider_name(model: str) -> str | None:
    """'Anthropic' for an anthropic/ model: the provider label without the
    parenthesized note, for the plain-language check messages."""
    provider = _provider_for_model(load_providers(), model)
    if provider.id == "other":
        return None
    return provider.label.split(" (", 1)[0]


def run_check(
    env: Mapping[str, str] | None, out: TextIO, *, timeout: int = CHECK_TIMEOUT_SECONDS
) -> bool:
    """The test call behind `certo init` and `certo check`: one tool call
    through the configured model, reported as one plain line. `env` None
    reads the settings as a run does (environment, then ./.env)."""
    try:
        cfg = load_config(env)
    except ConfigError as exc:
        print(f"Checking the model... not configured: {exc}", file=out)
        return False
    local = cfg.model.split("/", 1)[0] in ("ollama", "ollama_chat")
    wait = " (a local model may take a minute to load)" if local else ""
    print(f"Checking the model {cfg.model}{wait}...", end=" ", file=out, flush=True)
    result = check_tool_calling(cfg, timeout=timeout)
    details = detail_lines(result)
    if details:
        print(file=out)  # end the "Checking the model ..." line
        for line in details:
            print(line, file=out)
    print(explain(result, _provider_name(cfg.model)), file=out)
    return result.ok


def _settings_env(settings: Settings, env: Mapping[str, str]) -> dict[str, str]:
    """The CERTO_LLM_* values the written .env resolves to."""
    values = {"CERTO_LLM_MODEL": settings.model}
    key = settings.api_key or (env.get(settings.key_env, "") if settings.key_env else "")
    if key:
        values["CERTO_LLM_API_KEY"] = key
    if settings.base_url:
        values["CERTO_LLM_BASE_URL"] = settings.base_url
    return values


def build_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo check",
        description=(
            "Check that the configured model works: one small real call, which "
            "must come back as a tool call, since that's what Certo's agent "
            "needs. Reads the settings exactly as a run does: exported "
            "CERTO_LLM_* variables, then .env in the current folder, then the "
            "user settings file. Prints where each setting came from first. When "
            "a models.yaml (CERTO_MODELS_FILE) exists, also checks it: models, "
            "the models each task profile would use, ladders, errors and warnings."
        ),
    )
    parser.add_argument(
        "--task",
        metavar="TASK",
        help=(
            "Show how --auto-model would route this task (text, a task file or a "
            "URL, as for a run): the task profile it matches, why, and every "
            "model in the order it would try them. Calls no model and changes no "
            "file."
        ),
    )
    parser.add_argument(
        "--models",
        action="store_true",
        help=(
            "Also make the real tool-call test against every active model in "
            "models.yaml, one line per model."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=CHECK_TIMEOUT_SECONDS,
        help=f"Seconds to wait for the answer (default {CHECK_TIMEOUT_SECONDS}).",
    )
    return parser


def check_main(argv: list[str], *, out: TextIO | None = None) -> int:
    """`certo check`: re-run init's model check against the current settings."""
    args = build_check_parser().parse_args(argv)
    out = out or sys.stdout
    if args.task is not None:
        from .cli import resolve_task_source  # cli imports this module

        load_settings_files()  # the model-file settings can be in .env
        try:
            task = resolve_task_source(args.task)
        except ValueError as exc:
            print(f"Error: {exc}", file=out)
            return 1
        return 0 if print_task_routing(out, task) else 1
    print_setting_sources(load_settings_files(), out)
    ok = run_check(None, out, timeout=args.timeout)
    print(file=out)
    catalog_ok = print_catalog_report(
        out,
        test_models=args.models,
        timeout=args.timeout,
        check=lambda cfg, timeout: check_tool_calling(cfg, timeout=timeout),
        explain=lambda result, _provider: explain(result, _provider_name(result.model)),
    )
    if not ok or not catalog_ok:
        print("Fix the settings as described, then run: certo check", file=out)
    return 0 if ok and catalog_ok else 1


# The settings `certo check` reports. The key is shown only as set/not set.
_CHECK_SETTINGS = (
    "CERTO_LLM_MODEL",
    "CERTO_LLM_API_KEY",
    "CERTO_LLM_BASE_URL",
    "CERTO_LLM_REASONING_EFFORT",
)
_SECRET_SETTINGS = {"CERTO_LLM_API_KEY"}


def print_setting_sources(sources: Mapping[str, SettingSource], out: TextIO) -> None:
    """One line per LLM setting: its value (the key only as set/not set)
    and where it came from. Reads values from os.environ, which
    `load_settings_files` has just filled."""
    print("Settings:", file=out)
    width = max(len(name) for name in _CHECK_SETTINGS)
    for name in _CHECK_SETTINGS:
        value = (os.environ.get(name) or "").strip()
        source = sources.get(name)
        if not value or source is None:
            if name == "CERTO_LLM_REASONING_EFFORT":
                continue  # optional, and unset is the usual case
            print(f"  {name:<{width}}  not set", file=out)
            continue
        shown = "set" if name in _SECRET_SETTINGS else value
        print(f"  {name:<{width}}  {shown}, from {source.describe()}", file=out)
    print(file=out)


def build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo init",
        description=(
            "Save your model settings, for all projects on this computer or for "
            "one folder, and create a folder with sample tasks and a README with "
            "the next steps. On a terminal it asks a few questions; each flag "
            "below skips one."
        ),
        epilog=(
            "There is no --api-key flag, on purpose: a key typed on the command "
            "line is saved in your shell history. Type it at the hidden prompt, "
            "or export the provider's own variable (OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY or GEMINI_API_KEY) first and init offers to use it. "
            "Without a terminal and without flags, nothing is asked and FOLDER/.env "
            "is written with every provider commented out for you to fill in."
        ),
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=DEFAULT_FOLDER,
        help=f"Folder to create (default: ./{DEFAULT_FOLDER}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Write into a folder that isn't empty, replacing an existing .env and "
            "sample tasks. Without a terminal, or with --yes, also needed to "
            "replace an existing user settings file."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=[p.id for p in load_providers()],
        default=None,
        help="Model provider; skips that question.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id, e.g. anthropic/claude-sonnet-5-5; skips that question.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Server address, for Ollama or a self-hosted model; skips that question.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--global",
        dest="scope",
        action="store_const",
        const=USER_SCOPE,
        help=(
            "Save the settings for all projects on this computer, in the user "
            "settings file (~/.config/certo/.env, or under $XDG_CONFIG_HOME); "
            "skips that question. The default with --yes."
        ),
    )
    scope.add_argument(
        "--local",
        dest="scope",
        action="store_const",
        const=FOLDER_SCOPE,
        help="Save the settings in FOLDER/.env, for that folder only; skips that question.",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="With --global: don't create the folder with sample tasks.",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Don't make the test call to the model after writing .env.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Ask nothing and accept every default: settings for all projects, "
            "plus the sample folder. A key is used only from the environment."
        ),
    )
    return parser


def init_main(
    argv: list[str],
    *,
    prompter: Prompter | None = None,
    env: Mapping[str, str] | None = None,
    interactive: bool | None = None,
    fetch_models: Callable[[str], list[str]] = fetch_ollama_models,
    user_path: str | None = None,
    run_sample: Callable[[str, Sample], int] | None = None,
) -> int:
    """`certo init`. `user_path` defaults to `user_settings_path()`.
    `run_sample` runs a sample task in a folder; the CLI passes
    `run_sample_task`. None (the default, and in tests) never offers it."""
    if argv[:1] == ["models"]:
        # `certo init models`; a folder named "models" is `certo init ./models`.
        from .init_models import init_models_main

        return init_models_main(
            argv[1:], prompter=prompter, fetch_models=fetch_models, interactive=interactive
        )
    prompter = prompter or Prompter()
    out = prompter.out
    env = os.environ if env is None else env
    interactive = sys.stdin.isatty() if interactive is None else interactive
    user_path = user_settings_path() if user_path is None else user_path
    args = build_init_parser().parse_args(argv)
    folder = args.folder
    ask = interactive and not args.yes
    # Today's behaviour without a terminal: settings in FOLDER/.env, unless
    # a flag says otherwise. --yes means "all projects", the recommended one.
    scope = args.scope or (USER_SCOPE if args.yes else None if ask else FOLDER_SCOPE)

    if os.path.exists(folder) and not os.path.isdir(folder):
        print(f"Error: {folder} exists and is not a folder.", file=sys.stderr)
        return 1
    blocked = _folder_blocked(folder, args.force)
    if blocked and scope == FOLDER_SCOPE:
        print(f"Error: {blocked}", file=sys.stderr)
        return 1
    if scope == USER_SCOPE and not ask and os.path.exists(user_path) and not args.force:
        print(
            f"Error: {user_path} already exists ({describe_settings_file(user_path)}). "
            "Use --force to replace it.",
            file=sys.stderr,
        )
        return 1

    providers = load_providers()
    try:
        settings = gather_settings(
            args,
            prompter,
            providers=providers,
            env=env,
            interactive=interactive,
            fetch_models=fetch_models,
        )
        if scope is None:
            scope = _ask_scope(prompter)
        if scope == FOLDER_SCOPE and blocked:
            print(f"Error: {blocked} Nothing was written.", file=sys.stderr)
            return 1
        save = True
        if scope == USER_SCOPE and ask and os.path.exists(user_path):
            prompter.say(
                f"You already have settings for all projects in {user_path}: "
                f"{describe_settings_file(user_path)}."
            )
            save = prompter.confirm("Replace them?")
        samples = scope == FOLDER_SCOPE or _want_samples(args, prompter, ask, blocked)
    except Cancelled:
        print("\nCancelled. Nothing was written.", file=out)
        return 130
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if ask:
        prompter.say()

    env_text = render_env(providers, settings)
    if scope == USER_SCOPE:
        settings_path = user_path
        if save:
            write_user_settings(user_path, env_text)
        notes = (
            write_workspace(folder, None, f"the user settings file, `{user_path}`")
            if samples
            else []
        )
    else:
        settings_path = os.path.join(folder, ".env")
        notes = write_workspace(folder, env_text)

    checked_ok = None
    checkable = save and settings is not None and (settings.has_key or settings.base_url)
    if checkable and not args.no_check:
        checked_ok = run_check(_settings_env(settings, env), out)
        if not checked_ok:
            where = "" if scope == USER_SCOPE else " in that folder"
            print(
                f"Your settings are saved in {settings_path}. Fix them as described, "
                f"then run certo check{where}.",
                file=out,
            )
        print(file=out)

    if scope == USER_SCOPE:
        if save:
            print(f"Saved your settings for all projects in {settings_path}", file=out)
        else:
            print(
                f"Kept your settings in {settings_path}; your new answers were not saved.", file=out
            )
    if samples:
        shown = folder.rstrip("/") + "/"
        print(f"Created {shown}", file=out)
        if scope == FOLDER_SCOPE:
            print("  .env          your settings (not committed to git)", file=out)
        print("  tasks/        sample tasks to try", file=out)
        print("  README.md     what to do next", file=out)
        for note in notes:
            print(note, file=out)
        if shutil.which("node") is None:
            print(
                "\nThe browser games (space-rocks, mazeman, invaders) need Node 18 or newer, "
                "which isn't installed here. Start with Wordle or Hanoi.",
                file=out,
            )
    elif blocked and scope == USER_SCOPE and not args.no_samples:
        print(
            f"Skipped the sample folder: {blocked} The settings don't need it.",
            file=out,
        )
    if save and settings is None:
        print(
            f"\nNo terminal, so nothing was asked: {settings_path} has no model set yet. "
            "Open it and uncomment the lines for your provider.",
            file=out,
        )
    elif (
        save and not settings.has_key and settings.provider.id != "ollama" and not settings.base_url
    ):
        print(
            f"\nNo API key yet. Open {settings_path} and paste it after CERTO_LLM_API_KEY=.",
            file=out,
        )

    ran_sample = None
    if ask and samples and checked_ok is True and run_sample is not None:
        try:
            ran_sample = _offer_sample(prompter, folder, settings, run_sample)
        except Cancelled:
            ran_sample = None

    print("\nNext:", file=out)
    if samples and os.path.abspath(folder) != os.getcwd():
        print(f"  cd {folder}", file=out)
    if checked_ok is not True:
        print("  certo check", file=out)
    if samples and not ran_sample:
        print("  certo tasks/wordle.md --project wordle", file=out)
        print("      builds the Wordle sample; every file in tasks/ works the same way", file=out)
    if ran_sample:
        print(f"  open projects/{ran_sample.project}/ to see what the agent built", file=out)
    if samples:
        print(f"  certo {_OWN_TASK_EXAMPLE} --project todo", file=out)
        print("      builds your own project: describe it in quotes, or in a file", file=out)
        print("  Each project lands in projects/<name>/, the name given by --project.", file=out)
    if scope == USER_SCOPE:
        print(
            '\nYou can now run certo "<task>" in any project folder: the settings apply '
            "to every folder on this computer.",
            file=out,
        )
    return 0


# The task shown under "Next" for building your own project.
_OWN_TASK_EXAMPLE = '"A command-line to-do list in Python, with tests"'

# Measured first Wordle runs: 4m03s on a cloud model (gpt-5.6-luna,
# docs/benchmark/first-run-0.1.19.md); 9m28s, 11m49s and 15m04s on
# qwen3.8:27b over Ollama (2026-10-20). The other samples, once each on
# claude-sonnet-5-5 (2026-10-21), all verified: hanoi 37s, space-rocks
# 1m41s, invaders 1m38s, mazeman 2m34s; and once each on qwen3.8:27b over
# Ollama with a 1200s call timeout (2026-10-22), all verified: space-rocks
# 8m39s, hanoi 20m13s, invaders 27m26s, mazeman 41m09s (past the 30-minute
# budget; verified by the check after it). No cost figure is quoted: one
# measurement isn't one.
_SAMPLE_TIME_CLOUD = "a few minutes"
_SAMPLE_TIME_LOCAL = "10 to 40 minutes: Wordle and space rocks the least, mazeman the most"


@dataclass(frozen=True)
class Sample:
    """A sample task in `starter/tasks/`, as the menu offers it."""

    file: str
    project: str
    label: str
    needs_node: bool = False


# The menu's order. Measured times are above.
SAMPLES = (
    Sample("wordle.md", "wordle", "Wordle in the terminal (Python)"),
    Sample("hanoi.md", "hanoi", "Tower of Hanoi in the terminal (Python)"),
    Sample(
        "space-rocks.md", "space-rocks", "Space rocks: a ship shooting rocks, in the browser", True
    ),
    Sample("mazeman.md", "mazeman", "Mazeman: a maze chase with ghosts, in the browser", True),
    Sample(
        "invaders.md", "invaders", "Invaders: a cannon against an alien fleet, in the browser", True
    ),
)


def _offer_sample(
    prompter: Prompter,
    folder: str,
    settings: Settings,
    run_sample: Callable[[str, Sample], int],
) -> Sample | None:
    """Ask which sample task to run now; the one that ran, or None."""
    local = settings.provider.id == "ollama"
    took = f"A sample takes {_SAMPLE_TIME_LOCAL}." if local else f"Each takes {_SAMPLE_TIME_CLOUD}."
    cost = (
        "A run is free on your local model."
        if local
        else "A run uses your model credits; Certo prints the cost at the end."
    )
    where = os.path.join(folder.rstrip("/"), "projects")
    prompter.say(
        f"\nYou can run a sample task now. It is built in {where}/<name>/.\n"
        f"{took} {cost}\n"
        "How good the result is depends on your model: a smaller or local model may\n"
        "build a plainer game, or one whose tests fail. The verdict at the end says which."
    )
    # The browser games' tests need Node; without it, they aren't offered
    # (the Node notice above already said so).
    offered = [s for s in SAMPLES if not s.needs_node or shutil.which("node")]
    choice = prompter.choose("Which one?", [s.label for s in offered] + ["Not now"])
    if choice >= len(offered):
        return None
    prompter.say()
    run_sample(folder, offered[choice])
    return offered[choice]


def run_sample_task(folder: str, sample: Sample = SAMPLES[0]) -> int:
    """A sample task, as a normal run from the sample folder, in its own
    process (its output and Ctrl-C work as for any run)."""
    task = f"tasks/{sample.file}"
    command = [sys.executable, "-m", "certo", task, "--project", sample.project]
    try:
        return subprocess.run(command, cwd=folder, check=False).returncode
    except KeyboardInterrupt:
        return 130


def _folder_blocked(folder: str, force: bool) -> str | None:
    """Why `init` mustn't write into FOLDER, or None when it may."""
    if force:
        return None
    if os.path.exists(os.path.join(folder, ".env")):
        return f"{folder}/.env already exists. Use --force to replace it."
    if _folder_has_files(folder):
        return f"{folder} is not empty. Use --force to write into it anyway."
    return None


def _ask_scope(prompter: Prompter) -> str:
    index = prompter.choose(
        "Save these settings for:",
        ["All projects on this computer (recommended)", "This folder only"],
    )
    return (USER_SCOPE, FOLDER_SCOPE)[index]


def _want_samples(
    args: argparse.Namespace, prompter: Prompter, ask: bool, blocked: str | None
) -> bool:
    if args.no_samples or blocked:
        return False
    if not ask:
        return True
    return prompter.confirm("Create a folder with sample tasks to try?")
