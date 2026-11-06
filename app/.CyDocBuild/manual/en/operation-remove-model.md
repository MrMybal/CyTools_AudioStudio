---
id: operation-remove-model
title: remove_model
description: Delete the files of a model under data/models.
section: Reference
order: 200
parent: operations
revision: 4eea8bc562293bf4
---

Delete the files of a model under data/models.

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
runtime\python\Scripts\python.exe app\tool.py describe-operation remove_model
```
