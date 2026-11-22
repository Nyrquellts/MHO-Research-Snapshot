// SPDX-License-Identifier: AGPL-3.0-only
using Mho.Research.Motion;

HunterTrackChecks track = new();
TargetSelectorChecks targeting = new();
ClockChecks clock = new();
Action[] checks =
{
    track.TheFirstReport_IsWhereTheHunterIs_WithNoSpeed,
    track.ARunningHunter_IsCarriedOnBetweenReports_AndNotPastWhatTheSpeedSays,
    track.ANewReport_IsNotAJump_WhatWasShownFadesIntoIt,
    track.AStopReport_ZeroesTheSpeed_AndTheHunterSettlesOnIt,
    track.AJumpAcrossTheMap_IsTakenAtOnce_NoRunIsInventedFromIt,
    track.ABurstOfReports_AndAbsurdSpeeds_MakeNoRunawayLead,
    track.BadNumbers_AreNotTaken_AndSilenceIsStanding,
    targeting.TheNearestHunter_IsTheTarget_AndNobodyIsNoTarget,
    targeting.AHunterWhoHasHurtIt_DrawsItFromFurtherOff_UpToTheCap,
    targeting.AHunterWhoIsDown_IsPassedOver_UntilTheyAreTheOnlyOne,
    targeting.HuntersInAnotherRegion_AreOutOfReach_ButANobodyInRegionStillNamesOne,
    targeting.AMonsterKeepsItsTarget_UntilAnotherIsClearlyBetter_AndItHasHeldItAWhile,
    targeting.ATargetThatFaintsIsDroppedAtOnce_AUnknownCurrentIdIsJustTheBest,
    targeting.ANotANumberPosition_NeverWinsAndNeverThrows,
    targeting.ATie_GoesToTheHunterRegisteredFirst_AlwaysTheSame,
    clock.TheFixedStep_IsOnePeriodEveryTime_WhateverTheClockMeasured,
    clock.TheBaselineStep_IsTheMeasuredGap_WithTheSwitchOff,
    clock.AStallOfAFewPeriods_IsCaughtUp_StepByStep_AndTheScheduleKeepsItsGrid,
    clock.ALongStall_IsCaughtUpToTheBound_TheRestDroppedAndCounted,
    clock.AStepThatThrows_WhileCatchingUp_IsCountedAndTheLoopGoesOn,
    clock.AStopInsideTheCatchUp_AbandonsTheRest_NeitherCaughtUpNorDropped,
    GeometryChecks.WallSlidesAndLetsMovementAwayPass,
    GeometryChecks.WallReachDependsOnHeight,
    GeometryChecks.CornerConstrainsBothAxes,
    GeometryChecks.SteepStepsSlideAlongTheContour,
    GeometryChecks.DownhillReachAndUnknownHeight,
    GeometryChecks.TurnChoiceRespectsHeadingAndTiming,
    GeometryChecks.MovementOwnersSeparateTranslationAndRotation,
};

foreach (Action check in checks)
{
    try
    {
        check();
    }
    catch (Exception error)
    {
        Console.Error.WriteLine($"{check.Method.Name}: {error.Message}");
        return 1;
    }
}

Console.WriteLine($"{checks.Length} motion checks passed.");
return 0;
