// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

public sealed class TargetSelectorChecks
{
    private static TargetCandidate At(int id, float x, float y = 0f, int region = -1, bool down = false, float threat = 0f)
        => new(id, new Vector3(x, y, 0f), region, down, threat);

    private static int PickId(TargetCandidate[] hunters, int current = -1, double heldFor = 100, int region = -1, float monsterX = 0f)
    {
        int at = TargetSelector.Pick(new Vector3(monsterX, 0f, 0f), region, current, heldFor, hunters);
        return at < 0 ? -1 : hunters[at].Id;
    }

    public void TheNearestHunter_IsTheTarget_AndNobodyIsNoTarget()
    {
        Assert.Equal(2, PickId(new[] { At(1, 30), At(2, 10), At(3, 20) }));
        Assert.Equal(-1, PickId(Array.Empty<TargetCandidate>()));
        Assert.Equal(7, PickId(new[] { At(7, 500) }));
    }

    public void AHunterWhoHasHurtIt_DrawsItFromFurtherOff_UpToTheCap()
    {
        TargetCandidate near = At(1, 10), far = At(2, 25, threat: 3f);                  // 15 m further, 3 points of its health taken (18 m)
        Assert.Equal(2, PickId(new[] { near, far }));
        TargetCandidate tooFar = At(2, 80, threat: 50f);                                // the bonus is capped at 5 points = 30 m
        Assert.Equal(1, PickId(new[] { near, tooFar }));
        Assert.Equal(2, PickId(new[] { At(1, 10), At(2, 39, threat: 50f) }));
        Assert.Equal(TargetSelector.ThreatCap * TargetSelector.ThreatMetres, 30f);
    }

    public void AHunterWhoIsDown_IsPassedOver_UntilTheyAreTheOnlyOne()
    {
        Assert.Equal(2, PickId(new[] { At(1, 2, down: true), At(2, 200) }));
        Assert.Equal(1, PickId(new[] { At(1, 2, down: true), At(2, 200, down: true) }));   // all down: the nearest, as a lone hunter always was
        Assert.Equal(1, PickId(new[] { At(1, 5, down: true) }));
    }

    public void HuntersInAnotherRegion_AreOutOfReach_ButANobodyInRegionStillNamesOne()
    {
        TargetCandidate[] mixed = { At(1, 5, region: 2), At(2, 90, region: 1) };
        Assert.Equal(2, PickId(mixed, region: 1));                                        // the near one is in another world
        Assert.Equal(1, PickId(new[] { At(1, 5, region: 2), At(2, 90, region: 3) }, region: 1));   // nobody here: the nearest is named, and the monster stands down by its own rule
        Assert.Equal(1, PickId(new[] { At(1, 5, region: -1), At(2, 9, region: 1) }, region: 1));   // unknown region counts as here
        Assert.Equal(1, PickId(mixed, region: -1));                                        // a monster tied to no region sees everyone
    }

    public void AMonsterKeepsItsTarget_UntilAnotherIsClearlyBetter_AndItHasHeldItAWhile()
    {
        TargetCandidate a = At(1, 20), b = At(2, 17);                                       // b is 3 m nearer: not enough
        Assert.Equal(1, PickId(new[] { a, b }, current: 1, heldFor: 10));
        TargetCandidate c = At(2, 12);                                                      // 8 m nearer
        Assert.Equal(1, PickId(new[] { a, c }, current: 1, heldFor: 1.0));                  // it has held a for a second only
        Assert.Equal(2, PickId(new[] { a, c }, current: 1, heldFor: TargetSelector.MinDwell));
        Assert.Equal(2, PickId(new[] { a, c }, current: 2, heldFor: 0));                    // and a target that is the best stays
    }

    public void ATargetThatFaintsIsDroppedAtOnce_AUnknownCurrentIdIsJustTheBest()
    {
        Assert.Equal(2, PickId(new[] { At(1, 3, down: true), At(2, 50) }, current: 1, heldFor: 0));
        Assert.Equal(2, PickId(new[] { At(1, 30), At(2, 10) }, current: 99, heldFor: 0));   // the old target has left: no dwell to serve
        Assert.Equal(1, PickId(new[] { At(1, 30), At(2, 10) }, current: 1, heldFor: 0));    // a fresh challenger does not take a target held a moment
    }

    public void ANotANumberPosition_NeverWinsAndNeverThrows()
    {
        TargetCandidate broken = new(1, new Vector3(float.NaN, 0f, 0f), -1, false, float.NaN);
        Assert.Equal(2, PickId(new[] { broken, At(2, 400) }));
        Assert.Equal(1, PickId(new[] { broken }));
        Assert.True(float.IsFinite(TargetSelector.Score(Vector3.Zero, At(3, 1, threat: float.NaN))));
    }

    public void ATie_GoesToTheHunterRegisteredFirst_AlwaysTheSame()
    {
        TargetCandidate[] tied = { At(5, 10, 0), At(6, 10, 0), At(7, 0, 10) };
        for (int i = 0; i < 20; i++)
            Assert.Equal(5, PickId(tied));
    }
}
