// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;

namespace Mho.Research.Motion;

/// <summary>Slide a sphere along the exposed faces of supplied vertical barriers.</summary>
public sealed class LevelWalls
{
    /// <summary>How many times a step is held against the faces it meets (a corner holds it twice).</summary>
    public const int Rounds = 4;

    private const float Cell = 16f;
    private const float Epsilon = 1e-4f;

    private readonly Face[] _faces;
    private readonly string[] _wallNames;
    private readonly int[] _wallRegions;
    private readonly Dictionary<(int, int), int[]> _grid = new();     // read only once built: one scene's walls serve every hunt on it, on any thread

    private readonly struct Face
    {
        public readonly float Ax, Ay, Bx, By, ALo, AHi, BLo, BHi, Ux, Uy, Nx, Ny, Length;
        public readonly int Wall;

        public Face(float ax, float ay, float bx, float by, float aLo, float aHi, float bLo, float bHi, int wall)
        {
            Ax = ax; Ay = ay; Bx = bx; By = by; ALo = aLo; AHi = aHi; BLo = bLo; BHi = bHi; Wall = wall;
            float dx = bx - ax, dy = by - ay;
            Length = MathF.Sqrt(dx * dx + dy * dy);
            Ux = dx / Length; Uy = dy / Length;
            Nx = Uy; Ny = -Ux;                                  // the front: the right-hand side of a -> b
        }
    }

    private LevelWalls(List<Face> faces, List<string> names, List<int> regions)
    {
        _faces = faces.ToArray();
        _wallNames = names.ToArray();
        _wallRegions = regions.ToArray();
        var cells = new Dictionary<(int, int), List<int>>();
        for (int i = 0; i < _faces.Length; i++)
        {
            Face f = _faces[i];
            for (int cx = CellOf(MathF.Min(f.Ax, f.Bx)); cx <= CellOf(MathF.Max(f.Ax, f.Bx)); cx++)
                for (int cy = CellOf(MathF.Min(f.Ay, f.By)); cy <= CellOf(MathF.Max(f.Ay, f.By)); cy++)
                {
                    if (!cells.TryGetValue((cx, cy), out List<int> list))
                        cells[(cx, cy)] = list = new List<int>();
                    list.Add(i);
                }
        }
        foreach (var (key, list) in cells)
            _grid[key] = list.ToArray();
    }

    public int WallCount => _wallNames.Length;
    public int FaceCount => _faces.Length;

    /// <summary>The wall a face of <see cref="Stop"/> belongs to: its entity's name and region.</summary>
    public (string Name, int Region) WallOf(int face) => face >= 0 && face < _faces.Length
        ? (_wallNames[_faces[face].Wall], _wallRegions[_faces[face].Wall])
        : (null, -1);

    private static int CellOf(float v) => (int)MathF.Floor(v / Cell);

