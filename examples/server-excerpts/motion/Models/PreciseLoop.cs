// SPDX-License-Identifier: AGPL-3.0-only
namespace Mho.Research.Motion;

public static class StepRate
{
    /// <summary>The drive's step rate when nothing overrides it, steps a second.</summary>
    public const double DefaultHz = 165;

    /// <summary>The length of one step at <paramref name="hz"/> (the default rate when it is not a usable one), seconds.</summary>
    public static float Dt(double hz) => (float)(1.0 / Usable(hz));

    /// <summary><paramref name="steps"/> steps at <paramref name="hz"/>, in seconds.</summary>
    public static double Seconds(double steps, double hz = DefaultHz) => steps / Usable(hz);

    /// <summary><paramref name="seconds"/> at <paramref name="hz"/>, in whole steps (rounded).</summary>
    public static int Steps(double seconds, double hz = DefaultHz) => (int)Math.Round(seconds * Usable(hz));

    /// <summary>The length of one step in ticks of a clock that runs at <paramref name="frequency"/> ticks a second (at least one).</summary>
    public static long PeriodTicks(long frequency, double hz) => Math.Max(1, (long)(frequency / Usable(hz)));

    /// <summary>A usable rate (finite and at least 1 Hz), else the default one.</summary>
    public static double Usable(double hz) => double.IsFinite(hz) && hz >= 1 ? hz : DefaultHz;
}

/// <summary>What a fixed-rate loop measured about itself: how often it ran, how late it was and how much of its time the step took.</summary>
public readonly record struct LoopReport(long Ticks, double Seconds, long Late, long VeryLate, double MaxGapMilliseconds,
                                         double MeanBusyMilliseconds, double MaxBusyMilliseconds, double P99GapMilliseconds = 0,
                                         long Dropped = 0, double PeriodMilliseconds = 0, long CaughtUp = 0)
{
    /// <summary>The gap that counts as late: one and a half periods of the loop's own rate (so the verdict scales with the rate, not with a number of milliseconds).</summary>
    public double LateThresholdMilliseconds => PeriodMilliseconds * PreciseLoop.LateAtPeriods;

    /// <summary>The share of the steps that came late, 0 to 1.</summary>
    public double LateShare => Ticks > 0 ? (double)Late / Ticks : 0;

    /// <summary>Steps a second, on average.</summary>
    public double Hz => Seconds > 0 ? Ticks / Seconds : 0;
}

/// <summary>Where a <see cref="PreciseLoop"/> gets the time and waits for it; tests replace it.</summary>
public interface ILoopClock
{
    /// <summary>Now, in ticks of <see cref="Frequency"/> a second.</summary>
    long Now { get; }

    long Frequency { get; }

    /// <summary>Returns when <see cref="Now"/> has reached <paramref name="deadline"/> (at once when it has).</summary>
    void WaitUntil(long deadline);
}

/// <summary>Run clock-driven steps with bounded catch-up and measure schedule gaps.</summary>
public sealed class PreciseLoop
{
    /// <summary>A gap longer than this many periods is a late step; <see cref="VeryLateAtPeriods"/> a very late one.</summary>
    public const double LateAtPeriods = 1.5, VeryLateAtPeriods = 3.0;

    /// <summary>The width of one bucket of the gap histogram the p99 is read from, milliseconds, and the number of them (the last one holds every longer gap).</summary>
    private const double BucketMilliseconds = 0.25;
    private const int Buckets = 800;

    /// <summary>The longest step, seconds.</summary>
    public const float MaxStep = 0.1f;

    private readonly double _hz;
    private readonly Action<float> _step;
    private readonly ILoopClock _clock;
    private readonly object _lock = new();
    private bool _stop;
    private bool _hasStarted, _hasStopped;
    private long _ticks, _late, _veryLate, _started, _stopped;
    private double _maxGap, _busy, _maxBusy, _periodMs;
    private long _dropped, _caughtUp;
    private readonly bool _fixedStep;
    private readonly long[] _gaps = new long[Buckets];

    /// <summary>Raised when the step throws (the loop goes on; the step is expected to handle its own faults).</summary>
    public Action<Exception> Failed { get; set; }

    public PreciseLoop(double hz, Action<float> step, ILoopClock clock, bool fixedStep = false)
    {
        _hz = StepRate.Usable(hz);
        _step = step;
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _fixedStep = fixedStep;
    }

    public double Hz => _hz;

    public bool FixedStep => _fixedStep;

