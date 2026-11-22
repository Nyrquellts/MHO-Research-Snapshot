// SPDX-License-Identifier: AGPL-3.0-only
using System;
using System.Collections.Generic;

namespace Mho.Research.Infrastructure;

/// <summary>
/// Runs cleanup actions in order and returns a short report of each failure.
/// A failing action leaves the remaining actions eligible to run.
/// </summary>
public sealed class ZoneCleanup
{
    private readonly List<(string Name, Action Step)> _steps = new();

    public int Count => _steps.Count;

    public IEnumerable<string> Names
    {
        get
        {
            foreach ((string name, _) in _steps)
                yield return name;
        }
    }

    public ZoneCleanup Add(string name, Action step)
    {
        if (step != null)
            _steps.Add((string.IsNullOrWhiteSpace(name) ? "step" : name, step));
        return this;
    }

    /// <summary>Runs every step, returns those that failed as <c>name: message</c>; never throws.</summary>
    public List<string> Run()
    {
        List<string> failed = new();
        foreach ((string name, Action step) in _steps)
        {
            try
            {
                step();
            }
            catch (Exception ex)
            {
                failed.Add($"{name}: {Short(ex)}");
            }
        }
        return failed;
    }

    private const int MaxText = 140;
    private static string Short(Exception ex) => Short($"{ex.GetType().Name}: {ex.Message}");
    private static string Short(string text) => Trim((text ?? string.Empty).Replace('\r', ' ').Replace('\n', ' ').Replace('"', '\'').Trim(), MaxText);
    private static string Trim(string text, int max) => text.Length <= max ? text : text[..(max - 1)] + "~";
}
