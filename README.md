# Monster Hunter Online research snapshot

I tried to finish the offline revival, but real life came up and I had to pause. Here’s what I found and what I worked on myself.

## What I worked on

- **Combat and solo hunts.** I tried party-size tuning, hitzone damage, part breaks, and status buildup in Python before working through those behaviors in local hunts. The included values are prototype settings. [Gameplay modules](src/mho)
- **Movement and monster behavior.** I built a fixed-tick AI model and a height-grid lookup to keep monsters grounded. Comparing a recorded hunt with a replay exposed lost movement direction, playback timing errors, and attacks that kept restarting. [Movement, combat, and the hunt loop](docs/movement-and-hunts.md)
- **Progression and rewards.** I worked on player saves, gear skill points, crafting, quest selection, and seeded reward rolls. In the larger project I checked that leaving town, settling a hunt, and returning with rewards worked together. [Gameplay tests](tests)
- **Trace diagnostics.** I built tools to reduce repeated events, compare two runs, and find the earliest difference worth investigating. [Comparing recorded runs](docs/trace-diagnostics.md)
- **Localization.** I built checks for catalogs, plural forms, placeholders, writing direction, and font coverage. The font audit explained why a translated line could still be unreadable in the game. [Localization and font coverage](docs/localization-and-fonts.md)
- **Build verification.** I added fingerprints for source and data so I could check which build produced a result and spot mismatches with the checkout. [Build stamp module](src/mho/buildstamp.py)

The broader revival built on Arrowgene.MonsterHunterOnline by Sebastian Heinz and its contributors, along with work from the MHO Revival community. This is an unofficial fan research snapshot. The Python examples use synthetic inputs and run with the standard library.

## Run the tests

Use Python 3.11 or newer. The build-stamp tests use Git when it is installed. From the repository root, set `PYTHONPATH` to `src` for the test run.

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest discover -s tests -v
```

```sh
PYTHONPATH=src python -B -m unittest discover -s tests -v
```
