# Local documentation (CyDoc)

The editable Markdown listed in `sources.json` remains the source of truth. `build.py`
imports it into CyDoc with stable page IDs, local media, full operation schemas and a
lexical index of the shipped `app/tool.py`. Original French guides are retained; absent
translations are explicit and tracked. Do not hand-edit `app/help`.

From the application root (Node.js >=22 and npm are build requirements only):

```sh
python app/documentation/build.py --install
python app/documentation/build.py --check
python app/help_docs.py --page overview --locale en
```

`--install` installs the locked generator under `runtime/documentation-build`, outside
the shipped application. Subsequent builds need no installation. An already built
CyDoc checkout/package may be selected with `--cydoc-root PATH`.

The complete generated `app/help/` is shipped with application/update archives. Open
`app/help/index.html` through a file URL. F1 opens contextual help; Options provides
manual and workspace buttons. No HTTP server, CDN, network request or Node.js is
needed for reading. External reference links remain optional external navigation.

CyDoc is pinned in `cydoc-source.json` and distributed under MIT; its full notice is
in this directory, `app/help` and root `LICENCES`. Preserve generated third-party notices.
MeshStudio alone includes an original procedural GLB with the mesh module and Three.js.
Other modules are selected from actual imported media. Unused module scripts are absent.
No interactive graph, GIF decoder or video player is added merely because an application
can produce that format.

Review `app/help/migration-report.json` for old/missing links and `translation-report.json`
for missing/stale translations. SDK reference pages are labelled separately from actual
application capabilities. Linux/macOS launchers remain unverified unless a validation
report records an execution on those platforms.
