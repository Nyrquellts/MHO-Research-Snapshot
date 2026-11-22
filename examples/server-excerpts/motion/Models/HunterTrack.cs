// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

public sealed class HunterTrack
{
    /// <summary>Reports closer together than this move the position but do not make a new speed.</summary>
    public const float MinInterval = 0.04f;

    /// <summary>Silence longer than this (seconds) and the hunter is taken to be standing: the speed no longer says anything.</summary>
    public const float MaxGap = 1.2f;

    /// <summary>The furthest ahead of the last report, in seconds of travel, the hunter is ever taken to be (the lead saturates here).</summary>
    public const float Horizon = 0.45f;

    /// <summary>The fastest ground speed believed, m/s.</summary>
    public const float MaxSpeed = 25f;

    /// <summary>A position change larger than this distance resets velocity.</summary>
    public const float Jump = 30f;

    /// <summary>How long (seconds) the difference between what was shown and what a new report says takes to fade.</summary>
    public const float Blend = 0.12f;

    /// <summary>How much of a new speed replaces the old one (1: all of it).</summary>
    public const float SpeedShare = 0.65f;

    private Vector3 _pos, _velocity, _offset;
    private double _at;
    private bool _known;

    /// <summary>A report has been made.</summary>
    public bool Known => _known;

    /// <summary>The last reported position (not carried on).</summary>
    public Vector3 Latest => _pos;

    /// <summary>The ground speed in use, m/s (vertical is always zero).</summary>
    public Vector3 Velocity => _velocity;

    /// <summary>Record a new position and whether the sampled actor has stopped.</summary>
    public void Fix(Vector3 pos, double now, bool stopped = false)
    {
        if (!double.IsFinite(now) || !float.IsFinite(pos.X) || !float.IsFinite(pos.Y) || !float.IsFinite(pos.Z))
            return;
        if (!_known)
        {
            _pos = pos;
            _velocity = Vector3.Zero;
            _offset = Vector3.Zero;
            _at = now;
            _known = true;
            return;
        }
        Vector3 shown = At(now);
        double gap = Math.Max(0.0, now - _at);
        Vector3 step = pos - _pos;
        step.Z = 0f;
        float run = step.Length();
        bool jumped = run > Jump;
        if (stopped || jumped || gap > MaxGap)
            _velocity = Vector3.Zero;
        else if (gap >= MinInterval)
        {
            Vector3 speed = step / (float)gap;
            float length = speed.Length();
            if (length > MaxSpeed)
                speed *= MaxSpeed / length;
            _velocity = Vector3.Lerp(_velocity, speed, SpeedShare);
        }
        _pos = pos;
        _at = now;
        _offset = jumped ? Vector3.Zero : shown - pos;
        _offset.Z = 0f;
    }

    /// <summary>Where the hunter is taken to be at <paramref name="now"/>: the last report, carried on by the speed (saturating), plus what is
    /// left of the correction the last report made.</summary>
    public Vector3 At(double now)
    {
        if (!_known)
            return Vector3.Zero;
        float t = (float)Math.Max(0.0, now - _at);
        float lead = Horizon * MathF.Tanh(t / Horizon);
        if (t > MaxGap)
            lead *= MathF.Exp(-(t - MaxGap) / 0.5f);        // long silent: the speed says nothing any more, they are drawn back to where they last said
        Vector3 p = _pos + _velocity * lead;
        if (_offset != Vector3.Zero)
            p += _offset * MathF.Exp(-t / Blend);
        return p;
    }
}
