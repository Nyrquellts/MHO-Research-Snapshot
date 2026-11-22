// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>
/// Every party on the server and the rules for changing them -- the smallest model co-op needs: create, join, leave, kick, a new leader, a quest, ready
/// and unready, the countdown to the hunt, and the hunt's lifecycle as the party sees it (<see cref="PartyState"/>). Pure state: it holds no
/// connection and sends nothing. Every call returns a <see cref="PartyResult"/> -- what happened, or why not, plus the events the wire layer tells the
/// members about -- and a refused or repeated request leaves the party exactly as it was.
///
/// The server owns all of it: who leads, which quest, who is ready, when the hunt starts and under which session id. A client asks; this decides.
/// One lock guards the book (party operations are rare next to a hunt's traffic); nothing is called from inside it except the two small callbacks
/// (<c>hunting</c>, <c>sessionIds</c>), so a caller may hold no lock of its own when it calls in, and results are dispatched after the lock is released.
/// </summary>
public sealed class PartyBook
{
    private sealed class Member
    {
        public uint Id;
        public string Name;
        public uint Level;
        public bool Ready;
    }

    private sealed class Party
    {
        public long Id;
        public string Name;
        public uint LeaderId;
        public int MaxMembers;
        public readonly List<Member> Members = new();
        public int QuestId;
        public PartyState State;
        public long SessionId;
        public long Token, CompletedToken;
        public long Version;
        public long CreatedUnix;
    }

    private readonly object _lock = new();
    private readonly Dictionary<long, Party> _parties = new();
    private readonly Dictionary<uint, Party> _byMember = new();
    private readonly PartyOptions _options;
    private readonly IQuestGate _gate;
    private readonly Func<uint, bool> _hunting;
    private readonly Func<long> _sessionIds;
    private long _lastParty, _lastToken, _lastSession;
    private long _duplicates, _rejections;

    /// <param name="hunting">Is this hunter in a hunt of their own (one no party made)? Asked under the book's lock: it must not call back in.</param>
    /// <param name="sessionIds">The next hunt session id (the server's one source of them); a counter of the book's own when null.</param>
    public PartyBook(PartyOptions options = null, IQuestGate gate = null, Func<uint, bool> hunting = null, Func<long> sessionIds = null)
    {
        _options = options ?? new PartyOptions();
        _gate = gate ?? new OpenQuestGate();
        _hunting = hunting ?? (_ => false);
        _sessionIds = sessionIds ?? (() => ++_lastSession);
    }

    public PartyOptions Options => _options;

    /// <summary>Opens the hunt of a party whose countdown ran out, in the same critical section that moves the party to loading: a party that shows Loading always
    /// has its hunt, and a member who leaves in the next instant leaves a hunt that exists. It runs under the book's lock, so it must not call back into the book.</summary>
    public Action<PartyView> HuntOpener { get; set; }

    /// <summary>Parties that exist now (a closed party is gone).</summary>
    public int Count
    {
        get
        {
            lock (_lock)
                return _parties.Count;
        }
    }

    /// <summary>Requests that repeated something that already was, and requests that were refused: bounded counters for the session report.</summary>
    public long Duplicates => Interlocked.Read(ref _duplicates);

    public long Rejections => Interlocked.Read(ref _rejections);

    // -- reading ---------------------------------------------------------------------------------------------------------------
    public PartyView FindByMember(uint characterId)
    {
        lock (_lock)
            return _byMember.TryGetValue(characterId, out Party p) ? View(p) : null;
    }

    public PartyView Get(long partyId)
    {
        lock (_lock)
            return _parties.TryGetValue(partyId, out Party p) ? View(p) : null;
    }

    public IReadOnlyList<PartyView> All()
    {
        lock (_lock)
            return _parties.Values.OrderBy(p => p.Id).Select(View).ToList();
    }

