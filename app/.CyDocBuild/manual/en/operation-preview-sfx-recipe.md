---
id: operation-preview-sfx-recipe
title: preview_sfx_recipe
description: Parse a prompt with the procedural synthesizer and return the exact recipe without rendering.
section: Reference
order: 200
parent: operations
revision: 653b595b447ff898
---

Parse a prompt with the procedural synthesizer and return the exact recipe without rendering.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `prompt` | `string` | Yes | Description  |
| `duration_seconds` | `number/null` | No | See the operation parameters. `default=null`, `minimum=0.2`, `maximum=30.0` |
| `seed` | `integer` | No | Seed `default=0`, `minimum=0`, `maximum=2147483647` |
| `sample_rate` | `value` | No | Sample rate `default=44100`, `enum=[16000, 22050, 24000, 44100, 48000]` |
| `peak_dbfs` | `number` | No | Peak `default=-1.0`, `minimum=-40.0`, `maximum=0.0` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation preview_sfx_recipe
```
