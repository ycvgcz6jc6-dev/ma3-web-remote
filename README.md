# MA3 Web Remote — Add-on Home Assistant

## Installation

1. Copie le dossier `ma3-web-remote/` dans ton dossier d'add-ons locaux
   (généralement `/addons/` sur ton installation HA, visible via l'add-on
   "Samba" ou "File editor").
2. Dans HA : **Paramètres > Modules complémentaires > Boutique des modules
   complémentaires > ⋮ > Dépôts d'add-ons locaux**, actualise, l'add-on
   "MA3 Web Remote" doit apparaître.
3. Installe-le, configure tes consoles dans l'onglet **Configuration**, puis démarre-le.
4. Accepte la demande de permission d'accès à l'API Home Assistant si elle
   apparaît (nécessaire pour publier l'état des consoles).

## Configuration

```yaml
consoles:
  - name: "Console FOH"
    ip: "10.0.0.10"
    port: 8080        # port du Web Remote grandMA3 (http)
    osc_port: 8000     # port OSC d'entrée configuré sur la console
    osc_prefix: ""     # laisse vide sauf si tu as mis un préfixe custom (ex: "gma3")
    icon: ""           # URL d'une image/logo, sinon icône par défaut 🎛️
```

## Côté console grandMA3 (indispensable pour l'envoi de commandes)

Pour que la console accepte les commandes envoyées par l'add-on :

1. Menu **Setup > In & Out > OSC**
2. **Enable Input** = activé
3. Sur la ligne OSCData concernée : **Receive** = Yes, **Receive CMD** = Yes
4. Vérifie que le port configuré correspond à `osc_port` dans l'add-on (8000 par défaut)

Sans "Receive CMD" activé, la console reçoit le message OSC mais n'exécute rien.

## Accès à distance (Nabu Casa)

Une fois l'add-on démarré, il apparaît comme un panneau dans la sidebar HA.
Il est accessible via ton URL Nabu Casa exactement comme le reste de
l'interface HA — pas besoin d'ouvrir de port supplémentaire, l'ingress s'en
charge.

## Intégration dans des automatisations HA

L'add-on expose son API en interne sur le réseau Docker de HA (pas besoin de
passer par l'ingress pour ça). Ajoute ceci à ta `configuration.yaml` :

```yaml
rest_command:
  ma3_send_command:
    url: "http://local-grandma3-remote:5000/api/send"
    method: POST
    content_type: "application/json"
    payload: '{"index": {{ index }}, "command": "{{ command }}"}'
```

> Le nom d'hôte `local-grandma3-remote` correspond au slug `grandma3_remote`
> défini dans `config.yaml`, préfixé par `local-` puisque l'add-on est
> installé localement. Si jamais ça ne répond pas depuis une automatisation,
> vérifie le nom exact du conteneur dans **Paramètres > Système > Modules
> complémentaires** (ou logs Supervisor).

Exemple d'automatisation : envoyer "Go+ Sequence 1" à la Console 1
(index 0) quand une scène se déclenche :

```yaml
automation:
  - alias: "Lancer la séquence 1 sur MA3"
    trigger:
      - platform: state
        entity_id: input_boolean.lancer_show
        to: "on"
    action:
      - service: rest_command.ma3_send_command
        data:
          index: 0
          command: "Go+ Sequence 1"
```

Tu peux aussi t'en servir directement dans un script ou une scène Lovelace
avec un bouton.

## État des consoles dans HA

L'add-on publie automatiquement, toutes les 30 secondes, un `binary_sensor`
par console :

```
binary_sensor.ma3_console_foh   (on = joignable, off = injoignable)
```

Ajoute-le sur ton dashboard comme n'importe quel autre capteur.

## Note technique : pourquoi tout est servi à la racine (`/`)

Le Web Remote grandMA3 construit certaines de ses URLs internes (notamment
sa connexion WebSocket) en chemin absolu depuis la racine du domaine,
sans tenir compte d'un éventuel sous-dossier. C'est pour ça que l'add-on
sert **chaque console à la racine `/`**, en choisissant le bon backend via
un cookie (`ma3_console`) plutôt que via une URL du type `/c0/`, `/c1/`.
Si tu vois une version d'un autre outil (IA ou autre) qui propose de
préfixer les consoles par un chemin, sache que ça casse la connexion
WebSocket de grandMA3 — évite cette approche.

## Dépannage

- **Page blanche / logo HA bloqué** : regarde les logs de l'add-on
  (Paramètres > Modules complémentaires > MA3 Web Remote > Journal). Le
  script affiche "Backend Python prêt." avant de lancer nginx ; si ce
  message n'apparaît jamais, le backend a un souci de démarrage.
- **"Injoignable" pour une console qui fonctionne** : vérifie que HA et la
  console sont sur le même réseau (ou qu'une route existe entre les deux) et
  que le port configuré est bien celui du Web Remote (souvent 8080).
- **La commande OSC ne fait rien** : vérifie "Receive CMD" côté console
  (voir plus haut) — c'est la cause la plus fréquente.
