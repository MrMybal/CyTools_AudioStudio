# CyTools AudioStudio

Studio audio autonome : éditeur multipiste avec inserts par piste (106 effets natifs dont 92 en
temps réel, plugins VST3, chacun avec son interface), automation, bus master, effets et plugins
VST3 en workflows (avec rendu de la queue de reverb/delay), génération de bruitages, de musique et
de voix, presets de voix, mastering, assistant texte optionnel. Une seule application remplace CyTools_AudioGen,
ACE-Step 1.5, FishSpeech S2 Pro, Piper TTS et Qwen3-TTS.

## Démarrer

Double-cliquer `CyTools_AudioStudio.exe`. Aucun terminal, aucun JSON à éditer.

Onglets :

- **Editor** : ouvrir/importer des fichiers (WAV, FLAC, MP3, OGG, AAC…), enregistrer depuis le
  micro, plusieurs pistes (volume, pan, muet, solo, déplacement Alt+glisser), sélection à la souris,
  couper/copier/coller/supprimer/rogner/silence/scinder, annuler/rétablir, effets sur la sélection
  avec pré-écoute, application d'un workflow à la sélection, export du mixage (wav/flac/mp3/ogg/aac),
  sessions (dossier `data/sessions`).
  La barre au-dessus de la timeline est rangée en groupes titrés : Session, Transport, Sortie,
  Affichage, Options, Export ; chaque contrôle a une info-bulle. Le bouton **+ Piste** (coin en haut
  à gauche de la timeline) ajoute une piste vide.
  Une piste contient plusieurs clips, qui passent tous par les effets de la piste. Gestes sur un clip :
  glisser sa barre de titre pour le déplacer dans le temps, ou vers le haut / le bas pour le mettre
  sur une autre piste (il prend alors les effets de cette piste) ; glisser un bord gauche ou droit
  pour le rogner (l'audio est conservé, on peut revenir en arrière) ; glisser la poignée carrée d'un
  coin du haut pour un fondu entrant ou sortant (la poignée suit la fin du fondu) ; clic droit pour
  le menu (supprimer le clip, dupliquer, inverser (lecture à l'envers), scinder en deux clips, déplacer au curseur, déplacer vers
  une autre piste). Glisser dans la forme d'onde sélectionne une zone.
  Navigation : molette = zoom, Maj+molette, glisser avec le bouton droit ou le bouton du milieu,
  Espace+glisser, l'outil **Main** (H), la barre de défilement ou la **vue d'ensemble** en bas
  (double-clic = tout afficher) = se déplacer de gauche à droite ; clic ou glisser dans la règle =
  curseur ; Ctrl+molette = zoom vertical ; bord bas d'une piste = hauteur. Raccourcis : Espace
  lecture, Ctrl+Z/Y, Ctrl+X/C/V, Suppr, Début, Échap, H (main), F (panneau FX).
  **Inserts** : le bouton **FX** d'une piste (ou du **Master**, dernière ligne) ouvre le panneau du
  bas : chaîne d'effets et de plugins VST3 de cette piste, activés/contournés, réordonnés, avec
  l'interface de l'effet sélectionné (mesures d'entrée/sortie, forme d'onde et spectromètre temps
  réel de ce qui entre et sort de l'effet, courbe de
  transfert et réduction de gain du compresseur, spectre et points déplaçables de l'EQ, bandes du
  compresseur multibande, décroissance de la réverbération, échos du délai, LFO, goniomètre,
  analyseur...). Tout s'entend pendant la lecture. Le side-chain (ducking, gate déclenché, porteuse
  du vocoder) se choisit dans l'insert. Presets par effet et par plugin, « Depuis le workflow » /
  « Vers le workflow », « Figer » (rend la chaîne dans le clip, queue comprise). L'export du mixage
  passe par les inserts, l'automation et le master et prolonge le rendu jusqu'au silence.
  **Les effets appartiennent à une piste ou au master**, jamais à tout l'éditeur : un clic sur une
  piste (ou sur la ligne Master) affiche sa chaîne dans le panneau FX ; ajouter, retirer, contourner,
  glisser pour réordonner, figer dans le clip, ou envoyer vers l'onglet Workflows.
  **Glisser-déposer** : un son déposé sur une piste devient un clip de cette piste, à l'instant sous
  la souris si la place est libre, sinon juste après son dernier clip ; déposé sous les pistes, il
  crée une nouvelle piste ; une piste vide (bouton **+ Piste**) le prend en gardant ses inserts. Un
  dossier de session l'ouvre, un workflow .json le charge, une réponse impulsionnelle déposée sur
  l'effet de convolution est utilisée par lui. Les inserts et les éléments de chaîne se réordonnent
  par glisser-déposer.
  **Recherche** : chaque liste d'effets ou de plugins a un champ de recherche (sans accents ni
  majuscules, sur le nom, la catégorie et la description ; Entrée = premier résultat).
  **Automation** : le bouton **A** d'une piste (ou du master) choisit la courbe affichée (volume,
  panoramique, muet, tout paramètre d'insert ; clic droit sur un bouton d'effet = sa courbe).
  Clic sur la piste = nouveau point, glisser = déplacer, double-clic ou clic droit sur un point =
  supprimer (Ctrl+glisser sélectionne toujours). « Écrire l'automation » enregistre les mouvements
  des boutons pendant la lecture. Le tampon audio (256 à 4096) et la charge DSP sont dans la barre
  de transport.
