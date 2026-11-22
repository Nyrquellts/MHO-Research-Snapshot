// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections.Generic;

namespace MhoResearch.ServerExcerpts.Gameplay;

/// <summary>
/// The recent requests of one hunter and what came of each, so that a request that arrives twice -- a retransmission, a client that asks
/// again after a reconnect -- is answered with the first answer and changes nothing. A request has an id when the packet layer can give
/// one (the connection and the sequence number of the packet); an empty id is a request that cannot be recognised and is never remembered.
/// Bounded: the oldest are forgotten first, so a hunt cannot grow it.
/// </summary>
public sealed class RequestBook
{
    private readonly object _sync = new();
    private readonly int _capacity;

    /// <summary>Held by whoever carries out a request while it checks the book, acts and records the answer, so that two copies of one request
    /// cannot both act (the book's own lock is only for its dictionary).</summary>
    public object Sync { get; } = new();
    private readonly Dictionary<string, object> _results = new();
    private readonly Queue<string> _order = new();

    private sealed class ActionRecord
    {
        public object Result;
        public double At;
        public double RetryUntil = double.NegativeInfinity;
    }

    // An action key can survive a retry even when the original request ID changes.
    private readonly Dictionary<string, ActionRecord> _actions = new();

    public RequestBook(int capacity = 64)
    {
        _capacity = capacity < 1 ? 1 : capacity;
    }

    public int Count
    {
        get
        {
            lock (_sync)
                return _results.Count;
        }
    }

    /// <summary>The answer this request already got, if it is remembered.</summary>
    public bool TryGet<T>(string requestId, out T result) where T : class
    {
        result = null;
        if (string.IsNullOrEmpty(requestId))
            return false;
        lock (_sync)
        {
            if (!_results.TryGetValue(requestId, out object stored))
                return false;
            result = stored as T;
            return result != null;
        }
    }

    /// <summary>Remembers that an action was carried out and what came of it. <paramref name="key"/> names the action and what it acted on; <paramref name="at"/>
    /// is the hunt's clock. Bounded like the packets are.</summary>
    public void RememberAction(string key, object result, double at)
    {
        if (string.IsNullOrEmpty(key) || result == null || !double.IsFinite(at))
            return;
        lock (_sync)
        {
            _actions[key] = new ActionRecord { Result = result, At = at };
            while (_actions.Count > _capacity)
            {
                string oldest = null;
                double when = double.PositiveInfinity;
                foreach (KeyValuePair<string, ActionRecord> entry in _actions)
                {
                    if (entry.Value.At < when)
                    {
                        when = entry.Value.At;
                        oldest = entry.Key;
                    }
                }
                _actions.Remove(oldest);
            }
        }
    }

    /// <summary>
    /// The hunter's connection dropped and came back: whatever they did within <paramref name="window"/> seconds before <paramref name="now"/> may be asked for
    /// again by a client that never heard the answer, and the first ask of each, within <paramref name="window"/> seconds after <paramref name="now"/>, is answered
    /// with what was decided (<see cref="TryRetry{T}"/>) instead of being done a second time. A packet's identity is a connection's, so it cannot say that a request
    /// is a retry; the action and the time can.
    /// </summary>
    public void ArmRetries(double now, double window)
    {
        if (!double.IsFinite(now) || !double.IsFinite(window) || window < 0)
            return;
        lock (_sync)
            foreach (ActionRecord record in _actions.Values)
                record.RetryUntil = now - record.At <= window ? now + window : double.NegativeInfinity;
    }

    /// <summary>The recorded result of an action that a reconnected client is asking for again at <paramref name="now"/>, once; nothing once the window since the
    /// reconnect has passed (an ask that late is a new one).</summary>
    public bool TryRetry<T>(string key, double now, out T result) where T : class
    {
        result = null;
        if (string.IsNullOrEmpty(key) || !double.IsFinite(now))
            return false;
        lock (_sync)
        {
            if (!_actions.TryGetValue(key, out ActionRecord record) || now > record.RetryUntil || record.Result is not T typed)
                return false;
            record.RetryUntil = double.NegativeInfinity;
            result = typed;
            return true;
        }
    }

    /// <summary>Remembers the answer of a request that was carried out (a refusal is not remembered: asking again may succeed).</summary>
    public void Remember(string requestId, object result)
    {
        if (string.IsNullOrEmpty(requestId) || result == null)
            return;
        lock (_sync)
        {
            if (_results.ContainsKey(requestId))
                return;
            _results[requestId] = result;
            _order.Enqueue(requestId);
            while (_order.Count > _capacity)
                _results.Remove(_order.Dequeue());
        }
    }
}
