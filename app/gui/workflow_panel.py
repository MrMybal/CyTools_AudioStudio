"""Workflows tab: build a chain of effects / VST3 plugins, tail settings, save, load, apply."""
from pathlib import Path

from imgui_bundle import imgui

from audiostudio.paths import WORKFLOWS
from audiostudio.dsp import effects
from audiostudio.workflow import model as workflow_model
from audiostudio.vst import host as vst_host
from .widgets import draw_effect_params, draw_plugin_params, search_combo
from . import cyui
from .search import effect_haystack, plugin_haystack


class WorkflowPanel:
    def __init__(self, app):
        self.app = app
        self.document = workflow_model.new_workflow('New workflow')
        self.path = None
        self.effect_index = 0
        self.plugin_index = 0
        self.saved = []
        self.saved_index = 0
        self.message = ''
        self.refresh_saved()
        self.plugin_catalogue = []
        self.refresh_plugins()

    def tr(self, text):
        return self.app.tr(text)

    def refresh_saved(self):
        self.saved = workflow_model.list_workflows(WORKFLOWS)

    def refresh_plugins(self):
        try:
            from audiostudio.paths import PLUGIN_CACHE
            cache = vst_host.read_cache(PLUGIN_CACHE)
            self.plugin_catalogue = sorted([p for p in cache.get('plugins', {}).values() if p.get('state') == 'ok'], key=lambda p: p.get('name', '').lower())
        except Exception:
            self.plugin_catalogue = []

    # ------------------------------------------------------------------ actions
    def add_effect(self, effect_id):
        self.document['nodes'].append(workflow_model.new_node('effect', effect=effect_id))

    def add_plugin(self, info):
        params = {name: p.get('value') for name, p in info.get('parameters', {}).items() if isinstance(p.get('value'), (int, float, bool, str))}
        node = workflow_model.new_node('vst3', plugin=info['path'], pluginName=info.get('name', ''), params=params)
        node['_description'] = info
        self.document['nodes'].append(node)

    def load(self, path):
        self.document = workflow_model.load(path)
        self.path = Path(path)
        self.message = self.tr('Loaded ') + self.document['name']

    def save(self, name=None):
        name = name or self.document['name']
        self.document['name'] = name
        target = WORKFLOWS / (workflow_model.safe_name(name) + '.json')
        clean = {**self.document, 'nodes': [{k: v for k, v in n.items() if not k.startswith('_')} for n in self.document['nodes']]}
        workflow_model.save(target, clean)
        self.path = target
        self.refresh_saved()
        self.message = self.tr('Saved ') + str(target)
        return target

    def current(self):
        """Validated workflow document without UI-only keys."""
        clean = {**self.document, 'nodes': [{k: v for k, v in n.items() if not k.startswith('_')} for n in self.document['nodes']]}
        return workflow_model.validate(clean)

    # ------------------------------------------------------------------ drawing
    def draw(self):
        tr = self.tr
        icon = cyui.icon
        cyui.panel_header(tr('Workflows'), tr('A chain of effects and VST3 plugins, saved as a file, applied to a selection, to tracks or to files.'))
        cyui.space(4.0)
        # -- workflow file
        with cyui.toolbar('##workflow-file'):
            imgui.align_text_to_frame_padding()
            cyui.text_dim(tr('Workflow name'))
            imgui.same_line()
            imgui.push_item_width(cyui.dp(240.0))
            changed, name = imgui.input_text('##workflow-name', self.document['name'])
            imgui.pop_item_width()
            if changed:
                self.document['name'] = name
            imgui.same_line(0, 4)
            if cyui.icon_text_button(icon.save, tr('Save') + '###Save'):
                try:
                    self.save()
                except Exception as exc:
                    self.message = tr('Save failed: ') + str(exc)
            cyui.tooltip(tr('Save this workflow in data/workflows'))
            imgui.same_line(0, 2)
            if cyui.icon_button(icon.add, tr('New empty workflow'), id='New', fallback='+'):
                self.document = workflow_model.new_workflow('New workflow')
                self.path = None
            cyui.toolbar_separator()
            imgui.push_item_width(cyui.dp(220.0))
            labels = [f"{w['name']} ({w['nodes']})" for w in self.saved] or [tr('(no saved workflow)')]
            _, self.saved_index = imgui.combo('##saved', min(self.saved_index, max(0, len(labels) - 1)), labels)
            imgui.pop_item_width()
            cyui.tooltip(tr('Saved workflows (number of nodes)'))
            imgui.same_line(0, 4)
            with cyui.scoped_disabled(not self.saved):
                if cyui.icon_text_button(icon.open_file, tr('Load') + '###Load') and self.saved:
                    try:
                        self.load(self.saved[self.saved_index]['path'])
                    except Exception as exc:
                        self.message = tr('Load failed: ') + str(exc)
            imgui.same_line(0, 2)
            if cyui.icon_button(icon.refresh, tr('Refresh the saved workflows and the plugin catalogue'), id='Refresh', fallback='R'):
                self.refresh_saved()
                self.refresh_plugins()
        cyui.space(4.0)
        # -- tail rendering
        tail = self.document['tail']
        if cyui.begin_section(tr('Tail rendering') + '###tail-section'):
            if cyui.begin_properties('##tail', 220):
                cyui.property(tr('Extend until silence'), tr('Reverb and delay tails are never cut: rendering goes on after the input until it is silent.'))
                _, tail['enabled'] = cyui.toggle_switch('##tail-enabled', bool(tail['enabled']))
                cyui.property(tr('Silence threshold (dBFS)'))
                _, tail['threshold_db'] = cyui.slider_bar('##tail-threshold', float(tail['threshold_db']), -120.0, -20.0, '%.0f dBFS', -1)
                cyui.property(tr('Maximum extension (s)'))
                _, tail['max_seconds'] = cyui.slider_bar('##tail-max', float(tail['max_seconds']), 0.0, 60.0, '%.1f s', -1)
                cyui.property(tr('Hold after last sound (s)'))
                _, tail['hold_seconds'] = cyui.slider_bar('##tail-hold', float(tail['hold_seconds']), 0.0, 5.0, '%.2f s', -1)
                cyui.end_properties()
            cyui.end_section()
        # -- add a node
        cyui.section_title(tr('Add a node'))
        specs = list(effects.REGISTRY.values())
        _, self.effect_index = search_combo('addeffect', self.effect_index, [tr(s.name) for s in specs], cyui.dp(220.0),
                                            haystacks=[effect_haystack(s, tr) for s in specs], groups=[tr(s.category) for s in specs], tr=tr)
        imgui.same_line(0, 4)
        if cyui.icon_text_button(icon.add, tr('Add effect') + '###Add effect'):
            self.add_effect(list(effects.REGISTRY)[self.effect_index])
        imgui.same_line(0, 12)
        plugin_labels = [f"{p.get('name')} ({p.get('manufacturer', '')})" for p in self.plugin_catalogue] or [tr('(scan plugins in the Plugins tab)')]
        _, self.plugin_index = search_combo('addplugin', min(self.plugin_index, max(0, len(plugin_labels) - 1)), plugin_labels, cyui.dp(260.0),
                                            haystacks=[plugin_haystack(p) for p in self.plugin_catalogue] or None, tr=tr)
        imgui.same_line(0, 4)
        with cyui.scoped_disabled(not self.plugin_catalogue):
            if cyui.icon_text_button(icon.add, tr('Add VST3') + '###Add VST3') and self.plugin_catalogue:
                self.add_plugin(self.plugin_catalogue[self.plugin_index])
        cyui.space(4.0)
        # -- chain
        cyui.heading(tr('Chain') + f' ({len(self.document["nodes"])})', 3)
        p = cyui.palette()
        with cyui.scoped_colour((imgui.Col_.child_bg, p.bg0)):
            imgui.begin_child('##chain', (0, max(160.0, imgui.get_content_region_avail().y - imgui.get_frame_height() - cyui.dp(16.0))), imgui.ChildFlags_.borders)
        remove = None
        move = None
        if not self.document['nodes']:
            cyui.empty_state(tr('No node yet'), tr('Add an effect or a VST3 plugin above; they run from top to bottom.'), icon.equalizer)
        for index, node in enumerate(self.document['nodes']):
            imgui.push_id(node['id'])
            title = node.get('effect') if node['kind'] == 'effect' else ('VST3: ' + (node.get('pluginName') or Path(node['plugin']).stem)) if node['kind'] == 'vst3' else 'model: ' + node.get('model', '')
            if node['kind'] == 'effect' and node.get('effect') in effects.REGISTRY:
                title = tr(effects.REGISTRY[node['effect']].name)
            _, node['enabled'] = imgui.checkbox('##on', bool(node.get('enabled', True)))
            cyui.tooltip(tr('Enable or bypass this node'))
            imgui.same_line(0, 2)
            small = (imgui.get_frame_height() * 0.9, 0)
            if cyui.icon_button(icon.chevron_up, tr('Move up'), id='Move node up', fallback='^', size=small):
                move = (index, -1)
            imgui.same_line(0, 0)
            if cyui.icon_button(icon.chevron_down, tr('Move down'), id='Move node down', fallback='v', size=small):
                move = (index, 1)
            imgui.same_line(0, 0)
            if cyui.icon_button(icon.close, tr('Remove this node'), id='Remove node', fallback='X', size=small, active_colour=p.error):
                remove = index
            imgui.same_line(0, 4)
            if cyui.begin_section(f'{index + 1}. {title}###hdr', False):
                if cyui.begin_properties('##node', 220):
                    cyui.property(tr('Mix (dry/wet)'))
                    _, node['mix'] = cyui.slider_bar('##mix', float(node.get('mix', 1.0)), 0.0, 1.0, '%.2f', -1)
                    cyui.end_properties()
                if node['kind'] == 'effect':
                    spec = effects.get(node['effect'])
                    imgui.push_item_width(cyui.dp(260.0))
                    draw_effect_params(spec, node['params'], tr)
                    imgui.pop_item_width()
                elif node['kind'] == 'vst3':
                    description = node.get('_description')
                    if description is None:
                        description = next((p_ for p_ in self.plugin_catalogue if p_.get('path', '').lower() == str(node['plugin']).lower()), None)
                        node['_description'] = description or {'parameters': {}}
                    cyui.text_faint(str(node['plugin']))
                    if cyui.icon_text_button(icon.new_window, tr('Open plugin window') + '###Open plugin window'):
                        self.app.open_plugin_editor(node)
                    imgui.same_line()
                    imgui.align_text_to_frame_padding()
                    cyui.text_faint(tr('(state is captured when the window closes)'))
                    imgui.push_item_width(cyui.dp(260.0))
                    draw_plugin_params(node.get('_description') or {}, node['params'], tr)
                    imgui.pop_item_width()
                    if node.get('state'):
                        cyui.text_faint(tr('Saved plugin state: ') + f"{len(node['state'])} chars")
                cyui.end_section()
            imgui.pop_id()
        imgui.end_child()
        if remove is not None:
            del self.document['nodes'][remove]
        if move is not None:
            index, direction = move
            target = index + direction
            if 0 <= target < len(self.document['nodes']):
                nodes = self.document['nodes']
                nodes[index], nodes[target] = nodes[target], nodes[index]
        # -- apply
        cyui.space(4.0)
        if cyui.primary_button(cyui.icon_label(icon.play, tr('Apply to selection')) + '###Apply to selection'):
            self.app.apply_current_workflow(all_tracks=False)
        cyui.tooltip(tr('Renders the chain over the selection of the selected track (or its clips), with the tail'))
        imgui.same_line(0, 4)
        if cyui.button(tr('Apply to all tracks') + '###Apply to all tracks'):
            self.app.apply_current_workflow(all_tracks=True)
        imgui.same_line(0, 4)
        if cyui.icon_text_button(icon.folder, tr('Process files...') + '###Process files'):
            self.app.dialogs.open_file('batch', tr('Files to process with this workflow'), '', multiple=True)
        cyui.tooltip(tr('Each chosen file goes through this chain; the results are listed in the Generate tab'))
        imgui.same_line(0, 12)
        imgui.align_text_to_frame_padding()
        cyui.text_faint(workflow_model.summary(self.document))
