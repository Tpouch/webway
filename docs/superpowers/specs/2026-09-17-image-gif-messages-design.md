# Envoi d'images / GIFs dans le chat — design

Date : 2026-09-17

## Contexte et objectif

Webway est un chat TCP en TUI curses (`client.py`) avec un serveur relais
minimal (`server.py`), sans dépendance externe (bibliothèque standard
Python uniquement — cf. README). L'objectif est de permettre à un
utilisateur d'envoyer une image ou un GIF depuis un fichier local ou une
URL, et que ce média s'affiche (et s'anime, pour un GIF) directement dans
le panneau de chat de tous les clients connectés.

## Décisions actées

- **Dépendance** : Pillow est autorisée comme dépendance optionnelle,
  ajoutée à `requirements.txt`. Elle n'est nécessaire que pour *envoyer*
  une image (import différé, déclenché uniquement par `/img`) — recevoir
  et afficher une image ne demande aucune dépendance en plus de curses.
- **GIFs animés** : les GIFs sont rejoués en boucle dans le panneau de
  chat, intégrés à la boucle de rendu existante à 30 fps.
- **Commande** : `/img <chemin-ou-url>`. Accepte un chemin de fichier
  local ou une URL `http(s)://`.
- **Rendu** : demi-blocs `▀` (2 pixels par cellule de terminal : avant-plan
  = pixel du haut, arrière-plan = pixel du bas), couleurs mappées sur les
  256 couleurs xterm les plus proches, avec repli sur 8 couleurs de base
  si le terminal ne supporte pas 256 couleurs.
- **Historique / rejoue** : un client qui rejoint après l'envoi d'un GIF
  ne voit que la première frame (statique), pas l'animation complète.

## Architecture retenue (approche A)

Décodage et redimensionnement côté client émetteur (avec Pillow) ; le
serveur ne fait que relayer/valider/mémoriser la charge utile, sans
aucune logique image ; chaque client récepteur ré-échantillonne et
affiche la grille de pixels reçue à sa propre taille de terminal.

Deux alternatives ont été écartées :
- **Décodage côté serveur** : casserait le principe actuel d'un serveur
  relais sans dépendance, pour un bénéfice minime (Pillow resterait de
  toute façon nécessaire quelque part).
- **Protocoles image natifs du terminal (Sixel / Kitty / iTerm2)** :
  qualité photo supérieure, mais incompatibles avec le modèle de rendu
  actuel, qui redessine tout l'écran via curses à 30 fps ; curses ne sait
  pas positionner ni effacer ces images, ce qui casserait le défilement
  et le rafraîchissement de l'interface.

## Protocole

Nouveau type de message, envoyé client → serveur → broadcast, au même
niveau que `msg` / `action` :

```json
{
  "type": "img",
  "id": 42,
  "username": "Alice",
  "ts": 1234567890.0,
  "name": "cat.gif",
  "w": 96,
  "h": 64,
  "frames": [
    {"data": "<base64, w*h*3 octets RGB bruts>", "delay_ms": 80},
    ...
  ]
}
```

- Les pixels sont envoyés en RGB 24 bits bruts, sans quantification ni
  palette côté émetteur. Chaque client récepteur choisit lui-même la
  couleur terminal la plus proche au moment de l'affichage, et
  ré-échantillonne la grille à la taille de son propre panneau — deux
  clients avec des terminaux de tailles différentes affichent donc
  correctement la même image.
- `frames` contient une seule entrée pour une image statique.
- Le champ `id` suit la même séquence globale que les messages texte : une
  image peut donc être la cible des réactions existantes (`F5`..`F8`),
  exactement comme un message `msg`/`action`.

## Envoi (`/img <chemin-ou-url>`)

1. Résolution de la source :
   - Chemin local : doit exister, être un fichier régulier, taille ≤ 8
     Mo.
   - URL : seuls les schémas `http://` et `https://` sont acceptés (`
     file://` et autres sont rejetés explicitement, pour éviter une
     lecture arbitraire du système de fichiers du client). Récupération
     via `urllib.request` avec timeout de 10 s et lecture en flux
     interrompue si elle dépasse 8 Mo.
2. Import différé de Pillow (`from PIL import Image, ImageSequence`) ;
   si l'import échoue, message d'erreur local clair (« Pillow n'est pas
   installé — nécessaire pour envoyer des images : pip install Pillow »)
   et la commande s'arrête là, sans affecter le reste de l'application.
3. Décodage avec `Image.open`. Si le format n'est pas reconnu ou le
   fichier est corrompu, message d'erreur local clair.
4. Si l'image est animée (`getattr(im, "is_animated", False)`), itération
   des frames via `ImageSequence.Iterator`, plafonnée à 40 frames (les
   frames en trop sont ignorées).
