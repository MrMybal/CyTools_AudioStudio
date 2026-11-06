---
id: operation-scan-plugins
title: scan_plugins
description: Recherche dans les dossiers pour les plugins VST3, CLAP, LV2 et JSFX dans un processus travail isolé et stockage de leurs paramètres. Un plugin qui crash est signalé, mais ce n'est pas fatal.
section: Référence
order: 200
parent: operations
sourceRevision: 9fc6ee6dbd874c6c
---

Recherche dans les dossiers pour les plugins VST3, CLAP, LV2 et JSFX dans un processus travail isolé et stockage de leurs paramètres. Un plugin qui crash est signalé, mais ce n'est pas fatal.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `directories` | `array` | Non | Dossiers supplémentaires ; les dossiers de plugin standard sont toujours recherchés `default=[]` |
| `force` | `boolean` | Non | Relecture des plugins déjà stockés `default=false` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `plugins` | `array` | Oui | Voir les paramètres de l’opération.  |
| `failures` | `array` | Non | Voir les paramètres de l’opération.  |
| `count` | `integer` | Oui | Plugins trouvés `default=0` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation scan_plugins
```
