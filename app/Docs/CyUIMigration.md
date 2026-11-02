# Modular CyUI integration

The standalone application uses [CyUI](https://github.com/MrMybal/CyUI) 1.2.0,
pinned to [`ff023e6`](https://github.com/MrMybal/CyUI/tree/ff023e646c6a3038b3dfbfd53f6d2b4a2f5955e3).

## Selected modules and replacements

Core; Audio; AudioViews; Plots; Canvas; Diagnostics.

- Rotary controls and input/output peak/RMS meters use Audio.
- Realtime waveform and spectrum monitors use AudioViews/Plots; FFT, buffers and smoothing remain in DSP.
- Structured logs use Diagnostics, alongside a selectable text tab and full-file copy.
- The old private theme/widget/layout implementation is replaced by upstream Core; `gui/cyui` only forwards to the small `gui/style_bridge.py` host adapter.

## Reproducible source and delivery

`app/cyui-source.json` records every selected upstream file and its SHA-256.
`app/cyui.py` and `app/cyui_modules/*.py` are unchanged official sources, normalized
to LF. Do not edit them: host adapters live outside the library. Refresh only from
the exact pinned checkout:

```sh
python app/scripts/sync_cyui.py /path/to/CyUI
```

The sources are included with the application using its existing source-vendoring
mechanism. Neither a developer checkout elsewhere on disk nor an editable pip
installation is needed. There is one imgui-bundle renderer, at the version pinned
in `app/requirements.txt`; no C++ umbrella, CMake demo/gallery, CEF, extra model,
AI engine, NumPy installation or browser dependency is introduced by this migration.
Existing application/DSP/rendering dependencies are kept where required.

Keep `LICENCES/CyUI-MIT.txt` with the product. The application's own license does
not change. The Options licenses list identifies the upstream revision and source.

## Host responsibilities and retained adaptations

The multitrack timeline retains its fade handles, non-destructive source trims, cross-track drags, live automation overlay/write, overview and host interpolation. CyUI Python Timeline/Curves do not expose all of these combined behaviors or a transparent overlay surface. The advanced EQ/multiband editors retain their DSP overlays and drag policies; the common monitors around them have migrated. These are explicit host adaptations, not a fork of CyUI. Numeric-entry popovers, palette-file persistence and wrapping transport groups remain small host adapters because CyUI documents those Python gaps. No unused Timeline/Curves/Nodes module is shipped.

SDK operations, permissions, exclusive groups, temporary AI task files, model
installation, licenses/acceptance, generation recipes and Undo remain host-owned.
No CyToolsCore runtime or AI library is copied into CyUI. English remains the
default and French the persistent selectable second language.

## Verification

249 unit tests (including 4 new integration tests); native interaction scenario; realtime sweep of 92 effect panels. See the validation results recorded below.

Run the adapter tests from `app/` with the private Python:

```sh
python -m unittest discover -s tests -p test_modular_ui.py -v
```

They verify pinned-source integrity, bounded log refresh/redaction and native ImGui
frames across five themes, both densities, EN/FR and scale 1.0/1.5/2.0, plus the
application-specific data/edit routing. This simulated DPI check is not a physical
multi-monitor test. Windows native views are tested locally. Linux/macOS remain
unverified by this migration; the source integration stays platform-independent.

Windows packages include the migrated sources and their license notices.

Final local results: unittest 249 run, 245 passed and 4 skipped; native interactions 71 passed, 0 failed, 3 GPU/model checks explicitly skipped; 92 realtime effect panels and master-chain sweep passed. Existing worker-host ResourceWarnings are still printed by fixture tests. No AI model was downloaded for this migration.


CyUI license: [https://github.com/MrMybal/CyUI/blob/main/LICENSE](https://github.com/MrMybal/CyUI/blob/main/LICENSE). The complete MIT text ships with the application, including when the upstream repository is private.
