"""
discord_notify -- CTFd Plugin
============================
Notifica en Discord:
  * Cada vez que alguien resuelve un reto  (webhook de solves)
  * El primer blood de cada reto           (webhook de first blood)

Configuracion disponible en /admin/discord
"""

from __future__ import annotations

import threading
import time
from typing import Optional
import requests as _requests

from flask import Blueprint, request, render_template_string, session
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only
from CTFd.models import Solves, db


# ─────────────────────────────────────────────────────────────────────────────
# Claves de configuración persistidas en la DB de CTFd
# ─────────────────────────────────────────────────────────────────────────────
CFG_SOLVE_WEBHOOK          = "discord_solve_webhook"
CFG_BLOOD_WEBHOOK          = "discord_blood_webhook"
CFG_SOLVE_ENABLED          = "discord_solve_enabled"
CFG_BLOOD_ENABLED          = "discord_blood_enabled"
CFG_CTF_NAME               = "discord_ctf_name"
CFG_FOOTER                 = "discord_footer"
CFG_SCOREBOARD_ENABLED     = "discord_scoreboard_enabled"
CFG_SCOREBOARD_WEBHOOK     = "discord_scoreboard_webhook"
CFG_SCOREBOARD_INTERVAL    = "discord_scoreboard_interval"   # minutos

# ─────────────────────────────────────────────────────────────────────────────
# Scheduler de scoreboard (hilo daemon)
# ─────────────────────────────────────────────────────────────────────────────
_scoreboard_stop = threading.Event()
_scoreboard_thread: Optional[threading.Thread] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _cfg(key, default=""):
    val = get_config(key)
    return val if val is not None else default


def _send_webhook(url: str, payload: dict):
    """Dispara el webhook en un hilo aparte para no bloquear la petición."""
    if not url:
        return

    def _post():
        try:
            _requests.post(url, json=payload, timeout=10)
        except Exception as exc:
            print(f"[discord_notify] Error enviando webhook: {exc}")

    threading.Thread(target=_post, daemon=True).start()


def _is_first_blood(challenge_id: int) -> bool:
    """Devuelve True si aún no existe ningún Solve para este reto."""
    count = Solves.query.filter_by(challenge_id=challenge_id).count()
    # Se llama ANTES de que el solve actual se haya guardado, así count == 0
    return count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Builders de embed para Discord
# ─────────────────────────────────────────────────────────────────────────────
def build_solve_embed(user_name: str, team_name: Optional[str],
                      challenge_name: str, category: str,
                      points: int, solve_number: int) -> dict:
    ctf_name = _cfg(CFG_CTF_NAME, "CTF")
    footer   = _cfg(CFG_FOOTER, ctf_name)

    solver = user_name
    if team_name:
        solver = f"{user_name} ({team_name})"

    return {
        "embeds": [{
            "title": "✅  Reto Completado!",
            "color": 0x00FF88,          # verde neón
            "fields": [
                {"name": "👤 Solver",    "value": solver,         "inline": True},
                {"name": "🎯 Reto",      "value": challenge_name, "inline": True},
                {"name": "🗂️ Categoría", "value": category,       "inline": True},
                {"name": "💰 Puntos",    "value": str(points),    "inline": True},
                {"name": "🔢 Solve #",   "value": str(solve_number), "inline": True},
            ],
            "footer": {"text": footer},
        }]
    }


