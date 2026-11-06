---
id: operation-describe-plugin
title: describe_plugin
description: Load one VST3, CLAP, LV2 or JSFX plugin in a worker and return its parameters.
section: Reference
order: 200
parent: operations
revision: 23f08743eb4d8453
---

Load one VST3, CLAP, LV2 or JSFX plugin in a worker and return its parameters.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `plugin` | `string` | Yes | Path to a VST3, CLAP, LV2 bundle or JSFX script  |
| `plugin_name` | `string` | No | Plugin name or ID within a bundle `default=""` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation describe_plugin
```
