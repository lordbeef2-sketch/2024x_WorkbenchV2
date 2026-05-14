# TWC Workbench Cameo Plugin

This folder now contains a real Cameo plugin project scaffold, not just planning notes.

The plugin is designed to:
- load inside Cameo/MagicDraw as a standard `plugin.xml` plugin
- traverse the currently opened project model through Cameo OpenAPI
- capture a full recursive branch snapshot of semantic model data from the active primary model
- compute a branch delta on project close
- post snapshots and deltas into TWC Workbench through authenticated ingest endpoints
- fail clearly when Workbench ingest is not configured, instead of drifting into local file exports

## Folder layout

- [plugin.xml](C:/sand/fresh/New%20Project/plugin/plugin.xml): Cameo plugin descriptor
- [build.gradle](C:/sand/fresh/New%20Project/plugin/build.gradle): Gradle build for the plugin jar and staged plugin folder
- [settings.gradle](C:/sand/fresh/New%20Project/plugin/settings.gradle): Gradle project name
- [gradle.properties](C:/sand/fresh/New%20Project/plugin/gradle.properties): plugin coordinates and defaults
- [workbench-plugin.properties](C:/sand/fresh/New%20Project/plugin/config/workbench-plugin.properties): backing-store config file managed by the plugin
- [src/main/java](C:/sand/fresh/New%20Project/plugin/src/main/java): plugin source

Supporting design docs are still here if we want them while building:
- [PLUGIN_SPEC.md](C:/sand/fresh/New%20Project/plugin/PLUGIN_SPEC.md)
- [WORKBENCH_INGEST_API.md](C:/sand/fresh/New%20Project/plugin/WORKBENCH_INGEST_API.md)
- [DATA_MODEL.md](C:/sand/fresh/New%20Project/plugin/DATA_MODEL.md)

## Build

The simplest path now is the local build script, which downloads the needed JDKs,
builds both plugin targets, and stages installable outputs for each Cameo line.

Example:

```powershell
cd "C:\sand\fresh\New Project\plugin"
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-plugin.ps1
```

That produces:

```text
dist\2022x\
dist\2024x\
dist\twc-workbench-cameo-plugin-2022x.zip
dist\twc-workbench-cameo-plugin-2024x.zip
```

If you need a one-off manual build against a specific Cameo runtime, you can still
invoke Gradle directly with:

```powershell
<gradle> -p "C:\sand\fresh\New Project\plugin" clean stagePlugin `
  -PcameoHome="C:\path\to\Cameo_no_install" `
  -PpluginTarget=2022x `
  -PpluginJavaVersion=11
```

## Install into Cameo

Copy the staged folder into the Cameo installation `plugins` directory so the final layout looks like:

```text
<CAMEO_HOME>\plugins\twc-workbench-cameo-plugin\
  plugin.xml
  lib\twc-workbench-cameo-plugin.jar
  config\workbench-plugin.properties
```

## Current behavior

- Adds a `TWC Workbench` main-menu category
- Adds a `Configure Workbench Connection...` action inside Cameo
- Adds a manual `Publish Current Project Snapshot` action
- Captures a baseline snapshot when a project opens
- Publishes a full snapshot on project save
- Publishes a delta on project close when a baseline exists
- Exports owned elements recursively and includes names, qualified names, stereotypes, documentation, attributes, and cross-element references in the payload sent to Workbench
- Uses `Authorization: Bearer <token>` for Workbench ingest API access
- Uses the TWC resource id as the Workbench `projectId` key so cached data lands under the same project Workbench already exposes
- Resolves workspace and resource ids from the active remote TWC project instead of allowing manual override
- Requires `metadata.serverId` to match the Workbench server profile id exactly when posting to Workbench

The plugin now ships with a preset ingest bearer token for your current setup, and Workbench can store that same exact value in encrypted app storage through the admin Settings screen.

## Configure inside Cameo

After the plugin is installed, open the Cameo main menu:

```text
TWC Workbench -> Configure Workbench Connection...
```

That dialog now owns the plugin connection settings and writes them back to:

[workbench-plugin.properties](C:/sand/fresh/New%20Project/plugin/config/workbench-plugin.properties)

## Workbench config required for real ingest

Inside the Cameo dialog, fill these at minimum:

```properties
workbench.baseUrl=https://your-workbench-host
workbench.ingestToken=Hnwdujnq@!N)N!)NQOWDN!*@)*#nQ)DN)!!N()@N@N!)NF
metadata.serverId=twc-2022x
```

On the Workbench side, save that same exact write token in the admin Settings screen under `Plugin Ingest Token`. Workbench stores the app-managed token encrypted and can now accept a specific token value, not just a randomly generated one.

If the Cameo JVM does not trust the Workbench HTTPS certificate and snapshot
publishing fails with a `PKIX path building failed` error, either:

- install your organization CA certificate into the JVM trust store used by Cameo, or
- temporarily enable:

```properties
http.insecureTls=true
```

from `TWC Workbench -> Configure Workbench Connection...`

Use the TLS bypass only for controlled internal environments.

`CACHE_INGEST_TOKENS` still exists as a legacy fallback in `backend/.env` if you need file-based bootstrap during migration:

```env
CACHE_INGEST_TOKENS=["your-plugin-write-token"]
```

## Notes

- The plugin project is built for both 2022x and 2024x, but it still needs a real Cameo/TWC environment for live end-to-end validation.
- The export model aims to be rich enough for Workbench cache ingestion without forcing us into a fixed third-party file format.
