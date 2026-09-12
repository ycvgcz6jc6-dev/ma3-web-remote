#!/usr/bin/env python3
"""
Backend de l'add-on MA3 Web Remote.
- Sert la page de sélection des consoles (avec icônes et mini-dashboard d'état)
- Expose une API pour envoyer des commandes OSC ("/cmd") aux consoles grandMA3
- Vérifie périodiquement l'accessibilité de chaque console et publie l'état
  dans Home Assistant sous forme de binary_sensor
- Écoute uniquement sur 127.0.0.1:5000 : ce port n'est jamais exposé
  publiquement, nginx (ingress) fait proxy dessus pour l'UI, et les
  automatisations HA peuvent l'appeler directement via le nom interne
  de l'add-on sur le réseau Docker (ex: http://local-grandma3-remote:5000/api/send)
"""

import json
import os
import re
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPTIONS_FILE = "/data/options.json"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
SUPERVISOR_API = "http://supervisor/core/api"


def load_consoles():
    try:
        with open(OPTIONS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    consoles = data.get("consoles", [])
    for c in consoles:
        c.setdefault("osc_port", 8000)
        c.setdefault("osc_prefix", "")
        c.setdefault("icon", "")
    return consoles


def check_reachable(ip, port, timeout=1.5):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_osc_message(address, string_arg):
    """Construit un message OSC 1.0 minimal : adresse + type tag ',s' + argument string."""

    def pad(data: bytes) -> bytes:
        data += b"\x00"
        while len(data) % 4:
            data += b"\x00"
        return data

    return pad(address.encode()) + pad(b",s") + pad(string_arg.encode())


def send_osc_command(ip, osc_port, prefix, command):
    """Envoie une ligne de commande grandMA3 via OSC (/cmd), en UDP.

    Nécessite côté console : In & Out > OSC > Enable Input + Receive + Receive CMD
    activés sur la ligne OSCData concernée.
    """
    address = f"{prefix}/cmd" if prefix else "/cmd"
    msg = build_osc_message(address, command)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(msg, (ip, osc_port))
    finally:
        sock.close()


def slugify(name, idx):
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return slug or f"console_{idx}"


def push_ha_state(entity_id, state, attributes):
    if not SUPERVISOR_TOKEN:
        return
    url = f"{SUPERVISOR_API}/states/{entity_id}"
    body = json.dumps({"state": state, "attributes": attributes}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"[HA API] Erreur envoi état {entity_id}: {exc}", flush=True)


def status_loop():
    while True:
        consoles = load_consoles()
        for idx, c in enumerate(consoles):
            online = check_reachable(c["ip"], c["port"])
            entity_id = f"binary_sensor.ma3_{slugify(c['name'], idx)}"
            push_ha_state(
                entity_id,
                "on" if online else "off",
                {
                    "friendly_name": f"MA3 {c['name']}",
                    "device_class": "connectivity",
                    "icon": "mdi:lightboard" if online else "mdi:lightboard-off",
                },
            )
        time.sleep(30)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MA3 Web Remote</title>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; background:#111; color:#fff; padding: 24px 16px 60px; }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  .subtitle {{ opacity:.65; margin-bottom: 28px; }}
  .console-card {{ display:flex; align-items:center; gap:14px; background:#1c1c1c; border:1px solid #333;
                   border-radius:12px; padding:14px 16px; margin-bottom:12px; }}
  .console-card img {{ width:40px; height:40px; object-fit:contain; border-radius:6px; background:#000; }}
  .fallback-icon {{ width:40px; height:40px; display:flex; align-items:center; justify-content:center;
                     font-size:22px; background:#000; border-radius:6px; flex-shrink:0; }}
  .console-info {{ flex:1; min-width:0; }}
  .console-name {{ font-weight:600; font-size:17px; }}
  .status-dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; background:#666; }}
  .status-dot.on {{ background:#3ecf5e; }}
  .status-dot.off {{ background:#e5484d; }}
  .status-text {{ font-size:13px; opacity:.7; }}
  a.open-btn {{ background:#2a5bd7; color:#fff; text-decoration:none; padding:8px 14px; border-radius:8px;
                font-size:14px; white-space:nowrap; }}
  .cmd-section {{ margin-top: 32px; border-top: 1px solid #333; padding-top: 20px; }}
  .cmd-section h2 {{ font-size: 18px; margin-bottom: 10px; }}
  select, input[type=text] {{ width:100%; box-sizing:border-box; padding:10px; border-radius:8px; border:1px solid #444;
                               background:#1c1c1c; color:#fff; margin-bottom:10px; font-size:15px; }}
  button {{ background:#2a5bd7; color:#fff; border:none; padding:10px 18px; border-radius:8px; cursor:pointer; font-size:15px; }}
  #cmd-feedback {{ margin-top:8px; font-size:13px; opacity:.8; min-height:16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>MA3 Web Remote</h1>
  <div class="subtitle">Accès et contrôle des consoles grandMA3</div>

  <div id="consoles">{console_cards}</div>

  <div class="cmd-section">
    <h2>Envoyer une ligne de commande (OSC)</h2>
    <select id="cmd-console">{console_options}</select>
    <input type="text" id="cmd-text" placeholder="ex: Go+ Sequence 1">
    <button onclick="sendCommand()">Envoyer</button>
    <div id="cmd-feedback"></div>
  </div>
</div>

<script>
function selectConsole(idx) {{
  document.cookie = "ma3_console=" + idx + "; path=/; SameSite=Lax";
  location.reload();
}}

async function refreshStatus() {{
  try {{
    const res = await fetch('/api/status');
    const data = await res.json();
    data.forEach(c => {{
      const dot = document.getElementById('dot-' + c.index);
      const text = document.getElementById('status-' + c.index);
      if (dot) {{
        dot.classList.toggle('on', c.online);
        dot.classList.toggle('off', !c.online);
      }}
      if (text) text.textContent = c.online ? 'En ligne' : 'Injoignable';
    }});
  }} catch (e) {{ /* silencieux */ }}
}}

async function sendCommand() {{
  const idx = document.getElementById('cmd-console').value;
  const cmd = document.getElementById('cmd-text').value;
  const feedback = document.getElementById('cmd-feedback');
  if (!cmd) {{ feedback.textContent = 'Entre une commande.'; return; }}
  feedback.textContent = 'Envoi...';
  try {{
    const res = await fetch('/api/send', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{index: parseInt(idx), command: cmd}})
    }});
    const data = await res.json();
    feedback.textContent = data.ok ? 'Commande envoyée.' : ('Erreur : ' + data.error);
  }} catch (e) {{
    feedback.textContent = 'Erreur réseau.';
  }}
}}

refreshStatus();
setInterval(refreshStatus, 5000);
</script>
</body>
</html>
"""


def render_page(consoles):
    cards = []
    options = []
    for idx, c in enumerate(consoles):
        if c.get("icon"):
            icon_html = f'<img src="{c["icon"]}" alt="">'
        else:
            icon_html = '<div class="fallback-icon">🎛️</div>'
        cards.append(f"""
        <div class="console-card">
          {icon_html}
          <div class="console-info">
            <div class="console-name">{c['name']}</div>
            <div class="status-text"><span class="status-dot" id="dot-{idx}"></span><span id="status-{idx}">Vérification...</span></div>
          </div>
          <a class="open-btn" href="#" onclick="selectConsole({idx}); return false;">Ouvrir</a>
        </div>""")
        options.append(f'<option value="{idx}">{c["name"]}</option>')
    return PAGE_TEMPLATE.format(
        console_cards="".join(cards) or "<p>Aucune console configurée.</p>",
        console_options="".join(options),
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # évite de saturer les logs de l'add-on

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        consoles = load_consoles()
        if self.path.startswith("/api/consoles"):
            self._json(200, consoles)
        elif self.path.startswith("/api/status"):
            result = [
                {"index": idx, "name": c["name"], "online": check_reachable(c["ip"], c["port"])}
                for idx, c in enumerate(consoles)
            ]
            self._json(200, result)
        else:
            html = render_page(consoles).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    def do_POST(self):
        if self.path.startswith("/api/send"):
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                idx = int(payload["index"])
                command = str(payload["command"])
            except (KeyError, ValueError, json.JSONDecodeError):
                self._json(400, {"ok": False, "error": "requête invalide"})
                return

            consoles = load_consoles()
            if idx < 0 or idx >= len(consoles):
                self._json(404, {"ok": False, "error": "console inconnue"})
                return

            c = consoles[idx]
            try:
                send_osc_command(c["ip"], c["osc_port"], c["osc_prefix"], command)
                self._json(200, {"ok": True})
            except OSError as exc:
                self._json(500, {"ok": False, "error": str(exc)})
        else:
            self._json(404, {"ok": False, "error": "not found"})


if __name__ == "__main__":
    threading.Thread(target=status_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 5000), Handler)
    print("[app.py] Backend démarré sur 127.0.0.1:5000", flush=True)
    server.serve_forever()
