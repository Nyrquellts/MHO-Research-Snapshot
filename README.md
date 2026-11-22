# Monster Hunter Online research snapshot

I tried to finish the offline revival, but real life came up and I had to pause. Here’s what I found and what I worked on myself.

## What I worked on

- **Combat and solo hunts.** I tried party-size tuning, hitzone damage, part breaks, and status buildup in Python before working through those behaviors in local hunts. The included values are prototype settings. [Gameplay modules](src/mho)
- **Movement and monster behavior.** I built a fixed-tick AI model and a height-grid lookup to keep monsters grounded. Comparing a recorded hunt with a replay exposed lost movement direction, playback timing errors, and attacks that kept restarting. [Movement, combat, and the hunt loop](docs/movement-and-hunts.md)
- **Offline encounters and a C# port.** I used a seeded headless hunt to test how the models worked together, built a turn-based encounter prototype, and ported the terrain, combat, and scaling models to C#. [C# reference models](examples/csharp)
- **Server-side C# work.** I built party and hunt state, fixed-step motion, telemetry, localization, and queueing for the restoration. These standalone excerpts show the parts that can run with synthetic inputs. [Server excerpts](examples/server-excerpts)
- **Progression and rewards.** I worked on player saves, gear skill points, crafting, quest selection, and seeded reward rolls. In the larger project I checked that leaving town, settling a hunt, and returning with rewards worked together. [Gameplay tests](tests)
- **Trace diagnostics.** I built tools to reduce repeated events, compare two runs, and find the earliest difference worth investigating. The motion checks measure turns, tracking error, stalls, and flight from sample traces. [Comparing recorded runs](docs/trace-diagnostics.md)
- **Localization.** I built checks for catalogs, plural forms, placeholders, writing direction, and font coverage. The font audit explained why a translated line could still be unreadable in the game. [Localization and font coverage](docs/localization-and-fonts.md)
- **Build and runtime checks.** I added fingerprints for source, data, and generator dependencies. I also split the simulation and movement update clocks in the runtime profile and summarized tick timing, zone stages, and resource use from logs. [Build stamp module](src/mho/buildstamp.py)

The broader revival built on Arrowgene.MonsterHunterOnline by Sebastian Heinz and its contributors, along with work from the MHO Revival community. This is an unofficial fan research snapshot. The Python examples use synthetic inputs and run with the standard library.

[Inventory of the public snapshot and the rest of the local project](docs/project-inventory.md)

## Try the headless encounter

From the repository root, set `PYTHONPATH` to `src` as shown below, then run the same seeded encounter in Python.

```sh
python -c "from mho.hunt import simulate_solo_hunt; hunt = simulate_solo_hunt(seed=7); print(hunt.outcome, hunt.ticks, hunt.drops)"
```

## Run the tests

Use Python 3.11 or newer. The build-stamp tests use Git when it is installed. From the repository root, set `PYTHONPATH` to `src` for the test run.

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest discover -s tests -v
```

```sh
PYTHONPATH=src python -B -m unittest discover -s tests -v
```
