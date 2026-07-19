# claude-speak v2 — Hook Stop + résumé strict

Date : 2026-07-19
Statut : validé (design approuvé en session de brainstorming)

## Problème

La v1 (moniteur de fond qui surveille les JSONL) est inutilisable en pratique :

1. **Repli catastrophique** : sans marqueur de résumé détecté, la réponse
   entière est lue. C'est le cas le plus fréquent, et le pire possible.
2. **Marqueur instable** : l'extraction accepte des dizaines de variantes de
   libellés (« Résumé TTS: », « Résumé vocal: »...) pour compenser la dérive
   du modèle. Course sans fin.
3. **Heuristiques de flux fragiles** : debounce 2 s, gap de 1 s pour deviner
   les appels d'outils, accumulation de chunks. Lectures en plein milieu de
   tour, résumés ratés quand le marqueur tombe dans un autre chunk.

## Principe directeur v2

**Le TTS ne lit jamais rien d'autre qu'un résumé explicitement marqué.**

- Fin de réponse détectée par le hook `Stop` de Claude Code (timing exact,
  fourni par le produit — zéro heuristique).
- Marqueur strict : la forme HTML `<!-- TTS_SUMMARY ... TTS_SUMMARY -->`
  uniquement. Aucune variante de libellé n'est reconnue.
- Pas de marqueur → **silence total**. Pas de repli, pas de phrase générique,
  pas de blocage du tour pour forcer un résumé.

## Architecture

### Composant central : `speak.py` (un seul fichier, ~200 lignes)

Installé dans `~/.claude/tools/speak.py`. Deux modes :

#### `speak.py hook` — appelé par le hook `Stop`

Entrée : JSON du hook sur stdin (`transcript_path`, `cwd`, ...).

1. Vérifie les drapeaux pause : `~/.claude/projects/<enc>/speech-paused`
   (projet, `<enc>` dérivé de `cwd`) puis `~/.claude/speech-paused` (global).
   Pause → sortie 0 immédiate.
2. Lit le transcript JSONL, extrait le texte du **dernier message assistant**
   (concaténation des blocs `text` du dernier `message.id` assistant).
3. Cherche le marqueur strict (regex unique, tolérante uniquement aux
   espaces/retours à la ligne autour du contenu) :
   `<!--\s*TTS_SUMMARY\s*(.*?)\s*TTS_SUMMARY\s*-->` (DOTALL).
