# Documentation authoring

CyDoc is pinned in cydoc-source.json. Human content is authored in manual/en and manual/fr; keep the same IDs and explicit anchors. Internal records stay under internal. Nothing from this workspace belongs in an application distribution.

From the application root:

```sh
python app/.CyDocBuild/build.py --install --check
python app/tests/test_documentation.py
```

Open app/Documentation/Documentation.html. Do not hand-edit its generated resources. The separate DocAI.md sidecar carries assistant instructions and operation contracts.
