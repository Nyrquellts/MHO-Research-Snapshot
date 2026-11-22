// SPDX-License-Identifier: AGPL-3.0-only
namespace MhoResearch.ServerExcerpts.Gameplay;

public sealed class OtherChecks
{
    [Check]
    public void RememberedRequestsKeepTheFirstReplyAndEvictTheOldest()
    {
        RequestBook book = new(2);
        book.Remember("a", "first");
        book.Remember("a", "replacement");
        Assert.True(book.TryGet("a", out string reply));
        Assert.Equal("first", reply);
        Assert.False(book.TryGet("a", out object[] _));
        book.Remember("b", "second");
        book.Remember("c", "third");
        Assert.Equal(2, book.Count);
        Assert.False(book.TryGet("a", out string _));
        Assert.True(book.TryGet("c", out string _));
    }

    [Check]
    public void AnActionCanBeRetriedOnceOnlyDuringItsWindow()
    {
        RequestBook book = new(3);
        book.RememberAction("early", "expired", 2.0);
        book.RememberAction("eligible", "answer", 8.0);
        book.RememberAction("too late", "answer", 9.0);
        book.ArmRetries(now: 10.0, window: 3.0);
        Assert.False(book.TryRetry("early", 11.0, out string _));
        Assert.False(book.TryRetry("eligible", 11.0, out object[] _));
        Assert.True(book.TryRetry("eligible", 12.0, out string reply));
        Assert.Equal("answer", reply);
        Assert.False(book.TryRetry("eligible", 12.0, out string _));
        Assert.False(book.TryRetry("too late", 14.0, out string _));
    }

    [Check]
    public void ActionEvictionOmitsOldestAndRejectsInvalidTimestamps()
    {
        RequestBook book = new(1);
        book.RememberAction("ignored", "bad time", double.NaN);
        book.RememberAction("older", "old", 3.0);
        book.RememberAction("newer", "new", 4.0);
        book.ArmRetries(now: 5.0, window: 2.0);
        Assert.False(book.TryRetry("older", 5.0, out string _));
        Assert.True(book.TryRetry("newer", 5.0, out string _));
    }

    [Check]
    public void ProgressUsesCumulativeExperienceWithASeparateRankSchedule()
    {
        RankTable table = new(new[] { 20, 60, 90, 0 }, new long[] { 5, 35, 80 });
        Assert.Equal(1, table.LevelOf(19));
        Assert.Equal(2, table.LevelOf(20));
        Assert.Equal(3, table.LevelOf(80));
        Assert.Equal(4, table.LevelOf(999));
        Assert.Equal(170L, table.ExpToReach(999));
        Assert.Equal(2, table.Progress(50, out long earned, out long required));
        Assert.Equal((30L, 60L), (earned, required));
        Assert.Equal(2, table.RankOf(79));
        Assert.Equal(3, table.RankOf(80));
        Assert.Equal(35L, table.PointsToReach(2));
    }

    [Check]
    public void MissingProgressionDataUsesTheBaselineAndNeverDemotes()
    {
        RankTable table = new(null, null);
        Assert.True(table.Empty);
        Assert.Equal(1, table.LevelOf(1000));
        Assert.Equal(0, table.RankOf(1000));
        Assert.Equal(3, table.LevelFor(3, 0));
    }
}
