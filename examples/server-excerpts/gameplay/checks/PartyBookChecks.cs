// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>The party model: who is in it, who leads, which quest, who is ready, and the lifecycle a party moves through. Pure state -- no client, no
/// socket -- so every rule is checked here, and a refused or repeated request is checked to leave the party exactly as it was.</summary>
public sealed class PartyBookTest
{
    private const int Quest = 11;

    private static PartyMemberInfo H(uint id, uint level = 10) => new(id, "Hunter" + id, level);

    private static PartyBook Book(int max = 4, IQuestGate gate = null, HashSet<uint> hunting = null, Func<long> sessions = null)
        => new(new PartyOptions { MaxMembers = max }, gate, hunting == null ? null : id => hunting.Contains(id), sessions);

    /// <summary>A party of the given hunters (the first leads), in the lobby with the quest chosen.</summary>
    private static PartyView Lobby(PartyBook book, params uint[] ids)
    {
        PartyView party = book.Create(H(ids[0])).Party;
        foreach (uint id in ids.Skip(1))
            Assert.True(book.Join(H(id), party.Id).Applied);
        Assert.True(book.SelectQuest(ids[0], Quest).Applied);
        return book.Get(party.Id);
    }

    private static PartyView AllReady(PartyBook book, PartyView party)
    {
        foreach (MemberView m in party.Members)
            Assert.True(book.SetReady(m.CharacterId, true).Ok);
        return book.Get(party.Id);
    }

    /// <summary>The party after its countdown ran out: loading, one hunt session id.</summary>
    private static PartyView Loading(PartyBook book, params uint[] ids)
    {
        PartyView party = AllReady(book, Lobby(book, ids));
        PartyResult begun = book.BeginCountdown(party.LeaderId);
        Assert.True(begun.Applied);
        PartyResult done = book.CompleteCountdown(party.Id, begun.Party.CountdownToken);
        Assert.True(done.Applied);
        Assert.Equal(PartyState.Loading, done.Party.State);
        return done.Party;
    }

    // -- create ------------------------------------------------------------------------------------------------------------------
    [Check]
    public void Create_MakesAPartyOfOne_WithTheCreatorLeadingItInFormingState()
    {
        PartyBook book = Book();
        PartyResult result = book.Create(H(1));
        Assert.True(result.Applied);
        PartyView party = result.Party;
        Assert.Equal((1u, PartyState.Forming, 0, 0L), (party.LeaderId, party.State, party.QuestId, party.SessionId));
        Assert.Equal(new uint[] { 1 }, party.Members.Select(m => m.CharacterId).ToArray());
        Assert.False(party.Members[0].Ready);
        Assert.Equal(PartyEventKind.Created, Assert.Single(result.Events).Kind);
        Assert.Equal(party.Id, book.FindByMember(1).Id);                              // and reachable by any member
        Assert.Equal(1, book.Count);
    }

    [Check]
    public void Create_Twice_IsADuplicate_TheSamePartyBack()
    {
        PartyBook book = Book();
        PartyView first = book.Create(H(1)).Party;
        PartyResult again = book.Create(H(1));
        Assert.Equal(PartyOutcome.Duplicate, again.Outcome);
        Assert.Equal(first.Id, again.Party.Id);
        Assert.Equal(1, book.Count);
        Assert.Empty(again.Events);
        Assert.Equal(1, book.Duplicates);
    }

    [Check]
    public void Create_WhileInAnotherPartyOrAHuntOrWithNoId_IsRefused()
    {
        PartyBook book = Book(hunting: new HashSet<uint> { 9 });
        PartyView first = book.Create(H(1)).Party;
        book.Join(H(2), first.Id);
        PartyResult member = book.Create(H(2));                                      // a member of someone else's party
        Assert.Equal((PartyOutcome.Rejected, PartyError.AlreadyInParty), (member.Outcome, member.Error));
        Assert.Equal(first.Id, member.Party.Id);                                     // and told which one
        Assert.Equal(PartyError.InHunt, book.Create(H(9)).Error);                    // in a solo hunt
        Assert.Equal(PartyError.UnknownCharacter, book.Create(H(0)).Error);
        Assert.Equal(1, book.Count);
    }

