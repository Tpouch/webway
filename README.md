# webway

Un chat de terminal sur TCP/IP, avec une TUI curses **animée** : écran d'accueil, particules,
pluie Matrix, indicateurs de frappe en direct, réactions et thèmes de couleurs.

Aucune dépendance externe — bibliothèque standard Python uniquement.

## Utilisation

Lancer le serveur (sur la machine hôte) :

```
./run_server.sh [port]
```

Le port par défaut est `5555`.

Se connecter en tant que client (sur chaque machine) :

```
./run_client.sh <ip-serveur> <port> <ton-pseudo>
```

Exemple :

```
./run_client.sh 192.168.1.42 5555 Alice
```

Les deux scripts créent un `.venv`, installent `requirements.txt` et lancent l'application.

## Animations

- **Écran d'accueil** : logo ASCII révélé lettre par lettre en arc-en-ciel, barre d'onde et
  confettis pendant que la connexion s'établit (une touche pour passer).
- **Rendu continu à 30 fps** : tout bouge en permanence, même sans nouveau message.
- **Arrivée des messages** : glissement horizontal, flash, et liseré coloré qui s'estompe.
- **Confettis et feux d'artifice** : particules avec gravité, par-dessus toute l'interface.
- **Pluie Matrix** : colonnes de caractères en fond du panneau de chat (`F2`).
- **Mode arc-en-ciel** : tes propres messages défilent en dégradé animé (`F3`).
- **Indicateur de frappe** : « Bob tape... » animé sur la bordure du chat, et un `✎` qui pulse
  à côté de son pseudo dans la liste des participants.
- **Toasts** : notifications glissantes en haut à droite (arrivées, départs, mentions).
- **Flash de mention** : le cadre de l'écran clignote et le terminal bipe quand ton pseudo
  est cité.
- **Sparkline d'activité** : histogramme animé des messages des 20 dernières secondes.
- **En-tête vivant** : titre arc-en-ciel, spinner, latence réseau mesurée en direct, horloge.
- **Défilement fluide** : le scroll est interpolé, pas saccadé.
- **Nouveaux venus** : leur pseudo clignote quelques secondes dans la liste.

## Fonctionnalités

- Historique rejoué : un client qui arrive reçoit les 200 derniers évènements du salon.
- Réactions sur le dernier message (`F5`..`F8` → ★ ♥ ☺ ⚡), diffusées à tout le monde.
- Latence affichée en continu (ping/pong applicatif).
- 5 thèmes de couleurs (`Ctrl+T`), couleur personnelle synchronisée (`Ctrl+K`).
- Édition de ligne complète : curseur, mots, historique de saisie, complétion de pseudo.
- Un bot serveur qui répond quand on écrit `@bot`.
- Statistiques du serveur à la demande (`/stats`).

## Raccourcis

| Touche | Effet |
| --- | --- |
| `Entrée` | Envoyer le message |
| `Tab` | Compléter un pseudo |
| `↑` / `↓` | Rappeler un message envoyé |
| `←` `→` `Home` `End` | Déplacer le curseur |
| `Ctrl+W` / `Ctrl+U` | Effacer le mot précédent / la ligne |
| `PgUp` / `PgDn` | Défiler l'historique |
| `Ctrl+K` | Changer de couleur (visible par tous) |
| `Ctrl+T` | Thème suivant |
| `F1` | Panneau d'aide |
| `F2` | Pluie Matrix |
| `F3` | Mode arc-en-ciel |
| `F4` | Confettis |
| `F5`..`F8` | Réagir au dernier message (★ ♥ ☺ ⚡) |
| `Ctrl+C` | Quitter |

## Commandes

```
/me <texte>      action à la troisième personne
/confetti        lâcher de confettis
/fireworks       feu d'artifice
/matrix          pluie Matrix on/off
/rainbow         tes messages en arc-en-ciel
/theme           thème de couleurs suivant
/roll [NdM]      lancer de dés (défaut 1d6)
/flip            pile ou face
/shrug           ¯\_(ツ)_/¯
/users           qui est connecté
/stats           statistiques du serveur
/clear           vider l'affichage local
/quit            quitter
```
