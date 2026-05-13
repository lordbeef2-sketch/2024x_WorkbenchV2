# TWC Workbench Cameo Plugin

This folder now contains a real Cameo plugin project scaffold, not just planning notes.

The plugin is designed to:
- load inside Cameo/MagicDraw as a standard `plugin.xml` plugin
- traverse the currently opened project model through Cameo OpenAPI
- export a full branch snapshot of model data
- compute a branch delta on project close
- post snapshots and deltas into TWC Workbench through authenticated ingest endpoints
- fall back to writing JSON payloads locally when the Workbench ingest endpoint is not configured yet

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
- Adds a manual `Export Current Project Snapshot` action
- Captures a baseline snapshot when a project opens
- Publishes a full snapshot on project save
- Publishes a delta on project close when a baseline exists
- Uses `Authorization: Bearer <token>` for Workbench ingest API access
- Uses the TWC resource id as the Workbench `projectId` key so cached data lands under the same project Workbench already exposes
- Requires `metadata.serverId` to match the Workbench server profile id exactly when posting to Workbench

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
workbench.ingestToken=your-plugin-write-token
metadata.serverId=twc-2022x
```

If the plugin cannot resolve the TWC resource/workspace ids from the open remote project URL, also set:

```properties
metadata.workspaceId=...
metadata.resourceId=...
```

On the Workbench backend side, the same write token must exist in:

```env
CACHE_INGEST_TOKENS=["your-plugin-write-token"]
```

## Notes

- This scaffold is buildable, structured, and plugin-shaped, but it still needs a real Cameo environment to compile and run.
- The export model aims to be rich enough for Workbench cache ingestion without forcing us into a fixed third-party file format.
