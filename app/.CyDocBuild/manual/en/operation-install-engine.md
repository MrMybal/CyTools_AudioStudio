---
id: operation-install-engine
title: install_engine
description: Create or repair an engine environment (PyTorch CUDA or CPU, Piper) at its final path, with vendored sources and an import check.
section: Reference
order: 200
parent: operations
revision: 4afe763ceef0aace
---

Create or repair an engine environment (PyTorch CUDA or CPU, Piper) at its final path, with vendored sources and an import check.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `engine` | `value` | Yes | Engine `default="torch"`, `enum=["torch", "piper"]` |
| `cpu_only` | `boolean` | No | Install the CPU build of PyTorch `default=false` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: `network`
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation install_engine
```
