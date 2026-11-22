// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.IO;
using System.Text;
using System.Text.Json;

namespace Mho.Research.Infrastructure;

/// <summary>
/// Records a build's revision, working-tree state, build time, and source and data digests.
/// </summary>
public sealed class BuildStamp
{
    public const string FileName = "build_stamp.json";
    public const string LinePrefix = "build stamp: ";
    public const int ShortLength = 12;

    public string Sha { get; }
    public bool Dirty { get; }
    public string Built { get; }
    public string Source { get; }
    public string Data { get; }

    public BuildStamp(string sha, bool dirty, string built, string source, string data)
    {
        Sha = sha;
        Dirty = dirty;
        Built = built;
        Source = source;
        Data = data;
    }

    /// <summary>The stamp in <paramref name="folder"/>, or null when there is none or it is not a stamp (a missing file, damaged JSON, a field of the wrong kind).</summary>
    public static BuildStamp Load(string folder)
    {
        try
        {
            string path = Path.Combine(folder, FileName);
            return File.Exists(path) ? Parse(File.ReadAllText(path)) : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>The stamp a JSON text holds, or null when it is not one.</summary>
    public static BuildStamp Parse(string json)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(json);
            JsonElement root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
                return null;
            string sha = Text(root, "sha"), built = Text(root, "built"), source = Text(root, "source"), data = Text(root, "data");
            if (string.IsNullOrEmpty(sha) || string.IsNullOrEmpty(built) || string.IsNullOrEmpty(source) || string.IsNullOrEmpty(data))
                return null;
            if (!root.TryGetProperty("dirty", out JsonElement dirty) || (dirty.ValueKind != JsonValueKind.True && dirty.ValueKind != JsonValueKind.False))
                return null;
            return new BuildStamp(sha, dirty.GetBoolean(), built, source, data);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string Text(JsonElement root, string name)
        => root.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static string Short(string text) => text.Length <= ShortLength ? text : text.Substring(0, ShortLength);

    /// <summary>The one start-up line: <c>build stamp: &lt;commit&gt; clean|dirty built &lt;utc&gt; source &lt;digest&gt; data &lt;digest&gt;</c>, the commit and digests shortened to 12 characters.</summary>
    public string Describe()
        => $"{LinePrefix}{Short(Sha)} {(Dirty ? "dirty" : "clean")} built {Built} source {Short(Source)} data {Short(Data)}";

    /// <summary>The line for the stamp in <paramref name="folder"/>, or the line that says there is none.</summary>
    public static string Describe(string folder) => DescribeOrNone(Load(folder));

    /// <summary>Formats a stamp or reports its absence.</summary>
    public static string DescribeOrNone(BuildStamp stamp)
        => stamp?.Describe() ?? $"{LinePrefix}none ({FileName} is absent or unreadable)";

    /// <summary>Writes all stamp fields as JSON for <see cref="Parse"/> to read back.</summary>
    public void WriteTo(Utf8JsonWriter writer)
    {
        writer.WriteStartObject();
        writer.WriteString("sha", Sha);
        writer.WriteBoolean("dirty", Dirty);
        writer.WriteString("built", Built);
        writer.WriteString("source", Source);
        writer.WriteString("data", Data);
        writer.WriteEndObject();
    }

    public string ToJson()
    {
        using MemoryStream buffer = new();
        using (Utf8JsonWriter writer = new(buffer))
            WriteTo(writer);
        return Encoding.UTF8.GetString(buffer.ToArray());
    }
}
