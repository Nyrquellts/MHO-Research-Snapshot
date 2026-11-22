// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Generic;
using System.Threading;

namespace Mho.ServerExcerpts.Transport
{
    /// <summary>
    /// Counts unhandled and malformed inputs, with a bounded list of unhandled IDs for reports.
    /// </summary>
    public sealed class DispatchCounters
    {
        public const int MaxReportedIds = 8;
        private const int MaxSeenIds = 256;

        private readonly object _lock = new();
        private readonly HashSet<int> _seen = new();
        private readonly List<int> _order = new(MaxReportedIds);
        private long _unhandled, _malformed;

        public long Unhandled => Interlocked.Read(ref _unhandled);
        public long Malformed => Interlocked.Read(ref _malformed);

        /// <summary>Counts an unhandled input and returns whether its ID is absent from the bounded seen set.</summary>
        public bool RecordUnhandled(int cmd)
        {
            Interlocked.Increment(ref _unhandled);
            lock (_lock)
            {
                if (_seen.Contains(cmd))
                    return false;
                if (_seen.Count < MaxSeenIds)
                    _seen.Add(cmd);
                if (_order.Count < MaxReportedIds)
                    _order.Add(cmd);
                return true;
            }
        }

        /// <summary>Counts a malformed input.</summary>
        public void RecordMalformed() => Interlocked.Increment(ref _malformed);

        /// <summary>The first unhandled IDs seen (at most <see cref="MaxReportedIds"/>).</summary>
        public int[] ReportedIds()
        {
            lock (_lock)
                return _order.ToArray();
        }
    }
}
