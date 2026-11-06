---
id: operation-validate-jsfx
title: validate_jsfx
description: Compile source in an isolated process. Relative imports resolve beside the selected source directory. Does not replace any script.
section: Reference
order: 200
parent: operations
revision: 3cee9f534458c4a3
---

Compile source in an isolated process. Relative imports resolve beside the selected source directory. Does not replace any script.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `source` | `string` | Yes | JSFX source code  |
| `directory` | `string` | No | Directory for relative JSFX imports `default=""` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation validate_jsfx
```
