# Publishing the CyDoc reader

The web manual and the embedded manual are the same complete CyDoc HTML export.
Markdown files remain editable sources; GitHub Pages serves the generated reader,
including its navigation, full-text search, locales, styles, scripts and local media.

## Regenerate and stage

From the repository root, with Node.js 22+ and Python 3.11+:

```sh
python app/documentation/build.py --install --check
python app/tests/test_documentation.py
python app/tests/test_pages.py
python app/documentation/publish.py
```

The locked, vendored CyDoc package provides the generator. CI needs no access to
the upstream private repository and installs no model or application engine.
The publisher validates `app/help` and copies it byte-for-byte into `_site`, adding
only `.nojekyll` and a staging marker. It never publishes application `data/`,
`runtime/`, weights, credentials, conversations or generated user outputs.
Do not hand-edit `_site` or `app/help`; edit the sources in `sources.json` instead.
Source text hashes and indexed source copies use UTF-8 with LF newlines, and licence
ordering is case-independent, so Windows and Linux produce the same reader.
The original source documents are preserved.

## Automatic deployment

`.github/workflows/documentation.yml` rebuilds on pushes to `main` and can also be
started manually from Actions. Only `_site` is uploaded to the `github-pages`
artifact and deployed by the official Pages action. Set repository Settings →
Pages → Build and deployment → Source to **GitHub Actions**.

The root English README links to `#/en/overview`, and the French README to
`#/fr/overview`; the reader's language selector remains available on both.
Page and section links use hash routes so they work beneath a project Pages URL
and from an offline `file://` URL without server rewrites.

## Embedded help

The full `app/help` remains in the application distribution. F1 and Options keep
opening its local file URL. Publishing introduces no network dependency into
embedded help and does not replace it with a web link.

Public reader: [Documentation](https://mrmybal.github.io/CyTools_AudioStudio/#/en/overview).
