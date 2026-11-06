---
id: operation-get-workflow
title: get_workflow
description: Read a saved workflow document.
section: Reference
order: 200
parent: operations
revision: 618e580fa6fbe836
---

Read a saved workflow document.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | Yes | Workflow name or path  |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation get_workflow
```
