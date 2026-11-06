---
id: operation-read-jsfx
title: read_jsfx
description: Read a JSFX script without executing it.
section: Reference
order: 200
parent: operations
revision: 1c0b415a716438f6
---

Read a JSFX script without executing it.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `script` | `string` | Yes | JSFX source path  |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation read_jsfx
```
