// SPDX-License-Identifier: AGPL-3.0-only
namespace Mho.Research.Motion;

internal static class GeometryChecks
{
    private static LevelWalls Wall() => LevelWalls.Parse("""
        {"format":1,"walls":[{"name":"TestFace","region":1,"faces":[[8,0,-8,0,0,6,0,6]]}]}
        """);

    internal static void WallSlidesAndLetsMovementAwayPass()
    {
        LevelWalls wall = Wall();
        var (x, y, face) = wall.Stop(0f, 4f, 3f, -1f, 2f, 2f);
        Assert.InRange(x, 2.999f, 3.001f);
        Assert.InRange(y, 1.999f, 2.001f);
        Assert.Equal(0, face);
        Assert.Equal(("TestFace", 1), wall.WallOf(face));
        Assert.Equal((0f, 3f, -1), wall.Stop(0f, -4f, 0f, 3f, 2f, 2f));
        Assert.Equal((0f, 5f, -1), wall.Stop(0f, 3f, 0f, 5f, 2f, 2f));
    }

    internal static void WallReachDependsOnHeight()
    {
        LevelWalls wall = Wall();
        var result = wall.Stop(0f, 4f, 0f, 0f, 7.2f, 2f);
        Assert.InRange(result.Y, 1.599f, 1.601f);
        Assert.Equal((0f, 0f, -1), wall.Stop(0f, 4f, 0f, 0f, 9f, 2f));
    }

    internal static void CornerConstrainsBothAxes()
    {
        LevelWalls corner = LevelWalls.Parse("""
            {"format":1,"walls":[{"name":"TestCorner","faces":[[8,0,0,0,0,6,0,6],[0,0,0,8,0,6,0,6]]}]}
            """);
        var (x, y, face) = corner.Stop(6f, 6f, 0f, 0f, 2f, 2f);
        Assert.InRange(x, 1.999f, 2.001f);
        Assert.InRange(y, 1.999f, 2.001f);
        Assert.True(face >= 0);
    }

    internal static void SteepStepsSlideAlongTheContour()
    {
        TerrainSlope slope = new((x, _) => 2f * x);
        Assert.False(slope.Passable(0f, 0f, 2f, 1f, uphill: 25f, downhill: 70f));
        Assert.Equal((0f, 1f), slope.Slide(0f, 0f, 2f, 1f, uphill: 25f, downhill: 70f));
        Assert.False(slope.Passable(0f, 0f, 0f, 1f, uphill: 25f, downhill: 70f, stand: 30f));
        Assert.True(slope.Passable(0f, 0f, -1f, 0f, uphill: 25f, downhill: 70f, stand: 30f));
    }

    internal static void DownhillReachAndUnknownHeight()
    {
        TerrainSlope slope = new((x, _) => 2f * x);
        Assert.Equal((-2f, 0f), slope.SlideDown(0f, 0f, stand: 35f, reach: 2f));
        TerrainSlope unknown = new((_, _) => float.NaN);
        Assert.Equal((0f, 0f), unknown.SlideDown(0f, 0f, stand: 35f, reach: 2f));
    }

    internal static void TurnChoiceRespectsHeadingAndTiming()
    {
        TurnChoice[] clips =
        {
            new("RightLong", -90f, 1f),
            new("RightShort", -90f, 0.5f),
            new("Left", 105f, 1f),
            new("About", 170f, 2f),
            new("Invalid", -110f, float.NaN),
        };
        TurnTable turns = TurnTable.Build(clips);
        Assert.Equal(4, turns.Count);
        Assert.False(turns.Choose(20f).Found);
        Assert.Equal("RightShort", turns.Choose(95f).Clip);
        Assert.Equal("Left", turns.Choose(-95f).Clip);
        Assert.Equal("About", turns.Choose(170f).Clip);
    }

    internal static void MovementOwnersSeparateTranslationAndRotation()
    {
        Assert.Equal(MovementOwnership.Nobody, MovementOwnership.Owner(ActionClass.Idle, rotation: false));
        Assert.True(MovementOwnership.Owns(ActionClass.SteeredLocomotion, rotation: false, "MoveStep"));
        Assert.True(MovementOwnership.Owns(ActionClass.SteeredLocomotion, rotation: true, "Rotate"));
        Assert.False(MovementOwnership.Owns(ActionClass.Attack, rotation: true, "Rotate"));
        Assert.Equal(Enum.GetValues<ActionClass>().Length, MovementOwnership.TableRows().Count());
    }
}
