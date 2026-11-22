// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Concurrent;
using System.Globalization;
using System.Threading;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>
/// The compact progression record of one hunter across the economy loop -- hunt -> rewards -> craft -> equip -> supplies:
/// currency earned from hunts and spent at the smith and the shop, items bought, equipment crafted and materials used. It is
/// per CHARACTER, not per connection, because a hunt is paid on the battle connection while the smith and the shop are the
/// town connection's -- both are the same hunter. Counters only (an increment each, no allocation, nothing kept per
/// transaction); the hunt session's report reads them once when it ends. Nothing here reads a counter back to decide anything.
/// </summary>
public sealed class ProgressionTally
{
    private long _currencyEarned, _currencySpent, _itemsBought, _equipmentCrafted, _materialsUsed;

    /// <summary>A hunt paid the hunter in the supplied amount.</summary>
    public void HuntEarned(long currency)
    {
        if (currency > 0)
            Interlocked.Add(ref _currencyEarned, currency);
    }

    /// <summary>One craft: the equipment made, the currency it cost and the material stacks spent.</summary>
    public void Crafted(int equipment, long currencySpent, int materialsUsed)
    {
        if (equipment > 0)
            Interlocked.Add(ref _equipmentCrafted, equipment);
        if (currencySpent > 0)
            Interlocked.Add(ref _currencySpent, currencySpent);
        if (materialsUsed > 0)
            Interlocked.Add(ref _materialsUsed, materialsUsed);
    }

    /// <summary>A shop purchase: the item count bought and the currency it cost.</summary>
    public void Bought(int count, long currencySpent)
    {
        if (count > 0)
            Interlocked.Add(ref _itemsBought, count);
        if (currencySpent > 0)
            Interlocked.Add(ref _currencySpent, currencySpent);
    }

    /// <summary>A shop sale: the currency it earned (a sale is not a "hunt" earning, but it is currency in).</summary>
    public void Sold(long currencyEarned)
    {
        if (currencyEarned > 0)
            Interlocked.Add(ref _currencyEarned, currencyEarned);
    }

    public long CurrencyEarned => Interlocked.Read(ref _currencyEarned);
    public long CurrencySpent => Interlocked.Read(ref _currencySpent);
    public long ItemsBought => Interlocked.Read(ref _itemsBought);
    public long EquipmentCrafted => Interlocked.Read(ref _equipmentCrafted);
    public long MaterialsUsed => Interlocked.Read(ref _materialsUsed);

    /// <summary>Nothing has happened yet (all counters zero): the hunt report leaves the block out.</summary>
    public bool Empty => CurrencyEarned == 0 && CurrencySpent == 0 && ItemsBought == 0 && EquipmentCrafted == 0 && MaterialsUsed == 0;

    /// <summary>The PROGRESSION block for the session report, on a single line to keep the report compact (the whole file is
    /// capped a few dozen lines); empty string when nothing happened.</summary>
    public string ToJsonBlock(string indent = "  ")
    {
        if (Empty)
            return string.Empty;
        CultureInfo c = CultureInfo.InvariantCulture;
        return string.Format(c,
            "{0}\"PROGRESSION\": {{\"currency_earned\": {1}, \"currency_spent\": {2}, \"items_bought\": {3}, " +
            "\"equipment_crafted\": {4}, \"materials_used\": {5}}}",
            indent, CurrencyEarned, CurrencySpent, ItemsBought, EquipmentCrafted, MaterialsUsed);
    }
}

/// <summary>One progression tally per character ID, allocated on request.</summary>
public sealed class ProgressionBook
{
    private readonly ConcurrentDictionary<uint, ProgressionTally> _byCharacter = new();

    /// <summary>This character's tally, created on first use.</summary>
    public ProgressionTally For(uint characterId) => _byCharacter.GetOrAdd(characterId, _ => new ProgressionTally());
}
