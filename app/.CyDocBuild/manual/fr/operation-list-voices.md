---
id: operation-list-voices
title: list_voices
description: Voix par backend : catalogue de voix Piper (installées et téléchargeables), Qwen3-TTS interprètes et modes, capacités de Parole de Poisson, et préétablis enregistrés.
section: Référence
order: 200
parent: operations
sourceRevision: f71f5fca93217581
---

Voix par backend : catalogue de voix Piper (installées et téléchargeables), Qwen3-TTS interprètes et modes, capacités de Parole de Poisson, et préétablis enregistrés.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `backend` | `value` | Non | Filtre backend `default="all"`, `enum=["all", "piper", "qwen3tts", "fishspeech"]` |
| `language` | `string` | Non | Filtre de langue (par ex. fr, en) `default=""` |
| `installed_only` | `boolean` | Non | Seulement les voix Piper installées `default=false` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_voices
```
