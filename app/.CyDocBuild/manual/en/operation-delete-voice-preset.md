---
id: operation-delete-voice-preset
title: delete_voice_preset
description: Remove a saved voice preset.
section: Reference
order: 200
parent: operations
revision: 403d2da4ffbf853d
---

Remove a saved voice preset.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `preset` | `string` | Yes | Preset id  |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `deleted` | `boolean` | Yes | Deleted `default=true` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation delete_voice_preset
```