    [Check]
    public void Create_HoldsTeamSizeToTheConfiguredBound()
    {
        PartyBook book = Book(max: 3);
        Assert.Equal(3, book.Create(H(1), maxMembers: 12).Party.MaxMembers);
        Assert.Equal(2, book.Create(H(2), maxMembers: 2).Party.MaxMembers);
        Assert.Equal(3, book.Create(H(3)).Party.MaxMembers);
        Assert.Equal(1, Book(max: 0).Create(H(1)).Party.MaxMembers);
    }

    // -- join --------------------------------------------------------------------------------------------------------------------
    [Check]
    public void Join_PutsTheHunterInTheParty_AndTheLeaderStaysTheLeader()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        PartyResult joined = book.Join(H(2), party.Id);
        Assert.True(joined.Applied);
        Assert.Equal(new uint[] { 1, 2 }, joined.Party.Members.Select(m => m.CharacterId).ToArray());
        Assert.Equal(1u, joined.Party.LeaderId);
        Assert.Equal((PartyEventKind.MemberJoined, 2u), (joined.Events[0].Kind, joined.Events[0].CharacterId));
        Assert.Equal(party.Id, book.FindByMember(2).Id);
        Assert.True(book.JoinPartyOf(H(3), 2).Applied);                              // the wire names a player, not a party
        Assert.Equal(3, book.Get(party.Id).Members.Count);
    }

    [Check]
    public void Join_TheSamePartyAgain_IsADuplicate_AnotherPartyIsRefused()
    {
        PartyBook book = Book();
        PartyView a = book.Create(H(1)).Party, b = book.Create(H(5)).Party;
        book.Join(H(2), a.Id);
        PartyView before = book.Get(a.Id);
        PartyResult dup = book.Join(H(2), a.Id);
        Assert.Equal(PartyOutcome.Duplicate, dup.Outcome);
        Assert.Equal(before.Version, book.Get(a.Id).Version);                        // nothing changed
        PartyResult other = book.Join(H(2), b.Id);
        Assert.Equal(PartyError.AlreadyInParty, other.Error);
        Assert.Single(book.Get(b.Id).Members);
        Assert.Equal(2, book.Get(a.Id).Members.Count);
    }

    [Check]
    public void Join_AStaleOrInventedOrClosedPartyId_IsRefused()
    {
        PartyBook book = Book();
        Assert.Equal(PartyError.NoSuchParty, book.Join(H(2), 12345).Error);
        Assert.Equal(PartyError.NoSuchParty, book.Join(H(2), -1).Error);
        PartyView party = book.Create(H(1)).Party;
        book.Leave(1);                                                               // the only member leaves: the party is closed and gone
        PartyResult closed = book.Join(H(2), party.Id);
        Assert.Equal(PartyError.NoSuchParty, closed.Error);
        Assert.Equal(0, book.Count);
        Assert.Equal(PartyError.NoSuchParty, book.JoinPartyOf(H(2), 1).Error);       // nobody by that id is in a party
        Assert.Equal(PartyError.UnknownCharacter, book.Join(H(0), party.Id).Error);
    }

    [Check]
    public void Join_AFullParty_IsRefused_AndTheLimitHoldsUnderAnyOrder()
    {
        PartyBook book = Book(max: 2);
        PartyView party = book.Create(H(1)).Party;
        Assert.True(book.Join(H(2), party.Id).Applied);
        PartyResult full = book.Join(H(3), party.Id);
        Assert.Equal(PartyError.Full, full.Error);
        Assert.Equal(2, book.Get(party.Id).Members.Count);
        Assert.Null(book.FindByMember(3));
        book.Leave(2);
        Assert.True(book.Join(H(3), party.Id).Applied);                              // room again
    }

    [Check]
    public void Join_WhileTheHunterIsInASoloHunt_OrThePartyHasLeftTown_IsRefused()
    {
        PartyBook book = Book(hunting: new HashSet<uint> { 7 });
        PartyView party = Lobby(book, 1, 2);
        Assert.Equal(PartyError.InHunt, book.Join(H(7), party.Id).Error);
        PartyView loading = Loading(book, 3, 4);
        Assert.Equal(PartyError.WrongState, book.Join(H(8), loading.Id).Error);       // no joining a hunt that has begun
        Assert.Equal(2, book.Get(loading.Id).Members.Count);
    }

    [Check]
    public void Join_StopsTheCountdown_ANewFaceMeansEveryoneReadiesAgain()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        Assert.True(book.BeginCountdown(1).Applied);
        PartyResult joined = book.Join(H(3), party.Id);
        Assert.Contains(joined.Events, e => e.Kind == PartyEventKind.CountdownCancelled);
        Assert.False(joined.Party.Counting);
        Assert.False(joined.Party.AllReady);                                          // the newcomer is not ready
    }

    // -- leave -------------------------------------------------------------------------------------------------------------------
    [Check]
    public void Leave_ATwiceRepeatedLeave_IsADuplicate_AndNeverTouchesTheRest()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        book.Join(H(2), party.Id);
        Assert.True(book.Leave(2).Applied);
        PartyView after = book.Get(party.Id);
        PartyResult again = book.Leave(2);
        Assert.Equal(PartyOutcome.Duplicate, again.Outcome);
        Assert.Equal(after.Version, book.Get(party.Id).Version);
        Assert.Equal(PartyOutcome.Duplicate, book.Leave(99).Outcome);                // never in one
        Assert.Equal(new uint[] { 1 }, book.Get(party.Id).Members.Select(m => m.CharacterId).ToArray());
    }

    [Check]
    public void Leave_NamingAPartyThatIsNotTheirs_IsStale_AndDoesNotTakeThemOutOfTheirOwn()
    {
        PartyBook book = Book();
        PartyView a = book.Create(H(1)).Party, b = book.Create(H(5)).Party;
        PartyResult stale = book.Leave(1, b.Id);
        Assert.Equal(PartyError.NoSuchParty, stale.Error);
        Assert.NotNull(book.FindByMember(1));
        Assert.True(book.Leave(1, a.Id).Applied);
        Assert.Null(book.FindByMember(1));
    }

    [Check]
    public void Leave_TheLeader_HandsTheLeadToTheLongestStandingMember_TheLastOneClosesTheParty()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        book.Join(H(2), party.Id);
        book.Join(H(3), party.Id);
        PartyResult left = book.Leave(1);
        Assert.Equal(2u, left.Party.LeaderId);
        Assert.Contains(left.Events, e => e.Kind == PartyEventKind.LeaderChanged && e.CharacterId == 2);
        Assert.Contains(left.Events, e => e.Kind == PartyEventKind.MemberLeft && e.CharacterId == 1);
        book.Leave(2);
        PartyResult last = book.Leave(3);
        Assert.Equal(PartyState.Closed, last.Party.State);
        Assert.Contains(last.Events, e => e.Kind == PartyEventKind.Disbanded);
        Assert.Equal(0, book.Count);
        Assert.Null(book.Get(party.Id));
        Assert.Null(book.FindByMember(3));
    }

    [Check]
    public void Leave_ALeavingMember_StopsTheCountdown_AndTheOthersStayReady()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2, 3));
        Assert.True(book.BeginCountdown(1).Applied);
        PartyResult left = book.Leave(3);
        Assert.Contains(left.Events, e => e.Kind == PartyEventKind.CountdownCancelled);
        Assert.True(left.Party.Members.All(m => m.Ready));
        Assert.False(left.Party.Counting);
    }

    // -- kick and leader transfer ----------------------------------------------------------------------------------------------
    [Check]
    public void Kick_IsTheLeadersToDo_OnAMemberOtherThanThemselves_InTownOnly()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2, 3);
        Assert.Equal(PartyError.NotLeader, book.Kick(2, 3).Error);
        Assert.Equal(PartyError.UnknownCharacter, book.Kick(1, 99).Error);
        Assert.Equal(PartyError.UnknownCharacter, book.Kick(1, 1).Error);
        Assert.Equal(PartyError.NotInParty, book.Kick(77, 1).Error);
        Assert.Equal(3, book.Get(party.Id).Members.Count);
        PartyResult kicked = book.Kick(1, 3);
        Assert.True(kicked.Applied);
        Assert.Contains(kicked.Events, e => e.Kind == PartyEventKind.MemberKicked && e.CharacterId == 3);
        Assert.Null(book.FindByMember(3));
        PartyView hunt = Loading(book, 10, 11);
        Assert.Equal(PartyError.WrongState, book.Kick(10, 11).Error);
        Assert.Equal(2, book.Get(hunt.Id).Members.Count);
    }

    [Check]
    public void TransferLeader_ToAMember_ChangesTheLead_ANonLeaderOrANonMemberChangesNothing()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2, 3);
        Assert.Equal(PartyError.NotLeader, book.TransferLeader(2, 3).Error);
        Assert.Equal(PartyError.UnknownCharacter, book.TransferLeader(1, 99).Error);
        Assert.Equal(PartyOutcome.Duplicate, book.TransferLeader(1, 1).Outcome);
        Assert.Equal(1u, book.Get(party.Id).LeaderId);
        PartyResult moved = book.TransferLeader(1, 3);
        Assert.True(moved.Applied);
        Assert.Equal(3u, moved.Party.LeaderId);
        Assert.Equal(PartyError.NotLeader, book.SelectQuest(1, Quest + 1).Error);     // the old leader no longer decides
        Assert.True(book.SelectQuest(3, Quest + 1).Applied);
    }

    [Check]
    public void TransferLeader_DuringACountdown_StopsIt()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        Assert.True(book.BeginCountdown(1).Applied);
        PartyResult moved = book.TransferLeader(1, 2);
        Assert.Contains(moved.Events, e => e.Kind == PartyEventKind.CountdownCancelled);
        Assert.False(moved.Party.Counting);
    }

    [Check]
    public void Disband_IsTheLeadersToDo_AndEveryoneIsOut()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2);
        Assert.Equal(PartyError.NotLeader, book.Disband(2).Error);
        PartyResult gone = book.Disband(1);
        Assert.Equal(PartyState.Closed, gone.Party.State);
        Assert.Null(book.FindByMember(1));
        Assert.Null(book.FindByMember(2));
        Assert.Equal(0, book.Count);
        Assert.Equal(PartyError.NotInParty, book.Disband(1).Error);
    }

    // -- the quest ---------------------------------------------------------------------------------------------------------------
    [Check]
    public void SelectQuest_IsTheLeadersToDo_MovesToTheLobby_AndNobodyIsReady()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        book.Join(H(2), party.Id);
        Assert.Equal(PartyError.NotLeader, book.SelectQuest(2, Quest).Error);
        Assert.Equal(PartyState.Forming, book.Get(party.Id).State);
        Assert.Equal(0, book.Get(party.Id).QuestId);
        PartyResult chosen = book.SelectQuest(1, Quest);
        Assert.True(chosen.Applied);
        Assert.Equal((PartyState.Lobby, Quest), (chosen.Party.State, chosen.Party.QuestId));
        Assert.Contains(chosen.Events, e => e.Kind == PartyEventKind.QuestSelected && e.Detail == Quest);
        Assert.Equal(PartyError.NotInParty, book.SelectQuest(77, Quest).Error);
    }

    [Check]
    public void SelectQuest_TheSameQuestAgain_IsADuplicate_ANewOneClearsTheReadyFlags()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2);
        book.SetReady(2, true);
        PartyResult same = book.SelectQuest(1, Quest);
        Assert.Equal(PartyOutcome.Duplicate, same.Outcome);
        Assert.True(book.Get(party.Id).Member(2).Ready);                             // untouched
        PartyResult other = book.SelectQuest(1, Quest + 5);
        Assert.True(other.Applied);
        Assert.All(other.Party.Members, m => Assert.False(m.Ready));
    }

    private sealed class Gate : IQuestGate
    {
        public HashSet<int> Known { get; } = new() { Quest, Quest + 5 };
        public uint Refuses;

        public QuestVerdict Check(int questId, IReadOnlyList<MemberView> members, int maxMembers)
        {
            if (!Known.Contains(questId))
                return new QuestVerdict(PartyError.QuestUnknown);
            if (members.Count > 2)
                return new QuestVerdict(PartyError.QuestIllegal);
            MemberView barred = members.FirstOrDefault(m => m.CharacterId == Refuses);
            return barred != null ? new QuestVerdict(PartyError.NotEligible, barred.CharacterId) : QuestVerdict.Ok;
        }
    }

    [Check]
    public void SelectQuest_ThatTheServerCannotRunIsNotLegalForTheParty_OrABarredMember_IsRefused()
    {
        Gate gate = new();
        PartyBook book = Book(gate: gate);
        PartyView party = book.Create(H(1)).Party;
        book.Join(H(2), party.Id);
        Assert.Equal(PartyError.QuestUnknown, book.SelectQuest(1, 555).Error);
        gate.Refuses = 2;
        PartyResult barred = book.SelectQuest(1, Quest);
        Assert.Equal((PartyError.NotEligible, 2u), (barred.Error, barred.Subject));
        Assert.Equal(PartyState.Forming, book.Get(party.Id).State);                  // nothing happened
        gate.Refuses = 0;
        book.Join(H(3), party.Id);
        Assert.Equal(PartyError.QuestIllegal, book.SelectQuest(1, Quest).Error);      // three hunters, a quest for two
        book.Leave(3);
        Assert.True(book.SelectQuest(1, Quest).Applied);
    }

    [Check]
    public void ClearQuest_GoesBackToForming_AndACountdownStops()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        Assert.True(book.BeginCountdown(1).Applied);
        Assert.Equal(PartyError.NotLeader, book.ClearQuest(2).Error);
        PartyResult cleared = book.ClearQuest(1);
        Assert.True(cleared.Applied);
        Assert.Equal((PartyState.Forming, 0), (cleared.Party.State, cleared.Party.QuestId));
        Assert.Contains(cleared.Events, e => e.Kind == PartyEventKind.CountdownCancelled);
        Assert.All(cleared.Party.Members, m => Assert.False(m.Ready));
        Assert.Equal(PartyOutcome.Duplicate, book.ClearQuest(1).Outcome);
    }

    // -- ready -------------------------------------------------------------------------------------------------------------------
    [Check]
    public void Ready_NeedsAQuest_AndTheSameAgainIsADuplicate()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        Assert.Equal(PartyError.NoQuest, book.SetReady(1, true).Error);              // nothing to be ready for
        book.SelectQuest(1, Quest);
        Assert.True(book.SetReady(1, true).Applied);
        long version = book.Get(party.Id).Version;
        PartyResult again = book.SetReady(1, true);
        Assert.Equal(PartyOutcome.Duplicate, again.Outcome);
        Assert.Equal(version, book.Get(party.Id).Version);
        Assert.Equal(PartyOutcome.Duplicate, book.SetReady(1, true).Outcome);
        Assert.True(book.SetReady(1, false).Applied);
        Assert.Equal(PartyOutcome.Duplicate, book.SetReady(1, false).Outcome);
        Assert.Equal(PartyError.NotInParty, book.SetReady(42, true).Error);
    }

    [Check]
    public void Unready_StopsTheCountdown()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        Assert.True(book.BeginCountdown(1).Applied);
        PartyResult off = book.SetReady(2, false);
        Assert.Contains(off.Events, e => e.Kind == PartyEventKind.CountdownCancelled);
        Assert.False(off.Party.Counting);
        Assert.Equal(PartyError.NotAllReady, book.BeginCountdown(1).Error);
    }

    // -- the countdown and the hunt's id ---------------------------------------------------------------------------------------------
    [Check]
    public void BeginCountdown_NeedsTheLeader_AQuestAndEveryoneReady_AndOnlyOneRuns()
    {
        PartyBook book = Book();
        PartyView party = book.Create(H(1)).Party;
        book.Join(H(2), party.Id);
        Assert.Equal(PartyError.NoQuest, book.BeginCountdown(1).Error);
        book.SelectQuest(1, Quest);
        Assert.Equal(PartyError.NotAllReady, book.BeginCountdown(1).Error);
        book.SetReady(1, true);
        book.SetReady(2, true);
        Assert.Equal(PartyError.NotLeader, book.BeginCountdown(2).Error);             // a non-leader cannot start it
        PartyResult begun = book.BeginCountdown(1);
        Assert.True(begun.Applied);
        Assert.True(begun.Party.Counting);
        long token = begun.Party.CountdownToken;
        PartyResult dup = book.BeginCountdown(1);
        Assert.Equal(PartyOutcome.Duplicate, dup.Outcome);                            // a second start while the first runs
        Assert.Equal(token, dup.Party.CountdownToken);
        Assert.Equal(PartyError.NotInParty, book.BeginCountdown(99).Error);
    }

    [Check]
    public void CompleteCountdown_GivesTheHuntItsOneSessionId_OnceEvenIfTheTimerFiresTwice()
    {
        long next = 100;
        PartyBook book = Book(sessions: () => ++next);
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        long token = book.BeginCountdown(1).Party.CountdownToken;
        PartyResult done = book.CompleteCountdown(party.Id, token);
        Assert.True(done.Applied);
        Assert.Equal(101, done.SessionId);
        Assert.Equal((PartyState.Loading, 101L), (done.Party.State, done.Party.SessionId));
        Assert.Contains(done.Events, e => e.Kind == PartyEventKind.HuntStarted && e.Detail == 101);
        PartyResult again = book.CompleteCountdown(party.Id, token);                 // the timer and a late second one
        Assert.Equal(PartyOutcome.Duplicate, again.Outcome);
        Assert.Equal(101, again.SessionId);
        Assert.Equal(101, book.Get(party.Id).SessionId);
        Assert.Equal(102, next + 1);                                                  // and no second id was drawn
        Assert.Equal(PartyError.WrongState, book.BeginCountdown(1).Error);            // a second hunt cannot start while this one runs
    }

    [Check]
    public void CompleteCountdown_ATimerOfACancelledCountdown_FindsNoCountdown()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2));
        long old = book.BeginCountdown(1).Party.CountdownToken;
        book.SetReady(2, false);                                                      // cancels it
        book.SetReady(2, true);
        long fresh = book.BeginCountdown(1).Party.CountdownToken;
        Assert.NotEqual(old, fresh);
        Assert.Equal(PartyError.WrongState, book.CompleteCountdown(party.Id, old).Error);
        Assert.Equal(PartyState.Lobby, book.Get(party.Id).State);
        Assert.Equal(PartyError.WrongState, book.CompleteCountdown(party.Id, 0).Error);
        Assert.Equal(PartyError.NoSuchParty, book.CompleteCountdown(9999, fresh).Error);
        Assert.True(book.CompleteCountdown(party.Id, fresh).Applied);
    }

    [Check]
    public void ManyStartRequestsAtOnce_MakeExactlyOneHunt()
    {
        PartyBook book = Book();
        PartyView party = AllReady(book, Lobby(book, 1, 2, 3, 4));
        List<PartyResult> results = new();
        Parallel.For(0, 32, _ =>
        {
            PartyResult begun = book.BeginCountdown(1);
            if (begun.Ok && begun.Party.CountdownToken != 0)
            {
                PartyResult done = book.CompleteCountdown(party.Id, begun.Party.CountdownToken);
                lock (results)
                    results.Add(done);
            }
        });
        Assert.Single(results, r => r.Applied);
        Assert.Single(results.Where(r => r.Ok && r.SessionId != 0).Select(r => r.SessionId).Distinct());
        Assert.Equal(PartyState.Loading, book.Get(party.Id).State);
    }

    [Check]
    public void ManyJoinsAtOnce_NeverExceedTheLimit()
    {
        PartyBook book = Book(max: 4);
        PartyView party = book.Create(H(1)).Party;
        Parallel.For(2, 60, id => book.Join(H((uint)id), party.Id));
        PartyView view = book.Get(party.Id);
        Assert.Equal(4, view.Members.Count);
        Assert.Equal(4, view.Members.Select(m => m.CharacterId).Distinct().Count());
        Assert.Equal(4, Enumerable.Range(1, 60).Count(id => book.FindByMember((uint)id) != null));
    }

    // -- the lifecycle -----------------------------------------------------------------------------------------------------------
    [Check]
    public void TheLifecycle_WalksItsBoundedPath_ToTheHuntAndBackToForming()
    {
        PartyBook book = Book();
        PartyView party = Loading(book, 1, 2);
        long session = party.SessionId;
        Assert.Equal(PartyState.Loading, party.State);
        Assert.True(book.Advance(party.Id, session, PartyState.ReadyInHunt).Applied);
        Assert.True(book.Advance(party.Id, session, PartyState.Active).Applied);
        Assert.True(book.Advance(party.Id, session, PartyState.Resolving).Applied);
        Assert.True(book.Advance(party.Id, session, PartyState.Returning).Applied);
        PartyResult over = book.SessionEnded(party.Id, session);
        Assert.True(over.Applied);
        Assert.Equal((PartyState.Forming, 0, 0L), (over.Party.State, over.Party.QuestId, over.Party.SessionId));
        Assert.All(over.Party.Members, m => Assert.False(m.Ready));
        Assert.Equal(2, over.Party.Members.Count);                                     // the party goes on: a new quest, a new hunt
        Assert.True(book.SelectQuest(1, Quest + 1).Applied);
    }

    [Check]
    public void AnIllegalTransition_IsRefusedSafely_AndTheStateIsUnchanged()
    {
        PartyBook book = Book();
        PartyView party = Loading(book, 1, 2);
        long session = party.SessionId;
        Assert.Equal(PartyError.WrongState, book.Advance(party.Id, session, PartyState.Active).Error);        // Loading -> Active skips a step
        Assert.Equal(PartyError.WrongState, book.Advance(party.Id, session, PartyState.Forming).Error);       // and the hunt cannot un-start
        Assert.Equal(PartyError.WrongState, book.Advance(party.Id, session, PartyState.Closed).Error);
        Assert.Equal(PartyState.Loading, book.Get(party.Id).State);
        book.Advance(party.Id, session, PartyState.ReadyInHunt);
        book.Advance(party.Id, session, PartyState.Active);
        Assert.Equal(PartyError.WrongState, book.SelectQuest(1, Quest + 1).Error);                              // Active -> SelectQuest
        Assert.Equal(PartyError.WrongState, book.SetReady(2, false).Error);
        Assert.Equal(PartyError.WrongState, book.BeginCountdown(1).Error);                                      // Loading/Active -> a second start
        Assert.Equal(PartyError.WrongState, book.ClearQuest(1).Error);
        Assert.Equal(PartyError.WrongState, book.Kick(1, 2).Error);
        Assert.Equal(PartyError.WrongState, book.TransferLeader(1, 2).Error);
        Assert.Equal(PartyState.Active, book.Get(party.Id).State);
        Assert.Equal(PartyError.WrongState, book.Advance(party.Id, session, PartyState.ReadyInHunt).Error);   // backwards
        Assert.Equal(PartyOutcome.Duplicate, book.Advance(party.Id, session, PartyState.Active).Outcome);     // and the same again is a duplicate
    }

    [Check]
    public void AStaleSessionId_IsRefused_ItCannotMoveThePartyOrEndItsHunt()
    {
        PartyBook book = Book();
        PartyView party = Loading(book, 1, 2);
        Assert.Equal(PartyError.StaleSession, book.Advance(party.Id, party.SessionId + 1, PartyState.ReadyInHunt).Error);
        Assert.Equal(PartyError.StaleSession, book.SessionEnded(party.Id, party.SessionId + 1).Error);
        Assert.Equal(PartyError.StaleSession, book.Advance(party.Id, 0, PartyState.ReadyInHunt).Error);
        Assert.Equal(PartyState.Loading, book.Get(party.Id).State);
        Assert.Equal(PartyError.NoSuchParty, book.Advance(9999, 1, PartyState.ReadyInHunt).Error);
        Assert.Equal(PartyOutcome.Duplicate, book.SessionEnded(9999, 1).Outcome);                              // a party that is gone has nothing to end
    }

    [Check]
    public void ALoadThatCameToNothing_GoesHomeLikeAnyHunt()
    {
        PartyBook book = Book();
        PartyView party = Loading(book, 1, 2);
        Assert.True(book.Advance(party.Id, party.SessionId, PartyState.Returning).Applied);                    // Loading -> Returning is allowed
        PartyResult over = book.SessionEnded(party.Id, party.SessionId);
        Assert.Equal(PartyState.Forming, over.Party.State);
        Assert.Equal(PartyOutcome.Duplicate, book.SessionEnded(party.Id, party.SessionId).Outcome);            // ended once
    }

    [Check]
    public void AMemberWhoLeavesInTheHunt_LeavesTheParty_AndTheLastOneClosesIt()
    {
        PartyBook book = Book();
        PartyView party = Loading(book, 1, 2);
        PartyResult left = book.Leave(2);
        Assert.Contains(left.Events, e => e.Kind == PartyEventKind.MemberLeft && e.CharacterId == 2);
        Assert.Equal(PartyState.Loading, left.Party.State);                            // the hunt is not the leaver's to end
        Assert.Null(book.FindByMember(2));
        PartyResult last = book.Leave(1);
        Assert.Equal(PartyState.Closed, last.Party.State);
        Assert.Equal(0, book.Count);
        Assert.Equal(PartyOutcome.Duplicate, book.SessionEnded(party.Id, party.SessionId).Outcome);
    }

    [Check]
    public void AClosedParty_TakesNothing_ItIsGone()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2);
        PartyResult gone = book.Disband(1);
        Assert.Equal(PartyState.Closed, gone.Party.State);
        Assert.Equal(PartyError.NoSuchParty, book.Join(H(3), party.Id).Error);                                  // Closed -> Join
        Assert.Equal(PartyError.NotInParty, book.SelectQuest(1, Quest).Error);
        Assert.Equal(PartyError.NotInParty, book.SetReady(2, true).Error);
        Assert.Equal(PartyError.NoSuchParty, book.CompleteCountdown(party.Id, 1).Error);
        Assert.Equal(PartyError.NoSuchParty, book.Advance(party.Id, 1, PartyState.Active).Error);
        Assert.True(book.Create(H(1)).Applied);                                                                 // and its hunters are free to form again
    }

    [Check]
    public void TheTransitionTable_IsExactlyTheBoundedLifecycle()
    {
        (PartyState From, PartyState To)[] allowed =
        {
            (PartyState.Forming, PartyState.Lobby), (PartyState.Forming, PartyState.Closed),
            (PartyState.Lobby, PartyState.Forming), (PartyState.Lobby, PartyState.Loading), (PartyState.Lobby, PartyState.Closed),
            (PartyState.Loading, PartyState.ReadyInHunt), (PartyState.Loading, PartyState.Returning), (PartyState.Loading, PartyState.Closed),
            (PartyState.ReadyInHunt, PartyState.Active), (PartyState.ReadyInHunt, PartyState.Returning), (PartyState.ReadyInHunt, PartyState.Closed),
            (PartyState.Active, PartyState.Resolving), (PartyState.Active, PartyState.Returning), (PartyState.Active, PartyState.Closed),
            (PartyState.Resolving, PartyState.Returning), (PartyState.Resolving, PartyState.Closed),
            (PartyState.Returning, PartyState.Forming), (PartyState.Returning, PartyState.Closed),
        };
        foreach (PartyState from in Enum.GetValues<PartyState>())
            foreach (PartyState to in Enum.GetValues<PartyState>())
                Assert.Equal(allowed.Contains((from, to)), PartyStates.CanMove(from, to));
        Assert.False(PartyStates.InTown(PartyState.Active));
        Assert.True(PartyStates.InTown(PartyState.Lobby));
        Assert.True(PartyStates.InHunt(PartyState.Returning));
        Assert.False(PartyStates.InHunt(PartyState.Closed));
    }

    [Check]
    public void ARefusedRequest_CountsAsARejection_ARepeatAsADuplicate_AndNeitherChangesAParty()
    {
        PartyBook book = Book();
        PartyView party = Lobby(book, 1, 2);
        long version = book.Get(party.Id).Version;
        book.SelectQuest(2, Quest + 1);          // rejected: not the leader
        book.Kick(2, 1);                         // rejected
        book.SetReady(2, false);                 // duplicate: not ready already
        Assert.Equal(2, book.Rejections);
        Assert.Equal(1, book.Duplicates);
        Assert.Equal(version, book.Get(party.Id).Version);
    }
}
