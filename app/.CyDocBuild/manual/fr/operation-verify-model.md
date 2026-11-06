---
id: operation-verify-model
title: verify_model
description: Re-évaluer la présence, les tailles et les hachages d'un modèle installé.
section: Référence
order: 200
parent: operations
sourceRevision: c9bb80af90a2eaaf
---

Re-évaluer la présence, les tailles et les hachages d'un modèle installé.

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
runtime\python\Scripts\python.exe app\tool.py describe-operation verify_model
```
