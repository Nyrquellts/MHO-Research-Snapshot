// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;

namespace MhoResearch.ServerExcerpts.Gameplay;

public sealed class GameplayReportsChecks
{
    [Check]
    public void FieldReportsOnlyNonzeroCounters()
    {
        FieldTally tally = new();
        Assert.Equal(string.Empty, tally.ToJsonBlock());
        tally.Add(FieldCounter.PouchMoves, 2);
        tally.Add(FieldCounter.ItemsUsed);
        tally.Add(FieldCounter.PouchMoves, -7);
        tally.Add(FieldCounter.Count);
        using JsonDocument report = JsonDocument.Parse("{" + tally.ToJsonBlock() + "}");
        JsonElement counters = report.RootElement.GetProperty("FIELD");
        Assert.Equal(1L, counters.GetProperty("items_used").GetInt64());
        Assert.Equal(2L, counters.GetProperty("pouch_moves").GetInt64());
        Assert.Equal(2, counters.EnumerateObject().Count());
    }

    [Check]
    public void FieldAbsorbCombinesCounts()
    {
        FieldTally first = new(), second = new();
        first.Add(FieldCounter.Gathers, 2);
        second.Add(FieldCounter.Gathers, 5);
        second.Add(FieldCounter.GatherItems, 3);
        first.Absorb(second);
        first.Absorb(first);
        Assert.Equal(7L, first.Get(FieldCounter.Gathers));
        Assert.Equal(3L, first.Get(FieldCounter.GatherItems));
        Assert.Equal(5L, second.Get(FieldCounter.Gathers));
    }

    [Check]
    public void FieldUpdatesAreAtomic()
    {
        FieldTally tally = new();
        Parallel.For(0, 1200, _ => tally.Add(FieldCounter.PouchMoves, 2));
        Assert.Equal(2400L, tally.Get(FieldCounter.PouchMoves));
    }

    [Check]
    public void ProgressionRollsUpEarningsAndCosts()
    {
        ProgressionTally tally = new();
        Assert.Equal(string.Empty, tally.ToJsonBlock());
        tally.HuntEarned(10);
        tally.Sold(2);
        tally.Crafted(1, 5, 3);
        tally.Bought(2, 7);
        tally.Bought(-2, -4);
        Assert.Equal(12L, tally.CurrencyEarned);
        Assert.Equal(12L, tally.CurrencySpent);
        Assert.Equal(2L, tally.ItemsBought);
        Assert.Equal(1L, tally.EquipmentCrafted);
        Assert.Equal(3L, tally.MaterialsUsed);
        using JsonDocument report = JsonDocument.Parse("{" + tally.ToJsonBlock() + "}");
        Assert.Equal(12L, report.RootElement.GetProperty("PROGRESSION").GetProperty("currency_spent").GetInt64());
    }

    [Check]
    public void ProgressionTalliesAreIndependent()
    {
        ProgressionBook book = new();
        book.For(1).HuntEarned(9);
        Assert.Equal(9L, book.For(1).CurrencyEarned);
        Assert.Equal(0L, book.For(2).CurrencyEarned);
    }

    [Check]
    public void TownReportTracksActions()
    {
        TownTallies book = new();
        TownTally tally = book.For(1);
        Assert.Equal(string.Empty, tally.ToJsonBlock());
        tally.Crafted();
        tally.Purchased();
        tally.EquipmentChanged();
        tally.QuestSelected();
        tally.RequestFailed();
        tally.Synced();
        tally.Noticed(5);
        tally.Noticed(-1);
        using JsonDocument report = JsonDocument.Parse("{" + tally.ToJsonBlock() + "}");
        JsonElement counts = report.RootElement.GetProperty("TOWN");
        Assert.Equal(1L, counts.GetProperty("ui_request_failures").GetInt64());
        Assert.Equal(1L, counts.GetProperty("equipment_changes").GetInt64());
        Assert.Equal(5L, counts.GetProperty("notices").GetInt64());
        Assert.Equal(0L, book.For(2).Crafts);
    }

    [Check]
    public void HuntFactsCountOutcomesSeparately()
    {
        HuntFacts facts = new HuntFacts().Kill(1).Kill(1).Capture(1).Capture(2).Break(2, 2).Stagger(1);
        Assert.Equal(2, facts.KilledOf(1));
        Assert.Equal(1, facts.CapturedOf(1));
        Assert.Equal(1, facts.CapturedOf(2));
        Assert.Equal(2, facts.TotalKilled);
        Assert.Equal(2, facts.TotalCaptured);
        Assert.Equal(2, facts.TotalBroken);
        Assert.Equal(1, facts.TotalStaggered);
    }

    [Check]
    public void HuntFactsIgnoreEmptyChanges()
    {
        HuntFacts facts = new HuntFacts().Break(1, -2).Stagger(2, 0);
        Assert.Equal(0, facts.BrokenOf(1));
        Assert.Equal(0, facts.StaggeredOf(2));
        Assert.Equal(0, facts.KilledOf(7));
    }
}
