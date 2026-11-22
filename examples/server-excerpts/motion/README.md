# Server motion research excerpts

The original motion work grew out of an offline research project based on Arrowgene.MonsterHunterOnline by Sebastian Heinz and its contributors. This folder contains standalone extracts of the project's own C# changes. They use synthetic inputs and the .NET 8 standard library. The server excerpts are distributed under the GNU Affero General Public License version 3.

| Excerpt | What it checks |
| --- | --- |
| `HunterTrack` | Predicts horizontal position between samples, blends in corrections, and clears velocity on stops or jumps. |
| `TargetSelector` | Ranks nearby candidates using region, threat, and a minimum dwell time. |
| `PreciseLoop` | Runs variable or fixed simulation steps against a supplied clock and counts missed or caught-up steps. |
| `MovementOwnership` | Records which movement action is responsible for translation and rotation. |
| `TurnPlanner` | Chooses among supplied turn candidates according to heading, direction, and timing. |
| `TerrainSlope` and `LevelWalls` | Evaluate steps against supplied terrain heights and test sliding against one-sided wall segments. |

The turn planner takes measured clip summaries from the caller. The slope and wall examples take synthetic geometry. The loop's checks use a deterministic clock.

Run the 28 checks with the .NET 8 SDK.

```sh
dotnet run --project MotionResearch.csproj --configuration Release
```
