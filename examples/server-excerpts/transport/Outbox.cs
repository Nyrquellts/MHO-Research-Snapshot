// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Concurrent;
using System.Threading;

namespace Mho.ServerExcerpts.Transport
{
    /// <summary>
    /// Queues byte arrays for an injected writer. One worker drains the queue in order.
    /// A byte budget limits backlog, and a caller-supplied clock supports stall detection.
    /// </summary>
    public sealed class Outbox
    {
        /// <summary>Default limit for bytes waiting or being written.</summary>
        public const long DefaultLimitBytes = 32L * 1024 * 1024;

        /// <summary>Default duration used when checking for a blocked writer.</summary>
        public static readonly TimeSpan DefaultStall = TimeSpan.FromSeconds(30);

        private readonly Action<byte[]> _write;
        private readonly Action _close;
        private readonly Action<string, bool> _abandoned;
        private readonly Func<long> _now;
        private readonly long _stallMs;
        private readonly ConcurrentQueue<byte[]> _queue = new ConcurrentQueue<byte[]>();
        private long _pending;          // bytes queued or in the write in progress
        private long _writingSince;     // when the write in progress began (0: none)
        private int _pumping;           // 1 while a worker owns the queue
        private int _closing;           // Close was asked
        private int _dead;              // given up: nothing more is accepted
        private int _closed;            // the socket's close has run
        private Timer _grace;

        /// <param name="write">The writer callback. It can block until the consumer accepts the item.</param>
        /// <param name="close">The close callback. It can release a blocked writer.</param>
        /// <param name="abandoned">Told once, with the reason, when the connection is given up; <c>loud</c> is false for a plain failed write (the peer left).</param>
        /// <param name="now">Milliseconds; the clock the stall is measured on.</param>
        public Outbox(Action<byte[]> write, Action close, Action<string, bool> abandoned = null, long limitBytes = DefaultLimitBytes,
                      TimeSpan? stall = null, Func<long> now = null)
        {
            _write = write ?? throw new ArgumentNullException(nameof(write));
            _close = close ?? throw new ArgumentNullException(nameof(close));
            _abandoned = abandoned;
            LimitBytes = Math.Max(1, limitBytes);
            Stall = stall ?? DefaultStall;
            _stallMs = Math.Max(1, (long)Stall.TotalMilliseconds);
            _now = now ?? (() => Environment.TickCount64);
        }

        public long LimitBytes { get; }

        public TimeSpan Stall { get; }

        /// <summary>Bytes queued or being written.</summary>
        public long Pending => Interlocked.Read(ref _pending);

        /// <summary>The connection was given up (or closed): what is sent to it is dropped.</summary>
        public bool Dead => Volatile.Read(ref _dead) != 0 || Volatile.Read(ref _closing) != 0;

        /// <summary>Queues <paramref name="data"/> for the background writer.</summary>
        public void Send(byte[] data)
        {
            if (data == null || data.Length == 0 || Dead)
                return;
            long pending = Interlocked.Add(ref _pending, data.Length);
            _queue.Enqueue(data);
            if (pending > LimitBytes)
            {
                GiveUp($"{pending} bytes are waiting for a connection that is not taking them (the limit is {LimitBytes})", true);
                return;
            }

            long since = Interlocked.Read(ref _writingSince);
            if (since != 0 && _now() - since > _stallMs)
            {
                GiveUp($"a write has been blocked for {(_now() - since) / 1000.0:0} s (the limit is {_stallMs / 1000.0:0} s)", true);
                return;
            }

            Pump();
        }

        /// <summary>Closes the connection once what was queued is written (at once when nothing is).</summary>
        public void Close()
        {
            if (Interlocked.Exchange(ref _closing, 1) != 0)
                return;
            if (Volatile.Read(ref _dead) != 0 || (_queue.IsEmpty && Volatile.Read(ref _pumping) == 0))
            {
                FinishClose();
                return;
            }

            // a peer that does not take the rest is not waited for either
            _grace = new Timer(static o => ((Outbox)o).GiveUp("the connection did not take what was sent before it was closed", false), this,
                               _stallMs, Timeout.Infinite);
            Pump();
        }

        private void Pump()
        {
            if (Interlocked.CompareExchange(ref _pumping, 1, 0) == 0)
                ThreadPool.UnsafeQueueUserWorkItem(static o => o.Drain(), this, false);
        }

        private void Drain()
        {
            while (true)
            {
                while (_queue.TryDequeue(out byte[] data))
                {
                    if (Volatile.Read(ref _dead) != 0)
                    {
                        Interlocked.Add(ref _pending, -data.Length);
                        continue;
                    }

                    Interlocked.Exchange(ref _writingSince, Math.Max(1, _now()));
                    try
                    {
                        _write(data);
                    }
                    catch (Exception ex)
                    {
                        GiveUp($"a write failed ({ex.GetType().Name}: {ex.Message})", false);
                    }
                    finally
                    {
                        Interlocked.Exchange(ref _writingSince, 0);
                        Interlocked.Add(ref _pending, -data.Length);
                    }
                }

                Interlocked.Exchange(ref _pumping, 0);
                if (_queue.IsEmpty)
                {
                    if (Volatile.Read(ref _closing) != 0)
                        FinishClose();
                    return;
                }

                if (Interlocked.CompareExchange(ref _pumping, 1, 0) != 0)
                    return;                                   // something was sent as this worker finished: another worker has it
            }
        }

        private void GiveUp(string reason, bool loud)
        {
            if (Interlocked.Exchange(ref _dead, 1) != 0)
                return;
            while (_queue.TryDequeue(out byte[] data))
                Interlocked.Add(ref _pending, -data.Length);
            try
            {
                _abandoned?.Invoke(reason, loud);
            }
            catch (Exception)
            {
                // a log line is not worth a connection's cleanup
            }

            // The writer's close callback runs independently of the sender.
            ThreadPool.UnsafeQueueUserWorkItem(static o => o.FinishClose(), this, false);
        }

        private void FinishClose()
        {
            if (Interlocked.Exchange(ref _closed, 1) != 0)
                return;
            Timer grace = Interlocked.Exchange(ref _grace, null);
            grace?.Dispose();
            try
            {
                _close();
            }
            catch (Exception)
            {
                // The close action has already been attempted.
            }
        }
    }
}
