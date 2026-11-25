# Squirrel

Squirrel is a local, evidence-first playtesting bot for [Traveler](https://github.com/akodoreign/Traveler).
It follows quest markers, records blockers, exercises side quests and conversation choices, and queues minigames.
An Ollama model advises the runner and reviews dialogue and exposition. Findings are observations, not proof that
every path, choice, or game has been tested.

This is currently **Traveler-specific**, not a generic game-testing framework. The game and its test hooks are not
included in this repository. Squirrel uses the game's player-facing interactions and saves, plus explicitly assisted
testing: elevated party levels, Auto Battle, and minigame win-mode self-play. It labels assisted results; they do not
establish normal-difficulty or manual-input coverage. Conversation notes may suggest staging changes but do not edit
game code or dialogue.

## Requirements

- Windows, Python 3.10 or later, and a compatible Traveler checkout containing the native `rpgcobo.exe` and
  `RokuganChase.sk` test hook. The engine and hook must come from the Traveler installation; this repository
  does not install or build them.
- [Ollama](https://ollama.com/) running locally, with an available model. The existing setup uses the
  `squirrels:latest` alias based on `qwen3.6:35b-a3b`; the large model requires substantial memory.
- An available engine profile. Do not run another Squirrel scheduler against the same engine, save slots, or output
  directory at the same time. The runner creates engine temporary files and uses save slots 90 and 91.

## Setup and run

In PowerShell, from this repository:

```powershell
$env:SQUIRRELS_TRAVELER_ROOT = 'C:\path\to\Traveler'
$env:SQUIRRELS_MODEL = 'squirrels'
python -E tools\squirrel_loop.py --minutes 60
```

Set `SQUIRRELS_MODEL` to another locally installed Ollama model to use it instead. The loop uses one game window
and continues until stopped. On a new output directory it creates a fresh queue for the supported minigames.
The `--minutes` value is the per-run time budget, not the lifetime of the loop. Side-quest runs get twice that budget.
If the runner cannot start or the model is unavailable, the scheduler stops rather than counting a failed launch as
completed testing. Check the `orchestrator_w1.txt` log in the output directory before restarting it.

Output defaults to `runtime\` in this repository, which is ignored by Git. Set `SQUIRRELS_OUTPUT_ROOT` to an
absolute path to use a different directory. It contains `STATUS.md`, scheduler state, queued games, playtest logs,
notes, and learned walking hints. The game engine also stores temporary files and saves in the Traveler engine
directory. These files can contain spoilers and local paths; review them before sharing.

For a one-off run, use `python -E tools\markerchase.py games --only 6 --minutes 60 --windows 1 --engine main`.
Modes include `story`, `sidequests`, `conversations`, and `games`; the road indices are listed in `markerchase.py`.
Start the scheduler or a one-off run, not both against the same engine.

## Continuing existing progress

The new repository starts with separate, empty runtime data; it does not automatically take over an existing run.
Stop the old scheduler and game first, then set `SQUIRRELS_OUTPUT_ROOT` to the existing chase output directory.
Keep the same Traveler engine directory and its saves and snapshots. If applicable, copy the old
`tools\squirrels_walking_policy.py` into that output directory as `squirrels_walking_policy.py` so learned walking
hints are available to the new checkout. Back up the data before migrating. Use `--adopt` only when recovering an
interrupted job whose log should be reconciled; completed and blocked results remain evidence-based.

## Tests

The Python tests do not launch the game or contact Ollama:

```powershell
python -E -m unittest discover -s tools -p 'test_*.py'
```