    /// <summary>What the loop has measured so far (safe to call while it runs).</summary>
    public LoopReport Report()
    {
        lock (_lock)
        {
            long end = _hasStopped ? _stopped : _clock.Now;
            double seconds = _hasStarted ? (end - _started) / (double)_clock.Frequency : 0;
            return new LoopReport(_ticks, seconds, _late, _veryLate, _maxGap, _ticks > 0 ? _busy / _ticks : 0, _maxBusy, GapPercentile(0.99), _dropped, _periodMs, _caughtUp);
        }
    }

    /// <summary>Runs the schedule on the calling thread until <see cref="Stop"/>.</summary>
    public void Run()
    {
        long frequency = _clock.Frequency;
        long period = StepRate.PeriodTicks(frequency, _hz);
        long start = _clock.Now;
        lock (_lock)
        {
            _started = start;
            _hasStarted = true;
            _periodMs = period * 1000.0 / frequency;
        }
        long next = start + period, last = start;
        float fixedDt = (float)(1.0 / _hz);                            // the fixed step: one period, whatever the wall clock measured
        while (!_stop)
        {
            _clock.WaitUntil(next);
            if (_stop)
                break;
            long now = _clock.Now;
            double gap = (now - last) / (double)frequency;
            last = now;
            float dt = _fixedStep ? fixedDt : (float)Math.Min(MaxStep, Math.Max(0.0, gap));
            try
            {
                _step(dt);
            }
            catch (Exception ex)
            {
                Failed?.Invoke(ex);
            }
            long done = _clock.Now;
            Record(gap * 1000.0, (done - now) * 1000.0 / frequency, period * 1000.0 / frequency);
            next += period;
            if (done - next >= period)
            {
                if (_fixedStep)
                {
                    CatchUp((done - next) / period + 1, fixedDt, period, frequency, ref next, ref last);
                    continue;
                }
                // Reschedule after a full missed period and keep its count.
                long missed = (done - next) / period + 1;
                next = done + period;
                lock (_lock)
                    _dropped += missed;
            }
        }
        lock (_lock)
        {
            _stopped = _clock.Now;
            _hasStopped = true;
        }
    }

    /// <summary>The fixed step's answer to a stall (<see cref="Run"/>, <c>fixedStep</c>): of the <paramref name="owed"/> steps the stall left behind, up to <see cref="MaxStep"/>'s worth
    /// less the late step itself are run now, back to back, each told its one period (<see cref="LoopReport.CaughtUp"/>), so simulated time keeps up with the wall; the rest are dropped
    /// and counted (<see cref="LoopReport.Dropped"/>) and the schedule starts over a period from now. A stall costs a bounded burst, never an unbounded one; a stop that lands
    /// inside the burst ends it, and the steps it did not run are neither caught up nor dropped.</summary>
    private void CatchUp(long owed, float fixedDt, long period, long frequency, ref long next, ref long last)
    {
        long most = Math.Max(1, (int)(MaxStep * _hz)) - 1, bound = Math.Min(owed, most);
        long ran = 0;
        for (; ran < bound && !_stop; ran++)
        {
            long at = _clock.Now;
            try
            {
                _step(fixedDt);
            }
            catch (Exception ex)
            {
                Failed?.Invoke(ex);
            }
            Record((at - last) * 1000.0 / frequency, (_clock.Now - at) * 1000.0 / frequency, period * 1000.0 / frequency);
            last = at;
            next += period;
        }
        lock (_lock)
        {
            _caughtUp += ran;
            _dropped += owed - bound;                   // the steps beyond the bound; the ones a stop abandoned are neither caught up nor dropped
        }
        if (owed > bound)
            next = _clock.Now + period;
    }

    private void Record(double gapMs, double busyMs, double periodMs)
    {
        lock (_lock)
        {
            _ticks++;
            if (gapMs > periodMs * LateAtPeriods)
                _late++;
            if (gapMs > periodMs * VeryLateAtPeriods)
                _veryLate++;
            _gaps[(int)Math.Min(Buckets - 1, Math.Max(0.0, gapMs) / BucketMilliseconds)]++;
            if (gapMs > _maxGap)
                _maxGap = gapMs;
            _busy += busyMs;
            if (busyMs > _maxBusy)
                _maxBusy = busyMs;
        }
    }

    /// <summary>The gap the given share of the steps came within (<paramref name="share"/> 0 to 1), milliseconds, to the histogram's resolution; never above the longest gap seen. Call under the lock.</summary>
    private double GapPercentile(double share)
    {
        if (_ticks == 0)
            return 0;
        long want = (long)Math.Ceiling(_ticks * share), seen = 0;
        for (int i = 0; i < Buckets; i++)
        {
            seen += _gaps[i];
            if (seen >= want)
                return Math.Min(_maxGap, (i + 1) * BucketMilliseconds);
        }
        return _maxGap;
    }

    public void Stop() => _stop = true;
}