def build_first_blood_embed(user_name: str, team_name: Optional[str],
                             challenge_name: str, category: str,
                             points: int) -> dict:
    ctf_name = _cfg(CFG_CTF_NAME, "CTF")
    footer   = _cfg(CFG_FOOTER, ctf_name)

    solver = user_name
    if team_name:
        solver = f"{user_name} ({team_name})"

    return {
        "content": "@here 🩸 **FIRST BLOOD!**",
        "embeds": [{
            "title": "🩸  FIRST BLOOD!",
            "description": (
                f"**{solver}** ha sido el primero en resolver **{challenge_name}**!\n"
                f"Categoría: `{category}` · Puntos: `{points}`"
            ),
            "color": 0xFF0033,          # rojo sangre
            "footer": {"text": footer},
        }]
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scoreboard helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_top_standings(limit: int = 10) -> list[dict]:
    from CTFd.utils.config import is_teams_mode
    from CTFd.models import Teams, Users, Challenges
    from sqlalchemy import func

    if is_teams_mode():
        rows = (
            db.session.query(
                Teams.name,
                func.sum(Challenges.value).label("score"),
                func.count(Solves.id).label("solves"),
            )
            .join(Solves, Solves.team_id == Teams.id)
            .join(Challenges, Challenges.id == Solves.challenge_id)
            .filter(Teams.banned == False, Teams.hidden == False)
            .group_by(Teams.id)
            .order_by(func.sum(Challenges.value).desc())
            .limit(limit)
            .all()
        )
    else:
        rows = (
            db.session.query(
                Users.name,
                func.sum(Challenges.value).label("score"),
                func.count(Solves.id).label("solves"),
            )
            .join(Solves, Solves.user_id == Users.id)
            .join(Challenges, Challenges.id == Solves.challenge_id)
            .filter(Users.banned == False, Users.hidden == False, Users.type == "user")
            .group_by(Users.id)
            .order_by(func.sum(Challenges.value).desc())
            .limit(limit)
            .all()
        )
    return [{"name": r.name, "score": int(r.score or 0), "solves": r.solves} for r in rows]


def build_scoreboard_embed(standings: list[dict]) -> dict:
    ctf_name = _cfg(CFG_CTF_NAME, "CTF")
    footer   = _cfg(CFG_FOOTER, ctf_name)
    interval = int(_cfg(CFG_SCOREBOARD_INTERVAL, 60))

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, entry in enumerate(standings):
        prefix = medals[i] if i < 3 else f"`{i+1}.`"
        lines.append(f"{prefix} **{entry['name']}** — {entry['score']} pts ({entry['solves']} solves)")

    description = "\n".join(lines) if lines else "_Sin actividad todavía._"

    return {
        "embeds": [{
            "title": f"🏆 Scoreboard — {ctf_name}",
            "description": description,
            "color": 0xF1C40F,
            "footer": {"text": f"{footer} · próxima actualización en {interval} min"},
        }]
    }


def _send_scoreboard_notification(app):
    with app.app_context():
        try:
            if str(_cfg(CFG_SCOREBOARD_ENABLED)) != "1":
                return
            url = _cfg(CFG_SCOREBOARD_WEBHOOK)
            if not url:
                return
            standings = _get_top_standings(10)
            payload = build_scoreboard_embed(standings)
            _requests.post(url, json=payload, timeout=10)
        except Exception as exc:
            print(f"[discord_notify] Error en scoreboard: {exc}")


def _scoreboard_loop(app):
    last_sent = 0.0
    while not _scoreboard_stop.is_set():
        _scoreboard_stop.wait(60)           # revisa cada minuto
        if _scoreboard_stop.is_set():
            break
        try:
            with app.app_context():
                if str(_cfg(CFG_SCOREBOARD_ENABLED)) != "1":
                    continue
                interval_secs = int(_cfg(CFG_SCOREBOARD_INTERVAL, 60)) * 60
            now = time.time()
            if now - last_sent >= interval_secs:
                _send_scoreboard_notification(app)
                last_sent = now
        except Exception as exc:
            print(f"[discord_notify] Scheduler error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Event Listener for Solves
# ─────────────────────────────────────────────────────────────────────────────
from sqlalchemy import event

def _is_first_blood_event(challenge_id: int) -> bool:
    """Devuelve True si este es el primer solve del reto."""
    # Dado que estamos en 'after_insert', el solve actual ya está en la BD.
    # Por lo tanto, si el count es 1, es el First Blood.
    count = Solves.query.filter_by(challenge_id=challenge_id).count()
    return count == 1

@event.listens_for(Solves, 'after_insert')
def notify_discord_on_solve(mapper, connection, target):
    """
    Se ejecuta después de que un Solve es insertado en la BD.
    `target` es la instancia de Solves.
    """
    try:
        from CTFd.models import Users, Teams, Challenges
        # Cargar relaciones si es necesario
        user = Users.query.get(target.user_id)
        team = Teams.query.get(target.team_id) if target.team_id else None
        challenge = Challenges.query.get(target.challenge_id)

        if not user or not challenge:
            return

        is_blood = _is_first_blood_event(target.challenge_id)
        solve_number = Solves.query.filter_by(challenge_id=target.challenge_id).count()
        # ── First blood ──────────────────────────────────────────────────────────
        if str(_cfg(CFG_BLOOD_ENABLED)) == "1":
            blood_url = _cfg(CFG_BLOOD_WEBHOOK)
            if blood_url and is_blood:
                payload = build_first_blood_embed(
                    user_name=user.name,
                    team_name=team.name if team else None,
                    challenge_name=challenge.name,
                    category=challenge.category or "Sin categoría",
                    points=challenge.value or 0,
                )
                _send_webhook(blood_url, payload)

        # ── Solve normal ─────────────────────────────────────────────────────────
        if str(_cfg(CFG_SOLVE_ENABLED)) == "1":
            solve_url = _cfg(CFG_SOLVE_WEBHOOK)
            if solve_url:
                payload = build_solve_embed(
                    user_name=user.name,
                    team_name=team.name if team else None,
                    challenge_name=challenge.name,
                    category=challenge.category or "Sin categoría",
                    points=challenge.value or 0,
                    solve_number=solve_number,
                )
                _send_webhook(solve_url, payload)
    except Exception as exc:
        print(f"[discord_notify] Error en event hook: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Página de administración
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_TEMPLATE = """
{% extends "admin/base.html" %}
{% block content %}
<div class="jumbotron">
  <div class="container">
    <h1>🎮 Discord <span style="color:var(--primary)">Notify</span> Plugin</h1>
    <p class="lead">Configura los webhooks de Discord para anunciar solves y first bloods en tu servidor.</p>
  </div>
</div>
<div class="container">
  {% if saved %}
  <div class="alert alert-success">✅ Configuración guardada correctamente.</div>
  {% endif %}
  <form method="POST" id="config-form">
    <input type="hidden" name="nonce" value="{{ nonce }}">
    
    <div class="row">
      <!-- Solves -->
      <div class="col-md-6 mb-4">
        <div class="card h-100">
          <div class="card-header bg-success text-white">✅ Notificación de Solves</div>
          <div class="card-body">
            <div class="form-check mb-3">
              <input type="checkbox" class="form-check-input" name="solve_enabled" id="solve_enabled" value="1" {% if solve_enabled %}checked{% endif %}>
              <label class="form-check-label" for="solve_enabled">Activar notificaciones de solve</label>
            </div>
            <div class="form-group">
              <label>Webhook URL (canal de solves)</label>
              <input type="url" name="solve_webhook" class="form-control" placeholder="https://discord.com/api/webhooks/..." value="{{ solve_webhook }}">
              <small class="form-text text-muted">En Discord: Editar Canal → Integraciones → Webhooks → Nuevo Webhook</small>
            </div>
          </div>
        </div>
      </div>
      
      <!-- First Blood -->
      <div class="col-md-6 mb-4">
        <div class="card h-100">
          <div class="card-header bg-danger text-white">🩸 Notificación de First Blood</div>
          <div class="card-body">
            <div class="form-check mb-3">
              <input type="checkbox" class="form-check-input" name="blood_enabled" id="blood_enabled" value="1" {% if blood_enabled %}checked{% endif %}>
              <label class="form-check-label" for="blood_enabled">Activar anuncio de first blood</label>
            </div>
            <div class="form-group">
              <label>Webhook URL (canal de first blood)</label>
              <input type="url" name="blood_webhook" class="form-control" placeholder="https://discord.com/api/webhooks/..." value="{{ blood_webhook }}">
              <small class="form-text text-muted">El mensaje incluirá @here para notificar al canal.</small>
            </div>
          </div>
        </div>
      </div>
      
      <!-- Scoreboard periódico -->
      <div class="col-md-12 mb-4">
        <div class="card">
          <div class="card-header bg-warning text-dark">🏆 Scoreboard Periódico</div>
          <div class="card-body">
            <div class="form-check mb-3">
              <input type="checkbox" class="form-check-input" name="scoreboard_enabled" id="scoreboard_enabled" value="1" {% if scoreboard_enabled %}checked{% endif %}>
              <label class="form-check-label" for="scoreboard_enabled">Activar anuncios periódicos de scoreboard</label>
            </div>
            <div class="form-group mb-3">
              <label>Webhook URL (canal de scoreboard)</label>
              <input type="url" name="scoreboard_webhook" class="form-control" placeholder="https://discord.com/api/webhooks/..." value="{{ scoreboard_webhook }}">
            </div>
            <div class="form-group">
              <label>Intervalo de envío <small>(minutos, mínimo 10)</small></label>
              <input type="number" name="scoreboard_interval" class="form-control" min="10" max="1440" value="{{ scoreboard_interval }}" style="max-width:160px">
              <small class="form-text text-muted">El scoreboard se enviará automáticamente cada N minutos mientras el CTF esté activo.</small>
            </div>
          </div>
        </div>
      </div>

      <!-- General -->
      <div class="col-md-12 mb-4">
        <div class="card">
          <div class="card-header">⚙️ General</div>
          <div class="card-body">
            <div class="form-group">
              <label>Nombre del CTF <small>(aparece en los embeds)</small></label>
              <input type="text" name="ctf_name" class="form-control" placeholder="HackL4bs CTF 2025" value="{{ ctf_name }}">
            </div>
            <div class="form-group">
              <label>Footer de los embeds</label>
              <input type="text" name="footer" class="form-control" placeholder="HackL4bs CTF · hackl4bs.io" value="{{ footer }}">
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <button type="submit" class="btn btn-primary float-right">💾 Guardar configuración</button>
  </form>
  <br><br>
  
  <div class="card mt-5">
    <div class="card-header">🧪 Test de Webhooks</div>
    <div class="card-body">
      <p>Envía un mensaje de prueba a los webhooks configurados. <strong>Guarda primero</strong> antes de probar.</p>
      <button type="button" class="btn btn-secondary" onclick="testWebhooks()">Enviar mensaje de prueba</button>
      <div id="test-result" class="alert mt-3" style="display:none;"></div>
    </div>
  </div>
</div>

<script>
async function testWebhooks() {
  const el = document.getElementById('test-result');
  el.style.display = 'block';
  el.className = 'alert alert-info';
  el.textContent = '⏳ Enviando...';
  try {
    const r = await fetch('/admin/discord/test', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'CSRF-Token': '{{ nonce }}' },
      body: JSON.stringify({}) });
    const d = await r.json();
    if (d.ok) {
      el.className = 'alert alert-success';
      el.textContent = '✅ ' + d.message;
    } else {
      el.className = 'alert alert-danger';
      el.textContent = '❌ ' + d.message;
    }
  } catch(e) {
    el.className = 'alert alert-danger';
    el.textContent = '❌ Error de red: ' + e;
  }
}
</script>
{% endblock %}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Entry-point requerido por CTFd
# ─────────────────────────────────────────────────────────────────────────────
def load(app):
    global _scoreboard_thread, _scoreboard_stop

    # Inicia el scheduler de scoreboard
    _scoreboard_stop.clear()
    _scoreboard_thread = threading.Thread(
        target=_scoreboard_loop, args=(app,), daemon=True, name="discord-scoreboard"
    )
    _scoreboard_thread.start()

    bp = Blueprint("discord_notify", __name__)

    # ── Admin: página de configuración ───────────────────────────────────────
    @bp.route("/admin/discord", methods=["GET", "POST"])
    @admins_only
    def discord_admin():
        saved = False
        if request.method == "POST":
            set_config(CFG_SOLVE_WEBHOOK,       request.form.get("solve_webhook", "").strip())
            set_config(CFG_BLOOD_WEBHOOK,        request.form.get("blood_webhook", "").strip())
            set_config(CFG_SOLVE_ENABLED,        "1" if request.form.get("solve_enabled") else "0")
            set_config(CFG_BLOOD_ENABLED,        "1" if request.form.get("blood_enabled") else "0")
            set_config(CFG_CTF_NAME,             request.form.get("ctf_name", "").strip())
            set_config(CFG_FOOTER,               request.form.get("footer", "").strip())
            set_config(CFG_SCOREBOARD_WEBHOOK,   request.form.get("scoreboard_webhook", "").strip())
            set_config(CFG_SCOREBOARD_ENABLED,   "1" if request.form.get("scoreboard_enabled") else "0")
            interval = request.form.get("scoreboard_interval", "60").strip()
            set_config(CFG_SCOREBOARD_INTERVAL,  str(max(10, int(interval or 60))))
            saved = True

        return render_template_string(
            ADMIN_TEMPLATE,
            saved=saved,
            nonce=session.get("nonce", ""),
            solve_webhook=_cfg(CFG_SOLVE_WEBHOOK),
            blood_webhook=_cfg(CFG_BLOOD_WEBHOOK),
            solve_enabled=str(_cfg(CFG_SOLVE_ENABLED)) == "1",
            blood_enabled=str(_cfg(CFG_BLOOD_ENABLED)) == "1",
            ctf_name=_cfg(CFG_CTF_NAME),
            footer=_cfg(CFG_FOOTER),
            scoreboard_webhook=_cfg(CFG_SCOREBOARD_WEBHOOK),
            scoreboard_enabled=str(_cfg(CFG_SCOREBOARD_ENABLED)) == "1",
            scoreboard_interval=_cfg(CFG_SCOREBOARD_INTERVAL, "60"),
        )

    # ── Admin: endpoint de test ───────────────────────────────────────────────
    @bp.route("/admin/discord/test", methods=["POST"])
    @admins_only
    def discord_test():
        from flask import jsonify

        errors = []
        sent = []

        ctf_name = _cfg(CFG_CTF_NAME, "CTF")
        footer   = _cfg(CFG_FOOTER, ctf_name)

        test_payload = {
            "embeds": [{
                "title": "🧪 Test de Discord Notify",
                "description": (
                    f"El plugin **Discord Notify** está correctamente configurado "
                    f"para **{ctf_name}**.\n\n"
                    "¡Los anuncios de solves y first blood funcionarán correctamente! 🎉"
                ),
                "color": 0x7289DA,
                "footer": {"text": footer},
            }]
        }

        for label, url_key in [
            ("Solve Webhook", CFG_SOLVE_WEBHOOK),
            ("Blood Webhook", CFG_BLOOD_WEBHOOK),
        ]:
            url = _cfg(url_key)
            if url:
                try:
                    r = _requests.post(url, json=test_payload, timeout=8)
                    if r.status_code in (200, 204):
                        sent.append(label)
                    else:
                        errors.append(f"{label}: HTTP {r.status_code}")
                except Exception as e:
                    errors.append(f"{label}: {e}")

        if not sent and not errors:
            return jsonify({"ok": False,
                            "message": "No hay webhooks configurados. Guarda la configuración primero."})
        if errors:
            return jsonify({"ok": False, "message": " | ".join(errors)})
        return jsonify({"ok": True,
                        "message": f"Mensajes enviados correctamente a: {', '.join(sent)}"})

    app.register_blueprint(bp)

    print("[discord_notify] Plugin cargado. Admin en /admin/discord")
