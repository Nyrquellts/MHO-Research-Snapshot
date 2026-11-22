# Server infrastructure excerpts

These .NET 8 examples contain the build stamp, locale catalog and integer plural rules, a bounded telemetry ring, and an ordered cleanup runner. The build stamp records which revision and data digests belong to a build. The catalog reads plain text and plural forms from JSON. The ring keeps recent events in memory and counts drops when producers contend for a slot. The cleanup runner records failures and continues through the remaining actions.

Run the checks from this folder.

```sh
dotnet run --project Infrastructure.csproj -c Release
```

The checks use an example locale registry and synthetic in-memory build and event values. The code retains the AGPL-3.0 terms of the server source.
