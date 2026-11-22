namespace Mho.Solo;

public readonly record struct ScaleFactors(double Health, double Damage);

/// <summary>
/// Configurable monster health and damage multipliers by party size.
/// Port of the standalone Python scaling model.
/// </summary>
public static class Scaling
{
    // Authored offline tuning values and illustrative defaults for larger parties.
    public static readonly IReadOnlyDictionary<int, ScaleFactors> Default = new Dictionary<int, ScaleFactors>
    {
        [1] = new(0.40, 0.65),
        [2] = new(0.70, 0.80),
        [3] = new(0.85, 0.90),
        [4] = new(1.00, 1.00),
    };

    public static ScaleFactors FactorsFor(int playerCount, IReadOnlyDictionary<int, ScaleFactors>? table = null)
    {
        if (playerCount < 1) throw new ArgumentOutOfRangeException(nameof(playerCount));
        table ??= Default;
        if (table.TryGetValue(playerCount, out var f)) return f;
        int max = table.Keys.Max();
        return table[max];
    }

    public static (double health, double damage) ScaleMonster(
        double maxHealth, double baseDamage, int playerCount,
        IReadOnlyDictionary<int, ScaleFactors>? table = null)
    {
        var f = FactorsFor(playerCount, table);
        return (maxHealth * f.Health, baseDamage * f.Damage);
    }
}
