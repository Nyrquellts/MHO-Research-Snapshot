# Standalone C# models

This is the C# port of the terrain, combat, and party-scaling models in the Python examples. The terrain grid interpolates elevation between samples and clamps queries to its bounds. The combat model applies configurable hit-zone and defense values, accumulates damage on parts, and records flinches and breaks. The scaling model applies authored health and damage multipliers by party size.

The console project uses the .NET 8 SDK and its standard libraries. Run the 18 in-memory checks from the repository root.

```sh
dotnet run --project examples/csharp/Mho.Solo/Mho.Solo.csproj -c Release
```

The checks use small handcrafted examples. They exercise the models independently of a game installation.
