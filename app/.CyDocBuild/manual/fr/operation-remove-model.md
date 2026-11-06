---
id: operation-remove-model
title: remove_model
description: Supprimer les fichiers d'un modèle sous data/models.
section: Référence
order: 200
parent: operations
sourceRevision: 4eea8bc562293bf4
---

Supprimer les fichiers d'un modèle sous data/models.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `model` | `string` | Oui | Identifiant du modèle  |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation remove_model
```
