# What is in the snapshot

I worked on the standalone simulations, the tools I used to investigate problems, and a larger local restoration. This page records which parts are represented here and where the rest of the work sits.

## Standalone work

| Part | What I worked on |
| --- | --- |
| Encounter prototypes | A seeded, fixed-tick hunt simulator that combines terrain, AI, combat, status, and rewards. I also made a turn-based prototype with separate action and output callbacks. |
| C# reference models | A console project that ports the terrain lookup, hit-zone and part damage, and party-size scaling to C#. |
| Server-side C# excerpts | Party and hunt state, request replay, rank thresholds, fixed-step motion, telemetry, localization, and bounded background writers. The patches were reviewed against the imported server baseline. [Server excerpts](../examples/server-excerpts) |
| Motion analysis | Tools for checking turn rates, animation paths, movement update intervals, height changes, stalls, flight, and whether a dodge leaves the expected trace. The root-motion sampler keeps the source key times and endpoints. |
| Runtime and build checks | A profile parser for the fixed-step experiments, an offline log summarizer for timing and health measurements, and a source fingerprint that only follows the definitions and dependencies a generator needs. |
| Progression and localization | Player saves, equipment skills, crafting, quests, rewards, catalog checks, and font coverage. |

## Work still in the local project

| Part | What is still local |
| --- | --- |
| Runnable restoration | The integrated Arrowgene-based C# server, its network and multiplayer integration, and the server-based replay and deployment harnesses. Those integration patches depend on upstream code, the client, or game-derived files. The independent server logic is represented in the excerpts above. |
| Game client and compatibility | The launcher, client patch and protection work, protocol bridges, and game-format readers. Those are tied to a specific client or to separately licensed community tools. |
| Named boss prototypes | The browser and terminal Golden Jie Lung experiments and the later asset-pack branch. The browser version includes the game's monster stats, moves, and named rewards. The asset-pack branch works from the original game's assets. |
| Game-derived content | The map, item, animation, move, behavior, and font data, plus translations of existing game text and the client archives. |
| Captures and local run state | The recordings, packet and motion fixtures, profiling logs, saved database, and local build artifacts. The public notes preserve aggregate observations and the tests use synthetic inputs. |
| Later branch experiments | Follow-up work on companion AI, who drives monsters in hosted hunts, and later movement and flight fixes. The implementations and evidence are tied to the client, the restoration server, and private recorded sessions. |

The local work includes client observations and staged server checks. The public summary keeps those distinct because a passing replay or server check covers a different part of the behavior from a playthrough. [Movement, combat, and the hunt loop](movement-and-hunts.md)
