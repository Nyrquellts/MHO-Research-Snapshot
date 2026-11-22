// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Threading.Tasks;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>Tests for the outcome and retry-safe allowance.</summary>
public sealed class HuntQuestTest
{
    [Check]
    public void AHuntIsWonOnce_AWonHuntCannotBeLost_AndALostOneCannotBeWon()
    {
        HuntQuest won = new(4);
        Assert.Equal(QuestOutcome.Active, won.Outcome);
        Assert.True(won.TryWin(41));
        Assert.False(won.TryWin(41));
        Assert.False(won.TryDefeat());
        Assert.Equal((QuestOutcome.Victory, 41), (won.Outcome, won.LastBossId));

        HuntQuest lost = new(4);
        Assert.True(lost.TryDefeat());
        Assert.False(lost.TryDefeat());
        Assert.False(lost.TryWin(1));
        Assert.True(lost.Lost);
        Assert.Equal(0, lost.LastBossId);
    }

    [Check]
    public void TheSharedAllowance_IsUsedUpByTheWholeParty_AndAFaintCountsOnceHoweverOftenItIsReported()
    {
        HuntQuest quest = new(3, CartRule.Shared);
        CartResult first = quest.RecordCart(10, 1, 3);
        Assert.Equal((true, 1, false, false), (first.Counted, first.Total, first.HunterOut, first.Exhausted));
        CartResult repeat = quest.RecordCart(10, 1, 3);                            // the same faint reported again (a duplicate hit, a repeated death notice)
        Assert.Equal((false, 1), (repeat.Counted, repeat.Total));
        Assert.Equal(2, quest.RecordCart(20, 1, 3).Total);                         // another hunter's faint is another cart of the party's
        Assert.False(quest.RecordCart(20, 1, 3).Counted);
        Assert.Equal(2, quest.Carts);
        CartResult last = quest.RecordCart(10, 2, 3);
        Assert.Equal((true, 3, true, true), (last.Counted, last.Total, last.HunterOut, last.Exhausted));
        Assert.True(quest.RecordCart(30, 1, 3).Exhausted);                         // and anyone's next faint finds it used up
        Assert.False(quest.RecordCart(10, 0, 3).Counted);                          // a faint that is not the n-th of anyone is nothing
    }

    [Check]
    public void PerHunter_EachHasTheirOwnCarts_AndTheHuntIsLostWhenEveryoneIsOut()
    {
        HuntQuest quest = new(2, CartRule.PerHunter);
        Assert.False(quest.RecordCart(10, 1, 2).HunterOut);
        CartResult out10 = quest.RecordCart(10, 2, 2);
        Assert.Equal((true, false), (out10.HunterOut, out10.Exhausted));           // 10 is out, 20 still has all theirs
        Assert.False(quest.RecordCart(20, 1, 2).Exhausted);
        Assert.True(quest.RecordCart(20, 2, 2).Exhausted);                         // both out: the hunt is lost
        HuntQuest alone = new(3, CartRule.PerHunter);
        alone.RecordCart(7, 1);
        alone.RecordCart(7, 2);
        Assert.True(alone.RecordCart(7, 3).Exhausted);                             // a lone hunter also uses the configured limit
    }

    [Check]
    public void ManyFaintsReportedAtOnce_AreCountedExactlyOnce()
    {
        HuntQuest quest = new(1000, CartRule.Shared);
        Parallel.For(0, 200, i => quest.RecordCart(i % 4, 1 + i % 5, 4));
        Assert.Equal(20, quest.Carts);                                            // four hunters x five faints, each once
    }
}
