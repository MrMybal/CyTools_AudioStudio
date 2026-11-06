---
id: operation-save-workflow
title: save_workflow
description: Enregistrer un workflow sous data/workflows (action explicite de l'utilisateur).
section: Référence
order: 200
parent: operations
sourceRevision: 92348c48d14e956a
---

Enregistrer un workflow sous data/workflows (action explicite de l'utilisateur).

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | `string` | Oui | Nom du workflow  |
| `workflow` | `object` | Oui | Document de workflow intégré (format cytools-audiostudio-workflow). Utilisez workflow_name au lieu de cela pour faire référence à un workflow enregistré.  |
| `overwrite` | `boolean` | Non | Remplacer un workflow existant de ce nom `default=false` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `path` | `string` | Oui | Chemin enregistré  |
| `name` | `string` | Non | Nom  |
| `summary` | `string` | Non | Résumé de la chaîne  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_workflow
```
