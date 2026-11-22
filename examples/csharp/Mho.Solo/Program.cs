using Mho.Solo;

// Standalone self-checks with in-memory sample inputs.
int passed = 0, failed = 0;

void Check(bool cond, string name)
{
    if (cond) { passed++; }
    else { failed++; Console.WriteLine($"  FAIL: {name}"); }
}

void CheckClose(double a, double b, string name, double eps = 1e-6)
    => Check(Math.Abs(a - b) < eps, $"{name} ({a} vs {b})");

// -- Terrain --
var flat = MapGrid.FlatPlane(0, 100, 0, 100, 7.5f);
CheckClose(flat.GetGroundZ(50, 50), 7.5, "terrain flat");
CheckClose(flat.GetGroundZ(-100, 999), 7.5, "terrain out-of-bounds clamp");
var ramp = new MapGrid(0, 10, 0, 10, new float[2, 2] { { 0, 10 }, { 0, 10 } }); // z == x
CheckClose(ramp.GetGroundZ(5, 5), 5.0, "terrain bilinear midpoint");
CheckClose(ramp.GetGroundZ(2.5, 9), 2.5, "terrain bilinear");
try { ramp.GetGroundZ(double.NaN, 0); Check(false, "terrain NaN throws"); }
catch (ArgumentException) { Check(true, "terrain NaN throws"); }
var hm = MapGrid.FromHeightmap(new ushort[2, 2] { { 100, 100 }, { 100, 100 } }, 0.1);
CheckClose(hm.GetGroundZ(0, 0), 10.0, "terrain from heightmap (100*0.1)");

// -- Combat --
var (raw, ele, total) = Combat.ComputeDamage(22, 100, 45, 10);
CheckClose(raw, 22 * 100 * 0.45 / 10, "damage formula");           // 99
CheckClose(ele, 0, "no elemental");
var (r0, _, _) = Combat.ComputeDamage(20, 100, 100, 0);            // defense floored
Check(double.IsFinite(r0) && r0 > 0, "defense floor no div-by-zero");

var head = new MonsterPart("Head", new Hitzone(Cut: 65, Impact: 70, Shot: 50), breakThreshold: 120);
var body = new MonsterPart("Body", new Hitzone(Cut: 40));
var m = new Monster(2, maxHealth: 500, defense: 10, new[] { head, body });
var slash = new MotionValue("slash", 20, PhysType.Cut);
var hit = m.ApplyHit("Head", slash, 100);
CheckClose(hit.Total, 20 * 100 * 0.65 / 10, "monster hit total");  // 130
CheckClose(m.Health, 500 - 130, "monster hp after hit");
Check(hit.PartBroke && hit.Flinch, "part break flinches");          // 130 >= 120
var hit2 = m.ApplyHit("Head", slash, 100);
Check(!hit2.PartBroke, "already-broken part doesn't re-break");
var big = new Monster(1, 50, 10, new[] { new MonsterPart("Body", new Hitzone(Cut: 100)) });
Check(big.ApplyHit("Body", new MotionValue("x", 1000), 100).Killed, "kill flag");

// -- Scaling --
var f = Scaling.FactorsFor(1);
Check(f.Health == 0.40 && f.Damage == 0.65, "solo factors");
var (sh, sd) = Scaling.ScaleMonster(1000, 200, 1);
CheckClose(sh, 400, "solo health scale");
CheckClose(sd, 130, "solo damage scale");
Check(Scaling.FactorsFor(99).Equals(Scaling.FactorsFor(4)), "player count clamps");

Console.WriteLine($"Mho.Solo self-test: {passed} passed, {failed} failed");
return failed == 0 ? 0 : 1;
