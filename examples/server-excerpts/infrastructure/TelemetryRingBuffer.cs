// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;

namespace Mho.Research.Infrastructure;

/// <summary>One event copied out of the ring by a reader.</summary>
public readonly struct TelemetryEvent
{
    public TelemetryEvent(long ticket, long timestamp, ushort category, ushort payloadLength, byte[] payload)
    {
        Ticket = ticket;
        Timestamp = timestamp;
        Category = category;
        PayloadLength = payloadLength;
        Payload = payload;
    }

    /// <summary>The order the event was admitted in (0 for the first, never reused).</summary>
    public long Ticket { get; }

    /// <summary><see cref="Stopwatch.GetTimestamp"/> ticks when the event was written.</summary>
    public long Timestamp { get; }

    public ushort Category { get; }

    /// <summary>The original payload length, which may be more than <see cref="Payload"/> holds.</summary>
    public ushort PayloadLength { get; }
    /// <summary>The available bytes copied from the start of the event payload.</summary>
    public byte[] Payload { get; }
}

/// <summary>
/// A fixed-size ring of the last N events, with a lock-free write path.
/// <para>Storage is allocated once, in the constructor, as parallel arrays (one slab of <see cref="PayloadCapacity"/> bytes per slot for
/// the payloads), so a write copies into memory that already exists and a million writes make no garbage.</para>
/// <para>A writer takes the next ticket with <see cref="Interlocked.Increment(ref long)"/>; the ticket picks the slot. A slot has a stamp:
/// 0 = never written, odd = a writer is inside it, even = <c>(ticket + 1) * 2</c> of the event it holds. The writer moves the stamp to
/// odd with one compare-and-swap, fills the slot and publishes the even stamp. When the swap fails (a writer that lags a whole lap behind
/// is still inside, or a newer event already owns the slot) the write is dropped and counted; a writer never waits. A reader copies a
/// slot and keeps it only when the stamp is the same even value before and after, so it never returns a torn event.</para>
/// </summary>
public sealed class TelemetryRingBuffer
{
    /// <summary>Default number of events held.</summary>
    public const int DefaultCapacity = 8192;

    /// <summary>Payload bytes kept per event; a longer payload is cut here and its full length is still recorded.</summary>
    public const int PayloadCapacity = 256;

    private readonly int _mask;
    private readonly Func<long> _clock;
    private readonly long[] _stamp;
    private readonly long[] _time;
    private readonly ushort[] _category;
    private readonly ushort[] _len;
    private readonly ushort[] _kept;
    private readonly byte[] _payload;
    private long _head;
    private long _dropped;

    /// <param name="capacity">events held; a power of two from 16 to 65536</param>
    /// <param name="clock">a nonthrowing monotonic tick source. Defaults to <see cref="Stopwatch.GetTimestamp"/></param>
    public TelemetryRingBuffer(int capacity = DefaultCapacity, Func<long> clock = null)
    {
        if (capacity < 16 || capacity > 65536 || (capacity & (capacity - 1)) != 0)
            throw new ArgumentOutOfRangeException(nameof(capacity), "a power of two from 16 to 65536");
        Capacity = capacity;
        _mask = capacity - 1;
        _clock = clock ?? Stopwatch.GetTimestamp;
        _stamp = new long[capacity];
        _time = new long[capacity];
        _category = new ushort[capacity];
        _len = new ushort[capacity];
        _kept = new ushort[capacity];
        _payload = new byte[capacity * PayloadCapacity];
    }

    public int Capacity { get; }

    /// <summary>Bytes the ring holds (the arrays, not the object header).</summary>
    public long FootprintBytes => (long)Capacity * (8 + 8 + 2 + 2 + 2 + PayloadCapacity);

    /// <summary>Events admitted since the start (a drop does not take a ticket back).</summary>
    public long Written => Volatile.Read(ref _head);

    /// <summary>Events dropped because their slot was contended or already owned by a newer event.</summary>
    public long Dropped => Volatile.Read(ref _dropped);

    /// <summary>The tick source, for converting <see cref="TelemetryEvent.Timestamp"/>.</summary>
    public long Now() => _clock();

    /// <summary>Copies an event into a preallocated slot and drops the event if the slot is contended.</summary>
    /// <param name="payload">the bytes to keep the head of</param>
    /// <param name="payloadLength">the original payload length, clamped to the supported range</param>
    /// <returns>true when stored, false when dropped</returns>
    public bool Write(ushort category, ReadOnlySpan<byte> payload, int payloadLength)
    {
        long ticket = Interlocked.Increment(ref _head) - 1;
        int slot = (int)(ticket & _mask);
        long seen = Volatile.Read(ref _stamp[slot]);
        long mine = (ticket + 1) << 1;
        // odd: a writer is inside; a stamp past ours: a newer lap already owns the slot, and this older event is the one to lose
        if ((seen & 1) != 0 || seen > mine || Interlocked.CompareExchange(ref _stamp[slot], seen | 1, seen) != seen)
        {
            Interlocked.Increment(ref _dropped);
            return false;
        }
        int kept = Math.Min(payload.Length, PayloadCapacity);
        payload.Slice(0, kept).CopyTo(new Span<byte>(_payload, slot * PayloadCapacity, PayloadCapacity));
        _time[slot] = _clock();
        _category[slot] = category;
        _len[slot] = (ushort)Math.Clamp(Math.Max(payloadLength, kept), 0, ushort.MaxValue);
        _kept[slot] = (ushort)kept;
        Volatile.Write(ref _stamp[slot], mine);
        return true;
    }

    /// <summary>Samples recent events at or after <paramref name="sinceTimestamp"/> and returns up to the newest
    /// <paramref name="limit"/> matches in ticket order.</summary>
    /// <param name="category">Only include this category when the value is nonnegative</param>
    /// <param name="into">the list the events are added to</param>
    public void Read(long sinceTimestamp, int category, int limit, List<TelemetryEvent> into)
    {
        long head = Volatile.Read(ref _head);
        long first = Math.Max(0, head - Capacity);
        int start = into.Count;
        for (long ticket = head - 1; ticket >= first; ticket--)
        {
            int slot = (int)(ticket & _mask);
            long s1 = Volatile.Read(ref _stamp[slot]);
            if (s1 == 0 || (s1 & 1) != 0)
                continue;
            long held = (s1 >> 1) - 1;
            if (held < first)
                continue;                                   // a lap old: not part of the last Capacity events
            long t = _time[slot];
            ushort observedCategory = _category[slot];
            byte[] bytes = null;
            if ((category < 0 || observedCategory == category) && t >= sinceTimestamp)
            {
                int n = _kept[slot];
                bytes = new byte[n];
                Buffer.BlockCopy(_payload, slot * PayloadCapacity, bytes, 0, n);
            }
            ushort len = _len[slot];
            Thread.MemoryBarrier();
            if (Volatile.Read(ref _stamp[slot]) != s1 || bytes == null)
                continue;                                   // rewritten while it was copied, or not wanted
            into.Add(new TelemetryEvent(held, t, observedCategory, len, bytes));
        }
        // the scan ran newest first, so the surplus is at the end: keep the newest `limit`, hand them back oldest first
        int count = into.Count - start;
        if (count > limit)
        {
            into.RemoveRange(start + limit, count - limit);
            count = limit;
        }
        into.Sort(start, count, TicketOrder.Instance);
    }

    private sealed class TicketOrder : IComparer<TelemetryEvent>
    {
        public static readonly TicketOrder Instance = new();

        public int Compare(TelemetryEvent a, TelemetryEvent b) => a.Ticket.CompareTo(b.Ticket);
    }
}
