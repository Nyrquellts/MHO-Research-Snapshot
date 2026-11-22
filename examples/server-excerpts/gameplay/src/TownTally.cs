// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Concurrent;
using System.Globalization;
using System.Threading;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>
/// The town's compact record of one hunter: what they did at the smith, the vendors, the item box and the quest board, and how often a request was
/// turned away. Counters only -- an increment each, nothing kept per press, nothing read back to decide anything -- per CHARACTER, because the town
/// is one connection and the hunt that reports it is another. The hunt's report carries them as one line (<c>TOWN</c>) when anything happened.
/// </summary>
public sealed class TownTally
{
    private long _crafts, _purchases, _equipmentChanges, _questsSelected, _requestFailures, _syncs, _notices;

    public void Crafted() => Interlocked.Increment(ref _crafts);
    public void Purchased() => Interlocked.Increment(ref _purchases);
    public void EquipmentChanged() => Interlocked.Increment(ref _equipmentChanges);
    public void QuestSelected() => Interlocked.Increment(ref _questsSelected);
    public void RequestFailed() => Interlocked.Increment(ref _requestFailures);

    /// <summary>The town session sent the client an update (not one that found nothing to say).</summary>
    public void Synced() => Interlocked.Increment(ref _syncs);

    public void Noticed(int lines)
    {
        if (lines > 0)
            Interlocked.Add(ref _notices, lines);
    }

    public long Crafts => Interlocked.Read(ref _crafts);
    public long Purchases => Interlocked.Read(ref _purchases);
    public long EquipmentChanges => Interlocked.Read(ref _equipmentChanges);
    public long QuestsSelected => Interlocked.Read(ref _questsSelected);
    public long RequestFailures => Interlocked.Read(ref _requestFailures);
    public long Syncs => Interlocked.Read(ref _syncs);
    public long Notices => Interlocked.Read(ref _notices);

    /// <summary>Nothing has happened yet: the hunt report leaves the block out.</summary>
    public bool Empty => Crafts == 0 && Purchases == 0 && EquipmentChanges == 0 && QuestsSelected == 0 && RequestFailures == 0 && Syncs == 0 && Notices == 0;

    /// <summary>The TOWN block of the session report on one line (the file is kept to a few dozen lines); empty when nothing happened.</summary>
    public string ToJsonBlock(string indent = "  ")
    {
        if (Empty)
            return string.Empty;
        return string.Format(CultureInfo.InvariantCulture,
            "{0}\"TOWN\": {{\"crafts\": {1}, \"purchases\": {2}, \"equipment_changes\": {3}, \"quests_selected\": {4}, " +
            "\"ui_request_failures\": {5}, \"syncs\": {6}, \"notices\": {7}}}",
            indent, Crafts, Purchases, EquipmentChanges, QuestsSelected, RequestFailures, Syncs, Notices);
    }
}

/// <summary>One town tally per character ID, allocated on request.</summary>
public sealed class TownTallies
{
    private readonly ConcurrentDictionary<uint, TownTally> _byCharacter = new();

    public TownTally For(uint characterId) => _byCharacter.GetOrAdd(characterId, _ => new TownTally());
}
