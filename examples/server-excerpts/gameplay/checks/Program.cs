// SPDX-License-Identifier: AGPL-3.0-only
using System.Collections;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace MhoResearch.ServerExcerpts.Gameplay;

[AttributeUsage(AttributeTargets.Method)]
internal sealed class CheckAttribute : Attribute;

internal static class Program
{
    private static int Main()
    {
        int count = 0;
        int failures = 0;
        foreach (Type type in typeof(Program).Assembly.GetTypes().OrderBy(t => t.Name))
        {
            foreach (MethodInfo method in type.GetMethods().Where(m => m.IsDefined(typeof(CheckAttribute))).OrderBy(m => m.Name))
            {
                count++;
                try
                {
                    method.Invoke(Activator.CreateInstance(type), null);
                }
                catch (TargetInvocationException error)
                {
                    failures++;
                    Console.Error.WriteLine($"{type.Name}.{method.Name}: {error.InnerException?.Message ?? error.Message}");
                }
            }
        }
        Console.WriteLine($"{count - failures} of {count} gameplay checks passed.");
        return failures == 0 && count > 0 ? 0 : 1;
    }
}

internal static class Assert
{
    public static void True(bool value, [CallerArgumentExpression(nameof(value))] string expression = "")
    {
        if (!value)
            throw new InvalidOperationException($"Expected true: {expression}");
    }

    public static void False(bool value, [CallerArgumentExpression(nameof(value))] string expression = "")
    {
        if (value)
            throw new InvalidOperationException($"Expected false: {expression}");
    }

    public static void Equal<T>(T expected, T actual)
    {
        bool equal = expected is IEnumerable left && actual is IEnumerable right && expected is not string
            ? left.Cast<object>().SequenceEqual(right.Cast<object>())
            : EqualityComparer<T>.Default.Equals(expected, actual);
        if (!equal)
            throw new InvalidOperationException($"Expected {expected}, got {actual}.");
    }

    public static void NotEqual<T>(T expected, T actual) => False(EqualityComparer<T>.Default.Equals(expected, actual));
    public static void Null(object value) => True(value == null);
    public static void NotNull(object value) => True(value != null);
    public static T Single<T>(IEnumerable<T> items) => items.Single();
    public static T Single<T>(IEnumerable<T> items, Func<T, bool> predicate) => items.Single(predicate);
    public static void Empty<T>(IEnumerable<T> items) => False(items.Any());
    public static void Contains<T>(IEnumerable<T> items, Func<T, bool> predicate) => True(items.Any(predicate));

    public static void All<T>(IEnumerable<T> items, Action<T> check)
    {
        foreach (T item in items)
            check(item);
    }
}