- **Generate** : bruitages (synthé procédural instantané ou AudioLDM), musique (ACE-Step 1.5 :
  chanson, remix, retouche d'une section, écriture de paroles), voix (Piper CPU, Qwen3-TTS,
  Fish Speech S2 Pro, ou un preset sauvegardé). Chaque génération peut passer par un workflow de
  post-traitement et s'ajoute automatiquement à l'éditeur.
- **Effets** (106) : compresseur, **compresseur vintage (opto / VCA / FET / vari-mu)**, expandeur,
  noise gate, limiteur, **maximiseur à anticipation**, compresseur multibande, **EQ dynamique**,
  de-esser, modeleur de transitoires ; EQ paramétrique 8 bandes, EQ graphique 10 bandes, tilt, passe-haut/bas,
  passe-bande, coupe-bande, plateaux, cloche, filtre ladder, auto-wah, filtre LFO ; réverbérations
  (JUCE, hall/plaque/pièce/chambre/cathédrale/ressort par réponse impulsionnelle, convolution sur
  fichier, **shimmer**, **gated**), délai, délai ping-pong, délai multi-tap, **délai à bande**, **délai au
  tempo**, **double délai G/D**, **délai inversé**, Haas ;
  chorus, **chorus ensemble**, **doubleur**, flanger, phaser, vibrato, trémolo, auto-pan, modulateur en
  anneau, **décaleur de fréquence**, **cabine rotative**, **résonateur**, **transposition temps réel**,
  **octaveur / sub-bass** ; saturation bande, lampes, overdrive, fuzz, repli d'onde, exciter,
  **ampli guitare / basse** (clean, crunch, lead, bass + baffles 1x12/2x12/4x12/1x15), **baffle** seul,
  **saturation multibande**, distorsion, écrêtage, bitcrush, réducteur d'échantillonnage, téléphone,
  vinyle, **cassette**, codecs GSM/MP3 ; vocoder, **filtre de formants**, **correction de hauteur
  (auto-tune, gamme au choix)**, **harmoniseur** ; **stutter** et **trance gate** (motif 16 pas, tempo) ; largeur stéréo, **imageur
  stéréo 3 bandes**, **mid/side**, panoramique, balance, basses en mono, **outil de canaux** ;
  **anti-ronflement**, **dé-clic**, **réduction de bruit spectrale temps réel** (profil appris ou
  adaptatif, 75 ms de latence) ; analyseur, **loudness-mètre LUFS**, **générateur de test**,
  **dither** ; utilitaires et effets
  sur fichier entier (normalisation, LUFS, fondus, inversion, transposition, time stretch, réduction
  de bruit, rééchantillonnage...).
- **Workflows** : chaîne d'effets natifs et de plugins VST3, réglage « prolonger jusqu'au silence »
  (la reverb ou le delay ne sont jamais coupés), sauvegarde/chargement, application à la sélection,
  à toutes les pistes ou à des fichiers par lot.
- **Plugins** : dossiers VST3, scan dans un processus séparé (un plugin qui plante ne ferme pas
  l'application), catalogue, ouverture de la fenêtre du plugin (l'état est conservé dans le workflow).
- **Models** : moteurs (PyTorch CUDA, Piper) et modèles : état, taille, source, licence,
  Télécharger / Reprendre / Réparer / Vérifier / Supprimer, acceptation personnelle des licences.
- **Updates** : mises à jour GitHub de l'application (dépôt à configurer), des sources moteur
  (révisions épinglées) avec retour arrière ; les poids suivent leur propre catalogue.
