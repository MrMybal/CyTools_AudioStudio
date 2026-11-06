---
id: operation-diagnose-backend
title: diagnose_backend
description: Démarrer le worker d'un backend et rapporter les versions moteur, l'availability de la CUDA et les modèles résidents.
section: Référence
order: 200
parent: operations
sourceRevision: e5dfc32e2451ff44
---

Démarrer le worker d'un backend et rapporter les versions moteur, l'availability de la CUDA et les modèles résidents.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `backend` | `value` | Oui | Backend `default="sfx_procedural"`, `enum=["sfx_procedural", "audioldm", "acestep", "piper", "qwen3tts", "fishspeech", "llm", "whisper", "matchering"]` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation diagnose_backend
```
