// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

public sealed class HunterTrackChecks
{
    private static readonly Vector3 Origin = new(100f, 100f, 20f);

    private static Vector3 Along(float seconds, float speed = 6f) => Origin + new Vector3(0f, speed * seconds, 0f);

    // -- the track ---------------------------------------------------------------------------------------------------------------

    public void TheFirstReport_IsWhereTheHunterIs_WithNoSpeed()
    {
        HunterTrack track = new();
        Assert.False(track.Known);
        track.Fix(Origin, 5.0);
        Assert.True(track.Known);
        Assert.Equal(Origin, track.At(5.0));
        Assert.Equal(Origin, track.At(5.4));                                  // nothing to carry on by yet
        Assert.Equal(Vector3.Zero, track.Velocity);
    }

    public void ARunningHunter_IsCarriedOnBetweenReports_AndNotPastWhatTheSpeedSays()
    {
        HunterTrack track = new();
        for (int i = 0; i < 6; i++)                                           // a steady run, four reports a second
            track.Fix(Along(i * 0.25f), i * 0.25);
        Assert.InRange(track.Velocity.Y, 5.5f, 6.05f);                        // the speed is learned (not all at once)
        Vector3 last = track.Latest;
        float before = track.At(1.25).Y;                                      // (a little behind the report: what was shown fades into it)
        for (int i = 1; i <= 50; i++)
        {
            Vector3 p = track.At(1.25 + i * 0.01);
            Assert.True(p.Y >= before - 1e-4f, "carried on, never back");
            before = p.Y;
        }
        Assert.InRange(track.At(1.25 + 0.25).Y - last.Y, 1.0f, 1.5f);         // a quarter second on: about that much of the run
        Assert.True(track.At(60.0).Y - last.Y < 0.001f, "long silent: back where they last said");
        Assert.True(track.At(1.25 + 3.0).Y - last.Y <= 6.05f * HunterTrack.Horizon + 1e-3f, "the lead saturates");
    }

    public void ANewReport_IsNotAJump_WhatWasShownFadesIntoIt()
    {
        HunterTrack track = new();
        for (int i = 0; i < 5; i++)
            track.Fix(Along(i * 0.25f), i * 0.25);
        double now = 1.0 + 0.25;
        Vector3 shown = track.At(now);
        // the hunter swerved: the report is a metre and a half off the line the track was drawing
        track.Fix(shown + new Vector3(1.5f, -0.5f, 0f), now);
        Vector3 at = track.At(now);
        Assert.True(Vector3.Distance(at, shown) < 0.01f, $"continuous at the report ({Vector3.Distance(at, shown):0.000} m)");
        Vector3 later = track.At(now + 0.5);
        Assert.True(Vector3.Distance(later, track.Latest + track.Velocity * HunterTrack.Horizon * MathF.Tanh(0.5f / HunterTrack.Horizon)) < 0.05f,
                    "and half a second on it is the report's line");
        // never moves faster than the hunter plus the fade: sampled every 6 ms, no step is a jump
        Vector3 prev = track.At(now);
        for (int i = 1; i <= 100; i++)
        {
            Vector3 p = track.At(now + i * 0.006);
            Assert.True(Vector3.Distance(p, prev) < 0.35f, $"step {i}: {Vector3.Distance(p, prev):0.000} m");
            prev = p;
        }
    }

    public void AStopReport_ZeroesTheSpeed_AndTheHunterSettlesOnIt()
    {
        HunterTrack track = new();
        for (int i = 0; i < 6; i++)
            track.Fix(Along(i * 0.25f), i * 0.25);
        double now = 1.5;
        Vector3 shown = track.At(now);
        Vector3 spot = Along(1.4f);
        track.Fix(spot, now, stopped: true);
        Assert.Equal(Vector3.Zero, track.Velocity);
        Assert.True(Vector3.Distance(track.At(now), shown) < 0.01f);          // no pop
        Assert.True(Vector3.Distance(track.At(now + 1.0), spot) < 0.001f);    // and it comes to rest exactly there
        Assert.True(Vector3.Distance(track.At(now + 0.06), spot) < Vector3.Distance(track.At(now), spot));
    }

    public void AJumpAcrossTheMap_IsTakenAtOnce_NoRunIsInventedFromIt()
    {
        HunterTrack track = new();
        for (int i = 0; i < 6; i++)
            track.Fix(Along(i * 0.25f), i * 0.25);
        Vector3 there = new(700f, 900f, 40f);                                 // a region jump
        track.Fix(there, 1.5);
        Assert.Equal(there, track.At(1.5));
        Assert.Equal(Vector3.Zero, track.Velocity);
        Assert.Equal(there, track.At(2.0));
    }

    public void ABurstOfReports_AndAbsurdSpeeds_MakeNoRunawayLead()
    {
        HunterTrack track = new();
        track.Fix(Origin, 1.0);
        track.Fix(Origin + new Vector3(0f, 0.3f, 0f), 1.001);                 // two packets read in one go: 1 ms apart
        Assert.True(track.Velocity.Length() < 0.01f, "too close together to say anything about a speed");
        track.Fix(Origin + new Vector3(0f, 25f, 0f), 1.10);                   // 25 m in a tenth of a second is a glitch, not 250 m/s
        Assert.True(track.Velocity.Length() <= HunterTrack.MaxSpeed + 0.01f);
        Assert.True(Vector3.Distance(track.At(1.6), track.Latest) <= HunterTrack.MaxSpeed * HunterTrack.Horizon + 0.01f);
    }

    public void BadNumbers_AreNotTaken_AndSilenceIsStanding()
    {
        HunterTrack track = new();
        track.Fix(new Vector3(float.NaN, 0f, 0f), 1.0);
        Assert.False(track.Known);
        Assert.Equal(Vector3.Zero, track.At(2.0));
        track.Fix(Origin, 1.0);
        track.Fix(new Vector3(0f, float.PositiveInfinity, 0f), 1.2);
        Assert.Equal(Origin, track.Latest);
        for (int i = 0; i < 6; i++)
            track.Fix(Along(i * 0.25f), 2.0 + i * 0.25);
        track.Fix(Along(1.25f + 6f), 2.0 + 1.25 + 6.0);                       // six seconds later: the old speed is not applied across the gap
        Assert.Equal(Vector3.Zero, track.Velocity);
    }


}
