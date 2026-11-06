---
id: operation-analyze-audio
title: analyze_audio
description: Duration, peak, RMS, integrated loudness (LUFS), true peak, clipping, DC offset, leading/trailing silence.
section: Reference
order: 200
parent: operations
revision: 23de495c4a4a8100
---

Duration, peak, RMS, integrated loudness (LUFS), true peak, clipping, DC offset, leading/trailing silence.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `input` | `string` | Yes | Audio file  |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation analyze_audio
```