    // -- forming ---------------------------------------------------------------------------------------------------------------
    /// <summary>A new party with <paramref name="leader"/> in it. A hunter who leads one already gets it back (a repeated create); one who is in
    /// another party, or in a hunt, is refused. <paramref name="maxMembers"/> is what the client asked for, held to the server's own bound.</summary>
    public PartyResult Create(PartyMemberInfo leader, string name = null, int maxMembers = 0)
    {
        lock (_lock)
        {
            if (leader.CharacterId == 0)
                return Reject(PartyError.UnknownCharacter);
            if (_byMember.TryGetValue(leader.CharacterId, out Party mine))
                return mine.LeaderId == leader.CharacterId && PartyStates.InTown(mine.State) ? Duplicate(mine) : Reject(PartyError.AlreadyInParty, mine);
            if (_hunting(leader.CharacterId))
                return Reject(PartyError.InHunt);

            int cap = maxMembers > 0 ? Math.Min(maxMembers, _options.MaxMembers) : _options.MaxMembers;
            Party p = new()
            {
                Id = ++_lastParty,
                Name = string.IsNullOrWhiteSpace(name) ? leader.Name : name.Trim(),
                LeaderId = leader.CharacterId,
                MaxMembers = Math.Max(1, cap),
                State = PartyState.Forming,
                CreatedUnix = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
            };
            p.Members.Add(new Member { Id = leader.CharacterId, Name = leader.Name ?? string.Empty, Level = leader.Level });
            _parties[p.Id] = p;
            _byMember[leader.CharacterId] = p;
            p.Version++;
            return Applied(p, new PartyEvent(PartyEventKind.Created, p.Id, leader.CharacterId));
        }
    }

    /// <summary>Joins party <paramref name="partyId"/>. The party the hunter is in already is a duplicate; another one is refused, as is a party that is
    /// full, gone (a stale id) or no longer in town.</summary>
    public PartyResult Join(PartyMemberInfo who, long partyId)
    {
        lock (_lock)
            return JoinLocked(who, _parties.TryGetValue(partyId, out Party p) ? p : null);
    }

    /// <summary>Joins the party <paramref name="memberId"/> is in.</summary>
    public PartyResult JoinPartyOf(PartyMemberInfo who, uint memberId)
    {
        lock (_lock)
            return JoinLocked(who, _byMember.TryGetValue(memberId, out Party p) ? p : null);
    }

    private PartyResult JoinLocked(PartyMemberInfo who, Party target)
    {
        if (who.CharacterId == 0)
            return Reject(PartyError.UnknownCharacter);
        if (_byMember.TryGetValue(who.CharacterId, out Party mine))
            return mine == target ? Duplicate(mine) : Reject(PartyError.AlreadyInParty, mine);
        if (target == null)
            return Reject(PartyError.NoSuchParty);
        if (_hunting(who.CharacterId))
            return Reject(PartyError.InHunt, target);
        if (!PartyStates.InTown(target.State))
            return Reject(PartyError.WrongState, target);
        if (target.Members.Count >= target.MaxMembers)
            return Reject(PartyError.Full, target);

        // a new face changes who must be ready and whether the quest is legal for this many: the countdown starts over
        List<PartyEvent> events = new();
        CancelCountdown(target, events);
        target.Members.Add(new Member { Id = who.CharacterId, Name = who.Name ?? string.Empty, Level = who.Level });
        _byMember[who.CharacterId] = target;
        target.Version++;
        events.Add(new PartyEvent(PartyEventKind.MemberJoined, target.Id, who.CharacterId));
        return Applied(target, events);
    }

