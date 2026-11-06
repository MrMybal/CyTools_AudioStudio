---
id: operation-analyze-audio
title: analyze_audio
description: Durée, pic, RMS, intégrée du niveau sonore (LUFS), pic réel, coupure, DC décalage, silence initial/final.
section: Référence
order: 200
parent: operations
sourceRevision: 23de495c4a4a8100
---

Durée, pic, RMS, intégrée du niveau sonore (LUFS), pic réel, coupure, DC décalage, silence initial/final.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `input` | `string` | Oui | Fichier audio  |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation analyze_audio
```
