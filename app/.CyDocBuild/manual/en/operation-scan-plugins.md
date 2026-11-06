---
id: operation-scan-plugins
title: scan_plugins
description: Scan folders for VST3, CLAP, LV2 and JSFX plugins in an isolated worker process and cache their parameters. A crashing plugin is reported, not fatal.
section: Reference
order: 200
parent: operations
revision: 9fc6ee6dbd874c6c
---

Scan folders for VST3, CLAP, LV2 and JSFX plugins in an isolated worker process and cache their parameters. A crashing plugin is reported, not fatal.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `directories` | `array` | No | Extra folders; the standard plugin folders are always scanned `default=[]` |
| `force` | `boolean` | No | Rescan plugins already cached `default=false` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `plugins` | `array` | Yes | See the operation parameters.  |
| `failures` | `array` | No | See the operation parameters.  |
| `count` | `integer` | Yes | Plugins found `default=0` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation scan_plugins
```
