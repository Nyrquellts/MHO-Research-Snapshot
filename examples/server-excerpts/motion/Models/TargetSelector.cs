// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

public readonly struct TargetCandidate
{
    public TargetCandidate(int id, Vector3 position, int region, bool down, float threat)
    {
        Id = id;
        Position = position;
        Region = region;
        Down = down;
        Threat = threat;
    }

    /// <summary>The hunter's actor id.</summary>
    public int Id { get; }

    public Vector3 Position { get; }

    /// <summary>The region the hunter is in (-1: unknown).</summary>
    public int Region { get; }

    /// <summary>Fainted: a monster turns to one who is still up.</summary>
    public bool Down { get; }

    /// <summary>Caller-defined recent threat score.</summary>
    public float Threat { get; }
}

/// <summary>Rank eligible targets by distance, threat, and the current target's dwell time.</summary>
public static class TargetSelector
{
    /// <summary>Seconds a target is kept before a better one may take over (a down or missing target goes at once).</summary>
    public const double MinDwell = 2.0;

    /// <summary>How much better (in metres of reach) a challenger has to be than the current target.</summary>
    public const float SwitchMargin = 4f;

    /// <summary>Metres of reach a hunter gains per point of the monster's health they took lately.</summary>
    public const float ThreatMetres = 6f;

    /// <summary>The most points of threat that count (5 points = 30 m).</summary>
    public const float ThreatCap = 5f;

    /// <summary>Added to a hunter who is down: after everyone who is up.</summary>
    public const float DownPenalty = 100000f;

    /// <summary>How good a hunter is as a target: lower is better.</summary>
    public static float Score(Vector3 monster, in TargetCandidate hunter)
    {
        float dx = hunter.Position.X - monster.X, dy = hunter.Position.Y - monster.Y;
        float distance = MathF.Sqrt(dx * dx + dy * dy);
        float threat = float.IsFinite(hunter.Threat) ? Math.Clamp(hunter.Threat, 0f, ThreatCap) : 0f;
        return distance - threat * ThreatMetres + (hunter.Down ? DownPenalty : 0f);
    }

    /// <summary>Whether a hunter is in reach of a monster that lives in <paramref name="monsterRegion"/> (-1: it is tied to none).</summary>
    public static bool SameRegion(int monsterRegion, int hunterRegion) => monsterRegion < 0 || hunterRegion < 0 || monsterRegion == hunterRegion;

    /// <summary>The index in <paramref name="hunters"/> of the hunter the monster goes after; -1 when there are none.</summary>
    /// <param name="currentId">The hunter it goes after now (-1: none).</param>
    /// <param name="heldFor">Seconds it has had that target.</param>
    public static int Pick(Vector3 monster, int monsterRegion, int currentId, double heldFor, ReadOnlySpan<TargetCandidate> hunters)
    {
        if (hunters.Length == 0)
            return -1;
        // hunters out of the monster's region are out of reach; when nobody is in it the monster is still told of one, and stands down by its own rule
        bool anyInRegion = false;
        for (int i = 0; i < hunters.Length && !anyInRegion; i++)
            anyInRegion = SameRegion(monsterRegion, hunters[i].Region);

        int best = -1, current = -1;
        float bestScore = float.PositiveInfinity, currentScore = float.PositiveInfinity;
        for (int i = 0; i < hunters.Length; i++)
        {
            if (anyInRegion && !SameRegion(monsterRegion, hunters[i].Region))
                continue;
            float score = Score(monster, hunters[i]);
            if (!float.IsFinite(score))
                score = float.MaxValue;
            if (score < bestScore)
            {
                best = i;
                bestScore = score;
            }
            if (hunters[i].Id == currentId)
            {
                current = i;
                currentScore = score;
            }
        }
        if (best < 0)
            best = 0;
        if (current < 0 || current == best)
            return best;
        // the current target stays unless it is down and the best is not, or the best is clearly better and the current target has been held long enough
        bool downNow = hunters[current].Down && !hunters[best].Down;
        bool clearlyBetter = heldFor >= MinDwell && currentScore - bestScore >= SwitchMargin;
        return downNow || clearlyBetter ? best : current;
    }
}
