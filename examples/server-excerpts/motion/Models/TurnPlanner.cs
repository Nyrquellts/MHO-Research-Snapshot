// SPDX-License-Identifier: AGPL-3.0-only
namespace Mho.Research.Motion;

/// <summary>An authored turn clip with its signed heading change and duration.</summary>
public readonly record struct TurnChoice(string Clip, float Yaw, float Duration)
{
    public static TurnChoice None => new(null, 0f, 0f);
    public bool Found => Clip != null;
}

/// <summary>Pick a measured turn clip close to the desired change of heading.</summary>
public sealed class TurnTable
{
    /// <summary>A heading error up to this is left to the normal steering (the monster turns as it moves).</summary>
    public const float SteeringLimit = 45f;

    /// <summary>How far a clip's turn may be from the turn asked for and still be used (the rest is steered afterwards).</summary>
    public const float MaxMismatch = 45f;

    /// <summary>What counts as a turn clip: its measured root-motion turn.</summary>
    public const float MinTurn = 30f, MaxTurn = 200f;

    public const float MaxDuration = 6f;

    /// <summary>Above this bearing a turn the opposite way round reaches the same heading, so either side's clip will do.</summary>
    private const float AboutFace = 135f;

    private readonly List<TurnChoice> _left = new(), _right = new();

    /// <summary>The turn clips found, counter-clockwise (left) and clockwise (right).</summary>
    public IReadOnlyList<TurnChoice> Left => _left;

    public IReadOnlyList<TurnChoice> Right => _right;

    public int Count => _left.Count + _right.Count;

    public static TurnTable Build(IEnumerable<TurnChoice> candidates)
    {
        TurnTable table = new();
        foreach (TurnChoice clip in candidates)
        {
            if (!clip.Found || !float.IsFinite(clip.Yaw) || !float.IsFinite(clip.Duration)
                || clip.Duration <= 0.05f || clip.Duration > MaxDuration
                || MathF.Abs(clip.Yaw) < MinTurn || MathF.Abs(clip.Yaw) > MaxTurn)
                continue;
            (clip.Yaw > 0f ? table._left : table._right).Add(clip);
        }
        // stable: by size, then the shorter clip, then the name
        Comparison<TurnChoice> order = (a, b) =>
        {
            int c = MathF.Abs(a.Yaw).CompareTo(MathF.Abs(b.Yaw));
            if (c == 0)
                c = a.Duration.CompareTo(b.Duration);
            return c != 0 ? c : string.CompareOrdinal(a.Clip, b.Clip);
        };
        table._left.Sort(order);
        table._right.Sort(order);
        return table;
    }

    /// <summary>The turn to make for a point at <paramref name="bearing"/> degrees from the monster's facing (positive = to its right,
    /// clockwise): the clip whose measured turn is closest to the turn needed, in the
    /// right direction, within <see cref="MaxMismatch"/>. <see cref="TurnChoice.None"/> when the bearing is small enough to steer, or the
    /// monster has no clip for it.</summary>
    public TurnChoice Choose(float bearing)
    {
        if (!float.IsFinite(bearing))
            return TurnChoice.None;
        float need = MathF.Abs(bearing);
        if (need <= SteeringLimit)
            return TurnChoice.None;
        // the turn wanted has the opposite sign of the bearing: a target on the right is reached by turning clockwise (negative yaw)
        List<TurnChoice> same = bearing > 0f ? _right : _left;
        List<TurnChoice> other = bearing > 0f ? _left : _right;
        TurnChoice best = Closest(same, need, TurnChoice.None);
        if (need >= AboutFace)
            best = Closest(other, need, best, minTurn: 150f);
        return best;
    }

    private static TurnChoice Closest(List<TurnChoice> clips, float need, TurnChoice best, float minTurn = 0f)
    {
        float bestGap = best.Found ? MathF.Abs(need - MathF.Abs(best.Yaw)) : float.MaxValue;
        foreach (TurnChoice c in clips)
        {
            if (MathF.Abs(c.Yaw) < minTurn)
                continue;
            float gap = MathF.Abs(need - MathF.Abs(c.Yaw));
            if (gap <= MaxMismatch && gap < bestGap)
            {
                best = c;
                bestGap = gap;
            }
        }
        return best;
    }
}
