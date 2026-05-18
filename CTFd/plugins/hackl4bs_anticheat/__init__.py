"""
HackL4bs Anti-Brute Force — Rate limiting en intentos de flags.

Lógica:
  - Ventana deslizante: si un usuario envía >= MAX_ATTEMPTS intentos incorrectos
    en WINDOW_SECONDS segundos, queda bloqueado LOCKOUT_SECONDS segundos.
  - Estado en memoria (se resetea al reiniciar CTFd).
  - Log persistente en DB de cada bloqueo.
  - Alerta opcional a Discord cuando alguien es bloqueado.
"""
import threading
import time
from collections import defaultdict
from datetime import datetime

import requests as _http
from flask import Blueprint, jsonify, render_template_string, request, session
from CTFd.models import db, Challenges, Users
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only
from CTFd.utils.user import get_current_user
from CTFd.plugins import register_plugin_assets_directory, register_plugin_script

# Claves de configuración
_CFG_ENABLED  = "anticheat_enabled"
_CFG_MAX      = "anticheat_max_attempts"
_CFG_WINDOW   = "anticheat_window_seconds"
_CFG_LOCKOUT  = "anticheat_lockout_seconds"
_CFG_WEBHOOK  = "anticheat_discord_webhook"

# Estado en memoria
_mu      = threading.Lock()
_attempts: dict = defaultdict(list)   # (uid, cid) → [timestamp, ...]
_lockouts: dict = {}                   # (uid, cid) → expiry_timestamp


# ── Modelo ─────────────────────────────────────────────────────────────────────
class AnticheatLockoutLog(db.Model):
    __tablename__ = "hackl4bs_lockout_log"
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    challenge_id = db.Column(db.Integer, nullable=True)
    ip           = db.Column(db.String(64))
    attempts     = db.Column(db.Integer)
    locked_at    = db.Column(db.DateTime, default=datetime.utcnow)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _cfg_int(key, default):
    try:
        v = get_config(key)
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _enabled():
    return get_config(_CFG_ENABLED) != "0"


def _get_lockout(uid, cid):
    key = (uid, cid)
    with _mu:
        until = _lockouts.get(key)
        if until is None:
            return None
        if time.time() < until:
            return until
        del _lockouts[key]
    return None


def _record_wrong(uid, cid, ip, app):
    """Registra un intento incorrecto y bloquea si se supera el umbral."""
    max_a   = _cfg_int(_CFG_MAX,     10)
    window  = _cfg_int(_CFG_WINDOW,  300)
    lockout = _cfg_int(_CFG_LOCKOUT, 600)
    now     = time.time()
    key     = (uid, cid)

    with _mu:
        # Limpiar intentos fuera de la ventana deslizante
        _attempts[key] = [t for t in _attempts[key] if now - t < window]
        _attempts[key].append(now)
        count = len(_attempts[key])

        if count >= max_a and key not in _lockouts:
            _lockouts[key] = now + lockout
            # Log y Discord en thread separado para no bloquear la respuesta
            threading.Thread(
                target=_persist_lockout,
                args=(uid, cid, ip, count, app),
                daemon=True,
            ).start()
            return True
    return False


