// SPDX-License-Identifier: AGPL-3.0-only
using System.Numerics;

namespace Mho.Research.Motion;

/// <summary>Movement constraints over a caller-supplied terrain height function.</summary>
public sealed class TerrainSlope(Func<float, float, float> heightAt)
{
    private const float AnyGround = 90f;
    private readonly Func<float, float, float> _heightAt = heightAt ?? throw new ArgumentNullException(nameof(heightAt));

    /// <summary>How the ground rises at (x, y): (dz/dx, dz/dy), over <paramref name="step"/> metres each way; zero where the terrain is not known
    /// all round.</summary>
    public Vector2 Gradient(float x, float y, float step = 0.75f)
    {
        float xa = _heightAt(x - step, y), xb = _heightAt(x + step, y), ya = _heightAt(x, y - step), yb = _heightAt(x, y + step);
        if (!float.IsFinite(xa) || !float.IsFinite(xb) || !float.IsFinite(ya) || !float.IsFinite(yb))
            return Vector2.Zero;
        return new Vector2((xb - xa) / (2f * step), (yb - ya) / (2f * step));
    }

    /// <summary>The steepness of the ground at (x, y), degrees (0 where the terrain is not known).</summary>
    public float SlopeAt(float x, float y, float step = 0.75f)
        => MathF.Atan(Gradient(x, y, step).Length()) * 180f / MathF.PI;

    /// <summary>Follow the downhill gradient within the supplied distance.</summary>
    public (float X, float Y) SlideDown(float x, float y, float stand, float reach, float step = 0.25f)
    {
        if (!float.IsFinite(step) || step <= 0f)
            throw new ArgumentOutOfRangeException(nameof(step));
        if (!float.IsFinite(reach) || reach < 0f)
            throw new ArgumentOutOfRangeException(nameof(reach));
        float h = _heightAt(x, y);
        for (float gone = 0f; gone < reach && float.IsFinite(h);)
        {
            Vector2 g = Gradient(x, y);
            float len = g.Length();
            if (len < 1e-6f || MathF.Atan(len) * 180f / MathF.PI <= stand)
                break;
            float s = MathF.Min(step, reach - gone);
            float nx = x - g.X / len * s, ny = y - g.Y / len * s, nh = _heightAt(nx, ny);
            if (!float.IsFinite(nh) || nh >= h)
                break;
            (x, y, h) = (nx, ny, nh);
            gone += s;
        }
        return (x, y);
    }

    // -- walking ---------------------------------------------------------------------------------------------------------------
    /// <summary>Can a step from one point to another be taken: the ground between them does not rise more than <paramref name="uphill"/> degrees
    /// or fall more than <paramref name="downhill"/>, and a step that does not go down does not end on ground steeper than <paramref name="stand"/>
    /// (<see cref="SlopeAt"/>). A step that starts or ends where the terrain is unknown is permitted.</summary>
    public bool Passable(float fromX, float fromY, float toX, float toY, float uphill, float downhill, float stand = AnyGround)
    {
        float h0 = _heightAt(fromX, fromY), h1 = _heightAt(toX, toY);
        if (!float.IsFinite(h0) || !float.IsFinite(h1))
            return true;
        float run = MathF.Sqrt((toX - fromX) * (toX - fromX) + (toY - fromY) * (toY - fromY));
        if (run < 1e-5f)
            return true;
        float rise = h1 - h0;
        float limit = MathF.Tan((rise >= 0f ? uphill : downhill) * MathF.PI / 180f);
        if (MathF.Abs(rise) > limit * run)
            return false;
        return stand >= AnyGround || rise < 0f || SlopeAt(toX, toY) <= stand;
    }

    /// <summary>Where a monster that steps from (<paramref name="fromX"/>, <paramref name="fromY"/>) towards (<paramref name="toX"/>,
    /// <paramref name="toY"/>) ends up: there, when the ground allows the step; else it slides along the slope -- the step with its uphill part
    /// taken out, along the contour -- and if that is not allowed either it stays where it is (a wall it can only face). <paramref name="stand"/>: the
    /// steepest ground a step that does not go down may end on.</summary>
    public (float X, float Y) Slide(float fromX, float fromY, float toX, float toY, float uphill, float downhill,
        float stand = AnyGround)
    {
        if (Passable(fromX, fromY, toX, toY, uphill, downhill, stand))
            return (toX, toY);
        Vector2 step = new(toX - fromX, toY - fromY);
        Vector2 grad = Gradient(fromX, fromY);
        float g = grad.Length();
        if (g > 1e-4f)
        {
            Vector2 up = grad / g;
            Vector2 along = step - up * Vector2.Dot(step, up);
            if (along.LengthSquared() > 1e-10f && Passable(fromX, fromY, fromX + along.X, fromY + along.Y, uphill, downhill, stand))
                return (fromX + along.X, fromY + along.Y);
        }
        return (fromX, fromY);
    }
}
