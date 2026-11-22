namespace Mho.Solo;

public enum PhysType { Cut, Impact, Shot }

public enum Element { None, Fire, Water, Thunder, Ice, Dragon }

/// <summary>Per-part damage multipliers as percentages, with 100 for full damage.</summary>
public readonly record struct Hitzone(
    double Cut = 100, double Impact = 100, double Shot = 100,
    double Fire = 0, double Water = 0, double Thunder = 0, double Ice = 0, double Dragon = 0)
{
    public double Phys(PhysType t) => t switch
    {
        PhysType.Cut => Cut,
        PhysType.Impact => Impact,
        _ => Shot,
    };

    public double Elem(Element e) => e switch
    {
        Element.Fire => Fire,
        Element.Water => Water,
        Element.Thunder => Thunder,
        Element.Ice => Ice,
        Element.Dragon => Dragon,
        _ => 0,
    };
}

public sealed class MonsterPart(string name, Hitzone hitzone, double? breakThreshold = null)
{
    public string Name { get; } = name;
    public Hitzone Hitzone { get; } = hitzone;
    public double? BreakThreshold { get; } = breakThreshold;
    public double Accumulated { get; set; }
    public bool Broken { get; set; }
}

public readonly record struct MotionValue(
    string Name, double Value, PhysType PhysType = PhysType.Cut, double ElementModifier = 1.0);

public readonly record struct DamageResult(
    double Raw, double Elemental, double Total, string Part,
    bool PartBroke = false, bool Flinch = false, bool Killed = false);

/// <summary>
/// Calculates physical and elemental damage with configurable multipliers and a defense floor.
/// Port of the standalone Python combat model.
/// </summary>
public static class Combat
{
    public static (double raw, double elemental, double total) ComputeDamage(
        double motionValue, double playerAttack, double hitzonePct, double monsterDefense,
        double elementalAttack = 0, double elementHitzonePct = 0, double elementModifier = 1.0,
        double defenseFloor = 1.0)
    {
        double defense = monsterDefense > defenseFloor ? monsterDefense : defenseFloor;
        double raw = motionValue * playerAttack * (hitzonePct / 100.0) / defense;
        double elemental = elementalAttack * elementModifier * (elementHitzonePct / 100.0);
        return (Math.Max(0, raw), Math.Max(0, elemental), Math.Max(0, raw) + Math.Max(0, elemental));
    }
}

public sealed class Monster(int monsterId, double maxHealth, double defense, IEnumerable<MonsterPart> parts)
{
    public int MonsterId { get; } = monsterId;
    public double MaxHealth { get; set; } = maxHealth;
    public double Health { get; set; } = maxHealth;
    public double Defense { get; } = defense;
    public Dictionary<string, MonsterPart> Parts { get; } = parts.ToDictionary(p => p.Name);
    public bool Alive => Health > 0;

    public DamageResult ApplyHit(string partName, MotionValue motion, double playerAttack,
        Element element = Element.None, double elementalAttack = 0, double? flinchThreshold = null)
    {
        if (!Parts.TryGetValue(partName, out var part))
            throw new KeyNotFoundException($"unknown part {partName}");
        var hz = part.Hitzone;
        var (raw, elemental, total) = Combat.ComputeDamage(
            motion.Value, playerAttack, hz.Phys(motion.PhysType), Defense,
            elementalAttack, hz.Elem(element), motion.ElementModifier);

        bool wasAlive = Alive;
        Health = Math.Max(0, Health - total);

        bool partBroke = false;
        if (part.BreakThreshold is double thr && !part.Broken)
        {
            part.Accumulated += total;
            if (part.Accumulated >= thr) { part.Broken = true; partBroke = true; }
        }
        bool flinch = partBroke || (flinchThreshold is double f && total >= f);
        bool killed = wasAlive && !Alive;
        return new DamageResult(raw, elemental, total, partName, partBroke, flinch, killed);
    }
}
