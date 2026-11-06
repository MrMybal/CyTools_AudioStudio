---
id: operation-install-model
title: install_model
description: Download or resume a model with verification. The licence must be accepted personally when the source requires it; a gated source returns AccessRequired with the official page.
section: Reference
order: 200
parent: operations
revision: 33659d12c3df7a57
---

Download or resume a model with verification. The licence must be accepted personally when the source requires it; a gated source returns AccessRequired with the official page.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `model` | `string` | Yes | Model id (see list_models), e.g. piper.en_US-lessac-medium  |
| `accept_license` | `boolean` | No | I have read and accept the licence of this model `default=false` |
| `repair` | `boolean` | No | Re-hash existing files and re-download corrupted ones `default=false` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `modelId` | `string` | Yes | Model  |
| `state` | `string` | Yes | State  |
| `downloaded` | `integer` | No | Bytes downloaded `default=0` |

## Behaviour and access {#behaviour}

- Required permissions: `network`
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation install_model
```
