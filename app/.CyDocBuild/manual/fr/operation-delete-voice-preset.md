---
id: operation-delete-voice-preset
title: delete_voice_preset
description: Supprimer une prédéfinition de voix enregistrée.
section: Référence
order: 200
parent: operations
sourceRevision: 403d2da4ffbf853d
---

Supprimer une prédéfinition de voix enregistrée.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `preset` | `string` | Oui | Identifiant de la prédéfinition  |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `deleted` | `boolean` | Oui | Supprimé `default=true` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation delete_voice_preset
```
