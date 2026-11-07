# OpenAI, Claude and Gemini

This guide shows how to use a cloud model: OpenAI, Anthropic (Claude),
Google Gemini, DeepSeek, Kimi, or any other provider that LiteLLM
supports. It also shows
how to switch provider and how to try another model for one run only.

## Set up with `certo init`

```bash
certo init --provider anthropic     # or: openai, gemini, other
```

`--provider` skips the first question. `init` then asks for the model and
the API key. The default models are:

| Provider | `--provider` | Default model | Key variable it can reuse |
|---|---|---|---|
| OpenAI | `openai` | `openai/gpt-6.1-sol` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `anthropic/claude-sonnet-5-5` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini` | `gemini/gemini-3.8-flash` | `GEMINI_API_KEY` |
| DeepSeek | `deepseek` | `deepseek/deepseek-flash` | `DEEPSEEK_API_KEY` |
| Kimi (Moonshot AI) | `moonshot` | `moonshot/kimi-k3.1-pro` | `MOONSHOT_API_KEY` |

With DeepSeek, the run summary may show the cost as unknown: LiteLLM's
price list doesn't know the name `deepseek-flash` yet.

You can type any model id. If you type it without the provider prefix,
`init` adds it: `claude-sonnet-5-5` becomes `anthropic/claude-sonnet-5-5`.

**Reusing a key you already exported.** If the provider's own variable
(for example `ANTHROPIC_API_KEY`) is set in your shell, `init` offers to use
it. The settings file then refers to the variable instead of copying the
key:

```bash
CERTO_LLM_API_KEY=${ANTHROPIC_API_KEY}
```

That variable must then be exported wherever you run Certo.

## Set up by hand

Certo needs two settings. Put them in your shell, in a `.env` file in the
folder where you run `certo`, or in `~/.config/certo/.env` for every folder:

```bash
CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5
CERTO_LLM_API_KEY=sk-ant-...
```

The part before the `/` selects the provider. Then run `certo check`.

## Other providers

`CERTO_LLM_MODEL` takes any [LiteLLM model id](https://docs.litellm.ai/docs/providers),
so many more providers work the same way: the part before the `/` is
the provider, as in LiteLLM's list. With `certo init`, choose **Other**
and type the id. The model must support
tool calling (also called function calling): Certo's agent works only
through tool calls. `certo check` tells you if it doesn't.

Model ids change over time. If one stops working, check the provider's
model list and LiteLLM's documentation.

## Switch provider

Change only `CERTO_LLM_MODEL` (and the key, if the provider is different).
No code change is ever needed. [Provider swap in 0.1.19](../benchmark/provider-swap-0.1.19.md)
shows one task run this way with an OpenAI and an Anthropic model.

The settings file `certo init` writes has your active lines first, then
every other provider's two lines commented out with `#`. To switch, comment
out your active lines and remove the `#` from two others. Then run
`certo check`.

## Try another model for one run

Flags change the model for one run only. Your settings file is not touched.
They are enough on their own: you do not need `CERTO_LLM_MODEL` (or a key)
already set when the flags supply them.

```bash
certo "Add input validation to the signup form" --model openai/gpt-5.6-terra --api-key "$OPENAI_API_KEY"
certo "Try a local model" --model ollama/qwen3.8:27b --base-url http://localhost:11434
```

| Flag | Replaces, for this run |
|---|---|
| `--model` | `CERTO_LLM_MODEL` |
| `--api-key` | `CERTO_LLM_API_KEY` |
| `--base-url` | `CERTO_LLM_BASE_URL` |
| `--reasoning-effort` | `CERTO_LLM_REASONING_EFFORT` |

A flag you leave out keeps its configured value. A cloud model still needs
a key (flag or settings); a local model with `--base-url` needs no key.
This is useful to compare two models on the same task; to run one task on
a whole list of models, see [Compare models on one task](compare-models-on-a-task.md).
Note that `--api-key` puts the key in your shell history; prefer a variable
as in the example.

## Reasoning effort

`CERTO_LLM_REASONING_EFFORT` (or `--reasoning-effort`) asks the model to
think more or less before answering. Common values: `none`, `minimal`,
`low`, `medium`, `high`, `xhigh`, `max`. Certo passes the value through to
the provider and doesn't check it against a fixed list.

- Left empty, the default is `high`.
- `none` or `off` sends no reasoning setting at all.

More effort usually means better results on hard tasks, slower runs and
higher cost.

## Cost

Every run ends with a summary of tokens and cost. Prices come from
LiteLLM's model list, which is installed with Certo. A model newer than
your LiteLLM still works, but its cost shows as `unknown`. The default
models of `certo init` need LiteLLM 1.105 or newer; upgrade with
`uv tool upgrade certo` (or `pip install -U litellm`). See
[Run records and costs](run-records-and-costs.md), and
[Keep costs down](keep-costs-down.md) to spend less.

## Related

- Every setting: [Configuration](../reference/configuration.md)
- Problems with keys, credit or tool calling: [Troubleshooting](../troubleshooting.md)
- Let Certo choose between several models: [Pick models automatically](pick-models-automatically.md)
