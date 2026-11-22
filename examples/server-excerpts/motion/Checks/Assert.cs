// SPDX-License-Identifier: AGPL-3.0-only
namespace Mho.Research.Motion;

internal static class Assert
{
    internal static void True(bool condition, string message = "Expected true.")
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }

    internal static void False(bool condition) => True(!condition, "Expected false.");

    internal static void Equal<T>(T expected, T actual)
        => True(EqualityComparer<T>.Default.Equals(expected, actual), $"Expected {expected}, got {actual}.");

    internal static void InRange<T>(T actual, T minimum, T maximum) where T : IComparable<T>
        => True(actual.CompareTo(minimum) >= 0 && actual.CompareTo(maximum) <= 0,
                $"Expected {actual} in [{minimum}, {maximum}].");

    internal static void All<T>(IEnumerable<T> values, Action<T> check)
    {
        foreach (T value in values)
            check(value);
    }

    internal static void Contains<T>(IEnumerable<T> values, Func<T, bool> predicate)
        => True(values.Any(predicate), "No value matched the predicate.");
}
