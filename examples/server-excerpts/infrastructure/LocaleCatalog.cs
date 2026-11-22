// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace Mho.Research.Infrastructure;

/// <summary>
/// Parses a language catalog whose values are plain text or objects with text for each plural form.
/// Validates duplicate keys, empty text, and unsupported plural form names.
/// </summary>
public sealed class LocaleCatalog
{
    private readonly Dictionary<string, string> _text = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Dictionary<PluralCategory, string>> _plural = new(StringComparer.Ordinal);

    private LocaleCatalog(string tag)
    {
        Tag = tag;
    }

    public string Tag { get; }

    public int Count => _text.Count + _plural.Count;

    public IEnumerable<string> Keys => _text.Keys.Concat(_plural.Keys);

    public bool IsPlural(string key) => _plural.ContainsKey(key);

    public bool TryText(string key, out string text) => _text.TryGetValue(key, out text);

    /// <summary>The text of exactly this form (no fallback: a catalog that lacks it says so).</summary>
    public bool TryPlural(string key, PluralCategory form, out string text)
    {
        if (_plural.TryGetValue(key, out Dictionary<PluralCategory, string> forms) && forms.TryGetValue(form, out text))
            return true;
        text = null;
        return false;
    }

    /// <summary>The plural forms a key has (empty for a key that is not plural or absent).</summary>
    public IReadOnlyCollection<PluralCategory> FormsOf(string key)
        => _plural.TryGetValue(key, out Dictionary<PluralCategory, string> forms) ? forms.Keys : Array.Empty<PluralCategory>();

    public static LocaleCatalog Parse(string tag, string json)
    {
        LocaleCatalog catalog = new(tag);
        JsonDocumentOptions options = new() { CommentHandling = JsonCommentHandling.Disallow, AllowTrailingCommas = false };
        using JsonDocument doc = JsonDocument.Parse(json, options);
        if (doc.RootElement.ValueKind != JsonValueKind.Object)
            throw new FormatException($"{tag}: the catalog is not a JSON object");
        foreach (JsonProperty property in doc.RootElement.EnumerateObject())
        {
            string key = property.Name;
            if (key.Length == 0 || catalog._text.ContainsKey(key) || catalog._plural.ContainsKey(key))
                throw new FormatException($"{tag}: '{key}' is empty or given twice");
            switch (property.Value.ValueKind)
            {
                case JsonValueKind.String:
                    catalog._text[key] = NonEmpty(tag, key, property.Value.GetString());
                    break;
                case JsonValueKind.Object:
                {
                    Dictionary<PluralCategory, string> forms = new();
                    foreach (JsonProperty form in property.Value.EnumerateObject())
                    {
                        if (!PluralRules.TryParse(form.Name, out PluralCategory category) || forms.ContainsKey(category))
                            throw new FormatException($"{tag}: '{key}' has a plural form '{form.Name}' that is unknown or given twice");
                        if (form.Value.ValueKind != JsonValueKind.String)
                            throw new FormatException($"{tag}: '{key}.{form.Name}' is not a string");
                        forms[category] = NonEmpty(tag, key + "." + form.Name, form.Value.GetString());
                    }
                    if (!forms.ContainsKey(PluralCategory.Other))
                        throw new FormatException($"{tag}: '{key}' has no 'other' form");
                    catalog._plural[key] = forms;
                    break;
                }
                default:
                    throw new FormatException($"{tag}: '{key}' is neither a string nor an object of plural forms");
            }
        }
        return catalog;
    }

    /// <summary>The catalog of a locale compiled into this build (<c>Localization/Catalogs/&lt;tag&gt;.json</c>), or null when the build has none.</summary>
    public static LocaleCatalog Embedded(string tag)
    {
        using Stream stream = typeof(LocaleCatalog).Assembly.GetManifestResourceStream($"Localization.Catalogs.{tag}.json");
        if (stream == null)
            return null;
        using StreamReader reader = new(stream, new global::System.Text.UTF8Encoding(false, true));
        return Parse(tag, reader.ReadToEnd());
    }

    private static string NonEmpty(string tag, string what, string value)
    {
        if (string.IsNullOrEmpty(value))
            throw new FormatException($"{tag}: '{what}' is empty");
        return value;
    }
}
