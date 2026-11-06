---
id: operation-save-workflow
title: save_workflow
description: Persist a workflow document under data/workflows (explicit user action).
section: Reference
order: 200
parent: operations
revision: 92348c48d14e956a
---

Persist a workflow document under data/workflows (explicit user action).

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | `string` | Yes | Workflow name  |
| `workflow` | `object` | Yes | Inline workflow document (format cytools-audiostudio-workflow). Use workflow_name instead to reference a saved workflow.  |
| `overwrite` | `boolean` | No | Replace an existing workflow of that name `default=false` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `path` | `string` | Yes | Saved path  |
| `name` | `string` | No | Name  |
| `summary` | `string` | No | Chain summary  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: not declared.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_workflow
```
