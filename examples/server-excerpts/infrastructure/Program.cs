// SPDX-License-Identifier: AGPL-3.0-only
using System.Buffers.Binary;
using Mho.Research.Infrastructure;

int checks = 0;

void Check(bool condition, string name)
{
    if (!condition)
        throw new InvalidOperationException(name);
    checks++;
}

void CheckInvalidCatalog(string json)
{
    try
    {
        LocaleCatalog.Parse("en", json);
    }
    catch (FormatException)
    {
        checks++;
        return;
    }
    throw new InvalidOperationException("Invalid catalog was accepted");
}

var stamp = new BuildStamp("0123456789abcdef", false, "2000-01-01T00:00:00Z", "example-source", "example-data");
var parsed = BuildStamp.Parse(stamp.ToJson());
Check(parsed is not null && parsed.Sha == stamp.Sha && parsed.Source == stamp.Source && parsed.Data == stamp.Data,
      "Build stamp round trip");
Check(stamp.Describe() == "build stamp: 0123456789ab clean built 2000-01-01T00:00:00Z source example-sour data example-data",
      "Build stamp display");
Check(BuildStamp.Parse("not JSON") is null, "Malformed build stamp");
Check(BuildStamp.Parse("{}") is null, "Incomplete build stamp");

Check(LocaleRegistry.DefaultTag == "en", "Default locale");
Check(LocaleRegistry.Resolve("en_US") == "en", "Locale alias");
Check(LocaleRegistry.Resolve("pt-Latn") == "pt-BR", "Locale fallback");
Check(LocaleRegistry.Resolve("ja") is null, "Absent registry locale");

var catalog = LocaleCatalog.Embedded("en");
Check(catalog is not null && catalog.TryText("collection.title", out string title) && title == "Sample collection",
      "Plain catalog entry");
Check(catalog.TryPlural("collection.entries", PluralRules.Select("en", 2), out string entries) && entries == "{count} entries",
      "Plural catalog entry");
CheckInvalidCatalog("""{"duplicate":"first","duplicate":"second"}""");
CheckInvalidCatalog("""{"entries":{"one":"entry"}}""");
CheckInvalidCatalog("""{"entries":{"unknown":"entry","other":"entries"}}""");
Check(PluralRules.Select("ar", 2) == PluralCategory.Two, "Arabic dual");
Check(PluralRules.Select("ar", 103) == PluralCategory.Few, "Arabic few");
Check(PluralRules.Select("fil", 19) == PluralCategory.Other, "Filipino plural");
Check(PluralRules.Select("ja", long.MinValue) == PluralCategory.Other, "Invariant plural and extreme count");
Check(PluralRules.Select("pt-BR", 0) == PluralCategory.One, "Brazilian Portuguese zero");
Check(PluralRules.Select("pt-PT", 0) == PluralCategory.Other, "European Portuguese zero");
Check(PluralRules.Select("es", 1_000_000) == PluralCategory.Many, "Exact million form");

long tick = 0;
var ring = new TelemetryRingBuffer(16, () => ++tick);
for (int i = 0; i < 40; i++)
    ring.Write((ushort)(i % 2), new byte[] { (byte)i }, 1);

List<TelemetryEvent> events = new();
ring.Read(0, -1, 100, events);
Check(events.Select(item => item.Ticket).SequenceEqual(Enumerable.Range(24, 16).Select(ticket => (long)ticket)),
      "Ring wraparound");
Check(ring.Written == 40 && ring.Dropped == 0, "Sequential accounting");

events.Clear();
ring.Read(32, 1, 2, events);
Check(events.Select(item => item.Ticket).SequenceEqual(new long[] { 37, 39 }), "Category, time, and newest limit");

byte[] oversized = new byte[300];
oversized[0] = 5;
ring.Write(2, oversized, oversized.Length);
oversized[0] = 0;
events.Clear();
ring.Read(0, 2, 1, events);
Check(events.Count == 1 && events[0].PayloadLength == 300 && events[0].Payload.Length == TelemetryRingBuffer.PayloadCapacity &&
      events[0].Payload[0] == 5, "Clipped, owned payload");

var concurrent = new TelemetryRingBuffer(512);
Parallel.For(0, 4, writer =>
{
    Span<byte> bytes = stackalloc byte[4];
    for (int i = 0; i < 2_000; i++)
    {
        BinaryPrimitives.WriteInt32LittleEndian(bytes, writer);
        concurrent.Write((ushort)writer, bytes, bytes.Length);
    }
});
events.Clear();
concurrent.Read(0, -1, concurrent.Capacity, events);
Check(concurrent.Written == 8_000 && events.Count > 0, "Concurrent write accounting");
Check(events.All(item => item.Category == BinaryPrimitives.ReadInt32LittleEndian(item.Payload)),
      "Published concurrent payloads are consistent");

var cleanupOrder = new List<string>();
var cleanup = new ZoneCleanup()
    .Add("first", () => cleanupOrder.Add("first"))
    .Add("middle", () => throw new InvalidOperationException("sample failure\ncontinued"))
    .Add("last", () => cleanupOrder.Add("last"));
List<string> failures = cleanup.Run();
Check(cleanupOrder.SequenceEqual(new[] { "first", "last" }), "Cleanup continues in order after a failure");
Check(failures.SequenceEqual(new[] { "middle: InvalidOperationException: sample failure continued" }), "Cleanup formats one failure line");

Console.WriteLine($"Infrastructure self-checks: {checks} passed");
