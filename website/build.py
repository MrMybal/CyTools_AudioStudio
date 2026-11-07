"""Build the local product showcase alongside the unchanged CyDoc HTML reader.

Run from any directory: python website/build.py
No network, Node installation, AI engine or application data is needed.
"""
from pathlib import Path
import html, json, hashlib, importlib.util, shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
APP=ROOT/'app'

def build():
    content=json.loads((HERE/'content.json').read_text('utf-8'))
    manifest=json.loads((APP/'CyTool.json').read_text('utf-8'))
    product=manifest['name'];version=manifest['version'];short=content['shortName']
    repo='https://github.com/MrMybal/'+content['repository']
    copy={'product':product}
    def tr(key,value,tag='span',attrs=''):
        assert isinstance(value,dict) and set(value)=={'en','fr'} and all(isinstance(v,str) and v.strip() for v in value.values()),key
        copy[key]=value
        return f'<{tag} data-copy="{key}" {attrs}>{html.escape(value["en"])}</{tag}>'
    def pair(en,fr):return {'en':en,'fr':fr}
    def common(key,en,fr,tag='span',attrs=''):return tr(key,pair(en,fr),tag,attrs)
    def doc(key,en,fr,page='overview',class_='text-link'):
        return tr(key,pair(en,fr),'a',f'class="{class_}" data-doc="{page}" href="Documentation.html#/en/{page}"')
    assets=content['images']
    for key,item in assets.items():
        path=(HERE/item['file']).resolve()
        if not path.is_relative_to((HERE/'assets').resolve()) or not path.is_file():raise ValueError('Missing/conflicting image: '+key)
    def picture(name,caption,key,hero=False):
        item=assets[name];src=html.escape(item['file']);copy[key]=caption
        button='hero-frame' if hero else 'image-button'
        label=pair('Enlarge screenshot: '+caption['en'],'Agrandir la capture : '+caption['fr']);copy[key+'-open']=label
        image=f'<button type="button" class="{button}" data-image="{src}" data-caption="{key}" data-copy-label="{key}-open" aria-label="{html.escape(label["en"])}"><img src="{src}" width="{item["width"]}" height="{item["height"]}" data-copy-alt="{key}" alt="{html.escape(caption["en"])}" {"fetchpriority=high" if hero else "loading=lazy"} decoding="async"></button>'
        caption_html=tr(key,caption)
        if hero:caption_html+=common('zoom-hint','Click to enlarge ↗','Agrandir ↗',attrs='class="zoom-hint"')
        return f'<figure class="{"hero-visual" if hero else "shot"}">{image}<figcaption>{caption_html}</figcaption></figure>'
    logo=content.get('logo')
    brand=(f'<img src="{html.escape(logo)}" width="35" height="35" alt="">' if logo else '<span class="brand-mark" aria-hidden="true">CC</span>')+f'<span class="brand-name">{html.escape(short)}</span>'
    nav=common('nav-features','Features','Fonctionnalités','a','href="#features"')+doc('nav-docs','Documentation ↗','Documentation ↗',class_='')+common('nav-download','Downloads','Téléchargements','a','href="#download"')
    github=f'<a class="github-link" href="{repo}" target="_blank" rel="noopener noreferrer">GitHub <span aria-hidden="true">↗</span></a>'
    language='<div class="language" role="group" aria-label="Language / Langue"><button type="button" data-language="en" aria-pressed="true" lang="en">EN</button><button type="button" data-language="fr" aria-pressed="false" lang="fr">FR</button></div>'
    hero=(tr('category',content['category'],'p','class="eyebrow"')+f'<h1><small>CyTools</small>{html.escape(short)}</h1>'+tr('intro',content['intro'],'p','class="hero-lead"')+tr('description',content['description'],'p','class="hero-description"'))
    hero+='<div class="actions">'+common('hero-download','Download for Windows ↓','Télécharger pour Windows ↓','a','href="#download" class="button primary"')+common('hero-explore','Explore the tool ↘','Découvrir l’outil ↘','a','href="#features" class="button"')+'</div>'
    hero+='<p class="release-line"><span class="dot" aria-hidden="true"></span>'+common('release-status','Experimental release','Version expérimentale')+f' · v{html.escape(version)} · Windows x64</p>'
    chapters=''.join(f'<a href="#{s["id"]}"><span class="chapter-number">{i+1:02} </span>'+tr('chapter-'+s['id'],{locale:label.split(' / ',1)[-1] for locale,label in s['label'].items()})+'</a>' for i,s in enumerate(content['sections']))
    chapters+=common('chapter-more','More views','Autres vues','a','href="#gallery"')+common('chapter-requirements','Before you start','Avant de commencer','a','href="#requirements"')
    sections=[]
    for i,s in enumerate(content['sections']):
        prefix='section-'+s['id']
        text=tr(prefix+'-label',s['label'],'p','class="eyebrow"')+tr(prefix+'-title',s['title'],'h2')+tr(prefix+'-body',s['body'],'p')
        text+='<ul class="points">'+''.join(tr(prefix+'-point-'+str(j),p,'li') for j,p in enumerate(s['points']))+'</ul>'
        text+=doc(prefix+'-doc','Open the guide ↗','Ouvrir le guide ↗',s['doc'])
        sections.append(f'<section class="feature {"reverse" if i%2 else ""}" id="{s["id"]}"><div class="feature-copy">{text}</div>'+picture(s['image'],s['caption'],prefix+'-caption')+'</section>')
    gallery=[]
    for key,item in assets.items():
        gallery.append(picture(key,item['caption'],'gallery-'+key))
    flow=[(pair('Use the desktop','Utilisez l’application'),pair('Explore the actual workspaces, inspect results and adjust the native settings.','Explorez les espaces de travail, inspectez les résultats et réglez les paramètres natifs.'),'Desktop / CyUI'),(pair('Script an operation','Automatisez une opération'),pair('The CLI exposes the declared operations and their structured parameters.','La CLI expose les opérations déclarées et leurs paramètres structurés.'),'tool.py describe'),(pair('Connect an AI client','Connectez un client IA'),pair('MCP uses the same operation contracts. Export wanted task files before finishing a temporary AI task.','Le MCP utilise les mêmes contrats. Exportez les résultats souhaités avant de terminer une tâche IA temporaire.'),'tool.py mcp')]
    flow_html=''.join('<article class="flow-step"><span class="index">'+str(i+1).zfill(2)+' /</span>'+tr('flow-title-'+str(i),title,'h3')+tr('flow-body-'+str(i),body,'p')+f'<code>{code}</code></article>' for i,(title,body,code) in enumerate(flow))
    faq=[(pair('Are the models included?','Les modèles sont-ils inclus ?'),pair('No. Install the compatible engines and weights from the application when needed. Hardware, access conditions and licences depend on the component.','Non. Installez les moteurs et poids compatibles depuis l’application selon vos besoins. Matériel, accès et licences dépendent du composant.')),(pair('Is the application ready for every platform?','L’application est-elle prête pour toutes les plateformes ?'),pair('This is experimental software. A Windows x64 release is available. Other launchers or declared backends do not imply that they have been validated.','Le logiciel est expérimental. Une release Windows x64 est disponible. La présence d’autres lanceurs ou moteurs déclarés n’implique pas leur validation.')),(pair('Can I use every model commercially?','Puis-je utiliser tous les modèles commercialement ?'),pair('Check the application licence and each engine and model licence separately. The licence of CyToolsCore or CyUI does not override restrictions on model weights.','Vérifiez séparément la licence de l’application, des moteurs et des modèles. Les licences de CyToolsCore ou CyUI ne remplacent pas les restrictions des poids.'))]
    faq_html=''.join('<details><summary>'+tr('faq-q-'+str(i),q)+'</summary>'+tr('faq-a-'+str(i),a,'p')+'</details>' for i,(q,a) in enumerate(faq))
    private_note=pair('Private repository · a GitHub account with access is required.','Dépôt privé · un compte GitHub autorisé est nécessaire.') if content['private'] else pair('Public repository · portable Windows x64 ZIP available in Releases.','Dépôt public · ZIP Windows x64 portable disponible dans les releases.')
    parts=[
      '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
      f'<title>{html.escape(product)} — {html.escape(content["intro"]["en"])}</title><meta name="description" content="{html.escape(content["description"]["en"])}"><meta name="theme-color" content="#111316">',
      '<script>if(/^#\/(en|fr)\//.test(location.hash)){location.replace("Documentation.html"+location.search+location.hash);}</script>',
      '<link rel="stylesheet" href="__CSS__">'+(f'<link rel="icon" href="{html.escape(logo)}">' if logo else ''),
      f'</head><body style="--accent:{content["accent"]}">',common('skip','Skip to content','Aller au contenu','a','href="#main" class="skip"'),
      f'<header class="header"><div class="wrap header-inner"><a class="brand" href="#main" aria-label="{html.escape(product)}">{brand}</a><nav class="top-nav" aria-label="Navigation">{nav}</nav><div class="header-actions">{language}{github}</div></div></header>',
      f'<main id="main"><div class="wrap"><section class="hero"><div class="hero-copy">{hero}</div>'+picture(content['hero'],content['heroCaption'],'hero-caption',hero=True)+'</section>',
      '<div class="strips">'+common('strap','One desktop tool. Several ways to use it.','Un outil de bureau. Plusieurs façons de l’utiliser.',attrs='class="strap"')+''.join(tr('tag-'+str(i),tag,'strong') for i,tag in enumerate(content['tags']))+'</div></div>',
      '<nav class="chapters" aria-label="Chapters / Chapitres"><div class="wrap chapters-inner">'+chapters+'</div></nav><div class="wrap">',
      '<section class="intro" id="features">'+common('intro-label','Made for your workflow','Pour votre façon de travailler','p','class="eyebrow"')+tr('audience',content['audience'],'p')+'</section>',
      ''.join(sections),
      '<section class="gallery-section" id="gallery"><div class="section-top"><div>'+common('gallery-label','A closer look','De plus près','p','class="eyebrow"')+common('gallery-title','Inside the application.','Dans l’application.','h2','class="section-heading"')+'</div>'+common('gallery-body','Real application windows. Open an image to inspect it in the page; Escape closes the viewer.','De vraies fenêtres de l’application. Agrandissez une image dans la page ; Échap ferme le visualiseur.','p')+'</div><div class="gallery-grid">'+''.join(gallery)+'</div></section>',
      '<section class="workflow" id="automation"><div class="workflow-top"><div>'+common('workflow-label','Desktop / CLI / MCP','Application / CLI / MCP','p','class="eyebrow"')+common('workflow-title','Work visually. Automate the next step.','Travaillez visuellement. Automatisez la suite.','h2','class="section-heading"')+'</div>'+common('workflow-body','The standalone application and AI-facing operations share the CyToolsCore runtime. Consult the manual for the real input/output contracts and required permissions.','L’application autonome et les opérations destinées aux IA partagent le runtime CyToolsCore. Consultez le manuel pour les contrats d’entrée et de sortie et les permissions nécessaires.','p')+'</div><div class="flow-grid">'+flow_html+'</div></section>',
      '<section class="manual" id="documentation"><div>'+common('manual-label','Guides & reference','Guides et références','p','class="eyebrow"')+common('manual-title','The same manual. Online and offline.','Le même manuel. En ligne et hors ligne.','h2')+common('manual-body','Open the complete CyDoc reader: navigation, search, references and the available media. The application ships the local reader too. English is the default; French is fully selectable.','Ouvrez le lecteur CyDoc complet : navigation, recherche, références et médias disponibles. L’application fournit aussi le lecteur local. L’anglais est la langue par défaut ; le français est disponible.','p')+'</div><div class="actions">'+doc('manual-open','Open documentation ↗','Ouvrir la documentation ↗',class_='button primary')+'</div></section>',
      '<section class="requirements" id="requirements"><div>'+common('requirements-label','Before you start','Avant de commencer','p','class="eyebrow"')+common('requirements-title','Know what you are installing.','Sachez ce que vous installez.','h2')+'</div><div>'+tr('limits',content['limits'],'p')+faq_html+'</div></section>',
      '<section class="download" id="download"><div>'+common('download-label','Try the tool','Essayer l’outil','p','class="eyebrow"')+common('download-title','Start with the Windows release.','Commencez par la release Windows.','h2','class="section-heading"')+common('download-body','Extract the complete portable ZIP into a writable folder and open the application executable. Keep app/ and runtime/ beside it. Model weights are not bundled; follow the installation workspace when you need them.','Décompressez le ZIP portable complet dans un dossier accessible en écriture et ouvrez l’exécutable. Gardez app/ et runtime/ à côté. Les poids ne sont pas inclus ; utilisez l’espace d’installation selon vos besoins.','p')+doc('download-install','Read installation instructions ↗','Lire les instructions d’installation ↗','installation')+'</div><div class="download-card"><h3>'+html.escape(short)+' <span class="arrow">↗</span></h3>'+tr('download-access',private_note,'p')+'<div class="actions">'+common('download-release','Open latest release ↓','Ouvrir la dernière release ↓','a',f'class="button primary" href="{repo}/releases/latest" target="_blank" rel="noopener noreferrer"')+common('download-source','Source code ↗','Code source ↗','a',f'class="button" href="{repo}" target="_blank" rel="noopener noreferrer"')+'</div><p class="file-meta">Windows x64 · ZIP · SHA256</p></div></section></div></main>',
      '<footer class="footer"><div class="wrap footer-inner"><div><strong>'+html.escape(product)+'</strong> · Cyberalien · '+html.escape(content['licence'])+'</div><div class="footer-links">'+doc('footer-doc','Documentation','Documentation')+common('footer-release','Releases','Releases','a',f'href="{repo}/releases"')+common('footer-licence','Licence','Licence','a',f'href="{repo}/blob/main/LICENSE"')+'</div></div></footer>',
      '<dialog class="viewer" id="image-viewer" aria-labelledby="viewer-caption"><div class="viewer-head"><span class="viewer-title"></span><button type="button" class="viewer-prev" data-copy-label="previous" aria-label="Previous image">←</button><button type="button" class="viewer-next" data-copy-label="next" aria-label="Next image">→</button><button type="button" class="viewer-close" data-copy-label="close" aria-label="Close viewer">×</button></div><img alt=""><p class="viewer-caption" id="viewer-caption"></p></dialog>',
      '<noscript><p class="noscript">This English page remains readable without JavaScript. Enable JavaScript for French and the image viewer. / Cette page reste lisible en anglais sans JavaScript. Activez JavaScript pour le français et le visualiseur.</p></noscript>',
    ]
    copy.update({'previous':pair('Previous image','Image précédente'),'next':pair('Next image','Image suivante'),'close':pair('Close viewer (Escape)','Fermer le visualiseur (Échap)')})
    payload=json.dumps(copy,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    parts+=['<script type="application/json" id="site-copy">'+payload+'</script><script src="__JS__" defer></script></body></html>']
    rendered=''.join(parts)
    generated={}
    for source,placeholder in [('site.css','__CSS__'),('site.js','__JS__')]:
        data=(HERE/'src'/source).read_bytes();fingerprint=hashlib.sha256(data).hexdigest()[:12]
        name='assets/showcase/'+source.replace('.', '.'+fingerprint+'.',1)
        generated[name]=data;rendered=rendered.replace(placeholder,name)
    # The original publisher validates the complete offline reader and enforces a
    # confined, recognisable _site staging directory. It never reads user data.
    spec=importlib.util.spec_from_file_location('cydoc_publisher',APP/'.CyDocBuild/publish.py')
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    result=publisher.stage(ROOT/'_site')
    output=ROOT/'_site'
    for file in (HERE/'assets').rglob('*'):
        if file.is_symlink():raise ValueError('Showcase assets cannot be symlinks')
        if file.is_file():
            if file.suffix.lower() not in {'.webp','.png','.svg'}:raise ValueError('Unexpected showcase asset')
            target=output/file.relative_to(HERE);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
    for name,data in generated.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    (output/'index.html').write_text(rendered,encoding='utf-8')
    result.update({'showcase':product,'version':version,'locales':['en','fr'],'images':len(assets)})
    return result

if __name__=='__main__':print(json.dumps(build()))
