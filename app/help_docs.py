"""Application-owned CyDoc bridge. No browser/UI dependency is loaded on import."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import json
import logging
import webbrowser

APP = Path(__file__).resolve().parent
_context = {}
_last_error = ''
_workspace = ''
_workspace_frame = -1


@lru_cache(maxsize=1)
def catalog():
    return json.loads((APP/'help/help-map.json').read_text('utf-8'))


def help_url(page='overview', locale='en', anchor=None, media=None):
    """Encode a local file route; unknown legacy targets safely fall back to overview."""
    index=APP/'help/index.html'
    if not index.is_file():raise FileNotFoundError('The local manual is missing. Regenerate it with app/documentation/build.py.')
    data=catalog();page=data['legacyPaths'].get(str(page).replace('\\','/'),page)
    aliases={'user-guide':'guide-lisez-moi','api':'operations','readme':'overview','help':'overview'}
    page=aliases.get(page,page)
    if page not in data['pages']:page='overview'
    locale='fr' if str(locale).lower().startswith('fr') else 'en'
    fragment='#/'+quote(locale,safe='')+'/'+quote(str(page),safe='')
    if anchor:fragment+='/'+quote(str(anchor),safe='')
    if media:fragment+='?media='+quote(str(media),safe='')
    return index.resolve().as_uri()+fragment


def open_help(page='overview', locale=None, anchor=None, media=None):
    global _last_error
    try:
        if locale is None:
            import ui_common
            locale=ui_common.preferences.values.get('language','en')
        url=help_url(page,locale,anchor,media)
        if not webbrowser.open(url,new=2):raise RuntimeError('The default browser could not open the local manual.')
        _last_error='';return True
    except (OSError,ValueError,RuntimeError) as exc:
        _last_error=str(exc);logging.getLogger(__name__).error('Cannot open local documentation: %s',exc);return False


def set_context(values):
    global _context
    _context=values


def note_tab(name, frame):
    global _workspace, _workspace_frame
    if frame != _workspace_frame:
        _workspace=str(name).split('##',1)[0];_workspace_frame=frame


def contextual_page():
    # Read current workspace values at invocation time, never retain a conversation or job.
    values=_context() if callable(_context) else _context
    app=values.get('app')
    tool=getattr(app,'tools',None)
    operation=getattr(tool,'selected',None)
    view=values.get('view',{})
    view=view.get('page','') if isinstance(view,dict) else view
    page=str(getattr(app,'page','') or view or _workspace or values.get('current_tab','') or values.get('active_tab','') or '')
    if operation and page in ('','Tools'):
        import re
        id='operation-'+re.sub('[^a-z0-9]+','-',str(operation).lower()).strip('-')
        if id in catalog()['pages']:return id
    lower=page.lower()
    candidates=[]
    if 'workflow' in lower:candidates=['guide-app-docs-workflow']
    elif any(x in lower for x in ('install','model','compute')):candidates=['guide-app-docs-dependencies','guide-app-docs-runtimeinstallation','guide-app-docs-models']
    elif 'update' in lower:candidates=['guide-app-updates','guide-app-docs-updates']
    elif any(x in lower for x in ('viewer','3d')):candidates=['mesh-preview','guide-app-docs-meshviewer']
    elif any(x in lower for x in ('log','diagnostic')):candidates=['guide-app-docs-standalonediagnosticsandmodels']
    elif any(x in lower for x in ('option','setting')):candidates=['guide-app-ui-options','guide-app-docs-localization']
    for id in candidates:
        if id in catalog()['pages']:return id
    for id in ('guide-readme','guide-app-readme','guide-lisez-moi'):
        if id in catalog()['pages']:return id
    return 'overview'


def poll_shortcut():
    """Called once per UI frame; F1 does not consume text editing shortcuts."""
    from imgui_bundle import imgui
    if imgui.is_key_pressed(imgui.Key.f1,False):open_help(contextual_page())


def draw_options():
    from imgui_bundle import imgui
    from ui_common import tr
    imgui.push_id('cydoc-help')
    try:
        imgui.separator_text(tr('Documentation'))
        if imgui.button(tr('Open local manual (F1)')):open_help()
        imgui.same_line()
        if imgui.button(tr('Help for current workspace')):open_help(contextual_page())
        imgui.text_wrapped(tr('The manual opens locally in your browser and works offline.'))
        if _last_error:imgui.text_wrapped(_last_error)
    finally:imgui.pop_id()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page',default='overview');parser.add_argument('--locale',default='en')
    parser.add_argument('--anchor');parser.add_argument('--media');parser.add_argument('--print-url',action='store_true')
    args=parser.parse_args()
    if args.print_url:print(help_url(args.page,args.locale,args.anchor,args.media))
    else:raise SystemExit(0 if open_help(args.page,args.locale,args.anchor,args.media) else 1)
