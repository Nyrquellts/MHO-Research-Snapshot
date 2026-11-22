// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;

namespace Mho.ServerExcerpts.Transport
{
    /// <summary>
    /// Returns a preview budget for a record body. Each source and kind has its own quota.
    /// The class tracks counts and lengths, without storing any log content.
    /// </summary>
    public sealed class LogPreviewBudget
    {
        public const int FullDumps = 3;
        public const int HeadBytes = 512;
        public const int MaxKinds = 512;

        private readonly object _lock = new();
        private readonly Dictionary<(int Source, int Kind), int> _written = new();
        private readonly bool _everything;

        public LogPreviewBudget(bool everything = false)
        {
            _everything = everything;
        }

        /// <summary>Returns a byte limit or -1 for the whole record.</summary>
        public int BodyLimit(int kind, int source, int bodyLength)
        {
            if (_everything || bodyLength <= HeadBytes)
            {
                return -1;
            }

            lock (_lock)
            {
                if (_written.Count >= MaxKinds)
                {
                    _written.Clear();
                }

                _written.TryGetValue((source, kind), out int so_far);
                _written[(source, kind)] = so_far + 1;
                return so_far < FullDumps ? -1 : HeadBytes;
            }
        }
    }
}
