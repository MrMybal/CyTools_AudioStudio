---
id: operation-verify-model
title: verify_model
description: Re-check presence, sizes and hashes of an installed model.
section: Reference
order: 200
parent: operations
revision: c9bb80af90a2eaaf
---

Re-check presence, sizes and hashes of an installed model.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `model` | `string` | Yes | Model id  |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation verify_model
```
