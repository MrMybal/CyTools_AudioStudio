"""Plugins tab: scan VST3 folders, browse the catalogue, inspect and test a plugin."""
import json
from pathlib import Path

from imgui_bundle import imgui

from audiostudio.paths import SETTINGS, PLUGIN_CACHE, default_vst3_directories
from audiostudio.vst import host as vst_host
from .widgets import status_line


class PluginsPanel:
    def __init__(self, app):
        self.app = app
        self.settings_path = SETTINGS / 'plugins.json'
        self.settings = self._load_settings()
        self.new_directory = ''
        self.filter = ''
        self.selected = 0
        self.catalogue = []
        self.failures = []
        self.message = ''
        self.refresh()

    def tr(self, text):
        return self.app.tr(text)

    def _load_settings(self):
        try:
            value = json.loads(self.settings_path.read_text('utf-8-sig'))
            return value if isinstance(value, dict) else {'directories': []}
        except (OSError, ValueError):
            return {'directories': []}

    def _save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(self.settings, indent=2), 'utf-8')

    def refresh(self):
        cache = vst_host.read_cache(PLUGIN_CACHE)
        plugins = list(cache.get('plugins', {}).values())
        self.catalogue = sorted([p for p in plugins if p.get('state') == 'ok'], key=lambda p: (p.get('name') or '').lower())
        self.failures = [p for p in plugins if p.get('state') != 'ok']

    def scan(self, force=False):
        def done(job):
            self.refresh()
            self.app.workflows.refresh_plugins()
            if job['state'] == 'Completed':
                outputs = job['outputs']
                self.message = self.tr('Scan finished: ') + f"{outputs['count']} plugin(s), {len(outputs['failures'])} failure(s)"
        self.app.jobs.submit('scan_plugins', {'directories': self.settings.get('directories', []), 'force': force}, done, self.tr('Plugin scan'))

    def draw(self):
        tr = self.tr
        imgui.text_wrapped(tr('VST3 plugins are loaded in a separate worker process: a crashing plugin never closes the application. VST2 is not supported (no licence).'))
        imgui.separator_text(tr('Folders'))
        for folder in default_vst3_directories():
            imgui.bullet_text(str(folder) + '  ' + tr('(standard)'))
        remove = None
        for index, folder in enumerate(self.settings.get('directories', [])):
            imgui.push_id(index)
            imgui.bullet_text(folder)
            imgui.same_line()
            if imgui.small_button(tr('Remove')):
                remove = index
            imgui.pop_id()
        if remove is not None:
            del self.settings['directories'][remove]
            self._save_settings()
        imgui.push_item_width(420)
        _, self.new_directory = imgui.input_text(tr('Add folder'), self.new_directory)
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.button(tr('Browse') + '##plugdir'):
            self.app.dialogs.select_folder('plugin-dir', tr('VST3 folder'))
        imgui.same_line()
        if imgui.button(tr('Add')) and self.new_directory.strip():
            self.settings.setdefault('directories', []).append(self.new_directory.strip())
            self.new_directory = ''
            self._save_settings()
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == 'plugin-dir' else None
        if event:
            self.new_directory = event[1] if isinstance(event[1], str) else event[1][0]
        scanning = self.app.jobs.is_running('scan_plugins')
        imgui.begin_disabled(scanning)
        if imgui.button(tr('Scan plugins')):
            self.scan(False)
        imgui.same_line()
        if imgui.button(tr('Rescan all')):
            self.scan(True)
        imgui.end_disabled()
        if scanning:
            imgui.same_line()
            job = self.app.jobs.running('scan_plugins')[0]
            imgui.progress_bar(float((job.get('progress') or {}).get('percent', 0)) / 100, (250, 0), self.app.jobs.progress_text(job)[:60])
        imgui.separator_text(tr('Catalogue') + f' ({len(self.catalogue)})')
        imgui.push_item_width(250)
        _, self.filter = imgui.input_text(tr('Filter'), self.filter)
        imgui.pop_item_width()
        shown = [p for p in self.catalogue if self.filter.lower() in (p.get('name', '') + p.get('manufacturer', '')).lower()]
        imgui.begin_child('##pluginlist', (320, max(160.0, imgui.get_content_region_avail().y - 20)), True)
        for index, plugin in enumerate(shown):
            selected = index == self.selected
            if imgui.selectable(f"{plugin.get('name')}  -  {plugin.get('manufacturer', '')}##{index}", selected)[0]:
                self.selected = index
        for failure in self.failures:
            imgui.text_colored((1.0, 0.5, 0.4, 1.0), Path(failure.get('path', '')).name + ': ' + str(failure.get('error', ''))[:60])
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child('##plugininfo', (0, max(160.0, imgui.get_content_region_avail().y - 20)), True)
        if shown and self.selected < len(shown):
            plugin = shown[self.selected]
            imgui.text(str(plugin.get('name')))
            imgui.text_disabled(str(plugin.get('path')))
            imgui.text(tr('Manufacturer: ') + str(plugin.get('manufacturer', '')) + '   ' + tr('Version: ') + str(plugin.get('version', '')))
            imgui.text(tr('Type: ') + (tr('instrument') if plugin.get('isInstrument') else tr('effect')) + '   ' + tr('Latency: ') + f"{plugin.get('latencySamples', 0)} samples")
            if imgui.button(tr('Add to workflow')):
                self.app.workflows.add_plugin(plugin)
                self.message = tr('Added to the current workflow: ') + str(plugin.get('name'))
            imgui.same_line()
            if imgui.button(tr('Open plugin window')):
                node = {'plugin': plugin['path'], 'pluginName': plugin.get('name', ''), 'params': {}, 'state': ''}
                self.app.open_plugin_editor(node)
            imgui.separator_text(tr('Parameters') + f" ({len(plugin.get('parameters', {}))})")
            for name, info in list(plugin.get('parameters', {}).items())[:80]:
                imgui.bullet_text(f"{info.get('label', name)}: {info.get('value')} {info.get('units', '')}")
        else:
            imgui.text_disabled(tr('Select a plugin, or scan first.'))
        imgui.end_child()
        if self.message:
            status_line(self.message)
