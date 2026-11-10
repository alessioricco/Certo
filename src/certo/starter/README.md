# Certo workspace

Made by `certo init`. Run every command below from this folder.

## 1. Check your settings

```bash
certo check
```

Your model settings are in SETTINGS_FILE. `certo check` shows where each
setting comes from, then makes one small call to your model and confirms it
can call tools, which Certo's agent needs. If it reports a problem, fix the
settings as it says and run it again. To switch provider later, comment out
the two active lines in that file and uncomment the two for the provider
you want.

## 2. Run a task

```bash
certo tasks/wordle.md --project wordle
```

A task is a plain text file saying what to build. Open `tasks/wordle.md`
to see one, then write your own the same way. The other samples:

- `tasks/hanoi.md`: the Tower of Hanoi in the terminal, in Python;
- `tasks/space-rocks.md`: a ship shooting space rocks, in the browser;
- `tasks/mazeman.md`: a maze chase with ghosts, in the browser;
- `tasks/invaders.md`: a cannon against a marching alien fleet, in the
  browser.

The browser games need Node 18 or newer, for their tests.

Four bigger samples are written in **milestones**: each milestone is
built and checked before the next one starts, and if one fails, Certo
stops there and `certo --resume --project NAME` continues from it. They
are much bigger than the samples above, so a run takes much longer and
uses more model credits:

- `tasks/sky-hopper.md`: a side-scrolling platform game with parallax
  backgrounds, in the browser;
- `tasks/iron-horizon.md`: a first-person 3D tank game in wireframe, in
  the browser, with no 3D library;
- `tasks/team-board.md`: a team task board web app, with accounts, roles,
  a SQLite database and drag-and-drop cards, in Python;
- `tasks/star-swarm.md`: a fixed shooter with a diving enemy formation,
  in the browser, built to production quality in 10 milestones; the
  agent chooses the tech stack itself in the first one.

```bash
certo --milestones tasks/team-board.md --project team-board
```

## 3. Find the result

Each project lands in its own folder under `projects/`, here
`projects/wordle/`. The last lines Certo prints are the verdict:

```
Verification: verified
```

`verified` means Certo re-ran the project's own tests itself, after the
agent said it was done, and they passed. Then play:

```bash
cd projects/wordle
python3 wordle.py
```

## Good to know

- **The model matters.** The same task can come out quite differently on
  different models: a smaller or local model may build a plainer game, or
  one whose tests fail. The verdict says whether the tests passed, not how
  polished the game is.
- **Cost.** A run with a cloud model (OpenAI, Anthropic, Gemini) uses your
  model credits. Certo prints the tokens used and the cost at the end of
  every run, under "Run summary".
- **Checking an existing repo.** `certo verify path/to/repo` runs Certo's
  verification (the project's own tests and build) with no agent and no
  model, so it costs nothing.
- **Ollama.** On a machine with less than 24 GB of GPU memory, Ollama's
  default context window is 4096 tokens. That's too short for an agent: the
  model loses the start of the task and wanders. Start the server with a
  larger one, for example `OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or
  move the context slider in the Ollama app's settings. `ollama ps` shows
  the context a loaded model got.

The full documentation: https://github.com/alessioricco/certo/blob/main/docs/README.md
