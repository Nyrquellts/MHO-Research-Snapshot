// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Generic;
using System.Linq;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>How a party request ended. A duplicate is the request of something that already is (a second ready, a join of the party the
/// hunter is in): it changes nothing and reports the party as it stands, so a client that repeats itself gets the same answer twice.</summary>
public enum PartyOutcome : byte
{
    Applied,
    Duplicate,
    Rejected,
}

/// <summary>Why a party request was refused. None of them changes the party.</summary>
public enum PartyError : byte
{
    None,

    /// <summary>The id names nobody the request can be about (zero, not in this party).</summary>
    UnknownCharacter,

    /// <summary>A party id that is stale, invented or closed.</summary>
    NoSuchParty,

    /// <summary>The hunter is in another party.</summary>
    AlreadyInParty,

    NotInParty,
    Full,
    NotLeader,

    /// <summary>The party's state does not allow it (a quest change in a hunt, a join into a closed party, a second hunt).</summary>
    WrongState,

    /// <summary>No quest is chosen yet.</summary>
    NoQuest,

    /// <summary>The quest is not one the server can run.</summary>
    QuestUnknown,

    /// <summary>The quest exists but not for this party (too many hunters).</summary>
    QuestIllegal,

    /// <summary>A member may not hunt it (<see cref="PartyResult.Subject"/> says which).</summary>
    NotEligible,

    NotAllReady,

    /// <summary>The hunter is in a hunt already (their party's, or a solo one).</summary>
    InHunt,

    /// <summary>A hunt session id that is not the party's current one.</summary>
    StaleSession,
}

public enum PartyEventKind : byte
{
    Created,
    MemberJoined,
    MemberLeft,
    MemberKicked,
    LeaderChanged,
    QuestSelected,
    QuestCleared,
    ReadyChanged,
    CountdownStarted,
    CountdownCancelled,

    /// <summary>The countdown ran out: the hunt has its session id (<see cref="PartyEvent.Detail"/>) and the clients are to enter it.</summary>
    HuntStarted,

    StateChanged,
    Disbanded,
}

/// <summary>One thing that happened to a party, for the wire layer to tell the members about. <see cref="Detail"/> is the quest id, the session
/// id, the new state or the ready flag, by kind.</summary>
public readonly record struct PartyEvent(PartyEventKind Kind, long PartyId, uint CharacterId = 0, long Detail = 0);

/// <summary>A hunter as the party sees them.</summary>
public readonly record struct PartyMemberInfo(uint CharacterId, string Name, uint Level);

/// <summary>A member of a party, frozen at the moment of the snapshot.</summary>
public sealed record MemberView(uint CharacterId, string Name, uint Level, bool Ready);

/// <summary>A party frozen at the moment of the snapshot (the live one is only ever touched under the book's lock).</summary>
public sealed record PartyView(long Id, string Name, uint LeaderId, IReadOnlyList<MemberView> Members, int QuestId, PartyState State,
                               long SessionId, long CountdownToken, int MaxMembers, long Version, long CreatedUnix = 0)
{
    /// <summary>The "enter battle" countdown is running.</summary>
    public bool Counting => CountdownToken != 0;

    public bool AllReady => Members.Count > 0 && Members.All(m => m.Ready);

    public MemberView Member(uint characterId) => Members.FirstOrDefault(m => m.CharacterId == characterId);

    public bool Has(uint characterId) => Members.Any(m => m.CharacterId == characterId);
}

/// <summary>What a party request did: how it ended, why not, the party after it, and what happened (for the members to be told).</summary>
public sealed class PartyResult
{
    private static readonly IReadOnlyList<PartyEvent> NoEvents = new List<PartyEvent>();

    internal PartyResult(PartyOutcome outcome, PartyError error, PartyView party, IReadOnlyList<PartyEvent> events = null,
                         long sessionId = 0, uint subject = 0)
    {
        Outcome = outcome;
        Error = error;
        Party = party;
        Events = events ?? NoEvents;
        SessionId = sessionId;
        Subject = subject;
    }

    public PartyOutcome Outcome { get; }
    public PartyError Error { get; }

    /// <summary>The party after the call; for a refusal the party the request was about, when there is one.</summary>
    public PartyView Party { get; }

    public IReadOnlyList<PartyEvent> Events { get; }

    /// <summary>The hunt session the countdown created (<see cref="PartyEventKind.HuntStarted"/>), else 0.</summary>
    public long SessionId { get; }

    /// <summary>The hunter a refusal is about (the member who may not hunt the quest).</summary>
    public uint Subject { get; }

    /// <summary>Applied, or a duplicate of what already is: the request is satisfied.</summary>
    public bool Ok => Outcome != PartyOutcome.Rejected;

    public bool Applied => Outcome == PartyOutcome.Applied;

    public override string ToString() => $"{Outcome}{(Error != PartyError.None ? " " + Error : string.Empty)} party {Party?.Id ?? 0}";
}

/// <summary>What a quest needs of a party: that the server can run it, that this many hunters may take it, that each of them may.</summary>
public readonly record struct QuestVerdict(PartyError Error, uint Subject = 0)
{
    public static QuestVerdict Ok => default;

    public bool Allowed => Error == PartyError.None;
}

public interface IQuestGate
{
    /// <summary>Whether <paramref name="members"/> may hunt <paramref name="questId"/> (a hunt level) together, with a party of at most
    /// <paramref name="maxMembers"/>.</summary>
    QuestVerdict Check(int questId, IReadOnlyList<MemberView> members, int maxMembers);
}

/// <summary>Any positive quest id is fine (tests, and a server with no hunt catalog).</summary>
public sealed class OpenQuestGate : IQuestGate
{
    public QuestVerdict Check(int questId, IReadOnlyList<MemberView> members, int maxMembers)
        => questId > 0 ? QuestVerdict.Ok : new QuestVerdict(PartyError.QuestUnknown);
}

/// <summary>The bounds of a party: how many hunters, how long the "enter battle" countdown is.</summary>
public sealed class PartyOptions
{
    /// <summary>The configured limit for party membership.</summary>
    public int MaxMembers { get; init; } = 4;

    /// <summary>The delay after all members are ready.</summary>
    public global::System.TimeSpan Countdown { get; init; } = global::System.TimeSpan.FromSeconds(5);
}