    public static LevelWalls Parse(string json)
    {
        using JsonDocument doc = JsonDocument.Parse(json);
        JsonElement root = doc.RootElement;
        if (root.GetProperty("format").GetInt32() != 1)
            throw new InvalidDataException("walls of an unknown format");
        var faces = new List<Face>();
        var names = new List<string>();
        var regions = new List<int>();
        foreach (JsonElement wall in root.GetProperty("walls").EnumerateArray())
        {
            int index = names.Count;
            names.Add(wall.GetProperty("name").GetString() ?? string.Empty);
            regions.Add(wall.TryGetProperty("region", out JsonElement r) ? r.GetInt32() : -1);
            foreach (JsonElement row in wall.GetProperty("faces").EnumerateArray())
            {
                if (row.GetArrayLength() != 8)
                    throw new InvalidDataException("a face is not eight numbers");
                float[] v = new float[8];
                int k = 0;
                foreach (JsonElement n in row.EnumerateArray())
                    v[k++] = n.GetSingle();
                if (!Array.TrueForAll(v, float.IsFinite))
                    throw new InvalidDataException("a face that is not a number");
                float dx = v[2] - v[0], dy = v[3] - v[1];
                if (dx * dx + dy * dy < 1e-6f)
                    continue;
                faces.Add(new Face(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], index));
            }
        }
        return new LevelWalls(faces, names, regions);
    }

    /// <summary>
    /// Where a body may go on its way from (<paramref name="fromX"/>, <paramref name="fromY"/>) to (<paramref name="toX"/>, <paramref name="toY"/>): the sphere of
    /// <paramref name="radius"/> whose centre is at <paramref name="centreZ"/> is held off the front of every face it meets -- the step keeps its part along the face
    /// (it slides), loses the part into it -- and off a face's ends; one that already stands closer than its radius (a monster placed there) goes no closer. A face
    /// whose bottom or top is beyond the centre's height holds the sphere at its reach there (<c>sqrt(r^2 - dz^2)</c>), not at all when that is more than the radius.
    /// A body behind a face (on its back) passes freely. Returns the place and the face that held it last (-1: the step is free as asked).
    /// </summary>
    public (float X, float Y, int Face) Stop(float fromX, float fromY, float toX, float toY, float centreZ, float radius)
    {
        if (!float.IsFinite(radius) || !(radius > 0f) || !float.IsFinite(fromX) || !float.IsFinite(fromY) || !float.IsFinite(toX) || !float.IsFinite(toY) || !float.IsFinite(centreZ))
            return (toX, toY, -1);
        float x = toX, y = toY;
        int held = -1;
        for (int round = 0; round < Rounds; round++)
        {
            bool moved = false;
            int x0 = CellOf(MathF.Min(fromX, x) - radius), x1 = CellOf(MathF.Max(fromX, x) + radius);
            int y0 = CellOf(MathF.Min(fromY, y) - radius), y1 = CellOf(MathF.Max(fromY, y) + radius);
            for (int cx = x0; cx <= x1; cx++)
                for (int cy = y0; cy <= y1; cy++)
                {
                    if (!_grid.TryGetValue((cx, cy), out int[] list))
                        continue;
                    foreach (int i in list)
                    {
                        if (Hold(in _faces[i], fromX, fromY, ref x, ref y, centreZ, radius))
                        {
                            moved = true;
                            held = i;
                        }
                    }
                }
            if (!moved)
                break;
        }
        return (x, y, held);
    }

    /// <summary>One face's hold on a step: true when it moved the end of the step.</summary>
    private static bool Hold(in Face f, float fromX, float fromY, ref float x, ref float y, float centreZ, float radius)
    {
        float s0 = (fromX - f.Ax) * f.Nx + (fromY - f.Ay) * f.Ny;
        if (s0 < 0f)
            return false;                                       // behind the face: the step starts behind the face
        float s1 = (x - f.Ax) * f.Nx + (y - f.Ay) * f.Ny;
        float t0 = ((fromX - f.Ax) * f.Ux + (fromY - f.Ay) * f.Uy) / f.Length;
        float t1 = ((x - f.Ax) * f.Ux + (y - f.Ay) * f.Uy) / f.Length;
        float reach = Reach(in f, Math.Clamp(t1, 0f, 1f), centreZ, radius);
        if (reach <= 0f)
            return false;
        // where along the face the step meets its front at the sphere's reach (or ends, when it does not get that close)
        float t = t1;
        if (s0 >= reach && s1 < reach && s0 - s1 > Epsilon)
            t = t0 + (s0 - reach) / (s0 - s1) * (t1 - t0);
        if (t >= 0f && t <= 1f)
        {
            float limit = s0 >= reach ? reach : s0;             // one already closer goes no closer
            if (s1 >= limit - Epsilon)
                return false;
            x += f.Nx * (limit - s1);
            y += f.Ny * (limit - s1);
            return true;
        }
        // past an end: the face's edge there, round
        float ex = t < 0f ? f.Ax : f.Bx, ey = t < 0f ? f.Ay : f.By;
        float edge = Reach(in f, t < 0f ? 0f : 1f, centreZ, radius);
        float dx = x - ex, dy = y - ey;
        float d = MathF.Sqrt(dx * dx + dy * dy);
        if (d >= edge)
            return false;
        float d0 = MathF.Sqrt((fromX - ex) * (fromX - ex) + (fromY - ey) * (fromY - ey));
        float limitEdge = d0 >= edge ? edge : d0;
        if (d >= limitEdge - Epsilon)
            return false;
        if (d < Epsilon)
        {
            x = ex + f.Nx * limitEdge;                          // on the edge itself: out by the front
            y = ey + f.Ny * limitEdge;
        }
        else
        {
            x = ex + dx / d * limitEdge;
            y = ey + dy / d * limitEdge;
        }
        return true;
    }

    /// <summary>How far the face holds the sphere off at <paramref name="t"/> along it: the radius where the centre is within the face's height, less where its bottom
    /// or top is beyond the centre, nothing where that is a radius or more away.</summary>
    private static float Reach(in Face f, float t, float centreZ, float radius)
    {
        float lo = f.ALo + t * (f.BLo - f.ALo), hi = f.AHi + t * (f.BHi - f.AHi);
        float dz = centreZ < lo ? lo - centreZ : centreZ > hi ? centreZ - hi : 0f;
        return dz >= radius ? 0f : MathF.Sqrt(radius * radius - dz * dz);
    }
}
