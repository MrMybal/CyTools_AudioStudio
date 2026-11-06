---
id: operation-save-voice-preset
title: save_voice_preset
description: Stocke les paramètres d'une voix (sans texte) sous forme d'un préétabli réutilisable.
section: Référence
order: 200
parent: operations
sourceRevision: 80428cce99925f6a
---

Stocke les paramètres d'une voix (sans texte) sous forme d'un préétabli réutilisable.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | `string` | Oui | Nom du préétabli  |
| `backend` | `value` | Oui | Backend de voix `default="qwen3tts"`, `enum=["piper", "qwen3tts", "fishspeech"]` |
| `parameters` | `object` | Oui | Paramètres de l'opération correspondante voice_* (le texte est ignoré)  |
| `post_workflow` | `string` | Non | Travail optionnel (nom enregistré) appliqué au son généré, avec le rendu en queue. `default=""` |
| `notes` | `string` | Non | Notes `default=""` |
| `preset_id` | `string` | Non | Identifiant de la prédéfinition existante pour écraser `default=""` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | `string` | Oui | Identifiant de la prédéfinition  |
| `path` | `string` | Oui | Chemin enregistré  |
| `preset` | `object` | Non | Voir les paramètres de l’opération.  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_voice_preset
```
