---
id: operation-preview-sfx-recipe
title: preview_sfx_recipe
description: Analyser un prompt avec le synthesiseur procédural et retourner la recette exacte sans rendering.
section: Référence
order: 200
parent: operations
sourceRevision: 653b595b447ff898
---

Analyser un prompt avec le synthesiseur procédural et retourner la recette exacte sans rendering.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `prompt` | `string` | Oui | Description  |
| `duration_seconds` | `number/null` | Non | Voir les paramètres de l’opération. `default=null`, `minimum=0.2`, `maximum=30.0` |
| `seed` | `integer` | Non | Semence `default=0`, `minimum=0`, `maximum=2147483647` |
| `sample_rate` | `value` | Non | Taux d'échantillonnage `default=44100`, `enum=[16000, 22050, 24000, 44100, 48000]` |
| `peak_dbfs` | `number` | Non | Pic `default=-1.0`, `minimum=-40.0`, `maximum=0.0` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation preview_sfx_recipe
```
