// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;

namespace Mho.Research.Infrastructure;

/// <summary>The cardinal plural categories used by Unicode CLDR.</summary>
public enum PluralCategory
{
    Zero,
    One,
    Two,
    Few,
    Many,
    Other,
}

/// <summary>
/// Selects a cardinal plural category for an integer count in a supported locale.
/// Some locales have an optional form for exact multiples of one million.
/// </summary>
public static class PluralRules
{
    private enum Rule
    {
        Unknown,
        OtherOnly,        // ja ko zh vi th id
        OneIsOne,         // en de
        OneIsOneMany,     // it es: n = 1, and many for exact millions
        OneIsZeroOne,     // fr pt (pt-BR): n = 0 or 1 (pt-PT is OneIsOneMany)
        Filipino,         // fil
        Arabic,           // ar
    }

    private static readonly PluralCategory[] OtherOnlyForms = { PluralCategory.Other };
    private static readonly PluralCategory[] OneOther = { PluralCategory.One, PluralCategory.Other };
    private static readonly PluralCategory[] OneManyOther = { PluralCategory.One, PluralCategory.Many, PluralCategory.Other };
    private static readonly PluralCategory[] ArabicForms =
        { PluralCategory.Zero, PluralCategory.One, PluralCategory.Two, PluralCategory.Few, PluralCategory.Many, PluralCategory.Other };

    /// <summary>Whether the rules for this locale are known (a tag of the registry, or one of its regional forms).</summary>
    public static bool Supports(string tag) => RuleOf(tag) != Rule.Unknown;

    /// <summary>The forms a catalog must give for a plural text: every form a count below a million can take, and <see cref="PluralCategory.Other"/> always.</summary>
    public static IReadOnlyList<PluralCategory> Required(string tag) => RuleOf(tag) switch
    {
        Rule.OtherOnly => OtherOnlyForms,
        Rule.Arabic => ArabicForms,
        Rule.Unknown => OneOther,
        _ => OneOther,
    };

    /// <summary>Every form the language has (<see cref="Required"/> and the forms of exact millions).</summary>
    public static IReadOnlyList<PluralCategory> All(string tag) => RuleOf(tag) switch
    {
        Rule.OtherOnly => OtherOnlyForms,
        Rule.Arabic => ArabicForms,
        Rule.OneIsOneMany or Rule.OneIsZeroOne => OneManyOther,
        _ => OneOther,
    };

    /// <summary>Selects the form for <paramref name="count"/>. Unknown locales use the English rule.</summary>
    public static PluralCategory Select(string tag, long count)
    {
        ulong n = Magnitude(count);
        switch (RuleOf(tag))
        {
            case Rule.OtherOnly:
                return PluralCategory.Other;
            case Rule.OneIsOne:
            case Rule.Unknown:
                return n == 1 ? PluralCategory.One : PluralCategory.Other;
            case Rule.OneIsOneMany:
                return n == 1 ? PluralCategory.One : Millions(n) ? PluralCategory.Many : PluralCategory.Other;
            case Rule.OneIsZeroOne:
                return n <= 1 ? PluralCategory.One : Millions(n) ? PluralCategory.Many : PluralCategory.Other;
            case Rule.Filipino:
                // one: i = 1,2,3 or i % 10 != 4,6,9 (v = 0): 0 1 2 3 5 7 8 10 11 12 13 15 ... are singular, 4 6 9 14 16 19 24 ... are not
                return n is 1 or 2 or 3 || (n % 10) is not (4 or 6 or 9) ? PluralCategory.One : PluralCategory.Other;
            case Rule.Arabic:
            {
                if (n == 0)
                    return PluralCategory.Zero;
                if (n == 1)
                    return PluralCategory.One;
                if (n == 2)
                    return PluralCategory.Two;
                ulong r = n % 100;
                if (r is >= 3 and <= 10)
                    return PluralCategory.Few;
                if (r is >= 11 and <= 99)
                    return PluralCategory.Many;
                return PluralCategory.Other;
            }
            default:
                return PluralCategory.Other;
        }
    }

    /// <summary>The lower-case name a catalog uses for a form (<c>one</c>, <c>other</c> ...).</summary>
    public static string Name(PluralCategory category) => category switch
    {
        PluralCategory.Zero => "zero",
        PluralCategory.One => "one",
        PluralCategory.Two => "two",
        PluralCategory.Few => "few",
        PluralCategory.Many => "many",
        _ => "other",
    };

    public static bool TryParse(string name, out PluralCategory category)
    {
        switch (name)
        {
            case "zero": category = PluralCategory.Zero; return true;
            case "one": category = PluralCategory.One; return true;
            case "two": category = PluralCategory.Two; return true;
            case "few": category = PluralCategory.Few; return true;
            case "many": category = PluralCategory.Many; return true;
            case "other": category = PluralCategory.Other; return true;
            default: category = PluralCategory.Other; return false;
        }
    }

    private static ulong Magnitude(long count) => count < 0 ? (ulong)(-(count + 1)) + 1UL : (ulong)count;

    private static bool Millions(ulong n) => n != 0 && n % 1_000_000UL == 0;

    private static bool IsPortugalPortuguese(string tag)
        => tag != null && tag.StartsWith("pt", StringComparison.OrdinalIgnoreCase) && tag.EndsWith("-PT", StringComparison.OrdinalIgnoreCase);

    private static Rule RuleOf(string tag)
    {
        if (string.IsNullOrWhiteSpace(tag))
            return Rule.Unknown;
        int dash = tag.IndexOfAny(new[] { '-', '_' });
        string language = (dash < 0 ? tag : tag[..dash]).ToLowerInvariant();
        return language switch
        {
            "ja" or "ko" or "zh" or "vi" or "th" or "id" => Rule.OtherOnly,
            "en" or "de" => Rule.OneIsOne,
            "it" or "es" => Rule.OneIsOneMany,
            "fr" => Rule.OneIsZeroOne,
            "pt" => IsPortugalPortuguese(tag) ? Rule.OneIsOneMany : Rule.OneIsZeroOne,
            "fil" or "tl" => Rule.Filipino,
            "ar" => Rule.Arabic,
            _ => Rule.Unknown,
        };
    }
}
