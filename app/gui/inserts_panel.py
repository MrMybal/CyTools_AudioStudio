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
from .widgets import search_combo
from . import cyui
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
        node = workflow_model.new_node(info.get('format', 'VST3').lower(), plugin=info['path'], pluginName=info.get('pluginId') or info.get('name', ''), params=params)
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
        offset = track.offset                       # every clip of the track becomes one clip
        block, _ = renderer.clip_block(track, offset, track.frames)
        tail = document.tail
        extra = int(float(tail.get('max_seconds', 10.0)) * document.samplerate) if (tail.get('enabled', True) and any(
            n.get('enabled', True) and (n['kind'] in ('vst3', 'clap', 'lv2', 'jsfx') or effects.REGISTRY[n['effect']].stateful) for n in track.inserts)) else 0
        audio = np.concatenate([block, np.zeros((2, extra), np.float32)], axis=1) if extra else block
        parts = []
        for start in range(0, audio.shape[1], 4096):
            parts.append(renderer.run_chain(track, track.inserts, audio[:, start:start + 4096], offset + start, min(4096, audio.shape[1] - start)))
        rendered = np.concatenate(parts, axis=1)
        if extra:
            from audiostudio.dsp.tail import trim, TailSettings
            rendered = trim(rendered, document.samplerate, TailSettings.from_dict(tail), block.shape[1])
        document.edit('Bake inserts', [track.id])
        track.set_audio(rendered, offset, name=track.name + ' (baked)')
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
        p = cyui.palette()
        icon = cyui.icon
        with cyui.scoped_colour((imgui.Col_.child_bg, p.bg1)):
            imgui.begin_child('##inserts-panel', (0, height), imgui.ChildFlags_.borders)
        if owner is None:
            cyui.empty_state(tr('No track yet'), tr('Open a file or generate a sound, then add effects to its track here.'), icon.equalizer)
            imgui.end_child()
            return
        # ---------------------------------------------------------------- left: chain
        with cyui.scoped_colour((imgui.Col_.child_bg, p.bg2)):
            imgui.begin_child('##chain-list', (LIST_WIDTH, 0), imgui.ChildFlags_.borders | imgui.ChildFlags_.always_use_window_padding)
        is_master = owner is document.master
        chip = p.accent if is_master else cyui.from_floats(*owner.colour)
        cyui.colour_chip('##owner-colour', chip, (cyui.dp(4.0), imgui.get_text_line_height()))
        imgui.same_line(0, 6)
        cyui.heading(cyui.clip_text(tr('Master bus') if is_master else owner.name, LIST_WIDTH - 40), 3)
        cyui.tooltip(tr('Effects belong to one track or to the master. Click a track (or the master lane) to show its chain.'))
        changed, which = cyui.segmented('##inserts-owner', [tr('This track') + '###inserts-track', tr('Master') + '###inserts-master'], 1 if self.show_master else 0, -1)
        if changed:
            self.show_master = which == 1
            if not self.show_master:
                self.owner_id = None
        cyui.space(4.0)
        remove = None
        move = None
        drop = None
        selected_id = self.selected.get(owner.id)
        chain = [n for n in owner.inserts if not n.get('_preview')]   # the Effect... dialog's audition insert is not part of the chain
        for index, node in enumerate(owner.inserts):
            if node.get('_preview'):
                continue
            imgui.push_id(node['id'])
            changed, enabled = imgui.checkbox('##on', bool(node.get('enabled', True)))
            if changed:
                node['enabled'] = enabled
                document.touch()
            cyui.tooltip(tr('Enable or bypass this insert'))
            imgui.same_line(0, 4)
            title = tr(effects.REGISTRY[node['effect']].name) if node['kind'] == 'effect' and node['effect'] in effects.REGISTRY else ((node.get('_description') or {}).get('name') or node.get('pluginName') or Path(node.get('plugin', '')).stem)
            error = renderer.errors.get(node['id'])
            colour = p.error if error else (p.text if node.get('enabled', True) else p.textFaint)
            buttons = imgui.get_frame_height() * 3 + 8
            with cyui.scoped_colour((imgui.Col_.text, colour)):
                if imgui.selectable(f'{index + 1}. {title}###select', selected_id == node['id'], 0, (max(40.0, imgui.get_content_region_avail().x - buttons), 0))[0]:
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
                cyui.tooltip(error)
            imgui.same_line(0, 2)
            small = (imgui.get_frame_height() * 0.9, 0)
            if cyui.icon_button(icon.chevron_up, tr('Move up in the chain'), id='Move insert up', fallback='^', size=small):
                move = (node['id'], -1)
            imgui.same_line(0, 0)
            if cyui.icon_button(icon.chevron_down, tr('Move down in the chain'), id='Move insert down', fallback='v', size=small):
                move = (node['id'], 1)
            imgui.same_line(0, 0)
            if cyui.icon_button(icon.close, tr('Remove this insert (Ctrl+Z to undo)'), id='Remove insert', fallback='X', size=small, active_colour=p.error):
                remove = node['id']
            imgui.pop_id()
        if not chain:
            cyui.text_faint(tr('(no insert)'))
        else:
            cyui.text_wrapped_faint(tr('Drag an insert onto another to reorder the chain.'))
        if remove is not None:
            document.remove_insert(owner, remove)
            renderer.forget(remove)
        if move is not None:
            document.move_insert(owner, move[0], move[1])
        if drop is not None:
            document.reorder_insert(owner, drop[0], drop[1])
        cyui.divider()
        cyui.section_title(tr('Add to the chain'))
        specs = self.realtime_effects()
        add_width = cyui.button_width(tr('Add')) + 4
        _, self.effect_index = search_combo('add-effect', self.effect_index, [tr(s.name) for s in specs], imgui.get_content_region_avail().x - add_width - 4,
                                            haystacks=[effect_haystack(s, tr) for s in specs], groups=[tr(s.category) for s in specs],
                                            tooltips=[tr(s.help) if s.help else '' for s in specs], tr=tr)
        imgui.same_line(0, 4)
        if cyui.button(tr('Add') + '###Add insert effect') and specs:
            self.add_effect(owner, specs[self.effect_index].id)
        cyui.tooltip(tr('Add the chosen effect at the end of the chain'))
        catalogue = self.app.workflows.plugin_catalogue
        labels = [f"{p_.get('name')} ({p_.get('manufacturer', '')})" for p_ in catalogue] or [tr('(scan plugins in the Plugins tab)')]
        _, self.plugin_index = search_combo('add-plugin', min(self.plugin_index, max(0, len(labels) - 1)), labels, imgui.get_content_region_avail().x - add_width - 4,
                                            haystacks=[plugin_haystack(p_) for p_ in catalogue] or None, tr=tr)
        imgui.same_line(0, 4)
        with cyui.scoped_disabled(not catalogue):
            if cyui.button(tr('Add') + '###Add insert plugin') and catalogue:
                self.add_plugin(owner, catalogue[self.plugin_index])
        cyui.tooltip(tr('Add the chosen plugin at the end of the chain'))
        cyui.space(2.0)
        if cyui.ghost_button(tr('From workflow') + '###From workflow'):
            try:
                self.load_workflow(owner, self.app.workflows.current())
            except Exception as exc:
                self.message = str(exc)
        cyui.tooltip(tr('Adds the chain of the Workflows tab as inserts'))
        imgui.same_line(0, 2)
        if cyui.ghost_button(tr('To workflow') + '###To workflow'):
            self.to_workflow(owner)
        cyui.tooltip(tr('Opens this chain in the Workflows tab'))
        if not is_master:
            imgui.same_line(0, 2)
            with cyui.scoped_disabled(not chain):
                if cyui.ghost_button(tr('Bake') + '###Bake'):
                    self.bake(owner)
            cyui.tooltip(tr('Renders the inserts into the clip (with the tail) and removes them'))
        imgui.end_child()
        imgui.same_line()
        # ---------------------------------------------------------------- right: selected insert
        imgui.begin_child('##insert-editor', (0, 0), imgui.ChildFlags_.borders | imgui.ChildFlags_.always_use_window_padding)
        position, size = imgui.get_window_pos(), imgui.get_window_size()
        self.editor_rect = (position.x, position.y, position.x + size.x, position.y + size.y)     # for scripted hover sweeps
        node = self.selected_node(owner)
        if node is None:
            cyui.empty_state(tr('No effect in this chain'), tr('Add an effect or a plugin to this chain.'), icon.equalizer)
        else:
            width = imgui.get_content_region_avail().x
            imgui.push_id(node['id'])
            changed, enabled = cyui.toggle_switch(tr('On') + '##on', bool(node.get('enabled', True)))
            if changed:
                node['enabled'] = enabled
                document.touch()
            cyui.tooltip(tr('Enable or bypass this insert'))
            imgui.same_line(0, 12)
            imgui.align_text_to_frame_padding()
            cyui.text_dim(tr('Mix'))
            imgui.same_line()
            changed, mix = cyui.slider_bar('##mix', float(node.get('mix', 1.0)), 0.0, 1.0, '%.2f', cyui.dp(120.0))
            if imgui.is_item_activated():
                document._edit_owner('Mix', owner)
            if changed:
                node['mix'] = float(mix)
                document.touch()
            cyui.tooltip(tr('Dry / wet balance of this insert (double-click to type it)'))
            spec = effects.REGISTRY.get(node.get('effect')) if node['kind'] == 'effect' else None
            if spec is not None and spec.sidechain and not is_master:
                imgui.same_line(0, 12)
                imgui.align_text_to_frame_padding()
                cyui.text_dim(tr('Side-chain'))
                imgui.same_line()
                others = [t_ for t_ in document.tracks if t_.id != owner.id]
                labels = [tr('(no side-chain)')] + [t_.name for t_ in others]
                current = next((i + 1 for i, t_ in enumerate(others) if t_.id == node.get('sidechain')), 0)
                imgui.push_item_width(cyui.dp(160.0))
                changed, current = imgui.combo('##sidechain', current, labels)
                imgui.pop_item_width()
                if changed:
                    node['sidechain'] = others[current - 1].id if current > 0 else ''
                    if not node['sidechain']:
                        node.pop('sidechain', None)
                    document.touch()
                cyui.tooltip(tr('Another track feeds the detector (ducking) or the carrier (vocoder)'))
            imgui.same_line(0, 12)
            imgui.align_text_to_frame_padding()
            cyui.text_faint(tr('Right-click a knob for its automation lane'))
            cyui.divider(3.0)
            if node['kind'] == 'effect':
                self.effect_ui.draw(owner, node, renderer, width)
            elif node['kind'] in ('vst3', 'clap', 'lv2', 'jsfx'):
                if node.get('_description') is None:
                    node['_description'] = next((p_ for p_ in catalogue if p_.get('path', '').lower() == str(node['plugin']).lower() and (not node.get('pluginName') or node['pluginName'] in (p_.get('name'), p_.get('pluginId')))), None) or {'parameters': {}}
                self.effect_ui.draw_vst(owner, node, renderer, width)
            imgui.pop_id()
        imgui.end_child()
        imgui.end_child()
