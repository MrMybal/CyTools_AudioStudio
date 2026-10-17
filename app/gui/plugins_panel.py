"""Plugins tab: scan VST3 folders, browse the catalogue, inspect and test a plugin."""
import json
from pathlib import Path

from imgui_bundle import imgui

from audiostudio.paths import SETTINGS, PLUGIN_CACHE, default_vst3_directories
from audiostudio.vst import host as vst_host
from . import cyui


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
        icon = cyui.icon
        p = cyui.palette()
        cyui.panel_header(tr('Plugins'), tr('VST3 plugins are loaded in a separate worker process: a crashing plugin never closes the application. VST2 is not supported (no licence).'))
        cyui.space(4.0)
        if cyui.begin_section(tr('Folders') + '###folders'):
            for folder in default_vst3_directories():
                cyui.text_dim(str(folder))
                imgui.same_line()
                cyui.badge(tr('standard'))
            remove = None
            for index, folder in enumerate(self.settings.get('directories', [])):
                imgui.push_id(index)
                imgui.align_text_to_frame_padding()
                imgui.text(folder)
                imgui.same_line()
                if cyui.icon_button(icon.close, tr('Remove this folder'), id='Remove', fallback='x', active_colour=p.error):
                    remove = index
                imgui.pop_id()
            if remove is not None:
                del self.settings['directories'][remove]
                self._save_settings()
            imgui.push_item_width(cyui.dp(420.0))
            _, self.new_directory = imgui.input_text_with_hint('##add-folder', tr('Add folder'), self.new_directory)
            imgui.pop_item_width()
            imgui.same_line(0, 3)
            if cyui.icon_button(icon.folder, tr('Browse for a VST3 folder'), id='plugdir', fallback='...'):
                self.app.dialogs.select_folder('plugin-dir', tr('VST3 folder'))
            imgui.same_line(0, 3)
            with cyui.scoped_disabled(not self.new_directory.strip()):
                if cyui.button(tr('Add') + '###Add folder') and self.new_directory.strip():
                    self.settings.setdefault('directories', []).append(self.new_directory.strip())
                    self.new_directory = ''
                    self._save_settings()
            cyui.end_section()
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == 'plugin-dir' else None
        if event:
            self.new_directory = event[1] if isinstance(event[1], str) else event[1][0]
        scanning = self.app.jobs.is_running('scan_plugins')
        with cyui.scoped_disabled(scanning):
            if cyui.primary_button(cyui.icon_label(icon.search, tr('Scan plugins')) + '###Scan plugins'):
                self.scan(False)
            cyui.tooltip(tr('Scans the folders for new or changed plugins'))
            imgui.same_line(0, 4)
            if cyui.button(tr('Rescan all') + '###Rescan all'):
                self.scan(True)
        if scanning:
            imgui.same_line()
            job = self.app.jobs.running('scan_plugins')[0]
            percent = float((job.get('progress') or {}).get('percent', 0)) / 100
            cyui.progress_bar(percent if percent > 0 else -1.0, (cyui.dp(250.0), 0), self.app.jobs.progress_text(job)[:60])
        cyui.space(4.0)
        cyui.heading(tr('Catalogue') + f' ({len(self.catalogue)})', 3)
        _, self.filter = cyui.search_field('##filter', self.filter, tr('Filter'), cyui.dp(320.0))
        shown = [pl for pl in self.catalogue if self.filter.lower() in (pl.get('name', '') + pl.get('manufacturer', '')).lower()]
        height = max(160.0, imgui.get_content_region_avail().y - cyui.dp(4.0))
        with cyui.scoped_colour((imgui.Col_.child_bg, p.bg0)):
            imgui.begin_child('##pluginlist', (cyui.dp(320.0), height), imgui.ChildFlags_.borders)
        if not shown and not self.failures:
            cyui.empty_state(tr('No plugin'), tr('Scan the folders to list the VST3 plugins.'), icon.audio)
        for index, plugin in enumerate(shown):
            if imgui.selectable(f"{plugin.get('name')}  -  {plugin.get('manufacturer', '')}##{index}", index == self.selected)[0]:
                self.selected = index
        for failure in self.failures:
            cyui.text_coloured(p.error, Path(failure.get('path', '')).name + ': ' + str(failure.get('error', ''))[:60])
        imgui.end_child()
        imgui.same_line()
        cyui.begin_card('##plugininfo', None, height)
        if shown and self.selected < len(shown):
            plugin = shown[self.selected]
            cyui.heading(str(plugin.get('name')), 2)
            cyui.text_faint(str(plugin.get('path')))
            cyui.space(4.0)
            if cyui.begin_properties('##plugin-props', 140):
                cyui.property(tr('Manufacturer'))
                imgui.text(str(plugin.get('manufacturer', '')))
                cyui.property(tr('Version'))
                imgui.text(str(plugin.get('version', '')))
                cyui.property(tr('Type'))
                imgui.text(tr('instrument') if plugin.get('isInstrument') else tr('effect'))
                cyui.property(tr('Latency'))
                imgui.text(f"{plugin.get('latencySamples', 0)} " + tr('samples'))
                cyui.end_properties()
            cyui.space(4.0)
            if cyui.primary_button(cyui.icon_label(icon.add, tr('Add to workflow')) + '###Add to workflow'):
                self.app.workflows.add_plugin(plugin)
                self.message = tr('Added to the current workflow: ') + str(plugin.get('name'))
            imgui.same_line(0, 4)
            if cyui.icon_text_button(icon.new_window, tr('Open plugin window') + '###Open plugin window'):
                node = {'plugin': plugin['path'], 'pluginName': plugin.get('name', ''), 'params': {}, 'state': ''}
                self.app.open_plugin_editor(node)
            cyui.space(4.0)
            cyui.section_title(tr('Parameters') + f" ({len(plugin.get('parameters', {}))})")
            if cyui.begin_properties('##plugin-params', 200):
                for name, info in list(plugin.get('parameters', {}).items())[:80]:
                    cyui.property(str(info.get('label', name)))
                    imgui.text(f"{info.get('value')} {info.get('units', '')}")
                cyui.end_properties()
        else:
            cyui.empty_state(tr('No plugin selected'), tr('Select a plugin, or scan first.'), icon.audio)
        cyui.end_card()