- **Options** : langue (anglais par défaut, français), thème (gris moyen, gris clair, nuit ambrée,
  violet, bleu marine), densité (compacte ou confortable), taille du texte, licences,
  sauvegarde/chargement de configuration, stockage partagé.
- **Interface** : dessinée avec CyUI, la bibliothèque d'interface des logiciels Cy* (portage Python
  dans `app/gui/cyui`). Les barres d'outils sont des boutons-icônes avec une info-bulle qui nomme
  l'action et son raccourci (Espace, Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+Y, Ctrl+X/C/V, Suppr, H, F). La
  barre d'état en bas affiche le dernier message, les jobs en cours (progression, bouton pour
  annuler) et l'état du moteur audio ; les événements apparaissent aussi en notification.

## Traitement par lots d'une session (CLI / MCP, sans interface)

Préparez le projet dans l'éditeur (pistes de fond, une piste « emplacement » avec sa chaîne
d'inserts et son automation, inserts du master), enregistrez la session, puis pilotez-la par script :

- `batch_session` : rend la session une fois par son d'entrée ; chaque son remplace l'audio de la
  piste emplacement (sa chaîne, ses courbes, son gain et sa position sont conservés), le mixage est rendu
  avec la queue, puis le son suivant prend sa place. Sortie : un fichier par son dans le dossier choisi.
- `edit_session` : actions scriptées (ajouter / remplacer / supprimer une piste, poser une chaîne
  d'effets ou un workflow, régler le master, la queue), sauvegarde et rendu dans le même appel.

Exemple (Windows ; sous Linux `runtime/python/bin/python`, non exécuté par l'auteur) :

```powershell
.\runtime\python\Scripts\python.exe app\tool.py invoke batch_session --params "{\"session\": \"D:/x/data/sessions/modele\", \"inputs\": [\"D:/sons/a.wav\", \"D:/sons/b.wav\"], \"slot\": {\"track\": \"Voice\"}, \"output_dir\": \"D:/rendus\", \"suffix\": \"_mix\"}"
```

Les chemins d'entrée doivent être absolus. Détails et liste des actions : `app/README.md`.

## Voix : presets et annotations

Sauvegarder un preset après une génération conserve moteur, modèle et tous les paramètres
(référence vocale incluse, avec empreinte) : la même voix est régénérée avec un nouveau texte.
Qwen3-TTS (modèle 1.7B CustomVoice) accepte `[tone: chuchoté]` et `[pause: 500ms]` dans le texte.
L'opération `prepare_tts_text` (heuristique ou assistant Qwen3-1.7B) prépare ces annotations, ou
des tours de dialogue pour Fish Speech ; une IA pilotant l'outil par MCP peut le faire elle-même.

## Emplacements

- `data/models` : poids (déplacés depuis les anciens outils), `data/workflows`, `data/presets`,
  `data/sessions`, `data/jobs` (résultats de chaque job), `data/logs`, `data/reports` (preuves).
- `runtime/python` : Python privé de l'application ; `runtime/engines` : environnements moteurs ;
  `runtime/sources` : sources Fish Speech et ACE-Step épinglées.

## Licence

Le code de l'application (`app/`, lanceurs, documentation) est un logiciel libre sous **GNU GPL v3**
(fichier `LICENSE` à la racine), comme pedalboard/JUCE. Le SDK CyToolsCore 0.10.1 utilisé est sous
licence **MIT**, ce qui ne change pas la licence de l'application. Les moteurs et les poids des
modèles gardent leurs propres licences (onglet Options > licences, `app/licenses.json`).
Le dossier `LICENCES` (en anglais) accompagne chaque copie du logiciel : texte MIT du SDK,
liens vers les sources (`SOURCES.txt`) et notices des composants tiers.

## Limites connues

- Validé sous Windows 10 x64 avec une RTX 3090 uniquement. Linux : lanceur fourni, jamais exécuté.
- VST2 non pris en charge (pas de licence) ; ASIO non disponible (SDK Steinberg non détenu),
  lecture/enregistrement via WASAPI.
- Fish Speech et ACE-Step exigent un GPU NVIDIA ; Fish Speech ~20 Go de VRAM libre.
- 14 effets travaillent sur le fichier entier (transposition, time stretch, normalisation, fondus...)
  et ne sont pas proposés comme inserts ; ils restent disponibles sur une sélection et en workflow.
- Les plugins VST3 en insert tournent dans le processus de l'interface pour être entendus en temps
  réel : un plugin qui plante ferme l'application (le scan et la fenêtre du plugin restent isolés).

Guide développeur, commandes CLI/MCP et tests : `app/README.md`.
