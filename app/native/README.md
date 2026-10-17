# AudioStudio isolated plugin host

The worker is a separate executable: CLAP, LV2 and JSFX libraries are never loaded in the Python GUI process.
The host adapters and fixed shared-memory ABI were adapted from Cyberalien's CyDAW sources (commit e684957).
AudioStudio-specific changes add window visibility, reset with parameter preservation, parent-process lifetime,
Windows request/response events, and CLAP state/reset fixes. The Python bridge is original AudioStudio code.
VST3 remains on the existing pedalboard host. No VST2 support is compiled into this worker.

Build from the product root with `runtime/python/Scripts/python.exe app/scripts/build_plugin_host.py`.
CMake and a C++20 compiler are required. JUCE is downloaded by CMake at pinned commit
91ad83ae34a81e0833b1a2b0866f54846370ae53 (8.0.15); `--juce-source` supports offline builds.
`--nasm` selects NASM for native EEL2 compilation on MSVC; without it ysfx uses its portable interpreter.
Build products go in runtime/build/plugin-host and app/native/bin/<system>-<machine>.
Release archives require the compiled host and include it. Binaries are not tracked in Git.
Linux additionally needs JUCE's X11/fontconfig/freetype development packages; it has not been executed here.

## Dependencies and licences

- Native host executable: AGPL-3.0 due to JUCE 8 (full upstream notice in licenses/JUCE-LICENSE.md).
  The Python application retains its GPL-3.0-only licence; this is a separate worker executable.
- CLAP headers: free-audio/clap a47f6badb49d948fd009998f28309cdab78979c9, MIT; complete sources in third_party/clap.
- ysfx: jpcima/ysfx 8077347ccf4115567aed81400281dca57acbb0cc, Apache-2.0; complete sources in third_party/ysfx.
- dr_libs upstream tests (including their unrelated miniaudio copy and sample WAV) are omitted; they are not part of the host build.
- ysfx dr_libs: f13cbcfd06afe7287f99b1bb5982cefdf3d6a974, public-domain/MIT-0. WDL: zlib-style. stb: public-domain/MIT.
- Lilv, Serd, Sord, Sratom and LV2 come from pinned JUCE. Full notices are in licenses/LV2_SDK.
- JUCE's used graphics/core dependencies retain their notices in licenses/modules.
- Example JSFX scripts are MIT. External plugins and scripts retain their own licences.

The worker is a crash boundary, not an OS sandbox for untrusted code.
