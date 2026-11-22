// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace Mho.Research.Infrastructure;

/// <summary>Number formatting conventions for a locale.</summary>
/// <param name="Group">The thousands separator ("" for none).</param>
/// <param name="Decimal">The decimal separator.</param>
/// <param name="MinGroup">How many digits must stand before the first group separator may be placed: 1 groups 1,000, 2 leaves 1000 and groups 10,000 (Spanish).</param>
/// <param name="Digits">The numeral set, such as <c>latn</c> for Western digits.</param>
public sealed record NumberStyle(string Group, string Decimal, int MinGroup, string Digits);

/// <summary>One entry in the locale registry.</summary>
public sealed record LocaleInfo(
    string Tag, string Label, string English, string Native, string Script, bool RightToLeft,
    IReadOnlyList<string> Aliases, IReadOnlyList<string> PluralRequired, IReadOnlyList<string> PluralAll,
    NumberStyle Numbers, string Review, bool VariantDecided, string VariantNote);

/// <summary>
/// Resolves locale tags and aliases using the embedded locale registry.
/// </summary>
public static class LocaleRegistry
{
    private const string Resource = "Localization.locales.json";
    private static readonly Lazy<Loaded> State = new(Load);

    private sealed record Loaded(string Default, IReadOnlyList<LocaleInfo> All);

    /// <summary>The tag of the locale the text is written in first (English) and the one everything falls back to.</summary>
    public static string DefaultTag => State.Value.Default;

    public static IReadOnlyList<LocaleInfo> All => State.Value.All;

    /// <summary>The locale with exactly this tag (case does not matter), or null.</summary>
    public static LocaleInfo Get(string tag)
        => string.IsNullOrWhiteSpace(tag) ? null : All.FirstOrDefault(l => string.Equals(l.Tag, tag.Trim(), StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// Tries the exact tag and aliases, then shorter tags and finally a locale of the same language.
    /// </summary>
    public static string Resolve(string requested)
    {
        if (string.IsNullOrWhiteSpace(requested))
            return null;
        string tag = requested.Trim().Replace('_', '-');
        for (string candidate = tag; candidate.Length > 0; candidate = Shorten(candidate))
        {
            LocaleInfo exact = Get(candidate);
            if (exact != null)
                return exact.Tag;
            LocaleInfo alias = All.FirstOrDefault(l => l.Aliases.Any(a => string.Equals(a, candidate, StringComparison.OrdinalIgnoreCase)));
            if (alias != null)
                return alias.Tag;
        }
        string language = Language(tag);
        LocaleInfo sameLanguage = All.FirstOrDefault(l => string.Equals(Language(l.Tag), language, StringComparison.OrdinalIgnoreCase));
        return sameLanguage?.Tag;
    }

    private static string Language(string tag)
    {
        int dash = tag.IndexOf('-');
        return dash < 0 ? tag : tag[..dash];
    }

    private static string Shorten(string tag)
    {
        int dash = tag.LastIndexOf('-');
        return dash < 0 ? string.Empty : tag[..dash];
    }

    private static Loaded Load()
    {
        using Stream stream = typeof(LocaleRegistry).Assembly.GetManifestResourceStream(Resource)
                              ?? throw new InvalidOperationException($"the locale registry ({Resource}) is not part of this build");
        using JsonDocument doc = JsonDocument.Parse(stream);
        JsonElement root = doc.RootElement;
        string defaultTag = root.GetProperty("default").GetString();
        List<LocaleInfo> all = new();
        foreach (JsonElement e in root.GetProperty("locales").EnumerateArray())
        {
            JsonElement n = e.GetProperty("numbers");
            JsonElement variant = e.GetProperty("variant");
            all.Add(new LocaleInfo(
                e.GetProperty("tag").GetString(), e.GetProperty("label").GetString(), e.GetProperty("english").GetString(),
                e.GetProperty("native").GetString(), e.GetProperty("script").GetString(), e.GetProperty("dir").GetString() == "rtl",
                Strings(e.GetProperty("aliases")), Strings(e.GetProperty("plural_required")), Strings(e.GetProperty("plural_all")),
                new NumberStyle(n.GetProperty("group").GetString(), n.GetProperty("decimal").GetString(), n.GetProperty("min_group").GetInt32(), n.GetProperty("digits").GetString()),
                e.GetProperty("review").GetString(), variant.GetProperty("decided").GetBoolean(), variant.GetProperty("note").GetString()));
        }
        if (all.All(l => l.Tag != defaultTag))
            throw new InvalidOperationException($"the locale registry names {defaultTag} as its default but does not list it");
        return new Loaded(defaultTag, all);
    }

    private static IReadOnlyList<string> Strings(JsonElement array)
        => array.EnumerateArray().Select(x => x.GetString()).ToList();
}
