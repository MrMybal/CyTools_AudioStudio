---
id: troubleshooting
title: Troubleshooting
description: Find a failed installation or operation and preserve useful results.
section: Guide
order: 70
parent: overview
revision: 098183211ad5bb4f
---

## A model or engine is unavailable {#installation}

Check the installation status of the selected backend, not just whether a folder exists. Complete missing downloads, confirm the model format and check its hardware requirements. For restricted models, obtain access on the official site before retrying.

## A job fails or takes too long {#jobs}

Open the application log and read the latest error. Select the relevant lines and copy them, or copy the complete log when reporting a problem. Check source paths, free disk space and RAM/VRAM. Cancel a running job through the application and allow its worker to stop before changing or removing its files.

## Keep the output {#outputs}

Open or export the result before ending an AI task. Temporary task files can be cleaned up when the task finishes. Keep wanted outputs in a separate destination; do not use the Tool’s private job folder as permanent project storage.
