# Product showcase

This directory contains the static English/French product website. The editorial copy
is in `content.json`; the full-frame screenshots and their provenance are recorded in
`screenshots.json`. The application name and current version come from `app/CyTool.json`.
Do not infer platform support, model quality or licence rights from the version number.

## Build and preview

From the repository root, with Python 3.11 or later:

```sh
python website/build.py
python website/test_site.py
python -m http.server 8765 --bind 127.0.0.1 --directory _site
```

Open http://127.0.0.1:8765/ (English) or http://127.0.0.1:8765/?lang=fr (French).
The entire `_site` directory is the GitHub Pages artifact. Building does not publish.
The documentation workflow stages this artifact only after regenerating the CyDoc manual.
Retain the existing deployment gate for a private repository; never change its visibility.

`build.py` needs no network, model, application runtime or JavaScript package manager.
It first calls the existing, confined CyDoc exporter, then adds only the showcase HTML,
styles, script and explicitly checked assets. It never copies `data/`, `runtime/`, logs,
model weights, authoring notes or credentials.

## Documentation compatibility

The actual reader is `Documentation.html` with its unchanged `DocData/` resources.
Links follow the selected language, for example `Documentation.html#/fr/overview`.
Legacy documentation links at `/#/en/...` or `/#/fr/...` redirect to that reader.
The application's embedded `app/Documentation` and F1 help remain unchanged and offline.
Do not replace the reader with raw Markdown or an iframe rendering source files.

## Updating the page

- Edit the complete `en` and `fr` text pairs together. Keep technical identifiers unchanged.
- Use actual screenshots. A prepared example must be identified as such; do not label a
  manually written conversation or procedural mesh as an inference result.
- Review images for private paths, messages, accounts and metadata before adding them.
- Keep the hero full-frame with `object-fit: contain`; check desktop and mobile layouts.
- Keep GitHub accessible on mobile, native `<dialog>` keyboard dismissal and focus return.
- Rebuild after changing content, `src/site.css` or `src/site.js`. Their generated names
  include SHA256 content fingerprints, so edits renew browser cache URLs automatically.
- The default language is English. `?lang=fr` is the shareable French URL. No external
  fonts, CDNs, analytics, runtime API requests or mandatory remote scripts are used.

Vérification en français : `?lang=fr` doit traduire tous les textes, légendes, libellés
accessibles et liens de documentation. Les identifiants techniques ne sont pas traduits.
La vitrine ne modifie ni les contrats métier, ni les modèles, ni les données de l’application.
