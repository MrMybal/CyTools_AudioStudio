# CyDoc migration validation

## Scope

Existing user/developer guides, local illustrations, shipped operation schemas and the
public Python entry-point source were migrated. The original Markdown is retained as
editable source and for GitHub links. App/help is generated and includes all reader resources.
Node.js is required only for regeneration; the reader uses local classic scripts and file URLs.

## Checks executed on Windows

- Pinned CyDoc 0.1.0 built from revision 774f2a7eabf7dd181a98ffc5add115b580b67f42.
- App-local npm lockfile installation and full CyDoc build/check.
- Python routing tests: English/French, legacy paths, Unicode, spaces/hash characters,
  media links, unknown page fallback, browser failure, active operation and common anchors.
- Native ImGui test-engine clicks on both help buttons and F1, using the product interpreter.
  The browser call was intercepted to assert its file URL without launching tabs.
- The full standalone Options window was opened and closed in an isolated application copy.
- Generated reader tested in a DOM fixture with network calls forbidden: rendering,
  operation links/anchors, language switch and in-window image expansion/Escape when used.
- The pinned CyDoc core, interactions and packed-asset suites passed (25 tests), including
  keyboard/pointer controls and reading-position restoration.
- Distribution selections are checked for the entire help tree and notices.

## Limits

The automation browser blocks file URLs. A real browser visual check of file-origin
storage, layout, codecs and WebGL remains necessary; DOM fixtures do not prove it.
Linux and macOS were not executed. Touch-device behavior is covered by library interaction
fixtures, not a physical touch-device run. Existing missing translations remain visible
in translation-report.json. No model inference was needed or rerun for this migration.
The migration report records old missing references; SDK reference documents may describe
older SDK releases and are explicitly labelled separately from current operation contracts.

## Regenerate and verify

From the application root:

```sh
python app/documentation/build.py --install
python app/documentation/build.py --check
python app/tests/test_documentation.py
python app/help_docs.py --page overview --locale en --print-url
```

Existing release builders regenerate/validate the manual before packaging. When a builder
uses git archive, commit the generated reader together with its source changes first.
Keep the complete app/help directory and LICENCES/CyDoc-MIT.txt in the delivered product.
