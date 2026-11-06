---
id: operation-list-sfx-types
title: list_sfx_types
description: Archetypes of the procedural synthesizer with the English and French words that select them.
section: Reference
order: 200
parent: operations
revision: 85d484758f6458ea
---

Archetypes of the procedural synthesizer with the English and French words that select them.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `language` | `value` | No | Keyword language `default="all"`, `enum=["all", "en", "fr"]` |
| `query` | `string` | No | Filter `default=""` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_sfx_types
```
