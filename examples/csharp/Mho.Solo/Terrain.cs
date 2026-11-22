namespace Mho.Solo;

/// <summary>
/// A regular elevation grid over an axis-aligned world rectangle with bilinear interpolation.
/// Port of the standalone Python terrain model.
/// </summary>
public sealed class MapGrid
{
    private readonly float[,] _elevation; // [row, col]; row runs +Y, col runs +X
    public double MinX { get; }
    public double MaxX { get; }
    public double MinY { get; }
    public double MaxY { get; }
    public int Rows { get; }
    public int Cols { get; }

    public MapGrid(double minX, double maxX, double minY, double maxY, float[,] elevation)
    {
        if (maxX <= minX || maxY <= minY)
            throw new ArgumentException("max bounds must exceed min bounds");
        Rows = elevation.GetLength(0);
        Cols = elevation.GetLength(1);
        if (Rows < 2 || Cols < 2)
            throw new ArgumentException("grid needs >= 2 rows and cols");
        foreach (float v in elevation)
            if (!float.IsFinite(v))
                throw new ArgumentException("elevation samples must be finite");
        MinX = minX; MaxX = maxX; MinY = minY; MaxY = maxY;
        _elevation = elevation;
    }

    /// <summary>Interpolated, always-finite ground height at a world position. Out-of-bounds
    /// queries clamp to the nearest edge; a non-finite query throws.</summary>
    public double GetGroundZ(double worldX, double worldY)
    {
        if (!double.IsFinite(worldX) || !double.IsFinite(worldY))
            throw new ArgumentException("query coordinates must be finite");

        double gx = (worldX - MinX) / (MaxX - MinX) * (Cols - 1);
        double gy = (worldY - MinY) / (MaxY - MinY) * (Rows - 1);
        gx = Math.Clamp(gx, 0, Cols - 1);
        gy = Math.Clamp(gy, 0, Rows - 1);

        int c0 = (int)gx, r0 = (int)gy;
        int c1 = c0 < Cols - 1 ? c0 + 1 : c0;
        int r1 = r0 < Rows - 1 ? r0 + 1 : r0;
        double fx = gx - c0, fy = gy - r0;

        double top = _elevation[r0, c0] * (1 - fx) + _elevation[r0, c1] * fx;
        double bot = _elevation[r1, c0] * (1 - fx) + _elevation[r1, c1] * fx;
        return top * (1 - fy) + bot * fy;
    }

    public bool Contains(double x, double y) => x >= MinX && x <= MaxX && y >= MinY && y <= MaxY;

    /// <summary>Build from an in-memory unsigned height grid with configurable vertical and horizontal scales.</summary>
    public static MapGrid FromHeightmap(ushort[,] raw, double heightRatio = 1.0,
        double unitScale = 1.0, double originX = 0, double originY = 0)
    {
        int rows = raw.GetLength(0), cols = raw.GetLength(1);
        var elev = new float[rows, cols];
        for (int r = 0; r < rows; r++)
            for (int c = 0; c < cols; c++)
                elev[r, c] = (float)(raw[r, c] * heightRatio);
        return new MapGrid(originX, originX + (cols - 1) * unitScale,
                           originY, originY + (rows - 1) * unitScale, elev);
    }

    public static MapGrid FlatPlane(double minX, double maxX, double minY, double maxY, float z = 0)
        => new(minX, maxX, minY, maxY, new float[2, 2] { { z, z }, { z, z } });
}
