---
id: operation-list-models
title: list_models
description: Catalogue et état d'installation de chaque modèle (état, taille, octets présents, licence, source).
section: Référence
order: 200
parent: operations
sourceRevision: d6ed9f89eaa939c4
---

Catalogue et état d'installation de chaque modèle (état, taille, octets présents, licence, source).

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `backend` | `string` | Non | Filtre backend `default=""` |
| `include_voices` | `boolean` | Non | Inclure les 177 voix Piper `default=false` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation list_models
```
