---
id: operation-validate-jsfx
title: validate_jsfx
description: Compiler le code source dans un processus isolé. Les imports relatifs résolvent à côté du répertoire sélectionné pour le code source. Ne remplace aucune script.
section: Référence
order: 200
parent: operations
sourceRevision: 3cee9f534458c4a3
---

Compiler le code source dans un processus isolé. Les imports relatifs résolvent à côté du répertoire sélectionné pour le code source. Ne remplace aucune script.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `source` | `string` | Oui | Code source JSFX  |
| `directory` | `string` | Non | Répertoire pour les imports relatifs JSFX `default=""` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation validate_jsfx
```