    /// <summary>Leaves the party (<paramref name="partyId"/> 0: whichever it is). A hunter in none is a duplicate; a party id that is not theirs is a stale
    /// request and is refused without touching the party they are in. The leader leaving hands the lead on; the last one leaving closes the party.
    /// In a hunt the hunter leaves the hunt too -- the caller sees <see cref="PartyEventKind.MemberLeft"/> and takes them out of the session.</summary>
    public PartyResult Leave(uint characterId, long partyId = 0)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(characterId, out Party p))
                return Duplicate(null);                       // leaving what they are not in (a repeated leave, or a late one)
            if (partyId != 0 && p.Id != partyId)
                return Reject(PartyError.NoSuchParty, p);
            List<PartyEvent> events = new();
            Remove(p, p.Members.First(m => m.Id == characterId), kicked: false, events);
            return Applied(p, events);
        }
    }

    /// <summary>The leader removes a member (in town only).</summary>
    public PartyResult Kick(uint actorId, uint targetId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            if (!PartyStates.InTown(p.State))
                return Reject(PartyError.WrongState, p);
            Member target = p.Members.FirstOrDefault(m => m.Id == targetId);
            if (target == null || targetId == actorId)
                return Reject(PartyError.UnknownCharacter, p, targetId);
            List<PartyEvent> events = new();
            Remove(p, target, kicked: true, events);
            return Applied(p, events);
        }
    }

    /// <summary>The leader hands the lead to another member (in town only). The one who leads already is a duplicate.</summary>
    public PartyResult TransferLeader(uint actorId, uint newLeaderId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            if (!PartyStates.InTown(p.State))
                return Reject(PartyError.WrongState, p);
            if (p.Members.All(m => m.Id != newLeaderId))
                return Reject(PartyError.UnknownCharacter, p, newLeaderId);
            if (newLeaderId == p.LeaderId)
                return Duplicate(p);
            List<PartyEvent> events = new();
            CancelCountdown(p, events);
            p.LeaderId = newLeaderId;
            p.Version++;
            events.Add(new PartyEvent(PartyEventKind.LeaderChanged, p.Id, newLeaderId));
            return Applied(p, events);
        }
    }

    /// <summary>The leader disbands the party (any state): everyone is out and the party is closed.</summary>
    public PartyResult Disband(uint actorId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            List<PartyEvent> events = new();
            Close(p, events);
            return Applied(p, events);
        }
    }

    // -- the lobby -------------------------------------------------------------------------------------------------------------
    /// <summary>The leader picks the quest (a hunt level): the party moves to the lobby and nobody is ready any more. The quest it has is a duplicate.
    /// Refused when the quest is not one the server can run, not legal for this party, or a member may not hunt it.</summary>
    public PartyResult SelectQuest(uint actorId, int questId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            if (!PartyStates.InTown(p.State))
                return Reject(PartyError.WrongState, p);
            if (p.State == PartyState.Lobby && p.QuestId == questId)
                return Duplicate(p);
            QuestVerdict verdict = _gate.Check(questId, Members(p), p.MaxMembers);
            if (!verdict.Allowed)
                return Reject(verdict.Error, p, verdict.Subject);

            List<PartyEvent> events = new();
            CancelCountdown(p, events);
            foreach (Member m in p.Members)
                m.Ready = false;
            p.QuestId = questId;
            if (!Move(p, PartyState.Lobby, events))
                return Reject(PartyError.WrongState, p);
            p.Version++;
            events.Add(new PartyEvent(PartyEventKind.QuestSelected, p.Id, actorId, questId));
            return Applied(p, events);
        }
    }

    /// <summary>The leader takes the quest off the table: back to forming, nobody ready.</summary>
    public PartyResult ClearQuest(uint actorId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            if (p.State == PartyState.Forming)
                return Duplicate(p);
            if (p.State != PartyState.Lobby)
                return Reject(PartyError.WrongState, p);
            List<PartyEvent> events = new();
            CancelCountdown(p, events);
            foreach (Member m in p.Members)
                m.Ready = false;
            p.QuestId = 0;
            if (!Move(p, PartyState.Forming, events))
                return Reject(PartyError.WrongState, p);
            p.Version++;
            events.Add(new PartyEvent(PartyEventKind.QuestCleared, p.Id, actorId));
            return Applied(p, events);
        }
    }

    /// <summary>A member readies up or takes it back (lobby only). The same again is a duplicate. Taking it back stops a countdown that is running.</summary>
    public PartyResult SetReady(uint characterId, bool ready)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(characterId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.State == PartyState.Forming)
                return Reject(PartyError.NoQuest, p);
            if (p.State != PartyState.Lobby)
                return Reject(PartyError.WrongState, p);
            Member m = p.Members.First(x => x.Id == characterId);
            if (m.Ready == ready)
                return Duplicate(p);
            List<PartyEvent> events = new();
            m.Ready = ready;
            if (!ready)
                CancelCountdown(p, events);
            p.Version++;
            events.Add(new PartyEvent(PartyEventKind.ReadyChanged, p.Id, characterId, ready ? 1 : 0));
            return Applied(p, events);
        }
    }

    /// <summary>The leader starts the "enter battle" countdown (lobby, a quest chosen, every member ready, the quest legal for them). One already running
    /// is a duplicate -- a second start request while the first is being processed starts nothing. The result carries the countdown's token: the caller
    /// runs the timer and calls <see cref="CompleteCountdown"/> with it.</summary>
    public PartyResult BeginCountdown(uint actorId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            if (p.State == PartyState.Forming)
                return Reject(PartyError.NoQuest, p);
            if (p.State != PartyState.Lobby)
                return Reject(PartyError.WrongState, p);
            if (p.Token != 0)
                return Duplicate(p);
            if (!p.Members.All(m => m.Ready))
                return Reject(PartyError.NotAllReady, p);
            QuestVerdict verdict = _gate.Check(p.QuestId, Members(p), p.MaxMembers);
            if (!verdict.Allowed)
                return Reject(verdict.Error, p, verdict.Subject);

            p.Token = ++_lastToken;
            p.Version++;
            return Applied(p, new PartyEvent(PartyEventKind.CountdownStarted, p.Id, actorId, p.Token));
        }
    }

    /// <summary>The leader stops the countdown. None running is a duplicate.</summary>
    public PartyResult CancelCountdown(uint actorId)
    {
        lock (_lock)
        {
            if (!_byMember.TryGetValue(actorId, out Party p))
                return Reject(PartyError.NotInParty);
            if (p.LeaderId != actorId)
                return Reject(PartyError.NotLeader, p);
            List<PartyEvent> events = new();
            if (!CancelCountdown(p, events))
                return Duplicate(p);
            p.Version++;
            return Applied(p, events);
        }
    }

    /// <summary>The countdown ran out: the party goes to loading with a new hunt session id, once. The token ties the call to the countdown that armed it --
    /// a timer left over from one that was cancelled (or replaced) finds no such countdown and is refused; the countdown that already completed is a
    /// duplicate (same session id back).</summary>
    public PartyResult CompleteCountdown(long partyId, long token)
    {
        lock (_lock)
        {
            if (!_parties.TryGetValue(partyId, out Party p))
                return Reject(PartyError.NoSuchParty);
            if (token != 0 && token == p.CompletedToken && p.SessionId != 0)
                return Duplicate(p, p.SessionId);
            if (p.State != PartyState.Lobby || p.Token == 0 || p.Token != token)
                return Reject(PartyError.WrongState, p);
            if (!p.Members.All(m => m.Ready))
                return Reject(PartyError.NotAllReady, p);
            QuestVerdict verdict = _gate.Check(p.QuestId, Members(p), p.MaxMembers);
            if (!verdict.Allowed)
                return Reject(verdict.Error, p, verdict.Subject);

            List<PartyEvent> events = new();
            p.CompletedToken = p.Token;
            p.Token = 0;
            p.SessionId = _sessionIds();
            if (!Move(p, PartyState.Loading, events))
                return Reject(PartyError.WrongState, p);
            p.Version++;
            events.Add(new PartyEvent(PartyEventKind.HuntStarted, p.Id, p.LeaderId, p.SessionId));
            PartyResult started = Applied(p, events, p.SessionId);
            HuntOpener?.Invoke(started.Party);
            return started;
        }
    }

    // -- the hunt, as the party sees it ----------------------------------------------------------------------------------------
    /// <summary>The hunt session reports how far it is: <paramref name="to"/> is one of ReadyInHunt, Active, Resolving, Returning. A session id that is
    /// not the party's (a stale report) is refused; the state it is in already is a duplicate; going back or skipping a step the table does not allow
    /// is refused.</summary>
    public PartyResult Advance(long partyId, long sessionId, PartyState to)
    {
        lock (_lock)
        {
            if (!_parties.TryGetValue(partyId, out Party p))
                return Reject(PartyError.NoSuchParty);
            if (p.SessionId == 0 || p.SessionId != sessionId)
                return Reject(PartyError.StaleSession, p);
            if (to is not (PartyState.ReadyInHunt or PartyState.Active or PartyState.Resolving or PartyState.Returning))
                return Reject(PartyError.WrongState, p);
            if (p.State == to)
                return Duplicate(p);
            List<PartyEvent> events = new();
            if (!Move(p, to, events))
                return Reject(PartyError.WrongState, p);
            p.Version++;
            return Applied(p, events);
        }
    }

    /// <summary>The hunt is over for everyone: the party goes on in town (quest cleared, nobody ready) or, with no member left, closes. The session id must
    /// be the party's; a repeat after the party moved on is a duplicate.</summary>
    public PartyResult SessionEnded(long partyId, long sessionId)
    {
        lock (_lock)
        {
            if (!_parties.TryGetValue(partyId, out Party p))
                return Duplicate(null);
            if (p.SessionId == 0)
                return Duplicate(p);
            if (p.SessionId != sessionId)
                return Reject(PartyError.StaleSession, p);
            List<PartyEvent> events = new();
            if (p.State != PartyState.Returning && !Move(p, PartyState.Returning, events))
                return Reject(PartyError.WrongState, p);
            p.SessionId = 0;
            p.QuestId = 0;
            foreach (Member m in p.Members)
                m.Ready = false;
            if (p.Members.Count == 0)
                Close(p, events);
            else
                Move(p, PartyState.Forming, events);
            p.Version++;
            return Applied(p, events);
        }
    }

    // -- internals (under the lock) ----------------------------------------------------------------------------------------------
    private void Remove(Party p, Member member, bool kicked, List<PartyEvent> events)
    {
        CancelCountdown(p, events);
        p.Members.Remove(member);
        _byMember.Remove(member.Id);
        events.Add(new PartyEvent(kicked ? PartyEventKind.MemberKicked : PartyEventKind.MemberLeft, p.Id, member.Id));
        if (p.Members.Count == 0)
        {
            Close(p, events);
            return;
        }
        if (p.LeaderId == member.Id)
        {
            // the longest-standing member takes over
            p.LeaderId = p.Members[0].Id;
            events.Add(new PartyEvent(PartyEventKind.LeaderChanged, p.Id, p.LeaderId));
        }
        p.Version++;
    }

    private void Close(Party p, List<PartyEvent> events)
    {
        CancelCountdown(p, events);
        foreach (Member m in p.Members)
            _byMember.Remove(m.Id);
        Move(p, PartyState.Closed, events);
        events.Add(new PartyEvent(PartyEventKind.Disbanded, p.Id, p.LeaderId));
        _parties.Remove(p.Id);
        p.Version++;
    }

    /// <summary>Stops a running countdown (a new face, a member who is not ready any more, a new quest, a new leader, a member gone).</summary>
    private bool CancelCountdown(Party p, List<PartyEvent> events)
    {
        if (p.Token == 0)
            return false;
        events.Add(new PartyEvent(PartyEventKind.CountdownCancelled, p.Id, 0, p.Token));
        p.Token = 0;
        return true;
    }

    private bool Move(Party p, PartyState to, List<PartyEvent> events)
    {
        if (p.State == to)
            return true;
        if (!PartyStates.CanMove(p.State, to))
            return false;
        p.State = to;
        events.Add(new PartyEvent(PartyEventKind.StateChanged, p.Id, 0, (long)to));
        return true;
    }

    private static IReadOnlyList<MemberView> Members(Party p) => p.Members.Select(m => new MemberView(m.Id, m.Name, m.Level, m.Ready)).ToList();

    private static PartyView View(Party p) => new(p.Id, p.Name, p.LeaderId, Members(p), p.QuestId, p.State, p.SessionId, p.Token, p.MaxMembers, p.Version, p.CreatedUnix);

    private static PartyResult Applied(Party p, PartyEvent one, long session = 0) => Applied(p, new List<PartyEvent> { one }, session);

    private static PartyResult Applied(Party p, List<PartyEvent> events, long session = 0) => new(PartyOutcome.Applied, PartyError.None, View(p), events, session);

    private PartyResult Duplicate(Party p, long session = 0)
    {
        Interlocked.Increment(ref _duplicates);
        return new PartyResult(PartyOutcome.Duplicate, PartyError.None, p == null ? null : View(p), sessionId: session);
    }

    private PartyResult Reject(PartyError error, Party p = null, uint subject = 0)
    {
        Interlocked.Increment(ref _rejections);
        return new PartyResult(PartyOutcome.Rejected, error, p == null ? null : View(p), subject: subject);
    }
}
