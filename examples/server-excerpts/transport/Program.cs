// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Concurrent;
using Mho.ServerExcerpts.Transport;

var patience = TimeSpan.FromSeconds(5);
int passed = 0;

Check("queued writes are ordered and close after draining", () =>
{
    var written = new ConcurrentQueue<byte>();
    using var closed = new ManualResetEventSlim();
    var outbox = new Outbox(bytes => written.Enqueue(bytes[0]), closed.Set);
    outbox.Send(new byte[] { 1 });
    outbox.Send(new byte[] { 2 });
    outbox.Send(new byte[] { 3 });
    outbox.Close();
    Require(closed.Wait(patience), "writer did not close");
    Require(written.SequenceEqual(new byte[] { 1, 2, 3 }), "write order changed");
    Require(outbox.Pending == 0, "pending byte count did not return to zero");
});

Check("byte budget abandons a backed-up writer once", () =>
{
    using var entered = new ManualResetEventSlim();
    using var release = new ManualResetEventSlim();
    using var closed = new ManualResetEventSlim();
    int warnings = 0;
    var outbox = new Outbox(_ => { entered.Set(); release.Wait(patience); },
        () => { release.Set(); closed.Set(); },
        (_, loud) => { if (loud) Interlocked.Increment(ref warnings); }, limitBytes: 3);
    outbox.Send(new byte[] { 1 });
    Require(entered.Wait(patience), "writer did not receive the first item");
    outbox.Send(new byte[] { 2, 3, 4 });
    outbox.Send(new byte[] { 5 });
    Require(closed.Wait(patience) && outbox.Dead, "backed-up writer was not closed");
    Require(warnings == 1, "byte budget warning was duplicated or missing");
});

Check("stall detection uses the supplied clock", () =>
{
    using var entered = new ManualResetEventSlim();
    using var release = new ManualResetEventSlim();
    using var closed = new ManualResetEventSlim();
    long clock = 1;
    var outbox = new Outbox(_ => { entered.Set(); release.Wait(patience); },
        () => { release.Set(); closed.Set(); }, stall: TimeSpan.FromSeconds(1),
        now: () => Interlocked.Read(ref clock));
    outbox.Send(new byte[] { 1 });
    Require(entered.Wait(patience), "writer did not receive the item");
    Interlocked.Exchange(ref clock, 1002);
    outbox.Send(new byte[] { 2 });
    Require(closed.Wait(patience) && outbox.Dead, "stalled writer was not closed");
});

Check("a write failure abandons the writer", () =>
{
    using var closed = new ManualResetEventSlim();
    bool? loud = null;
    var outbox = new Outbox(_ => throw new InvalidOperationException("sample write failure"),
        closed.Set, (_, warned) => loud = warned);
    outbox.Send(new byte[] { 1 });
    Require(closed.Wait(patience) && outbox.Dead, "failed writer was not closed");
    Require(loud is false, "ordinary write failure should be quiet");
});

Check("dispatch counters keep totals and a bounded report", () =>
{
    var counters = new DispatchCounters();
    Require(counters.RecordUnhandled(20), "first ID was not reported");
    Require(!counters.RecordUnhandled(20), "duplicate ID was reported");
    for (int index = 0; index < 20; index++) counters.RecordUnhandled(index);
    counters.RecordMalformed();
    Require(counters.Unhandled == 22 && counters.Malformed == 1, "counter totals differ");
    Require(counters.ReportedIds().SequenceEqual(new[] { 20, 0, 1, 2, 3, 4, 5, 6 }), "report was not bounded");
});

Check("preview budget tracks each source and kind independently", () =>
{
    var budget = new LogPreviewBudget();
    for (int index = 0; index < LogPreviewBudget.FullDumps; index++)
        Require(budget.BodyLimit(kind: 1, source: 1, bodyLength: 1000) == -1, "quota ended early");
    Require(budget.BodyLimit(1, 1, 1000) == LogPreviewBudget.HeadBytes, "preview quota was ignored");
    Require(budget.BodyLimit(1, 2, 1000) == -1, "a separate source shared the quota");
    Require(budget.BodyLimit(1, 1, 100) == -1, "short record was limited");
});

Console.WriteLine($"Transport excerpt checks: {passed} passed.");

void Check(string name, Action run)
{
    run();
    Console.WriteLine($"PASS {name}");
    passed++;
}

static void Require(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}
