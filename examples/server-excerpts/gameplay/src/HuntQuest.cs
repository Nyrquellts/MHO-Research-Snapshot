// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Generic;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>How a hunt's quest stands.</summary>
public enum QuestOutcome : byte
{
    Active,
    Victory,
    Defeat,
}

/// <summary>Whose carts count: one allowance for the whole party (a fainted hunter costs the party a cart), or each hunter's own.</summary>
public enum CartRule : byte
{
    /// <summary>The party shares the configured number of faints: the hunt is lost when they are used up, whoever fainted. What a lone hunter always had.</summary>
    Shared,

    /// <summary>Each hunter has the configured number of faints of their own; one who has used them is out (not revived), and the hunt is lost when every hunter is.</summary>
    PerHunter,
}

/// <summary>What one fainting came to.</summary>
/// <param name="Counted">The faint was new (a repeat of one already counted is not).</param>
/// <param name="Total">Faints counted in all.</param>
/// <param name="HunterOut">This hunter has no cart left: they are not revived.</param>
/// <param name="Exhausted">The allowance is used up: the hunt is lost.</param>
public readonly record struct CartResult(bool Counted, int Total, bool HunterOut, bool Exhausted);

/// <summary>
/// The quest of one hunt -- the single truth of whether it is won or lost, however many hunters are in it -- and its carts. Won when the last target
/// falls (once), lost when the carts are used up (once); a won hunt cannot be lost and a lost one cannot be won. Each hunter's own lifecycle reads it: the
/// result screen, the rewards and the way home are per hunter, the outcome is not.
///
/// Carts are counted by the faint, not by the message: a faint is the hunter's n-th (their own faint count), and the same (hunter, n) reported again -- a
/// duplicate hit, a repeated death notice -- counts once.
/// </summary>
public sealed class HuntQuest
{
    private readonly object _sync = new();
    private readonly HashSet<(int Hunter, int Ordinal)> _counted = new();
    private readonly Dictionary<int, int> _faints = new();
    private readonly HashSet<int> _out = new();
    private int _outcome;

    /// <summary>The allowance of a level whose mode has unlimited carts: no count of faints reaches it.</summary>
    public const int Unlimited = int.MaxValue;

    public HuntQuest(int maxCarts, CartRule rule = CartRule.Shared)
    {
        MaxCarts = maxCarts < 1 ? 1 : maxCarts;
        Rule = rule;
    }

    /// <summary>The faints that end the hunt (<see cref="Unlimited"/>: none does).</summary>
    public int MaxCarts { get; }
    public CartRule Rule { get; }

    public QuestOutcome Outcome
    {
        get
        {
            lock (_sync)
                return (QuestOutcome)_outcome;
        }
    }

    public bool Won => Outcome == QuestOutcome.Victory;
    public bool Lost => Outcome == QuestOutcome.Defeat;

    /// <summary>The last target killed when the hunt was won (0 before that).</summary>
    public int LastBossId { get; private set; }

    /// <summary>Faints counted so far, all hunters together.</summary>
    public int Carts
    {
        get
        {
            lock (_sync)
                return _counted.Count;
        }
    }

    /// <summary>Whether the last target was captured.</summary>
    public bool LastBossCaptured { get; private set; }

    /// <summary>The caller-defined reason for a loss.</summary>
    public int LossReason { get; private set; }

    /// <summary>Whether the time limit expired.</summary>
    public bool TimedOut { get; private set; }

    /// <summary>The hunt is won -- once, by the first call after the last target fell. False when it was decided already (won, or lost).</summary>
    public bool TryWin(int lastBossId) => TryWin(lastBossId, false);

    /// <summary>The same, saying whether the last target was captured.</summary>
    public bool TryWin(int lastBossId, bool captured)
    {
        lock (_sync)
        {
            if (_outcome != (int)QuestOutcome.Active)
                return false;
            _outcome = (int)QuestOutcome.Victory;
            LastBossId = lastBossId;
            LastBossCaptured = captured;
            return true;
        }
    }

    /// <summary>The hunt is lost -- once. False when it was decided already: a won hunt cannot be lost, a lost one is lost once.</summary>
    public bool TryDefeat() => TryDefeat(0, false);

    /// <summary>The same, recording the caller's reason and whether it was the clock.</summary>
    public bool TryDefeat(int reason, bool timedOut)
    {
        lock (_sync)
        {
            if (_outcome != (int)QuestOutcome.Active)
                return false;
            _outcome = (int)QuestOutcome.Defeat;
            LossReason = reason;
            TimedOut = timedOut;
            return true;
        }
    }

    /// <summary>The hunter <paramref name="hunterId"/> gave up instead of being revived: they are out of the hunt as if their carts
    /// were used up, and the hunt is lost when every hunter in it is. A second call for the same hunter changes nothing.</summary>
    public CartResult GiveUp(int hunterId, int huntersInPlay = 1)
    {
        lock (_sync)
        {
            _out.Add(hunterId);
            return new CartResult(false, _counted.Count, true, _out.Count >= global::System.Math.Max(1, huntersInPlay));
        }
    }

    /// <summary>The hunter <paramref name="hunterId"/> fainted for the <paramref name="ordinal"/>-th time. <paramref name="huntersInPlay"/> is how many hunters the
    /// hunt has (for <see cref="CartRule.PerHunter"/>: it is lost when they are all out). A faint counted already counts nothing more.</summary>
    public CartResult RecordCart(int hunterId, int ordinal, int huntersInPlay = 1)
    {
        lock (_sync)
        {
            bool counted = ordinal > 0 && _counted.Add((hunterId, ordinal));
            if (counted)
                _faints[hunterId] = _faints.GetValueOrDefault(hunterId) + 1;
            if (Rule == CartRule.Shared)
            {
                bool exhausted = _counted.Count >= MaxCarts;
                return new CartResult(counted, _counted.Count, exhausted, exhausted);
            }
            bool hunterOut = _faints.GetValueOrDefault(hunterId) >= MaxCarts;
            if (hunterOut)
                _out.Add(hunterId);
            return new CartResult(counted, _counted.Count, hunterOut, _out.Count >= global::System.Math.Max(1, huntersInPlay));
        }
    }
}
