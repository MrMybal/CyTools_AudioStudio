"""CyTools_AudioStudio business package.

Audio editing, processing workflows, VST3 hosting, generation backends and mastering.
Nothing here imports Dear ImGui; the interface lives in app/gui. Heavy engines run in
separate worker processes (see audiostudio.engines and audiostudio.backends).
"""
__version__ = '0.1.1'
