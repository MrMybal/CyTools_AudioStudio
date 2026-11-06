---
id: operation-diagnose-backend
title: diagnose_backend
description: Start the worker of a backend and report engine versions, CUDA availability and resident models.
section: Reference
order: 200
parent: operations
revision: e5dfc32e2451ff44
---

Start the worker of a backend and report engine versions, CUDA availability and resident models.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `backend` | `value` | Yes | Backend `default="sfx_procedural"`, `enum=["sfx_procedural", "audioldm", "acestep", "piper", "qwen3tts", "fishspeech", "llm", "whisper", "matchering"]` |
## Returns {#returns}

No named fields are declared at this level. Inspect the operation schema with `describe-operation` for its exact shape.

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation diagnose_backend
```
