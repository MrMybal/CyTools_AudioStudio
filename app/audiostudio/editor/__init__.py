"""Multitrack editor model: document, tracks, undo/redo, edit operations, mixdown, sessions.

No ImGui here; the interface in app/gui renders this model. Audio is kept in memory as
float32 (channels, frames) per track at the document sample rate.
"""
