# Original server-side experiments

These are standalone C# excerpts from the MHO restoration’s changes to its Arrowgene-based server. I worked on party and hunt state, the simulation clock, movement, telemetry, and keeping a slow writer from holding up a simulation. Each example uses local, synthetic inputs.

| Area | Included work |
| --- | --- |
| Gameplay | Party state and countdowns, hunt outcomes and duplicate-faint handling, a bounded retry ledger, rank thresholds supplied by the caller, and tallies for hunt, field, town, and progression events. [Gameplay source](gameplay) |
| Motion | Fixed-step scheduling, sampled position prediction, target and turn selection, tracking which code controls movement, slope checks, and wall sliding. The slope and wall excerpts came from follow-up branches. [Motion source](motion) |
| Infrastructure | Build fingerprints, locale rules and catalogs, a bounded in-memory telemetry ring, and an ordered cleanup runner. [Infrastructure source](infrastructure) |
| Queueing | An ordered background writer with a byte budget and stall checks, bounded dispatch counters, and per-category log preview budgets. [Queueing source](transport) |

## Run the checks

Use the .NET 8 SDK from the repository root. The four projects use the .NET standard libraries.

```sh
dotnet run --project examples/server-excerpts/gameplay/GameplayChecks.csproj -c Release
dotnet run --project examples/server-excerpts/motion/MotionResearch.csproj -c Release
dotnet run --project examples/server-excerpts/infrastructure/Infrastructure.csproj -c Release
dotnet run --project examples/server-excerpts/transport/TransportChecks.csproj -c Release
```

## Source and license

The patch review screened 241 non-merge server changes after the Arrowgene import, including 49 changes on other local branch histories, and checked 31 merge diffs separately. The selected implementations were traced to their introduction and follow-up changes in the restoration project. The upstream server project was created by Sebastian Heinz and the Arrowgene contributors.

These excerpts were adapted on November 22, 2026. The adaptations isolate the core logic from the original server, supply caller-defined parameters in place of game-specific inputs, and use synthetic examples for the checks. The source in this directory is distributed under the GNU Affero General Public License, version 3, as in the server project. [License text](LICENSE.md) · [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html)
