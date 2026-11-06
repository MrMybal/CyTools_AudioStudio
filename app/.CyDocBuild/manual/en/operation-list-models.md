---
id: operation-list-models
title: list_models
description: Catalogue and installation state of every model (state, size, present bytes, licence, source).
section: Reference
order: 200
parent: operations
revision: d6ed9f89eaa939c4
---

Catalogue and installation state of every model (state, size, present bytes, licence, source).

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `backend` | `string` | No | Backend filter `default=""` |
| `include_voices` | `boolean` | No | Include the 177 Piper voices `default=false` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_models
```
