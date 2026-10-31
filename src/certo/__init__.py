"""Certo — a coding-agent harness built on the OpenHands SDK.

Implementation is built out per docs/history/SPEC.md. Modules to add:
config, llm, tools, agent, runner, cli, and custom_tools/.
"""

import os

# The SDK prints a startup banner when `openhands.sdk` is first imported.
# Every entry point (certo, certo-server, certo-admin, python -m certo)
# imports this package first, so set it here, before any SDK import.
# setdefault: an explicit OPENHANDS_SUPPRESS_BANNER=0 still shows it.
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
# LiteLLM's import runs `load_dotenv()` with no path unless LITELLM_MODE is
# set to something other than DEV. python-dotenv then searches upward from
# LiteLLM's own install folder, not the current one: from a venv inside a
# checkout that finds the repo's .env, and from `uv tool install` it can
# find a ~/.env. Those values then win over the current folder's .env,
# which config.py loads without overriding. Certo reads only ./.env.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

__version__ = "0.1.27"
