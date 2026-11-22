// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

public sealed class ClockChecks
{
    private static double Hz => 60.0;
    private static float FixedDt => (float)(1.0 / 60.0);
    private static long Period => StepRate.PeriodTicks(1_000_000, 60.0);

    /// <summary>Microsecond time that only moves when the loop waits (a stall is an overshoot of one wait, by the number of the wait).</summary>
    private sealed class FakeClock : ILoopClock
    {
        public long Time;
        public int Waits;
        public Func<int, long> Overshoot = _ => 0;
        public long Frequency => 1_000_000;
        public long Now => Time;

        public void WaitUntil(long deadline)
        {
            if (deadline > Time)
                Time = deadline + Overshoot(++Waits);
        }
    }

    private static (List<float> Dts, LoopReport Report, double WallSeconds, int Failures) Run(bool fixedStep, int steps, Func<int, long> overshoot = null,
                                                                                             Func<int, bool> throwAt = null, Func<int, bool> stopAt = null)
    {
        FakeClock clock = new() { Overshoot = overshoot ?? (_ => 0) };
        List<float> dts = new();
        int failures = 0;
        PreciseLoop loop = null;
        loop = new PreciseLoop(Hz, dt =>
        {
            dts.Add(dt);
            if (dts.Count >= steps)
                loop.Stop();
            if (stopAt != null && stopAt(dts.Count))
                loop.Stop();
            if (throwAt != null && throwAt(dts.Count))
                throw new InvalidOperationException("a step that fails");
        }, clock, fixedStep) { Failed = _ => failures++ };
        long start = clock.Time;
        loop.Run();
        return (dts, loop.Report(), (clock.Time - start) / 1_000_000.0, failures);
    }

    // -- the loop -------------------------------------------------------------------------------------------------------------------------------------------

    public void TheFixedStep_IsOnePeriodEveryTime_WhateverTheClockMeasured()
    {
        // jitter: every third wait overshoots by 2 ms (the baseline tells those steps 18.7 ms and the next 14.7)
        var (dts, r, wall, _) = Run(fixedStep: true, 600, w => w % 3 == 0 ? 2_000 : 0);
        Assert.Equal(600, dts.Count);
        Assert.All(dts, dt => Assert.Equal(FixedDt, dt));
        Assert.Equal(0, r.CaughtUp);
        Assert.Equal(0, r.Dropped);
        Assert.InRange(r.Hz, Hz - 0.5, Hz + 0.5);
        Assert.InRange(dts.Sum(), wall - 1.0 / Hz, wall + 1.0 / Hz);          // simulated time keeps to the wall within one period
    }

    public void TheBaselineStep_IsTheMeasuredGap_WithTheSwitchOff()
    {
        var (dts, r, _, _) = Run(fixedStep: false, 600, w => w % 3 == 0 ? 2_000 : 0);
        Assert.Equal(600, dts.Count);
        Assert.Contains(dts, dt => dt > FixedDt + 0.0015f);                   // the step after an overshoot is told the longer gap
        Assert.Contains(dts, dt => dt < FixedDt - 0.0015f);                   // and the one after that the shorter
        Assert.Equal(0, r.CaughtUp);
        Assert.Equal(0, r.Dropped);
    }

    public void AStallOfAFewPeriods_IsCaughtUp_StepByStep_AndTheScheduleKeepsItsGrid()
    {
        long stall = (long)(3.5 * Period);
        var (dts, r, wall, _) = Run(fixedStep: true, 30, w => w == 10 ? stall : 0);
        Assert.Equal(30, dts.Count);
        Assert.All(dts, dt => Assert.Equal(FixedDt, dt));                      // no step of 0.1 s: the stall is spread over steps of one period
        Assert.Equal(3, r.CaughtUp);
        Assert.Equal(0, r.Dropped);
        Assert.Equal(1, r.Late);                                               // the one late step is still counted late: the wall gap was measured
        Assert.InRange(dts.Sum(), wall - 1.0 / Hz, wall + 1.0 / Hz);          // simulated time caught the wall up
        // the baseline on the same stall: one step told the long gap and three periods dropped, never run
        var (legacy, lr, _, _) = Run(fixedStep: false, 30, w => w == 10 ? stall : 0);
        Assert.Contains(legacy, dt => dt > 3f * FixedDt);
        Assert.Equal(3, lr.Dropped);
        Assert.Equal(0, lr.CaughtUp);
    }

    public void ALongStall_IsCaughtUpToTheBound_TheRestDroppedAndCounted()
    {
        long stall = 20 * Period;
        var (dts, r, wall, _) = Run(fixedStep: true, 40, w => w == 10 ? stall : 0);
        Assert.Equal(40, dts.Count);
        Assert.All(dts, dt => Assert.Equal(FixedDt, dt));
        long most = (long)(PreciseLoop.MaxStep * Hz) - 1;                      // MaxStep's worth of steps, less the late one itself
        Assert.Equal(5, most);
        Assert.Equal(most, r.CaughtUp);
        Assert.Equal(20 - most, r.Dropped);                                    // the steps the schedule owed (the baseline's own count of them) less those run
        Assert.InRange(wall - dts.Sum(), (r.Dropped - 1) / Hz, (r.Dropped + 1) / Hz);   // simulated time is behind the wall by the dropped steps, and no more
        var (legacy, lr, _, _) = Run(fixedStep: false, 40, w => w == 10 ? stall : 0);
        Assert.Equal(PreciseLoop.MaxStep, legacy[9]);                          // the baseline: one step of the clamp, nothing run for the rest
        Assert.Equal(20, lr.Dropped);
        Assert.Equal(0, lr.CaughtUp);
    }

    public void AStepThatThrows_WhileCatchingUp_IsCountedAndTheLoopGoesOn()
    {
        long stall = (long)(3.5 * Period);
        var (dts, r, _, failures) = Run(fixedStep: true, 30, w => w == 10 ? stall : 0, throwAt: n => n == 11 || n == 12);
        Assert.Equal(30, dts.Count);
        Assert.Equal(2, failures);
        Assert.Equal(3, r.CaughtUp);
        Assert.Equal(0, r.Dropped);
    }

    public void AStopInsideTheCatchUp_AbandonsTheRest_NeitherCaughtUpNorDropped()
    {
        // a 20-period stall at wait 10: the late step (10), then the burst of five (11 to 15); the stop lands inside the burst's third step
        var (dts, r, _, _) = Run(fixedStep: true, 60, w => w == 10 ? 20 * Period : 0, stopAt: i => i == 13);
        Assert.Equal(13, dts.Count);
        Assert.Equal(3, r.CaughtUp);
        Assert.Equal(15, r.Dropped);                                           // owed 20, the bound 5: the 15 beyond the bound; the 2 the stop abandoned are neither
    }
}