4. Absent ou contenu vide → sortie 0 silencieuse.
5. Présent → résout la voix (projet > global > défaut), écrit le résumé
   dans un fichier temporaire, lance `speak.py say <fichier>` en
   **processus détaché** (le texte passe par fichier, jamais par argv —
   évite les problèmes de quoting/longueur sous Windows) et sort
   immédiatement (le hook ne bloque jamais l'interface).

#### `speak.py say` — synthèse et lecture

1. Nettoyage minimal du résumé (retire décorations markdown résiduelles
   `**`/`` ` ``, compresse les blancs). Le résumé est censé être déjà propre.
1b. Lit le texte depuis le fichier temporaire passé en argument, puis le
    supprime.
2. Synthèse edge-tts → mp3 temporaire.
3. **Verrou fichier inter-sessions** (`~/.claude/speech-playing.lock`) :
   si une autre lecture est en cours, attend qu'elle finisse (avec timeout
   de sécurité ~60 s) avant de jouer. Pas de voix superposées.
4. Lecture : MCI (Windows), `afplay` (macOS), `ffplay` (Linux).
5. Supprime le fichier temporaire.

`speak.py` expose aussi les fonctions `synthesize(text, voice, rate, path)`
et `play(path)` importables — utilisées par l'UI web pour la pré-écoute.

### Enregistrement du hook

Dans `~/.claude/settings.json` :

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/tools/speak.py hook"}
        ]
      }
    ]
  }
}
```

(Sous Windows : `python` au lieu de `python3` ; l'installateur gère la
différence.) Seul l'événement `Stop` est enregistré — pas `SubagentStop`.

## Configuration

Fichiers-drapeaux, inchangés par rapport à la v1 (compatibilité `/speak`) :

| Fichier | Rôle |
|---|---|
| `~/.claude/speech-paused` | pause globale |
| `~/.claude/projects/<enc>/speech-paused` | pause par projet |
| `~/.claude/speech-voice` | voix globale |
| `~/.claude/projects/<enc>/speech-voice` | voix par projet |

Encodage `<enc>` : chemin du CWD avec `:`, `\`, `/` remplacés par `-`
(identique à Claude Code et à la v1).

- Voix par défaut : `fr-FR-RemyMultilingualNeural` (multilingue — lit
  correctement français et anglais).
- Débit : `+10%` par défaut, surchargeable par la variable d'environnement
  `CC_SPEAK_RATE`.
- Supprimé : `speech-snippet`, `speech-preamble` (modes intro),
  backend OpenAI, tout réglage de debounce.

## Skill `/speak`

Simplifié : `on`, `off` (et bascule sans argument), `status`,
`voice <nom>`, `voice reset`, `voices`. Les sous-commandes
`snippet`/`preamble` disparaissent. Le skill continue de manipuler
directement les fichiers-drapeaux (aucun redémarrage nécessaire — le hook
relit la config à chaque réponse).

## Interface web (conservée, adaptée)

`configure.py` + `settings.html` sont conservés pour la navigation dans les
400+ voix, la pré-écoute audio et les réglages pause/voix par projet.
Adaptations :

- L'import de `cc-speak.py` est remplacé par l'import des fonctions
  `synthesize`/`play` de `speak.py`.
- Les API et éléments d'UI de start/stop du moniteur sont **supprimés**
  (plus de moniteur, plus de PID files). L'UI n'affiche plus d'état
  « monitor running ».
- Les réglages snippet/preamble sont retirés de l'UI s'ils y figurent.
- Le reste (liste des projets, pause/voix, pré-écoute, CSRF) est inchangé.

## Installation

`install.sh` (Linux/macOS) et `install.ps1` (Windows) :

1. Vérifient Python 3.8+ et installent `edge-tts` si absent
   (`pip install edge-tts`) ; sous Linux, signalent si `ffplay` manque.
2. Copient `speak.py`, `configure.py`, `settings.html` vers
   `~/.claude/tools/`.
3. Installent le skill dans `~/.claude/skills/speak/SKILL.md`.
4. **Fusionnent** l'entrée hook `Stop` dans `~/.claude/settings.json` sans
   écraser les hooks existants (parse JSON, ajoute si absente ; sauvegarde
   `settings.json.bak` avant modification).
5. Affichent le bloc d'instructions TTS à conserver dans le CLAUDE.md
   global (le bloc actuel de l'utilisateur est déjà conforme — le README
   documente le snippet canonique pour les nouveaux PC).

## Gestion d'erreurs

Règle absolue : **le hook ne casse jamais Claude Code.**

- Toute exception dans le mode hook → sortie code 0, silencieuse.
- Échec réseau edge-tts, lecteur audio absent → abandon silencieux de la
  lecture (une seule tentative, pas de retry).
- Journal optionnel : si `~/.claude/speech-debug` existe (fichier-drapeau),
  les erreurs sont tracées dans `~/.claude/tools/speak.log` pour diagnostic.
  Sans le drapeau, aucun fichier de log n'est écrit.
- Verrou de lecture : timeout ~60 s puis le verrou est considéré périmé et
  repris (un crash pendant une lecture ne bloque pas les suivantes).

## Suppressions (restent dans l'historique git)

`claude-speak.py` (moniteur JSONL), `cc-speak.py` (moteur TTS ~1000 lignes),
`Start-ClaudeWithSpeech.ps1`, modes snippet/preamble, backend OpenAI,
`__pycache__/`. Le README est réécrit pour la v2.

## Tests

- **Unitaires** (pytest, sans réseau ni audio) :
  - extraction du dernier message assistant depuis des transcripts JSONL
    réels (multi-lignes, blocs tool_use intercalés, message scindé sur
    plusieurs lignes de même `message.id`) ;
  - extraction du marqueur strict : présent, absent, vide, multiligne,
    plusieurs marqueurs (le dernier gagne), libellés v1 (« Résumé TTS: »)
    qui ne doivent PLUS matcher ;
  - résolution pause/voix (projet > global > défaut) ;
  - nettoyage minimal du résumé.
- **Intégration manuelle** : script de bout en bout qui simule l'entrée
  stdin du hook sur un transcript de test et vérifie que l'audio part
  (validation à l'oreille sur les deux PC).

## Critères de succès

1. Plus jamais une réponse complète lue à voix haute.
2. Aucune lecture en plein milieu d'un tour (le hook ne se déclenche
   qu'à la fin).
3. Réponse sans marqueur = silence, sans erreur visible.
4. `/speak off` coupe instantanément, `/speak voice` change la voix à la
   réponse suivante.
5. Deux sessions simultanées ne parlent jamais en même temps.
