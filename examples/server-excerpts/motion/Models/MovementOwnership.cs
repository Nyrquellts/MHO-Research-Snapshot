// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.Linq;

namespace Mho.Research.Motion;

/// <summary>Movement states used by the single-writer audit table.</summary>
public enum ActionClass
{
    /// <summary>Nothing asked for, nothing held: it stands.</summary>
    Idle,
    /// <summary>The trees turn it in place (the rotate tree, or a turn the combat tree asks for); no walk.</summary>
    TurnInPlace,
    /// <summary>The trees walk or dash it and the step steers itself towards its destination.</summary>
    Locomotion,
    /// <summary>The trees walk it and turn it at once: the rotate tree steers, the step moves along the facing.</summary>
    SteeredLocomotion,
    /// <summary>Airborne with a root-motion clip held: the flight carries it, the clip's yaw track faces it.</summary>
    Jump,
    /// <summary>Airborne with no root-motion clip held.</summary>
    JumpFree,
    /// <summary>A native turn clip is held: its yaw track turns the body.</summary>
    NativeTurn,
    /// <summary>A clip the trees play is held and has root motion: the clip's own tracks move and face it.</summary>
    Attack,
    /// <summary>A clip the trees play is held and has no root motion: it acts where it stands, the trees may still turn it.</summary>
    AttackInPlace,
    /// <summary>A hit's reaction is held and has root motion: the trees stand down, the clip moves it.</summary>
    Reaction,
    /// <summary>A hit's reaction is held and has no root motion: nothing moves it.</summary>
    ReactionInPlace,
    /// <summary>The end sample of a held root-motion clip that ran out this step (<c>SettleClip</c>).</summary>
    ClipEnd,
    /// <summary>The designer's region-path transfer: one placement at the linked arrival.</summary>
    Transfer,
    /// <summary>Dead, captured or gone (vanished): the end reaction plays out where it stood.</summary>
    Resolved,
    /// <summary>an attack's input clip with root motion plays out and the trees neither walk nor turn it: the clip's tracks move and face it.</summary>
    HeldInput,
    /// <summary>the same while the rotate tree turns it (a steered dash): the clip's translation moves it along the facing the rotate tree gives.</summary>
    SteeredHeldInput,
}

/// <summary>Describe the expected writer of translation and rotation in each movement state.</summary>
public static class MovementOwnership
{
    public const string Nobody = "-";

    /// <summary>The owner of each field in one class, and when the class holds.</summary>
    public readonly record struct Owners(string Translation, string Rotation, string When)
    {
        public string Of(bool rotation) => rotation ? Rotation : Translation;
    }

    public static Owners Of(ActionClass action) => action switch
    {
        ActionClass.Idle => new(Nobody, Nobody, "nothing asked for, nothing held"),
        ActionClass.TurnInPlace => new(Nobody, "Rotate", "the trees turn it in place"),
        ActionClass.Locomotion => new("MoveStep", "MoveStep", "the trees walk it; the step steers itself"),
        ActionClass.SteeredLocomotion => new("MoveStep", "Rotate", "the trees walk it and turn it at once"),
        ActionClass.Jump => new("StepJump", "Hold", "airborne, a root-motion clip held"),
        ActionClass.JumpFree => new("StepJump", "Rotate", "airborne, no root-motion clip held"),
        ActionClass.NativeTurn => new("Hold", "Hold", "a native turn clip held"),
        ActionClass.Attack => new("Hold", "Hold", "a clip of the trees held, with root motion"),
        ActionClass.AttackInPlace => new(Nobody, "Rotate", "a clip of the trees held, without root motion"),
        ActionClass.Reaction => new("Hold", "Hold", "a hit's reaction held, with root motion"),
        ActionClass.ReactionInPlace => new(Nobody, Nobody, "a hit's reaction held, without root motion"),
        ActionClass.ClipEnd => new("SettleClip", "SettleClip", "a held root-motion clip ran out this step"),
        ActionClass.Transfer => new("TransferAlongRegionPath", "TransferAlongRegionPath", "the region path's transfer"),
        ActionClass.Resolved => new("Hold", "Hold", "dead, captured or gone: the end reaction plays out"),
        ActionClass.HeldInput => new("FollowHeldInput", "FollowHeldInput", "an attack's input clip with root motion plays out"),
        ActionClass.SteeredHeldInput => new("FollowHeldInput", "Rotate", "an attack's input clip with root motion plays out, the rotate tree turns it"),
        _ => throw new ArgumentOutOfRangeException(nameof(action), action, null),
    };

    /// <summary>The one method that may write the field in this class, or <see cref="Nobody"/>.</summary>
    public static string Owner(ActionClass action, bool rotation) => Of(action).Of(rotation);

    /// <summary>Is <paramref name="by"/> (a <c>CallerMemberName</c>) the owner of the field in this class?</summary>
    public static bool Owns(ActionClass action, bool rotation, string by) => Owner(action, rotation) == by;

    /// <summary>Every class in order.</summary>
    public static IEnumerable<ActionClass> Classes => Enum.GetValues<ActionClass>();

    /// <summary>The table formatted as Markdown, one row per class: class, when, translation owner, rotation owner.</summary>
    public static IEnumerable<string> TableRows()
        => Classes.Select(c => Of(c)).Zip(Classes, (o, c) => $"| `{c}` | {o.When} | `{o.Translation}` | `{o.Rotation}` |");
}