def _persist_lockout(uid, cid, ip, count, app):
    with app.app_context():
        try:
            db.session.add(AnticheatLockoutLog(
                user_id=uid, challenge_id=cid, ip=ip, attempts=count
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        webhook = get_config(_CFG_WEBHOOK) or get_config("discord_webhook_url")
        if not webhook:
            return
        try:
            u = Users.query.get(uid)
            c = Challenges.query.get(cid)
            lockout_secs = _cfg_int(_CFG_LOCKOUT, 600)
            mins = lockout_secs // 60
            _http.post(webhook, json={
                "embeds": [{
                    "title": "🚨 Anti-Brute Force — Lockout",
                    "color": 0xFF4444,
                    "fields": [
                        {"name": "Usuario",  "value": f"`{u.name if u else uid}`",  "inline": True},
                        {"name": "Reto",     "value": f"*{c.name if c else cid}*",  "inline": True},
                        {"name": "Intentos", "value": str(count),                   "inline": True},
                        {"name": "IP",       "value": f"`{ip}`",                    "inline": True},
                        {"name": "Lockout",  "value": f"{mins} minutos",            "inline": True},
                    ],
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }, timeout=5)
        except Exception:
            pass


def _get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ── Plugin load ────────────────────────────────────────────────────────────────
def load(app):
    with app.app_context():
        db.create_all()

    bp = Blueprint("hackl4bs_anticheat", __name__)
    register_plugin_assets_directory(app, base_path="/plugins/hackl4bs_anticheat/assets/")
    register_plugin_script("/plugins/hackl4bs_anticheat/assets/anticheat.js")

    # ── before_request: bloquear si el usuario está en lockout ────────────────
    @app.before_request
    def _anticheat_gate():
        if not _enabled():
            return
        if request.method != "POST" or "/api/v1/challenges/attempt" not in request.path:
            return

        user = get_current_user()
        if not user:
            return

        # Buffering explícito del body para que el route handler pueda releerlo
        request.get_data()
        data = request.get_json(silent=True) or {}
        chal_id = data.get("challenge_id")
        if not chal_id:
            return

        until = _get_lockout(user.id, int(chal_id))
        if not until:
            return

        remaining = max(0, int(until - time.time()))
        mins, secs = divmod(remaining, 60)
        msg = (
            f"Demasiados intentos fallidos. Intenta de nuevo en {mins}m {secs}s."
            if mins else
            f"Demasiados intentos fallidos. Intenta de nuevo en {secs}s."
        )
        return jsonify({
            "success": False,
            "data": {
                "status": "ratelimit",
                "message": msg,
                "remaining_seconds": remaining,
            }
        }), 429

    # ── after_request: registrar intentos incorrectos ─────────────────────────
    @app.after_request
    def _anticheat_track(response):
        if not _enabled():
            return response
        if request.method != "POST" or "/api/v1/challenges/attempt" not in request.path:
            return response
        try:
            user = get_current_user()
            if not user:
                return response
            req_data = request.get_json(silent=True) or {}
            chal_id = req_data.get("challenge_id")
            if not chal_id:
                return response

            resp_data = response.get_json(silent=True) or {}
            status = resp_data.get("data", {}).get("status", "")

            if status == "incorrect":
                ip = _get_client_ip()
                _record_wrong(user.id, int(chal_id), ip, app)
            elif status in ("correct", "already_solved"):
                # Limpiar penalizaciones al resolver correctamente
                key = (user.id, int(chal_id))
                with _mu:
                    _attempts.pop(key, None)
                    _lockouts.pop(key, None)
        except Exception:
            pass
        return response

    # ── API: estado de lockout del usuario actual ─────────────────────────────
    @bp.route("/api/hackl4bs/anticheat/status/<int:chal_id>")
    def lockout_status(chal_id):
        user = get_current_user()
        if not user:
            return jsonify({"locked": False})
        until = _get_lockout(user.id, chal_id)
        if until:
            remaining = max(0, int(until - time.time()))
            return jsonify({"locked": True, "remaining_seconds": remaining})
        key = (user.id, chal_id)
        with _mu:
            count = len(_attempts.get(key, []))
        return jsonify({
            "locked": False,
            "attempts": count,
            "max_attempts": _cfg_int(_CFG_MAX, 10),
        })

    # ── Admin: configuración y dashboard ─────────────────────────────────────
    @bp.route("/admin/hackl4bs_anticheat", methods=["GET", "POST"])
    @admins_only
    def admin_config():
        saved = False
        if request.method == "POST":
            set_config(_CFG_ENABLED, request.form.get("enabled", "1"))
            set_config(_CFG_MAX,     request.form.get("max_attempts", "10"))
            set_config(_CFG_WINDOW,  request.form.get("window", "300"))
            set_config(_CFG_LOCKOUT, request.form.get("lockout", "600"))
            set_config(_CFG_WEBHOOK, request.form.get("webhook", ""))
            saved = True

        # Lockouts activos en memoria
        now = time.time()
        active = []
        with _mu:
            for (uid, cid), until in list(_lockouts.items()):
                if now < until:
                    u = Users.query.get(uid)
                    c = Challenges.query.get(cid)
                    rem = int(until - now)
                    m, s = divmod(rem, 60)
                    active.append({
                        "username":  u.name if u else f"user#{uid}",
                        "challenge": c.name if c else f"chal#{cid}",
                        "remaining": f"{m}m {s}s",
                    })

        # Top abusadores por intentos en ventana actual
        top_abusers = []
        with _mu:
            window = _cfg_int(_CFG_WINDOW, 300)
            cutoff = now - window
            for (uid, cid), timestamps in _attempts.items():
                recent = [t for t in timestamps if t > cutoff]
                if len(recent) >= 3:
                    u = Users.query.get(uid)
                    c = Challenges.query.get(cid)
                    top_abusers.append({
                        "username":  u.name if u else f"user#{uid}",
                        "challenge": c.name if c else f"chal#{cid}",
                        "count":     len(recent),
                    })
        top_abusers.sort(key=lambda x: -x["count"])

        # Historial de lockouts
        logs = AnticheatLockoutLog.query.order_by(
            AnticheatLockoutLog.locked_at.desc()
        ).limit(50).all()
        log_data = []
        for lg in logs:
            u = Users.query.get(lg.user_id) if lg.user_id else None
            c = Challenges.query.get(lg.challenge_id) if lg.challenge_id else None
            log_data.append({
                "username":  u.name if u else "?",
                "challenge": c.name if c else "?",
                "ip":        lg.ip or "?",
                "attempts":  lg.attempts,
                "locked_at": lg.locked_at.strftime("%Y-%m-%d %H:%M"),
            })

        return render_template_string("""
{% extends "admin/base.html" %}
{% block content %}
<div class="jumbotron">
  <div class="container">
    <h1>🛡️ Anti-Brute Force <span style="color:var(--primary)">HackL4bs</span></h1>
    <p class="lead">Rate limiting en intentos de flags por usuario/reto.</p>
  </div>
</div>
<div class="container">
  {% if saved %}<div class="alert alert-success">✅ Configuración guardada</div>{% endif %}

  <div class="row">
    <!-- Configuración -->
    <div class="col-md-5">
      <div class="card mb-4"><div class="card-body">
        <h5 class="card-title">Configuración</h5>
        <form method="POST">
          <input type="hidden" name="nonce" value="{{ nonce }}">
          <div class="form-group">
            <div class="form-check">
              <input type="checkbox" class="form-check-input" name="enabled" value="1"
                     id="enabledChk" {{ 'checked' if enabled != '0' }}>
              <label class="form-check-label" for="enabledChk">Habilitado</label>
            </div>
          </div>
          <div class="form-group">
            <label>Intentos incorrectos antes del lockout</label>
            <input type="number" name="max_attempts" value="{{ max_attempts }}"
                   class="form-control" min="1" max="100">
          </div>
          <div class="form-group">
            <label>Ventana de tiempo (segundos)</label>
            <input type="number" name="window" value="{{ window }}"
                   class="form-control" min="30">
            <small class="text-muted">Ventana en que se acumulan los intentos</small>
          </div>
          <div class="form-group">
            <label>Duración del bloqueo (segundos)</label>
            <input type="number" name="lockout" value="{{ lockout }}"
                   class="form-control" min="30">
          </div>
          <div class="form-group">
            <label>Discord Webhook (alertas de lockout)</label>
            <input type="text" name="webhook" value="{{ webhook }}"
                   class="form-control"
                   placeholder="https://discord.com/api/webhooks/...">
            <small class="text-muted">Deja vacío para usar el webhook del plugin discord_notify</small>
          </div>
          <button type="submit" class="btn btn-primary">Guardar</button>
        </form>
      </div></div>
    </div>

    <div class="col-md-7">
      <!-- Lockouts activos -->
      <div class="card mb-4"><div class="card-body">
        <h5 class="card-title">Lockouts activos ahora ({{ active|length }})</h5>
        {% if active %}
        <table class="table table-sm mb-0">
          <thead><tr><th>Usuario</th><th>Reto</th><th>Tiempo restante</th></tr></thead>
          <tbody>
            {% for l in active %}
            <tr><td>{{ l.username }}</td><td>{{ l.challenge }}</td>
                <td><span class="badge badge-danger">{{ l.remaining }}</span></td></tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}
        <p class="text-muted mb-0">Ningún lockout activo ahora mismo.</p>
        {% endif %}
      </div></div>

      <!-- Top intentos en ventana actual -->
      {% if top_abusers %}
      <div class="card mb-4"><div class="card-body">
        <h5 class="card-title">Intentos recientes (ventana actual)</h5>
        <table class="table table-sm mb-0">
          <thead><tr><th>Usuario</th><th>Reto</th><th>Intentos</th></tr></thead>
          <tbody>
            {% for a in top_abusers %}
            <tr>
              <td>{{ a.username }}</td>
              <td>{{ a.challenge }}</td>
              <td><span class="badge badge-warning">{{ a.count }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div></div>
      {% endif %}
    </div>
  </div>

  <!-- Historial -->
  <h5>Historial de lockouts (últimos 50)</h5>
  <div class="table-responsive">
    <table class="table table-sm table-striped">
      <thead>
        <tr><th>Usuario</th><th>Reto</th><th>IP</th><th>Intentos</th><th>Fecha</th></tr>
      </thead>
      <tbody>
        {% for l in logs %}
        <tr>
          <td>{{ l.username }}</td>
          <td>{{ l.challenge }}</td>
          <td><code>{{ l.ip }}</code></td>
          <td>{{ l.attempts }}</td>
          <td><small class="text-muted">{{ l.locked_at }}</small></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
""",
            enabled=get_config(_CFG_ENABLED) or "1",
            max_attempts=_cfg_int(_CFG_MAX, 10),
            window=_cfg_int(_CFG_WINDOW, 300),
            lockout=_cfg_int(_CFG_LOCKOUT, 600),
            webhook=get_config(_CFG_WEBHOOK) or "",
            active=active,
            top_abusers=top_abusers,
            logs=log_data,
            nonce=session.get("nonce"),
        )

    app.register_blueprint(bp)
    print("[HackL4bs Anticheat] Plugin cargado.")
