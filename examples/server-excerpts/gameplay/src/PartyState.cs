// SPDX-License-Identifier: AGPL-3.0-only
namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>
/// Where a party stands, as ONE value: a bounded lifecycle in place of a handful of flags that could contradict each other
/// (a party that is "loading" and "in the lobby" at once). Every change goes through <see cref="PartyStates.CanMove"/>; anything
/// the table does not list is refused and leaves the party as it was.
///
/// <code>
/// Forming -> Lobby -> Loading -> ReadyInHunt -> Active -> Resolving -> Returning -> Forming (the party goes on) | Closed
/// </code>
/// </summary>
public enum PartyState : byte
{
    /// <summary>Hunters are gathering in town; no quest is chosen.</summary>
    Forming,

    /// <summary>A quest is chosen (the hunt room is open): members ready up, the leader's ready with everyone else's starts the countdown.</summary>
    Lobby,

    /// <summary>The hunt exists (one session id) and the members' clients are loading it; nothing waits on a slow one for long.</summary>
    Loading,

    /// <summary>Everyone who will play is in the scene: the monsters are placed and the fight is about to be released.</summary>
    ReadyInHunt,

    /// <summary>The fight is on.</summary>
    Active,

    /// <summary>The quest is decided (won or lost): rewards are settled, carves are open.</summary>
    Resolving,

    /// <summary>The way home: hunters leave for town, on their own or when the countdown says.</summary>
    Returning,

    /// <summary>Over: nobody is left, or the leader disbanded it. Final -- nothing joins, changes or starts.</summary>
    Closed,
}

/// <summary>The party lifecycle's rules: which state may follow which, and what each state allows.</summary>
public static class PartyStates
{
    /// <summary>May a party go from <paramref name="from"/> to <paramref name="to"/>? Staying put is not a move.</summary>
    public static bool CanMove(PartyState from, PartyState to) => from switch
    {
        PartyState.Forming => to is PartyState.Lobby or PartyState.Closed,
        PartyState.Lobby => to is PartyState.Forming or PartyState.Loading or PartyState.Closed,
        // a hunt that never got going (nobody made it in) or was given up on goes home like any other
        PartyState.Loading => to is PartyState.ReadyInHunt or PartyState.Returning or PartyState.Closed,
        PartyState.ReadyInHunt => to is PartyState.Active or PartyState.Returning or PartyState.Closed,
        PartyState.Active => to is PartyState.Resolving or PartyState.Returning or PartyState.Closed,
        PartyState.Resolving => to is PartyState.Returning or PartyState.Closed,
        PartyState.Returning => to is PartyState.Forming or PartyState.Closed,
        _ => false,
    };

    /// <summary>Members may join, leave quietly, be kicked and have the leader changed: the party is still in town.</summary>
    public static bool InTown(PartyState state) => state is PartyState.Forming or PartyState.Lobby;

    /// <summary>The party has a hunt session (one id, from <see cref="PartyState.Loading"/> until the way home is over).</summary>
    public static bool InHunt(PartyState state) => state is PartyState.Loading or PartyState.ReadyInHunt or PartyState.Active
        or PartyState.Resolving or PartyState.Returning;
}
