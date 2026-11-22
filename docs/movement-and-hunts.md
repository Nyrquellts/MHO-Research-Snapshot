# Movement, combat, and the hunt loop

Once I had a local hunt running, I spent most of my time on what happened between leaving town and getting back. I wanted to see the monster move and attack properly, make a dodge count, and finish a hunt without losing the rewards or getting stuck in the map. I used actual client sessions to find problems, then replayed recordings and exercised the server to see which changes held up.

## What I saw in the game

In an October 4 client session I fought for about 85 seconds and then abandoned the hunt. The client showed the supply notices and the recording gave me movement and combat to work with. Capture, a tail cut, a kill, and a low-health retreat were still unobserved in that run.

In later client sessions I could see attacks stutter even after the first timing changes. The trace showed the same attack starting and getting cut off by idle over and over. In one stretch it restarted around 30 times a second. I also found a monster that kept playing its walk at a region boundary with almost no change in position. That stall lasted about four and a half seconds. The motion trace let me pin down both problems. I kept the cases where movement was meant to jump from one region to another out of the ordinary movement measurements.

## What I changed in movement and animation

- I made animation playback and movement agree about speed. A clip already moving the body through its animation had to advance on its own clock. Ordinary movement had to respect the playback speed and keep its direction, including backwards steps. A speed change had been getting lost along one of those paths.
- I put one part of the simulation in charge of position and facing for each kind of movement. That gave me a way to diagnose when steering, a turn, or an animation was trying to move the same monster twice. I tested a fixed 60 Hz simulation with a separate cadence for updates sent to the client. The earlier 165 Hz behavior stayed available as a reference.
- I let an attack finish its animation before idle could take over, and gave a knockdown its own transition into recovery. I added evidence for starts, interruptions, and repeated idle updates so I could see which part actually ran. Full airborne hit reactions still had gaps.
- I addressed two different terrain problems. An eligible monster could finish a region transition after it stalled at the boundary, and a flying monster could keep its height through takeoff, hover, and landing. The flight work made the vertical part of the animation count when the server placed the monster. Automated checks exercised those changes. The final visual behavior in the client remains open.
- I bounded a charge that overshot the hunter while keeping its recovery sequence. The original recording covered about 86 m in its longest five-second sample for that case. The revised charge and recovery covered about 47 m from start to finish in the October 4 replay.

The October 4 motion replay checked 24 recorded runs at 587 sample times. The largest position discrepancy against the source motion samples was under one millimeter under the replay's linear interpolation. The recording was too sparse to judge whether the feet stayed planted between frames. The replay checked the movement calculation, and a smooth-looking animation still needed a client run.

## What I changed in combat

I worked on matching a contact to the attack that actually caused it, then keeping that result consistent while the dodge was resolved. The October 4 replay reproduced all 16 recorded perfect evades and all 28 recorded ordinary dodges in its cases. It also matched the recorded attack identity and damage assignment for all 85 contacts checked. This gave me a way to catch a regression with an old recording even when I could only test the current build headless.

I also separated health changes from hit reactions in the evidence. Some reactions could occur without a loss of health. Exact reaction timing and the original defense formula were still uncertain, so my damage and defense behavior was an approximation. Other changes carried the hunter's last known weapon-gauge state through updates, kept combat HUD state available while a threat was active, improved aim information, and made part breaks easier to track. The later server work covered pieces of those behaviors. Ranged actions, flight transitions, and the HUD and gauge changes still needed another client pass.

## Getting through a hunt

I tied departure, arrival, the active hunt, results, cleanup, and the trip back to town into one lifecycle. The checks covered victory and defeat, timer expiry, reconnect, abandoning a hunt, and returning with rewards. I also checked the Free Hunt picker against what the server actually opened. All 139 distinct selections in that check opened their matching rooms.

- **Supplies and capture.** The staged server granted the hunt supplies, refused a duplicate claim, and completed a capture in both trap and tranquilizer orders. Each run settled once. The supply-box display is a separate client check.
- **Part breaks and carving.** The staged checks covered severing, the carved piece, the reward reaching inventory, and exhaustion of the carve allowance for 24 out of 24 tested monster families. Those runs used relaxed combat settings. They measured the server flow across those families, with normal weapon pace and visible part breaks left for client testing.
- **Hunt timer.** In two later staged runs with normal combat limits, successful hunts advertised a 60-second carve window and returned after about 65 seconds with the grace period included. The ordinary run still allowed three carves at 55 seconds. Requesting results early settled the rewards and the original return deadline held.
- **Retreat and recovery.** A staged hunt followed an injured monster across a region boundary to its resting area. The recording showed a roughly four-minute sleep, 179 healing updates, and a completed wake. The server sequence was verified. The player's view of the retreat, sleep, and wake remains unverified.

The October 4 gate also covered 62 solo levels, 31 party levels, 11 simultaneous fights, 1,500 connection endings, and 139 malformed-input cases. Those were staged checks, alongside checks for progression, crafting, reconnect, and deployment consistency. The later 60 Hz work had separate regression checks against the baseline, which already had failures. A clean pass on the entire later build and a full playthrough with every later repair enabled remain open.

## Where I left it

I got far enough to exercise the hunt from selection through results and make specific movement and combat fixes against recordings. The biggest gaps left were things I needed to see and feel in the actual game. Those include foot planting, collision timing on rendered frames, airborne hit reactions, ranged actions, and how all the later repairs behave together through a full hunt. Real life came up before I could finish that work.
