---
id: guide-app-docs-pluginformats
title: Audio plugins: VST3, CLAP, LV2, JSFX
description: Audio plugins: VST3, CLAP, LV2, JSFX
section: Guide
order: 40
parent: guide-lisez-moi
revision: c50680545d2b5fb0
---

## Audio plugins: VST3, CLAP, LV2, JSFX {#plugins-audio-vst3-clap-lv2-jsfx}

## Usage {#utilisation}

Open Plugins, add your plugin folders, then scan plugins. Existing standard locations and app/examples/JSFX are offered automatically. CLAP_PATH, LV2_PATH, and JSFX_PATH variables add locations. Existing custom folders are preserved. The catalog indicates the format and loading errors. A bundle containing multiple plugins keeps each identity separately. Effects can be added to workflows and track/master insertions, automated, adjusted, disabled, and saved with existing sessions and presets. Instruments are described, but AudioStudio does not have a MIDI sequencer to play them.

The parameters of the three new formats use a normalized 0–1 value in AudioStudio's controls. The catalog also displays the text provided by the plugin. Its window offers its units and its own controls. Recorded states include native content and current values, including a setting modified just before the next audio block. Effect chains are rendered by the same engine as internal effects. The VST3 continues to use pedalboard.

## JSFX scripts {#scripts-jsfx}

Expand Plugins > JSFX script editor. Open a script or create one, modify the EEL2 code, click Compile JSFX, then Save JSFX. An invalid compilation keeps the previous version. Saved scripts go in data/scripts/JSFX; scan this folder to use them. Relative imports resolve next to the script; to save a copy of a script with imports, keep its auxiliary files in this folder. Scripts without a REAPER extension are recognized by their content. .jsfx-inc files are libraries, not effects. Windows JSFX can display @gfx, via ysfx. Each script keeps its license.

CLI and MCP use the same operations: scan_plugins, list_plugins, describe_plugin (option plugin_name to choose an element from a bundle), read_jsfx, validate_jsfx, and save_jsfx. Workflows accept kind vst3, clap, lv2, or jsfx and fields plugin, pluginName, params, state.

## Execution and limits verified {#execution-et-limites-verifiees}

CLAP/LV2/JSFX : a native process per instance and audio exchanges in shared memory. Loading, scanning and windows do not load their DLL into the Python interface. A crash is reported and insertion can be circumvented by the renderer. This is a crash isolation, not a security sandbox. The VST3 in real-time reading preserves the existing pedalboard behavior. Recompiled scripts are reloaded during the next workflow rendering; reinsert a live instance to change its program. Sessions do not transport binaries or imports JSFX. The global compensation of latency between tracks is not added by this change; high latency effects require alignment control during parallel mixing.
