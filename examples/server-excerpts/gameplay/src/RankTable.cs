// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>Compute experience levels and ranks from supplied thresholds.</summary>
public sealed class RankTable
{
    private readonly long[] _levelStart;     // total experience at which level L begins (index L; index 1 = 0)
    private readonly long[] _rankStart;       // total points at which hunter rank N begins (index N; index 0 = 0)

    public RankTable(IReadOnlyList<int> expToNext, IReadOnlyList<long> pointsForRank)
    {
        expToNext ??= Array.Empty<int>();
        pointsForRank ??= Array.Empty<long>();
        _levelStart = new long[expToNext.Count + 2];
        for (int level = 1; level <= expToNext.Count; level++)
            _levelStart[level + 1] = _levelStart[level] + Math.Max(0, expToNext[level - 1]);
        _rankStart = new long[pointsForRank.Count + 1];
        for (int rank = 1; rank <= pointsForRank.Count; rank++)
            _rankStart[rank] = pointsForRank[rank - 1];
    }

    /// <summary>The highest character level the table has a step for (the last row's level: the one nothing is asked of).</summary>
    public int MaxLevel => Math.Max(1, _levelStart.Length - 2);

    /// <summary>The highest hunter rank the table reaches.</summary>
    public int MaxRank => Math.Max(0, _rankStart.Length - 1);

    public bool Empty => MaxLevel == 1 && MaxRank == 0;

    /// <summary>The character level that <paramref name="totalExp"/> experience is: 1 at nothing, then one more for each step of the table, never past <see cref="MaxLevel"/>.</summary>
    public int LevelOf(long totalExp)
    {
        if (totalExp <= 0)
            return 1;
        int level = 1;
        while (level < MaxLevel && _levelStart[level + 1] <= totalExp)
            level++;
        return level;
    }

    /// <summary>Where <paramref name="totalExp"/> stands inside its level: the experience already earned towards the next (<paramref name="into"/>) and what the whole step is
    /// (<paramref name="step"/>, 0 at the top level).</summary>
    public int Progress(long totalExp, out long into, out long step)
    {
        int level = LevelOf(totalExp);
        into = Math.Max(0, totalExp - _levelStart[level]);
        step = level < MaxLevel ? _levelStart[level + 1] - _levelStart[level] : 0;
        return level;
    }

    /// <summary>The total experience at which a level begins (0 for level 1; the table's last for a level past it).</summary>
    public long ExpToReach(int level) => level <= 1 ? 0 : _levelStart[Math.Min(level, MaxLevel)];

    /// <summary>Return the higher of the current level and the earned level.</summary>
    public int LevelFor(int characterLevel, long totalExp) => Math.Max(Math.Max(1, characterLevel), LevelOf(totalExp));

    /// <summary>The hunter rank that <paramref name="points"/> hunter-rank points are: 0 below the first step, then one more for each step reached.</summary>
    public int RankOf(long points)
    {
        int rank = 0;
        while (rank < MaxRank && _rankStart[rank + 1] <= points)
            rank++;
        return rank;
    }

    /// <summary>The points at which a hunter rank begins (0 for rank 0).</summary>
    public long PointsToReach(int rank) => rank <= 0 ? 0 : _rankStart[Math.Min(rank, MaxRank)];

    public string Describe() => $"{MaxLevel} character levels ({ExpToReach(MaxLevel)} experience to the top), {MaxRank} hunter ranks";
}
