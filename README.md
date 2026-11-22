# Monster Hunter Online research snapshot

I tried to finish the offline revival, but real life came up and I had to pause. Here’s what I found and what I worked on myself.

- **Solo hunts needed their own tuning.** I built a small Python prototype that scales monster health and damage by party size. I also tried a solo progression policy that lets you repeat hunts and craft with the materials you’ve earned. The settings here are values I chose for the prototype.
- **Movement needed a consistent way to find the ground.** I wrote a height-grid lookup that interpolates between samples and clamps queries to the map edge. I used it in a fixed-tick monster AI prototype to keep the actor grounded as it moves.
- **Comparing a recorded hunt with a replay exposed movement bugs.** Part of the movement code was treating backward and sideways motion as forward motion, and animation playback was using a fixed rate. I worked on preserving movement direction and playback timing.
- **Headless tests only took me so far.** They let me check scaling, terrain, and state transitions in isolation. I still had work to do on testing and polishing the complete hunt experience in the game client.

The broader revival built on Arrowgene.MonsterHunterOnline by Sebastian Heinz and its contributors, along with work from the MHO Revival community. This is an unofficial fan research snapshot. The Python examples use synthetic inputs and run with the standard library.

## Run the tests

Use Python 3.11 or newer. From the repository root, set `PYTHONPATH` to `src` for the test run.

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest discover -s tests -v
```

```sh
PYTHONPATH=src python -B -m unittest discover -s tests -v
```
