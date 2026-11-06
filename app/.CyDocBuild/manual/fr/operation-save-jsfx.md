---
id: operation-save-jsfx
title: save_jsfx
description: Compilez en premier, puis enregistrez sous data/scripts/JSFX. Une erreur de compilation conserve le script existant.
section: Référence
order: 200
parent: operations
sourceRevision: 11ac6445b80f023d
---

Compilez en premier, puis enregistrez sous data/scripts/JSFX. Une erreur de compilation conserve le script existant.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | `string` | Oui | Nom du script sans extension  |
| `source` | `string` | Oui | Code source JSFX  |
| `overwrite` | `boolean` | Non | Remplacez le script existant `default=false` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation save_jsfx
```
