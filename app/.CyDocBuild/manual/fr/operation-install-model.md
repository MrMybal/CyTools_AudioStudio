---
id: operation-install-model
title: install_model
description: Télécharger ou reprendre un modèle avec vérification. La licence doit être acceptée personnellement lorsque le source le nécessite ; un source gâté retourne AccessRequired avec la page officielle.
section: Référence
order: 200
parent: operations
sourceRevision: 33659d12c3df7a57
---

Télécharger ou reprendre un modèle avec vérification. La licence doit être acceptée personnellement lorsque le source le nécessite ; un source gâté retourne AccessRequired avec la page officielle.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `model` | `string` | Oui | Identifiant du modèle (voir list_models), par exemple piper.en_US-lessac-medium  |
| `accept_license` | `boolean` | Non | J'ai lu et accepté la licence de ce modèle `default=false` |
| `repair` | `boolean` | Non | Re-hacher les fichiers existants et re-télécharger les fichiers corrompus `default=false` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `modelId` | `string` | Oui | Modèle  |
| `state` | `string` | Oui | État  |
| `downloaded` | `integer` | Non | Octets téléchargés `default=0` |

## Comportement et accès {#behaviour}

- Autorisations requises : `network`
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation install_model
```
