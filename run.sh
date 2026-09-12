#!/bin/bash
set -eu

CONFIG_FILE="/data/options.json"
NGINX_CONFIG="/etc/nginx/http.d/ingress.conf"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERREUR: fichier de configuration introuvable (${CONFIG_FILE})"
    exit 1
fi

CONSOLES=$(jq -c '.consoles // []' "$CONFIG_FILE")
COUNT=$(echo "$CONSOLES" | jq 'length')

if [ "$COUNT" -eq 0 ]; then
    echo "Aucune console configurée - l'application démarre en mode configuration"
fi

{
    # ---- Table de correspondance cookie -> backend (IP:PORT de la console) ----
    echo 'map $cookie_ma3_console $ma3_backend {'
    echo '    default "";'

    IDX=0
    echo "$CONSOLES" | jq -c '.[]' | while IFS= read -r CONSOLE; do
        IP=$(echo "$CONSOLE" | jq -r '.ip')
        PORT=$(echo "$CONSOLE" | jq -r '.port')
        echo "    \"${IDX}\" \"${IP}:${PORT}\";"
        IDX=$((IDX + 1))
    done

    echo '}'

    # ---- Serveur : tout est proxyfié à la RACINE (essentiel : le Web Remote
    # grandMA3 construit ses URLs, notamment le WebSocket, en chemin absolu
    # depuis la racine du domaine ; le servir sous un sous-chemin comme /c0/
    # casse la connexion WebSocket). La console affichée dépend d'un cookie. ----
    cat <<'NGINX'

server {
    listen 8099;

    # Nécessaire car proxy_pass utilise une variable ($ma3_backend) : nginx
    # doit pouvoir la "résoudre", même si c'est déjà une IP littérale.
    resolver 127.0.0.11 valid=10s;

    location /api/ {
        proxy_pass http://127.0.0.1:5000/api/;
        proxy_http_version 1.1;
        proxy_read_timeout 30s;
    }

    location = /__selector__ {
        internal;
        proxy_pass http://127.0.0.1:5000/;
        proxy_http_version 1.1;
    }

    location / {
        if ($ma3_backend = "") {
            rewrite ^ /__selector__ last;
        }

        proxy_pass http://$ma3_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $ma3_backend;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
        proxy_set_header Accept-Encoding "";

        sub_filter 'ws://' 'wss://';
        sub_filter 'serverURI="wss://"+window.location.host+"/?ma=1"' 'serverURI="wss://"+window.location.host+"$http_x_ingress_path/?ma=1"';
        sub_filter '</body>' '<a href="#" onclick="document.cookie=&#39;ma3_console=; Max-Age=0; path=/&#39;;location.href=&#39;/&#39;;return false;" style="position:fixed;bottom:16px;right:16px;z-index:99999;background:#222;color:#fff;padding:10px 16px;border-radius:8px;font-family:sans-serif;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.4);">🏠 Sélecteur</a></body>';
        sub_filter_once off;
        sub_filter_types text/html application/javascript text/javascript;
    }
}
NGINX
} > "$NGINX_CONFIG"

echo "================================"
echo "MA3 Web Remote"
echo "Consoles configurées : $COUNT"
echo "================================"

# Démarre le backend Python (page de sélection + API + OSC) en arrière-plan
python3 /app.py &

# Attend que le backend soit prêt avant de démarrer nginx
for i in $(seq 1 20); do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',5000))" 2>/dev/null; then
        echo "Backend Python prêt."
        break
    fi
    sleep 0.5
done

exec nginx -g "daemon off;"
