---
id: operation-list-sfx-types
title: list_sfx_types
description: Archetypes du synthétiseur procédural avec les mots anglais et français qui les sélectionnent.
section: Référence
order: 200
parent: operations
sourceRevision: 85d484758f6458ea
---

Archetypes du synthétiseur procédural avec les mots anglais et français qui les sélectionnent.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `language` | `value` | Non | Langue des mots-clés `default="all"`, `enum=["all", "en", "fr"]` |
| `query` | `string` | Non | Filtre `default=""` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_sfx_types
```
