---
id: guide-app-docs-pluginformats
title: Plugins audio : VST3, CLAP, LV2, JSFX
description: Plugins audio : VST3, CLAP, LV2, JSFX
section: Guide
order: 40
parent: guide-lisez-moi
sourceRevision: c50680545d2b5fb0
---

## Plugins audio : VST3, CLAP, LV2, JSFX {#plugins-audio-vst3-clap-lv2-jsfx}

## Utilisation {#utilisation}

Ouvrez **Plugins**, ajoutez les dossiers de vos plugins puis **Scan plugins**. Les emplacements standards existants et app/examples/JSFX sont proposés automatiquement. Les variables CLAP_PATH, LV2_PATH et JSFX_PATH ajoutent des emplacements. Les dossiers personnalisés existants sont conservés. Le catalogue indique le format et les erreurs de chargement. Un bundle contenant plusieurs plugins conserve chaque identité séparément. Les effets peuvent être ajoutés aux workflows et aux insertions de piste/master, automatisés, dosés, désactivés et enregistrés avec les sessions et presets existants. Les instruments sont décrits, mais AudioStudio n'a pas de séquenceur MIDI pour les jouer.

Les paramètres des trois nouveaux formats utilisent une valeur normalisée 0–1 dans les contrôles AudioStudio. Le catalogue affiche aussi le texte fourni par le plugin. Sa fenêtre propose ses unités et ses contrôles propres. Les états enregistrés comprennent le contenu natif et les valeurs courantes, y compris un réglage modifié juste avant le prochain bloc audio. Les queues d'effets sont rendues par le même moteur que les effets internes. Le VST3 continue d'utiliser pedalboard.

## Scripts JSFX {#scripts-jsfx}

Dépliez **Plugins > JSFX script editor**. Ouvrez un script ou créez-en un, modifiez le code EEL2, cliquez **Compile JSFX**, puis **Save JSFX**. Une compilation invalide conserve la version précédente. Les scripts enregistrés vont dans data/scripts/JSFX ; scannez ce dossier pour les utiliser. Les imports relatifs se résolvent à côté du script ; pour enregistrer une copie d'un script avec imports, conservez ses fichiers auxiliaires dans ce dossier. Les scripts sans extension de REAPER sont reconnus par leur contenu. Les fichiers .jsfx-inc sont des bibliothèques, pas des effets. Les fenêtres JSFX peuvent afficher @gfx, via ysfx. Chaque script garde sa licence.

CLI et MCP utilisent les mêmes opérations : scan_plugins, list_plugins, describe_plugin (option plugin_name pour choisir un élément d'un bundle), read_jsfx, validate_jsfx et save_jsfx. Les workflows acceptent kind vst3, clap, lv2 ou jsfx et les champs plugin, pluginName, params, state.

## Exécution et limites vérifiées {#execution-et-limites-verifiees}

CLAP/LV2/JSFX : un processus natif par instance et échanges audio en mémoire partagée. Le chargement, le scan et les fenêtres ne chargent pas leurs DLL dans l'interface Python. Une panne est signalée et l'insertion peut être contournée par le renderer. Il s'agit d'une isolation de plantage, pas d'une sandbox de sécurité. Le VST3 en lecture temps réel conserve le comportement existant de pedalboard. Les scripts recompilés sont rechargés lors du prochain rendu de workflow ; réinsérez une instance live pour changer son programme. Les sessions ne transportent pas les binaires ni les imports JSFX. La compensation globale de latence entre pistes n’est pas ajoutée par ce changement ; les effets à forte latence demandent un contrôle d’alignement lors d’un mixage parallèle.
