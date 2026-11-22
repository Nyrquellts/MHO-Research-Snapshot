// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Globalization;
using System.Text;
using System.Threading;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>What the field layer counts. The name in the report is the snake_case of the member.</summary>
public enum FieldCounter
{
    ItemsUsed,
    HealingReceived,
    DrinksAtFullHealth,
    StaminaRecovered,
    Sharpened,
    SharpnessRestored,
    BuffsGranted,
    BuffsCleared,
    PouchMoves,
    PouchItemsMoved,
    PouchRefused,
    Gathers,
    GatherItems,
    GatherContention,
    ToolsBroken,
    Carves,
    CarveItems,
    CarveDepleted,
    TrapsPlaced,
    TrapsTriggered,
    TrapDeclined,
    BombsPlaced,
    BombsExploded,
    BombDamage,
    InvalidActions,
    DuplicatesRejected,
    WriteFailures,
    Count,
}

/// <summary>
/// The compact record of one hunter's field actions in one hunt: counters only (an increment each, nothing kept per action), read once when
/// the hunt's report is written. A counter that is zero is left out of the block, so a hunt with no field actions adds nothing to the report;
/// the block is one line, like the economy loop's. Nothing here reads a counter back to decide anything.
/// </summary>
public sealed class FieldTally
{
    private readonly long[] _counts = new long[(int)FieldCounter.Count];

    public void Add(FieldCounter counter, long amount = 1)
    {
        if (amount > 0 && (int)counter >= 0 && (int)counter < _counts.Length)
            Interlocked.Add(ref _counts[(int)counter], amount);
    }

    public long Get(FieldCounter counter) => Interlocked.Read(ref _counts[(int)counter]);

    /// <summary>Takes another tally's counts into this one (a hunter who is back on a new connection goes on with the counts of their hunt).</summary>
    public void Absorb(FieldTally other)
    {
        if (other == null || ReferenceEquals(other, this))
            return;
        for (int i = 0; i < _counts.Length; i++)
            Add((FieldCounter)i, Interlocked.Read(ref other._counts[i]));
    }

    public bool Empty
    {
        get
        {
            for (int i = 0; i < _counts.Length; i++)
                if (Interlocked.Read(ref _counts[i]) != 0)
                    return false;
            return true;
        }
    }

    /// <summary>The FIELD block: the non-zero counters on one line; empty when nothing happened.</summary>
    public string ToJsonBlock(string indent = "  ")
    {
        StringBuilder sb = new();
        CultureInfo c = CultureInfo.InvariantCulture;
        bool first = true;
        for (int i = 0; i < _counts.Length; i++)
        {
            long n = Interlocked.Read(ref _counts[i]);
            if (n == 0)
                continue;
            sb.Append(c, $"{(first ? string.Empty : ", ")}\"{Name((FieldCounter)i)}\": {n}");
            first = false;
        }
        return first ? string.Empty : $"{indent}\"FIELD\": {{{sb}}}";
    }

    /// <summary>The report key of a counter: <c>ItemsUsed</c> -> <c>items_used</c>.</summary>
    public static string Name(FieldCounter counter)
    {
        string text = counter.ToString();
        StringBuilder sb = new(text.Length + 4);
        for (int i = 0; i < text.Length; i++)
        {
            if (i > 0 && char.IsUpper(text[i]))
                sb.Append('_');
            sb.Append(char.ToLowerInvariant(text[i]));
        }
        return sb.ToString();
    }
}
