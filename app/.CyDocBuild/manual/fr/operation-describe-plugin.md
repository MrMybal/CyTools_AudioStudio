---
id: operation-describe-plugin
title: describe_plugin
description: Charger un plugin VST3, CLAP, LV2 ou JSFX dans un worker et retourner ses paramètres.
section: Référence
order: 200
parent: operations
sourceRevision: 23f08743eb4d8453
---

Charger un plugin VST3, CLAP, LV2 ou JSFX dans un worker et retourner ses paramètres.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `plugin` | `string` | Oui | Chemin vers un bundle VST3, CLAP, LV2 ou un script JSFX  |
| `plugin_name` | `string` | Non | Nom du plugin ou ID dans un bundle `default=""` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation describe_plugin
```
