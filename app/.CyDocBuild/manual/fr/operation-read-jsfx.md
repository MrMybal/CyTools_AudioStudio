---
id: operation-read-jsfx
title: read_jsfx
description: Lire un script JSFX sans l'exécuter.
section: Référence
order: 200
parent: operations
sourceRevision: 1c0b415a716438f6
---

Lire un script JSFX sans l'exécuter.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `script` | `string` | Oui | Chemin source JSFX  |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation read_jsfx
```
