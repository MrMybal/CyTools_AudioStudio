---
id: operation-get-workflow
title: get_workflow
description: Lire un workflow enregistré.
section: Référence
order: 200
parent: operations
sourceRevision: 618e580fa6fbe836
---

Lire un workflow enregistré.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | `string` | Oui | Nom ou chemin du workflow  |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : non déclarée.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation get_workflow
```
