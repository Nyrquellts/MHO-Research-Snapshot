// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Generic;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>Aggregate caller-supplied combat outcomes by participant type.</summary>
public sealed class HuntFacts
{
    private readonly Dictionary<int, int> _killed = new();
    private readonly Dictionary<int, int> _captured = new();
    private readonly Dictionary<int, int> _broken = new();
    private readonly Dictionary<int, int> _staggered = new();

    public IReadOnlyDictionary<int, int> Killed => _killed;
    public IReadOnlyDictionary<int, int> Captured => _captured;

    public int KilledOf(int monsterId) => _killed.TryGetValue(monsterId, out int n) ? n : 0;
    public int CapturedOf(int monsterId) => _captured.TryGetValue(monsterId, out int n) ? n : 0;

    /// <summary>The parts of this monster that broke, over every one of it that was in the hunt.</summary>
    public int BrokenOf(int monsterId) => _broken.TryGetValue(monsterId, out int n) ? n : 0;

    /// <summary>How many times this monster staggered (flinched from a hit that built up enough), over every one of it that was in the hunt.</summary>
    public int StaggeredOf(int monsterId) => _staggered.TryGetValue(monsterId, out int n) ? n : 0;

    public int TotalCaptured => Sum(_captured);
    public int TotalKilled => Sum(_killed);
    public int TotalBroken => Sum(_broken);
    public int TotalStaggered => Sum(_staggered);

    private static int Sum(Dictionary<int, int> counts)
    {
        int total = 0;
        foreach (int n in counts.Values)
            total += n;
        return total;
    }

    public HuntFacts Kill(int monsterId)
    {
        _killed[monsterId] = KilledOf(monsterId) + 1;
        return this;
    }

    public HuntFacts Capture(int monsterId)
    {
        _captured[monsterId] = CapturedOf(monsterId) + 1;
        return this;
    }

    public HuntFacts Break(int monsterId, int parts = 1)
    {
        if (parts > 0)
            _broken[monsterId] = BrokenOf(monsterId) + parts;
        return this;
    }

    public HuntFacts Stagger(int monsterId, int times = 1)
    {
        if (times > 0)
            _staggered[monsterId] = StaggeredOf(monsterId) + times;
        return this;
    }
}
