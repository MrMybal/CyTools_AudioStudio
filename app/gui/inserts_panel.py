"""Inserts panel under the timeline: the effect / VST3 chain of the selected track or of the
master bus, with the interface of the selected insert on the right (gui/effect_ui.py).

The chain uses the workflow node format, so a saved workflow can be loaded as inserts and a
chain can be sent to the Workflows tab; "Bake" renders the chain into the clip (with the
tail) and clears it.
"""
from pathlib import Path

import numpy as np
from imgui_bundle import imgui

from audiostudio.dsp import effects
from audiostudio.workflow import model as workflow_model
from audiostudio.editor.renderer import Renderer
from .effect_ui import EffectUI
from .widgets import Row, status_line, search_combo
from .search import effect_haystack, plugin_haystack

LIST_WIDTH = 250.0


class InsertsPanel:
    def __init__(self, app):
        self.app = app
        self.show_master = False
        self.owner_id = None                 # None = the selected track
        self.selected = {}                   # owner id -> node id
        self.effect_index = 0
        self.plugin_index = 0
        self.effect_ui = EffectUI(app)
        self.message = ''
        self.editor_rect = None
        self._effects = None

    def tr(self, text):
        return self.app.tr(text)

    @property
    def document(self):
        return self.app.document

    # ------------------------------------------------------------------ helpers
    def realtime_effects(self):
        if self._effects is None:
            self._effects = [spec for spec in effects.REGISTRY.values() if spec.realtime]
            self._effects.sort(key=lambda s: (s.category, s.name))
        return self._effects

    def owner(self):
        document = self.document
        if self.show_master:
            return document.master
        if self.owner_id:
            track = document.track(self.owner_id)
            if track is not None:
                return track
        return document.current_track()

    def show(self, owner):
        """Called by the timeline FX buttons."""
        self.show_master = owner is self.document.master
        self.owner_id = None if self.show_master else owner.id
        if not self.show_master:
            self.document.selected_track = next((i for i, t in enumerate(self.document.tracks) if t.id == owner.id), self.document.selected_track)
        self.app.editor.show_inserts = True

    def follow(self, owner):
        """A click on a track (or on the master) shows its chain, without opening the panel."""
        self.show_master = owner is self.document.master
        self.owner_id = None if self.show_master else owner.id

    def drop_target_node(self):
        """The selected insert of the shown chain when it takes a file (convolution impulse response)."""
        owner = self.owner()
        node = self.selected_node(owner) if owner is not None else None
        spec = effects.REGISTRY.get(node.get('effect')) if node and node['kind'] == 'effect' else None
        if spec is not None and any(p.kind == 'string' and p.id == 'impulse_response' for p in spec.params):
            return node
        return None

    def selected_node(self, owner):
        node_id = self.selected.get(owner.id)
        node = next((n for n in owner.inserts if n['id'] == node_id), None)
        if node is None and owner.inserts:
            node = owner.inserts[-1]
            self.selected[owner.id] = node['id']
        return node

    def add_effect(self, owner, effect_id):
        node = self.document.add_insert(owner, workflow_model.new_node('effect', effect=effect_id))
        self.selected[owner.id] = node['id']
        self._prebuild(node)
        return node

    def _prebuild(self, node):
        """Build the processor now (impulse responses, plugin loading) instead of inside the audio callback."""
        try:
            self.app.player.renderer.processor_for(node)
        except Exception as exc:
            self.message = str(exc)

    def add_plugin(self, owner, info):
        params = {name: p.get('value') for name, p in info.get('parameters', {}).items() if isinstance(p.get('value'), (int, float, bool, str))}
        node = workflow_model.new_node('vst3', plugin=info['path'], pluginName=info.get('name', ''), params=params)
        node['_description'] = info
        node = self.document.add_insert(owner, node)
        self.selected[owner.id] = node['id']
        self._prebuild(node)
        return node

    def load_workflow(self, owner, workflow):
        for node in workflow.get('nodes', []):
            if node['kind'] == 'model':
                continue
            if node['kind'] == 'effect' and not effects.REGISTRY[node['effect']].realtime:
                self.message = self.tr('Skipped (whole-file effect): ') + node['effect']
                continue
            self.document.add_insert(owner, dict(node, id=None))
        self.message = self.tr('Workflow loaded as inserts: ') + workflow.get('name', '')

    def to_workflow(self, owner):
        panel = self.app.workflows
        panel.document = workflow_model.new_workflow(owner.name + ' inserts', nodes=[{k: v for k, v in n.items() if not k.startswith('_') and k != 'sidechain'} for n in owner.inserts])
        panel.path = None
        self.app.select_tab('Workflows')

    def bake(self, track):
        """Render the chain (with its tail) into the clip, then clear the chain."""
        document = self.document
        if track is document.master or not track.inserts:
            return
        renderer = Renderer(document)
        block, _ = renderer.clip_block(track, track.offset, track.frames)
        tail = document.tail
        extra = int(float(tail.get('max_seconds', 10.0)) * document.samplerate) if (tail.get('enabled', True) and any(
            n.get('enabled', True) and (n['kind'] == 'vst3' or effects.REGISTRY[n['effect']].stateful) for n in track.inserts)) else 0
        audio = np.concatenate([block, np.zeros((2, extra), np.float32)], axis=1) if extra else block
        parts = []
        for start in range(0, audio.shape[1], 4096):
            parts.append(renderer.run_chain(track, track.inserts, audio[:, start:start + 4096], track.offset + start, min(4096, audio.shape[1] - start)))
        rendered = np.concatenate(parts, axis=1)
        if extra:
            from audiostudio.dsp.tail import trim, TailSettings
            rendered = trim(rendered, document.samplerate, TailSettings.from_dict(tail), block.shape[1])
        document.edit('Bake inserts', [track.id])
        track.flatten()
        track.audio = np.ascontiguousarray(rendered)
        track.fade_in = track.fade_out = 0.0
        track.inserts = []
        track.automation = {k: v for k, v in track.automation.items() if '.' not in k}
        track.invalidate()
        document.touch()
        self.message = self.tr('Inserts rendered into the clip')

    # ------------------------------------------------------------------ drawing
    def draw(self, height):
        tr = self.tr
        document = self.document
        renderer = self.app.player.renderer
        owner = self.owner()
        imgui.begin_child('##inserts-panel', (0, height), imgui.ChildFlags_.borders)
        if owner is None:
            imgui.text_disabled(tr('No track: open a file or generate a sound, then add inserts here.'))
            imgui.end_child()
            return
        # ---------------------------------------------------------------- left: chain
        imgui.begin_child('##chain-list', (LIST_WIDTH, 0), imgui.ChildFlags_.borders)
        owner_colour = (0.98, 0.62, 0.2, 1.0) if owner is document.master else (*owner.colour, 1.0)
        imgui.text_colored(owner_colour, (tr('Master bus') if owner is document.master else tr('Track') + ': ' + owner.name)[:30])
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Effects belong to one track or to the master. Click a track (or the master lane) to show its chain.'))
        if imgui.radio_button(tr('This track') + '##inserts-track', not self.show_master):
            self.show_master = False
            self.owner_id = None
        imgui.same_line()
        if imgui.radio_button(tr('Master') + '##inserts-master', self.show_master):
            self.show_master = True
        imgui.separator()
        remove = None
        move = None
        drop = None
        selected_id = self.selected.get(owner.id)
        for index, node in enumerate(owner.inserts):
            if node.get('_preview'):
                continue                              # the Effect... dialog's audition insert is not part of the chain
            imgui.push_id(node['id'])
            changed, enabled = imgui.checkbox('##on', bool(node.get('enabled', True)))
            if changed:
                node['enabled'] = enabled
                document.touch()
            if imgui.is_item_hovered():
                imgui.set_tooltip(tr('Enable or bypass this insert'))
            imgui.same_line()
            title = tr(effects.REGISTRY[node['effect']].name) if node['kind'] == 'effect' and node['effect'] in effects.REGISTRY else (node.get('pluginName') or Path(node.get('plugin', '')).stem)
            error = renderer.errors.get(node['id'])
            if error:
                imgui.push_style_color(imgui.Col_.text, (1.0, 0.5, 0.4, 1.0))
            if imgui.selectable(f'{index + 1}. {title}###select', selected_id == node['id'], 0, (LIST_WIDTH - 110, 0))[0]:
                self.selected[owner.id] = node['id']
            if imgui.begin_drag_drop_source():
                imgui.set_drag_drop_payload_py_id('audiostudio-insert', index)
                imgui.text(title)
                imgui.end_drag_drop_source()
            if imgui.begin_drag_drop_target():
                payload = imgui.accept_drag_drop_payload_py_id('audiostudio-insert')
                if payload is not None:
                    dragged = owner.inserts[payload.data_id]['id'] if 0 <= payload.data_id < len(owner.inserts) else None
                    if dragged is not None:
                        drop = (dragged, index)
                imgui.end_drag_drop_target()
            if error:
                imgui.pop_style_color()
                if imgui.is_item_hovered():
                    imgui.set_tooltip(error)
            imgui.same_line()
            if imgui.small_button('^###Move insert up'):
                move = (node['id'], -1)
            imgui.same_line()
            if imgui.small_button('v###Move insert down'):
                move = (node['id'], 1)
            imgui.same_line()
            if imgui.small_button('X###Remove insert'):
                remove = node['id']
            imgui.pop_id()
        if not owner.inserts:
            imgui.text_disabled(tr('(no insert)'))
        else:
            imgui.push_style_color(imgui.Col_.text, imgui.get_style().color_(imgui.Col_.text_disabled))
            imgui.text_wrapped(tr('Drag an insert onto another to reorder the chain.'))
            imgui.pop_style_color()
        if remove is not None:
            document.remove_insert(owner, remove)
            renderer.forget(remove)
        if move is not None:
            document.move_insert(owner, move[0], move[1])
        if drop is not None:
            document.reorder_insert(owner, drop[0], drop[1])
        imgui.separator()
        specs = self.realtime_effects()
        _, self.effect_index = search_combo('add-effect', self.effect_index, [tr(s.name) for s in specs], LIST_WIDTH - 70,
                                            haystacks=[effect_haystack(s, tr) for s in specs], groups=[tr(s.category) for s in specs],
                                            tooltips=[tr(s.help) if s.help else '' for s in specs], tr=tr)
        imgui.same_line()
        if imgui.button(tr('Add') + '###Add insert effect') and specs:
            self.add_effect(owner, specs[self.effect_index].id)
        catalogue = self.app.workflows.plugin_catalogue
        labels = [f"{p.get('name')} ({p.get('manufacturer', '')})" for p in catalogue] or [tr('(scan plugins in the Plugins tab)')]
        _, self.plugin_index = search_combo('add-plugin', min(self.plugin_index, max(0, len(labels) - 1)), labels, LIST_WIDTH - 70,
                                            haystacks=[plugin_haystack(p) for p in catalogue] or None, tr=tr)
        imgui.same_line()
        if imgui.button(tr('Add') + '###Add insert plugin') and catalogue:
            self.add_plugin(owner, catalogue[self.plugin_index])
        row = Row()
        if row.button('From workflow', tr):
            try:
                self.load_workflow(owner, self.app.workflows.current())
            except Exception as exc:
                self.message = str(exc)
        if imgui.is_item_hovered():
            imgui.set_tooltip(tr('Adds the chain of the Workflows tab as inserts'))
        if row.button('To workflow', tr):
            self.to_workflow(owner)
        if owner is not document.master:
            if row.button('Bake', tr):
                self.bake(owner)
            if imgui.is_item_hovered():
                imgui.set_tooltip(tr('Renders the inserts into the clip (with the tail) and removes them'))
        imgui.end_child()
        imgui.same_line()
        # ---------------------------------------------------------------- right: selected insert
        imgui.begin_child('##insert-editor', (0, 0), imgui.ChildFlags_.borders)
        position, size = imgui.get_window_pos(), imgui.get_window_size()
        self.editor_rect = (position.x, position.y, position.x + size.x, position.y + size.y)     # for scripted hover sweeps
        node = self.selected_node(owner)
        if node is None:
            imgui.text_disabled(tr('Add an effect or a VST3 plugin to this chain.'))
        else:
            width = imgui.get_content_region_avail().x
            imgui.push_id(node['id'])
            changed, enabled = imgui.checkbox(tr('On') + '##on', bool(node.get('enabled', True)))
            if changed:
                node['enabled'] = enabled
                document.touch()
            imgui.same_line()
            imgui.push_item_width(120)
            changed, mix = imgui.slider_float(tr('Mix') + '##mix', float(node.get('mix', 1.0)), 0.0, 1.0, '%.2f')
            if imgui.is_item_activated():
                document._edit_owner('Mix', owner)
            if changed:
                node['mix'] = float(mix)
                document.touch()
            imgui.pop_item_width()
            spec = effects.REGISTRY.get(node.get('effect')) if node['kind'] == 'effect' else None
            if spec is not None and spec.sidechain and owner is not document.master:
                imgui.same_line()
                others = [t for t in document.tracks if t.id != owner.id]
                labels = [tr('(no side-chain)')] + [t.name for t in others]
                current = next((i + 1 for i, t in enumerate(others) if t.id == node.get('sidechain')), 0)
                imgui.push_item_width(160)
                changed, current = imgui.combo(tr('Side-chain') + '##sidechain', current, labels)
                imgui.pop_item_width()
                if changed:
                    node['sidechain'] = others[current - 1].id if current > 0 else ''
                    if not node['sidechain']:
                        node.pop('sidechain', None)
                    document.touch()
                if imgui.is_item_hovered():
                    imgui.set_tooltip(tr('Another track feeds the detector (ducking) or the carrier (vocoder)'))
            imgui.same_line()
            imgui.text_disabled(tr('Right-click a knob for its automation lane'))
            imgui.separator()
            if node['kind'] == 'effect':
                self.effect_ui.draw(owner, node, renderer, width)
            elif node['kind'] == 'vst3':
                if node.get('_description') is None:
                    node['_description'] = next((p for p in catalogue if p.get('path', '').lower() == str(node['plugin']).lower()), None) or {'parameters': {}}
                self.effect_ui.draw_vst(owner, node, renderer, width)
            imgui.pop_id()
        if self.message:
            status_line(self.message)
        imgui.end_child()
        imgui.end_child()