5. Chaque frame est convertie en RGB puis redimensionnée (en conservant
   le ratio d'aspect) pour tenir dans une grille de référence de 120×80
   pixels maximum. Ce redimensionnement borne la bande passante et la
   mémoire ; l'échantillonnage fin à la taille d'affichage réelle se fait
   côté client récepteur (voir Rendu).
6. Les octets RGB bruts (`im.tobytes()`) de chaque frame sont encodés en
   base64.
7. Envoi du message `img` via le mécanisme d'envoi existant (JSON
   newline-delimited, comme les autres types de messages).

Toute erreur à n'importe quelle étape (fichier introuvable, URL
inaccessible ou schéma interdit, fichier trop gros, Pillow absent, image
corrompue) produit un message d'erreur local dans le chat (type `info`
existant), sans crasher le client ni envoyer quoi que ce soit au serveur.

## Serveur

Changement minimal :

- Validation défensive du message `img` reçu, dans le même esprit que le
  troncage existant de `text[:1000]` : `w` et `h` ≤ 200, nombre de
  `frames` ≤ 40, longueur des données base64 de chaque frame cohérente
  avec `w * h * 3`. Un message hors bornes est silencieusement ignoré
  (même style que les autres validations dans `handle_client`).
- `broadcast()` doit pouvoir stocker dans `HISTORY` une charge utile
  différente de celle diffusée en direct : on ajoute un paramètre optionnel
  (ex. `history_payload=None`, par défaut égal à `payload`). Pour un
  message `img`, le serveur diffuse la charge complète (toutes les
  frames) en direct, mais mémorise dans `HISTORY` une version tronquée à
  la première frame uniquement.
- Le compteur `STATS["messages"]` est incrémenté comme pour `msg`/`action`.

## Rendu côté client

- Nouveau type d'entrée dans l'état du chat (`ChatState`), `"img"`,
  portant : `username`, `frames` (liste de `(largeur, hauteur, bytes RGB
  décodés)` + `delay_ms`), index de frame courant, horodatage de la
  dernière avance de frame, nom/légende.
- Décodage base64 → bytes fait une fois à la réception, pas à chaque
  frame de rendu.
- Intégration à la boucle de rendu à 30 fps existante : à chaque tick,
  l'index de frame de chaque entrée `img` avance si le temps écoulé
  dépasse `delay_ms` de la frame courante, puis boucle à la fin de la
  liste de frames.
- Affichage : la grille de pixels de la frame courante est
  ré-échantillonnée (plus proche voisin) à la largeur disponible dans le
  panneau de chat, avec une hauteur plafonnée (ex. 16 lignes de
  terminal, soit 32 pixels grâce aux demi-blocs) pour qu'une image ne
  monopolise pas tout le panneau.
- Chaque cellule de sortie est un caractère `▀` : la couleur de premier
  plan vient du pixel du haut, la couleur d'arrière-plan du pixel du bas.
  Chaque couleur RGB est mappée vers la couleur xterm-256 la plus proche
  (cube 6×6×6 + rampe de gris). Les paires de couleurs curses
  `(fg, bg)` nécessaires sont allouées à la demande depuis un pool réservé
  et borné (cache LRU), pour ne jamais dépasser `curses.COLOR_PAIRS`.
- Repli : si `curses.COLORS < 256`, quantification sur les 8 couleurs de
  base seulement (fidélité réduite mais fonctionnel).
- Un client qui n'a pas Pillow installé peut recevoir, afficher et voir
  animer normalement les images des autres — Pillow ne sert qu'à
  l'envoi.

## Limites et constantes

| Constante | Valeur |
| --- | --- |
| Taille max de la source (fichier ou URL) | 8 Mo |
| Timeout de récupération HTTP(S) | 10 s |
| Schémas d'URL autorisés | `http`, `https` |
| Grille de référence max à l'encodage | 120×80 px |
| Frames max par GIF | 40 |
| Hauteur max à l'affichage | 16 lignes de terminal (32 px) |
| `w`/`h` max acceptés côté serveur | 200 |

## Documentation

Comme chaque commande existante est déjà listée à deux endroits, `/img`
doit suivre le même traitement : ajout à `COMMAND_LINES` dans
`client.py` (panneau `/help`) et à la table des commandes du `README.md`.

## Tests (manuels, pas de suite automatisée existante)

Le projet n'a actuellement aucun test automatisé ; la validation reste
manuelle, dans le même esprit que le reste du projet :

1. Deux clients locaux : envoyer une image statique puis un GIF animé
   local avec `/img`, vérifier que les deux s'affichent et que le GIF
   s'anime chez les deux.
2. Un troisième client qui rejoint après l'envoi du GIF ne voit que la
   première frame, figée.
3. Sans Pillow installé : `/img` échoue proprement avec un message
   d'installation, le reste de l'application continue de fonctionner.
4. Chemin inexistant, fichier dépassant 8 Mo, URL `file://` : rejetés
   côté client avec un message d'erreur clair, rien n'est envoyé au
   serveur.
5. Redimensionner le terminal pendant qu'une image/un GIF est affiché(e)
   ne doit pas crasher, l'image se ré-échantillonne à la nouvelle
   largeur.
