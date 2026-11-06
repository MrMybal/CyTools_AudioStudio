---
id: operation-save-jsfx
title: save_jsfx
description: Compile first, then save under data/scripts/JSFX. A compilation error preserves the existing script.
section: Reference
order: 200
parent: operations
revision: 11ac6445b80f023d
---

Compile first, then save under data/scripts/JSFX. A compilation error preserves the existing script.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | Yes | Script name without extension  |
| `source` | `string` | Yes | JSFX source code  |
| `overwrite` | `boolean` | No | Replace existing script `default=false` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_jsfx
```
