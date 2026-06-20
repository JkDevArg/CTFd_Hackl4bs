import os
import re
import threading
from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, request, render_template_string, session
from sqlalchemy import event
from sqlalchemy.exc import StatementError
from sqlalchemy.sql import text

from CTFd.models import Awards, Challenges, Solves, Teams, Users, db
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.user import get_current_user

# ── Config ─────────────────────────────────────────────────────────────────────
WHALEY_URL       = os.environ.get("WHALEY_URL",       "http://localhost:8001")
WHALEY_ADMIN_KEY = os.environ.get("WHALEY_ADMIN_KEY", "")
WHALEY_FLAG_PREFIX = os.environ.get("WHALEY_FLAG_PREFIX", "H4L")
DISCORD_WEBHOOK  = os.environ.get("DISCORD_WEBHOOK_URL", "")
SIEM_COLLECTOR_URL = os.environ.get("SIEM_COLLECTOR_URL", "http://host.docker.internal:9501")
SIEM_API_KEY       = os.environ.get("SIEM_API_KEY", "")
BAN_HOURS        = 4


def get_ban_hours() -> int:
    """Devuelve la duración del ban en horas (configurable desde el admin panel)."""
    stored = get_config("ban_hours")
    try:
        return max(1, int(stored)) if stored else BAN_HOURS
    except (ValueError, TypeError):
        return BAN_HOURS


def is_anticheat_enabled() -> bool:
    """Devuelve True si el anti-cheat está activo (por defecto sí)."""
    val = get_config("anticheat_enabled")
    if val is None:
        return True
    return str(val).lower() not in ("0", "false", "no", "off")


def _emit_siem_event(
    event_type: str,
    severity: str = "high",
    team: str = None,
    team_id: int = None,
    player: str = None,
    player_id: int = None,
    challenge: str = None,
    challenge_id: int = None,
    message: str = None,
    metadata: dict = None,
):
    """Envía un evento al collector del SIEM en background (no bloquea la request)."""
    def _send():
        try:
            payload = {
                "event_type":   event_type,
                "severity":     severity,
                "team":         team,
                "team_id":      team_id,
                "player":       player,
                "player_id":    player_id,
                "challenge":    challenge,
                "challenge_id": challenge_id,
                "message":      message,
                "metadata":     metadata or {},
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            headers = {"Content-Type": "application/json"}
            if SIEM_API_KEY:
                headers["X-Api-Key"] = SIEM_API_KEY
            requests.post(
                SIEM_COLLECTOR_URL + "/api/v1/event",
                json=payload,
                headers=headers,
                timeout=5,
            )
        except Exception as e:
            print(f"[Whaley→SIEM] Error emitiendo evento '{event_type}': {e}")
    threading.Thread(target=_send, daemon=True).start()


def get_whaley_url():
    url = get_config("whaley_url")
    return url.rstrip("/") if url else WHALEY_URL.rstrip("/")


# ── Inject snippet ──────────────────────────────────────────────────────────────
INJECT_SCRIPT = """
<script>
  window.__WHALEY_API__ = "/api/whaley";
</script>
<script defer src="/plugins/whaley_ctfd_plugin/assets/whaley.js"></script>
"""

ADMIN_PAGE = """
{% extends "admin/base.html" %}
{% block content %}
<style>
.badge-steal  { background:#dc3545; color:#fff; }
.badge-leak   { background:#fd7e14; color:#fff; }
.badge-noinstance { background:#ffc107; color:#000; }
.badge-manual { background:#6c757d; color:#fff; }
.badge-expired{ background:#dee2e6; color:#555; }
.badge-lifted { background:#198754; color:#fff; }
.reason-badge { font-size:0.75em; padding:2px 6px; border-radius:4px; white-space:nowrap; }
</style>
<div class="jumbotron">
  <div class="container">
    <h1>Whaley <span style="color:var(--primary)">Anti-Cheat</span></h1>
    <p class="lead mb-1">Panel de gestión de bans y configuración del plugin.</p>
    <span class="badge {{ 'badge-success' if anticheat_enabled else 'badge-danger' }}">
      Anti-cheat {{ 'ACTIVO' if anticheat_enabled else 'DESACTIVADO' }}
    </span>
  </div>
</div>
<div class="container">

  <!-- Tabs -->
  <ul class="nav nav-tabs mb-3" id="whaleyTabs">
    <li class="nav-item">
      <a class="nav-link active" data-toggle="tab" href="#tab-active">
        🚨 Bans activos
        {% if active_bans %}<span class="badge badge-danger ms-1">{{ active_bans|length }}</span>{% endif %}
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link" data-toggle="tab" href="#tab-history">📋 Historial</a>
    </li>
    <li class="nav-item">
      <a class="nav-link" data-toggle="tab" href="#tab-ban">⛔ Ban manual</a>
    </li>
    <li class="nav-item">
      <a class="nav-link" data-toggle="tab" href="#tab-config">⚙️ Configuración</a>
    </li>
  </ul>

  <div class="tab-content">

    <!-- ── Tab: Bans activos ── -->
    <div class="tab-pane active" id="tab-active">
      {% if active_bans %}
      <div class="mb-3 d-flex gap-2">
        <button id="unban-all-btn" class="btn btn-warning">
          🔓 Desbanear TODOS ({{ active_bans|length }})
        </button>
        <div id="unban-all-msg"></div>
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead class="table-dark">
            <tr>
              <th>Equipo</th>
              <th>Tipo</th>
              <th>Reto</th>
              <th>Equipo relacionado</th>
              <th>Motivo</th>
              <th>Flag</th>
              <th>Baneado (UTC)</th>
              <th>Tiempo restante</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {% for ban in active_bans %}
            <tr id="ban-row-{{ ban.id }}">
              <td><strong>{{ ban.team_name }}</strong></td>
              <td>
                {% if ban.reason_type == 'steal' %}
                  <span class="reason-badge badge-steal">🔴 Flag robada</span>
                {% elif ban.reason_type == 'leak' %}
                  <span class="reason-badge badge-leak">🟠 Flag filtrada</span>
                {% elif ban.reason_type == 'noinstance' %}
                  <span class="reason-badge badge-noinstance">🟡 Sin instancia</span>
                {% else %}
                  <span class="reason-badge badge-manual">⚫ Manual</span>
                {% endif %}
              </td>
              <td><small>{{ ban.challenge_name or '—' }}</small></td>
              <td><small>{{ ban.related_team_name or '—' }}</small></td>
              <td><small class="text-muted">{{ ban.reason }}</small></td>
              <td><code style="font-size:0.7em">{{ ban.offending_flag or '—' }}</code></td>
              <td><small>{{ ban.banned_at }}</small></td>
              <td><span class="badge badge-warning text-dark">{{ ban.remaining_str }}</span></td>
              <td>
                <button class="btn btn-sm btn-outline-success unban-btn"
                        data-id="{{ ban.id }}" data-name="{{ ban.team_name }}">
                  Desbanear
                </button>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <div class="alert alert-success">✅ No hay equipos baneados actualmente.</div>
      {% endif %}
    </div>

    <!-- ── Tab: Historial ── -->
    <div class="tab-pane" id="tab-history">
      {% if history_bans %}
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead class="table-secondary">
            <tr>
              <th>Equipo</th>
              <th>Tipo</th>
              <th>Reto</th>
              <th>Equipo relacionado</th>
              <th>Motivo</th>
              <th>Baneado (UTC)</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {% for ban in history_bans %}
            <tr>
              <td><strong>{{ ban.team_name }}</strong></td>
              <td>
                {% if ban.reason_type == 'steal' %}
                  <span class="reason-badge badge-steal">🔴 Robó flag</span>
                {% elif ban.reason_type == 'leak' %}
                  <span class="reason-badge badge-leak">🟠 Flag filtrada</span>
                {% elif ban.reason_type == 'noinstance' %}
                  <span class="reason-badge badge-noinstance">🟡 Sin instancia</span>
                {% else %}
                  <span class="reason-badge badge-manual">⚫ Manual</span>
                {% endif %}
              </td>
              <td><small>{{ ban.challenge_name or '—' }}</small></td>
              <td><small>{{ ban.related_team_name or '—' }}</small></td>
              <td><small class="text-muted">{{ ban.reason }}</small></td>
              <td><small>{{ ban.banned_at }}</small></td>
              <td>
                {% if ban.lifted_at %}
                  <span class="reason-badge badge-lifted">✅ Levantado {{ ban.lifted_at }}</span>
                {% else %}
                  <span class="reason-badge badge-expired">⏱ Expirado</span>
                {% endif %}
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <p class="text-muted">No hay historial de bans.</p>
      {% endif %}
    </div>

    <!-- ── Tab: Ban manual ── -->
    <div class="tab-pane" id="tab-ban">
      <div class="card" style="max-width:500px">
        <div class="card-header"><strong>Banear equipo manualmente</strong></div>
        <div class="card-body">
          <div class="mb-3">
            <label class="form-label">Equipo</label>
            <select id="manual-team-select" class="form-control">
              <option value="">— Seleccionar equipo —</option>
              {% for team in all_teams %}
              <option value="{{ team.id }}">{{ team.name }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label">Motivo</label>
            <input type="text" id="manual-reason" class="form-control"
                   placeholder="Descripción del motivo..." value="Ban manual por administrador">
          </div>
          <div class="mb-3">
            <label class="form-label">Duración (horas)</label>
            <input type="number" id="manual-hours" class="form-control"
                   value="{{ ban_hours }}" min="1" max="168" style="max-width:100px">
          </div>
          <button type="button" id="manual-ban-btn" class="btn btn-danger">⛔ Aplicar ban</button>
          <div id="manual-ban-msg" class="mt-2"></div>
        </div>
      </div>
    </div>

    <!-- ── Tab: Configuración ── -->
    <div class="tab-pane" id="tab-config">
      <div class="card" style="max-width:520px">
        <div class="card-header"><strong>Configuración del plugin</strong></div>
        <div class="card-body">
          <form method="POST">
            <input type="hidden" name="nonce" value="{{ nonce }}">
            <div class="mb-3">
              <label class="form-label"><strong>URL de Whaley</strong></label>
              <input type="text" name="whaley_url" value="{{ current_url }}"
                     class="form-control" placeholder="http://host.docker.internal:8001">
            </div>
            <div class="mb-3">
              <label class="form-label"><strong>Duración del ban (horas)</strong></label>
              <input type="number" name="ban_hours" value="{{ ban_hours }}"
                     class="form-control" min="1" max="168" style="max-width:120px">
            </div>
            <div class="mb-3">
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" name="anticheat_enabled"
                       id="anticheatToggle" value="1" {{ 'checked' if anticheat_enabled else '' }}>
                <label class="form-check-label" for="anticheatToggle">
                  <strong>Anti-cheat activo</strong>
                </label>
              </div>
              <small class="text-muted">Desactivar suspende todos los bans automáticos en tiempo real.</small>
            </div>
            <button type="submit" class="btn btn-primary">Guardar</button>
            <a href="?test=1" class="btn btn-outline-secondary ms-2">Probar conexión a Whaley</a>
          </form>
          {% if saved %}
          <div class="alert alert-success mt-3 mb-0">✅ Configuración guardada.</div>
          {% endif %}
          {% if conn_status %}
          <div class="alert {{ 'alert-success' if conn_ok else 'alert-danger' }} mt-3 mb-0">{{ conn_status }}</div>
          {% endif %}
        </div>
      </div>
    </div>

  </div><!-- /tab-content -->
</div>

<script>
function whaleyNonce() {
  if (window.init && window.init.csrfNonce) return window.init.csrfNonce;
  var m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.getAttribute('content') : '';
}
function whaleyFetch(url, opts, successCb, errEl) {
  var headers = {'Content-Type':'application/json','Accept':'application/json','CSRF-Token':whaleyNonce()};
  fetch(url, Object.assign({credentials:'same-origin', headers:headers}, opts))
  .then(function(r){
    if (!r.ok && r.status === 403) throw new Error('Acceso denegado (403) — recarga la página e intenta de nuevo');
    return r.json();
  })
  .then(function(d){
    if (d.success) {
      successCb(d);
    } else {
      var msg = d.message || 'Error desconocido';
      if (errEl) errEl.innerHTML = '<div class="alert alert-danger mt-2 mb-0">' + msg + '</div>';
      else alert('Error: ' + msg);
    }
  })
  .catch(function(e){
    if (errEl) errEl.innerHTML = '<div class="alert alert-danger mt-2 mb-0">' + e.message + '</div>';
    else alert('Error: ' + e.message);
  });
}

// Desbanear individual
document.querySelectorAll('.unban-btn').forEach(function(btn){
  btn.onclick = function(){
    var id   = btn.dataset.id;
    var name = btn.dataset.name;
    if (!confirm('¿Desbanear al equipo "' + name + '"?')) return;
    btn.disabled = true;
    var msg = document.createElement('div');
    whaleyFetch('/api/whaley/admin/red-flags/' + id + '/lift',
      {method:'POST'},
      function(d){
        var row = document.getElementById('ban-row-' + id);
        if (row) row.style.opacity = '0.4';
        btn.textContent = '✅ Desbaneado';
        setTimeout(function(){ location.reload(); }, 900);
      },
      msg
    );
    btn.parentNode.appendChild(msg);
  };
});

// Desbanear todos
var unbanAllBtn = document.getElementById('unban-all-btn');
if (unbanAllBtn) {
  unbanAllBtn.onclick = function(){
    if (!confirm('¿Desbanear a TODOS los equipos actualmente baneados?')) return;
    unbanAllBtn.disabled = true;
    var msg = document.getElementById('unban-all-msg');
    whaleyFetch('/api/whaley/admin/red-flags/lift-all',
      {method:'POST'},
      function(d){
        msg.innerHTML = '<div class="alert alert-success mb-0">✅ ' + d.message + '</div>';
        setTimeout(function(){ location.reload(); }, 1200);
      },
      msg
    );
  };
}

// Ban manual
var manualBtn = document.getElementById('manual-ban-btn');
if (manualBtn) {
  manualBtn.onclick = function(){
    var team_id = document.getElementById('manual-team-select').value;
    var reason  = document.getElementById('manual-reason').value.trim();
    var hours   = parseInt(document.getElementById('manual-hours').value);
    if (!team_id) { alert('Selecciona un equipo.'); return; }
    if (!reason)  { alert('Ingresa un motivo.'); return; }
    var teamName = document.getElementById('manual-team-select').selectedOptions[0].text;
    if (!confirm('¿Banear al equipo "' + teamName + '" por ' + hours + 'h?\nMotivo: ' + reason)) return;
    manualBtn.disabled = true;
    var msg = document.getElementById('manual-ban-msg');
    whaleyFetch('/api/whaley/admin/red-flags/ban',
      {method:'POST', body: JSON.stringify({team_id: team_id, reason: reason, hours: hours})},
      function(d){
        msg.innerHTML = '<div class="alert alert-success mb-0">✅ ' + d.message + '</div>';
        setTimeout(function(){ location.reload(); }, 1500);
      },
      msg
    );
  };
}

// Tabs con data-toggle
document.querySelectorAll('[data-toggle="tab"]').forEach(function(link){
  link.onclick = function(e){
    e.preventDefault();
    document.querySelectorAll('[data-toggle="tab"]').forEach(function(l){ l.classList.remove('active'); });
    document.querySelectorAll('.tab-pane').forEach(function(p){ p.classList.remove('active'); });
    link.classList.add('active');
    document.querySelector(link.getAttribute('href')).classList.add('active');
  };
});

// Abrir tab de config si hay ?saved o ?test
if (window.location.search.match(/saved|test/)) {
  document.querySelector('[href="#tab-config"]').click();
}
</script>
{% endblock %}
"""


# ── Models ──────────────────────────────────────────────────────────────────────

class WhaleyInstanceLog(db.Model):
    __tablename__ = "whaley_instance_log"
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey("users.id",  ondelete="CASCADE"))
    challenge_id     = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"))
    start_time       = db.Column(db.DateTime, default=datetime.utcnow)
    solve_time       = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)


class WhaleyPenalty(db.Model):
    """Penalización individual (nivel usuario) — sigue activa como capa secundaria."""
    __tablename__ = "whaley_penalty"
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    penalty_type  = db.Column(db.String(32), nullable=False)   # 'block' | 'ban'
    reason        = db.Column(db.String(255))
    offending_flag = db.Column(db.String(512))
    challenge_id  = db.Column(db.Integer, nullable=True)
    offender_team_id = db.Column(db.Integer, nullable=True)
    owner_user_id = db.Column(db.String(64), nullable=True)
    owner_team_id = db.Column(db.String(64), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at    = db.Column(db.DateTime, nullable=False)

    def is_active(self):
        return datetime.utcnow() < self.expires_at

    def remaining_seconds(self):
        return max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))

    def remaining_str(self):
        secs = self.remaining_seconds()
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:  return f"{h}h {m}m {s}s"
        if m:  return f"{m}m {s}s"
        return f"{s}s"


class TeamRedFlag(db.Model):
    """Ban a nivel de equipo. Todos los miembros quedan bloqueados durante el período."""
    __tablename__ = "teams_red_flag"
    id              = db.Column(db.Integer, primary_key=True)
    team_id         = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    reason          = db.Column(db.String(255), nullable=False)
    # El otro equipo involucrado (si aplica)
    related_team_id = db.Column(db.Integer, nullable=True)
    challenge_id    = db.Column(db.Integer, nullable=True)
    offending_flag  = db.Column(db.String(128), nullable=True)   # flag truncada
    banned_at       = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at      = db.Column(db.DateTime, nullable=False)
    lifted_at       = db.Column(db.DateTime, nullable=True)
    lifted_by       = db.Column(db.Integer,  nullable=True)      # admin user_id

    def is_active(self):
        if self.lifted_at:
            return False
        return datetime.utcnow() < self.expires_at

    def remaining_seconds(self):
        if not self.is_active():
            return 0
        return max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))

    def remaining_str(self):
        secs = self.remaining_seconds()
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:  return f"{h}h {m}m"
        if m:  return f"{m}m {s}s"
        return f"{s}s"


# ── Whaley service helpers ──────────────────────────────────────────────────────

def _whaley_service_headers():
    """Headers para llamadas service-to-service a los endpoints admin de Whaley."""
    return {
        "X-Admin-Key": WHALEY_ADMIN_KEY,
        "Content-Type": "application/json",
    }


def _whaley_user_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _check_flag_ownership(flag_string: str) -> dict:
    """
    Consulta /admin/api/check-flag de Whaley.
    Devuelve el dict de respuesta o {} en caso de error.
    """
    try:
        resp = requests.post(
            get_whaley_url() + "/admin/api/check-flag",
            json={"flag": flag_string},
            headers=_whaley_service_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[Whaley] check-flag error: {e}")
    return {}


# ── Discord helpers ─────────────────────────────────────────────────────────────

def _discord_color(reason_type: str) -> int:
    return {
        "steal":  0xFF0000,
        "leak":   0xFF8800,
        "noinstance": 0xFFCC00,
    }.get(reason_type, 0xFF0000)


def _send_discord(payload: dict):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=5)
    except Exception as e:
        print(f"[Whaley] Discord error: {e}")


def _discord_team_ban_notification(
    cheater_team: str, owner_team: str,
    challenge_name: str, ban_hours: int,
):
    payload = {
        "embeds": [{
            "title": "🚨 FLAG ROBADA — Ambos equipos baneados",
            "color": 0xFF0000,
            "fields": [
                {"name": "Equipo tramposo",      "value": cheater_team, "inline": True},
                {"name": "Equipo víctima/cómplice", "value": owner_team, "inline": True},
                {"name": "Reto",                 "value": challenge_name, "inline": True},
                {"name": "Sanción",              "value": f"Ban de **{ban_hours}h** + logros revocados", "inline": False},
            ],
            "footer": {"text": "Whaley Anti-Cheat"},
        }]
    }
    threading.Thread(target=_send_discord, args=(payload,), daemon=True).start()


def _discord_no_instance_ban(team_name: str, challenge_name: str, ban_hours: int):
    payload = {
        "embeds": [{
            "title": "⚠️ Intento de flag sin instancia",
            "color": 0xFFCC00,
            "fields": [
                {"name": "Equipo",   "value": team_name,      "inline": True},
                {"name": "Reto",     "value": challenge_name, "inline": True},
                {"name": "Sanción",  "value": f"Ban de **{ban_hours}h**", "inline": True},
            ],
            "footer": {"text": "Whaley Anti-Cheat"},
        }]
    }
    threading.Thread(target=_send_discord, args=(payload,), daemon=True).start()


# ── Anti-cheat operations ───────────────────────────────────────────────────────

def _get_team_member_ids(team_id: int) -> list:
    """Devuelve lista de user_id de todos los miembros del equipo."""
    try:
        members = Users.query.filter_by(team_id=team_id).all()
        return [m.id for m in members]
    except Exception:
        return []


def _revoke_achievements_for_team(team_id: int) -> int:
    """Elimina todos los logros de los miembros del equipo. Devuelve cuántos usuarios afectó."""
    try:
        from CTFd.plugins.hackl4bs_achievements import AchievementEarned  # type: ignore
        member_ids = _get_team_member_ids(team_id)
        if not member_ids:
            return 0
        AchievementEarned.query.filter(
            AchievementEarned.user_id.in_(member_ids)
        ).delete(synchronize_session=False)
        db.session.commit()
        return len(member_ids)
    except Exception as e:
        db.session.rollback()
        print(f"[Whaley] Error revocando logros del equipo {team_id}: {e}")
        return 0


def _delete_team_challenge_solve(team_id: int, challenge_id: int):
    """
    Elimina el Solve del equipo para un reto específico.
    También borra el Award de first-blood si lo tenían.
    """
    try:
        # Eliminar solve(s) del equipo para este reto
        deleted = Solves.query.filter_by(
            team_id=team_id, challenge_id=challenge_id
        ).delete(synchronize_session=False)

        # Eliminar award de first blood si existe
        Awards.query.filter_by(
            team_id=team_id,
            category="first_blood",
        ).filter(
            Awards.description.contains(f"#{challenge_id}")
        ).delete(synchronize_session=False)

        db.session.commit()
        if deleted:
            print(f"[Whaley] Solve del equipo {team_id} en reto {challenge_id} eliminado.")
    except Exception as e:
        db.session.rollback()
        print(f"[Whaley] Error eliminando solve del equipo {team_id}: {e}")


def _nullify_first_blood_records(team_id: int, challenge_id: int):
    """Borra los registros de first-blood en WhaleyInstanceLog del equipo para el reto."""
    try:
        member_ids = _get_team_member_ids(team_id)
        if not member_ids:
            return
        WhaleyInstanceLog.query.filter(
            WhaleyInstanceLog.user_id.in_(member_ids),
            WhaleyInstanceLog.challenge_id == challenge_id,
            WhaleyInstanceLog.solve_time.isnot(None),
        ).update(
            {WhaleyInstanceLog.solve_time: None, WhaleyInstanceLog.duration_seconds: None},
            synchronize_session=False,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Whaley] Error limpiando first-blood del equipo {team_id}: {e}")


def _nullify_all_fast_resolves(team_id: int):
    """Limpia todos los fast_resolve del equipo (duration_seconds → NULL en todos los retos)."""
    try:
        member_ids = _get_team_member_ids(team_id)
        if not member_ids:
            return
        WhaleyInstanceLog.query.filter(
            WhaleyInstanceLog.user_id.in_(member_ids),
            WhaleyInstanceLog.duration_seconds.isnot(None),
        ).update(
            {WhaleyInstanceLog.duration_seconds: None},
            synchronize_session=False,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Whaley] Error limpiando fast_resolves del equipo {team_id}: {e}")


def _kill_team_instances(team_id: int) -> int:
    """Detiene todas las instancias Whaley activas de los miembros del equipo."""
    try:
        member_ids = {str(uid) for uid in _get_team_member_ids(team_id)}
        if not member_ids:
            return 0
        resp = requests.get(
            get_whaley_url() + "/admin/api/instances",
            headers=_whaley_service_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return 0
        instances = resp.json().get("instances", [])
        killed = 0
        for inst in instances:
            if str(inst.get("user_id", "")) in member_ids:
                iid = inst.get("instance_id") or inst.get("id")
                if iid:
                    try:
                        requests.delete(
                            get_whaley_url() + f"/admin/api/instances/{iid}",
                            headers=_whaley_service_headers(),
                            timeout=10,
                        )
                        killed += 1
                    except Exception:
                        pass
        return killed
    except Exception as e:
        print(f"[Whaley] Error al detener instancias del equipo {team_id}: {e}")
        return 0


def _is_team_banned(team_id: int) -> "TeamRedFlag | None":
    """Devuelve el TeamRedFlag activo del equipo, o None si no hay ban vigente."""
    now = datetime.utcnow()
    return (
        TeamRedFlag.query
        .filter(
            TeamRedFlag.team_id == team_id,
            TeamRedFlag.expires_at > now,
            TeamRedFlag.lifted_at.is_(None),
        )
        .order_by(TeamRedFlag.expires_at.desc())
        .first()
    )


def _ban_team(
    team_id: int,
    reason: str,
    challenge_id: int = None,
    related_team_id: int = None,
    offending_flag: str = None,
    hours: int = BAN_HOURS,
) -> "TeamRedFlag":
    """
    Crea un registro de ban de equipo en teams_red_flag.
    Si ya tiene un ban activo, no crea duplicado.
    """
    now = datetime.utcnow()
    existing = _is_team_banned(team_id)
    if existing:
        return existing

    record = TeamRedFlag(
        team_id         = team_id,
        reason          = reason,
        challenge_id    = challenge_id,
        related_team_id = related_team_id,
        offending_flag  = (offending_flag[:80] + "...") if offending_flag and len(offending_flag) > 80 else offending_flag,
        banned_at       = now,
        expires_at      = now + timedelta(hours=hours),
    )
    db.session.add(record)
    db.session.commit()
    print(f"[Whaley] Equipo {team_id} baneado {hours}h — {reason}")
    return record


def _apply_full_cheat_penalty(
    cheater_team_id: int,
    owner_team_id: int,
    challenge_id: int,
    challenge_name: str,
    flag_truncated: str,
):
    """
    Aplica la penalización completa cuando se detecta flag robada:
    - Ban 4h a ambos equipos
    - Revoca logros de ambos equipos
    - Elimina el solve robado del equipo tramposo
    - Limpia registros de first-blood del equipo tramposo
    """
    cheater_team = Teams.query.get(cheater_team_id)
    owner_team   = Teams.query.get(owner_team_id)
    cheater_name = cheater_team.name if cheater_team else f"equipo#{cheater_team_id}"
    owner_name   = owner_team.name   if owner_team   else f"equipo#{owner_team_id}"

    # Ban a ambos equipos
    _ban_team(
        team_id         = cheater_team_id,
        reason          = f"Usó flag robada del reto '{challenge_name}' perteneciente al equipo '{owner_name}'",
        challenge_id    = challenge_id,
        related_team_id = owner_team_id,
        offending_flag  = flag_truncated,
        hours           = get_ban_hours(),
    )
    _ban_team(
        team_id         = owner_team_id,
        reason          = f"Flag del reto '{challenge_name}' fue compartida/robada por el equipo '{cheater_name}'",
        challenge_id    = challenge_id,
        related_team_id = cheater_team_id,
        offending_flag  = flag_truncated,
        hours           = get_ban_hours(),
    )

    # Revocar logros de ambos equipos
    _revoke_achievements_for_team(cheater_team_id)
    _revoke_achievements_for_team(owner_team_id)

    # Eliminar solve robado y first-blood del equipo tramposo
    _delete_team_challenge_solve(cheater_team_id, challenge_id)
    _nullify_first_blood_records(cheater_team_id, challenge_id)

    # Limpiar fast_resolve badges de ambos equipos
    _nullify_all_fast_resolves(cheater_team_id)
    _nullify_all_fast_resolves(owner_team_id)

    # Detener instancias activas de ambos equipos
    _kill_team_instances(cheater_team_id)
    _kill_team_instances(owner_team_id)

    # SIEM — ban por flag robada (ambos equipos)
    _emit_siem_event(
        event_type="team_ban",
        severity="critical",
        team=cheater_name,
        team_id=cheater_team_id,
        challenge=challenge_name,
        challenge_id=challenge_id,
        message=f"🚨 Equipo '{cheater_name}' baneado {get_ban_hours()}h por usar flag robada de '{challenge_name}' (equipo víctima: {owner_name})",
        metadata={"ban_hours": get_ban_hours(), "related_team": owner_name, "related_team_id": owner_team_id, "flag_truncated": flag_truncated, "reason": "flag_theft"},
    )
    _emit_siem_event(
        event_type="team_ban",
        severity="high",
        team=owner_name,
        team_id=owner_team_id,
        challenge=challenge_name,
        challenge_id=challenge_id,
        message=f"⚠️ Equipo '{owner_name}' baneado {get_ban_hours()}h — su flag de '{challenge_name}' fue comprometida por '{cheater_name}'",
        metadata={"ban_hours": get_ban_hours(), "related_team": cheater_name, "related_team_id": cheater_team_id, "flag_truncated": flag_truncated, "reason": "flag_leaked"},
    )

    # Discord
    _discord_team_ban_notification(cheater_name, owner_name, challenge_name, get_ban_hours())

    print(f"[Whaley] Penalización completa aplicada: tramposo={cheater_name}, víctima={owner_name}, reto={challenge_name}")


# ── SQLAlchemy event listeners ──────────────────────────────────────────────────

@event.listens_for(Solves, "after_insert")
def record_whaley_solve_time(mapper, connection, target):
    """Registra la hora de solve en WhaleyInstanceLog cuando CTFd acepta una flag."""
    try:
        query = text(
            "SELECT id, start_time FROM whaley_instance_log "
            "WHERE user_id = :u AND challenge_id = :c AND solve_time IS NULL "
            "ORDER BY start_time DESC LIMIT 1"
        )
        result = connection.execute(query, {"u": target.user_id, "c": target.challenge_id}).fetchone()
        if result:
            log_id, start_time = result
            solve_date = target.date or datetime.utcnow()
            if isinstance(start_time, str):
                try:
                    start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            if isinstance(solve_date, str):
                try:
                    solve_date = datetime.strptime(solve_date, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    solve_date = datetime.strptime(solve_date, "%Y-%m-%d %H:%M:%S")
            if solve_date and start_time:
                diff = (solve_date - start_time).total_seconds()
                connection.execute(
                    text("UPDATE whaley_instance_log SET solve_time = :st, duration_seconds = :d WHERE id = :id"),
                    {"st": solve_date, "d": diff, "id": log_id},
                )
    except Exception as e:
        print(f"[Whaley] Error en record_whaley_solve_time: {e}")


# ── Spawn in-progress lock (evita doble spawn por el mismo usuario+reto) ───────
_spawn_in_progress: set = set()
_spawn_lock_mutex = threading.Lock()

# ── ID cache (CTFd ID → Whaley local ID) ───────────────────────────────────────
_whaley_id_cache: dict = {}
_WHALEY_CACHE_TTL = 60


def _resolve_whaley_id(ctfd_challenge_id, token: str):
    import time
    key = str(ctfd_challenge_id)
    cached = _whaley_id_cache.get(key)
    if cached:
        local_id, ts = cached
        if time.time() - ts < _WHALEY_CACHE_TTL:
            return local_id
    whaley_base = get_whaley_url()
    try:
        resp = requests.get(
            f"{whaley_base}/admin/api/flags",
            headers=_whaley_service_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            mapping = data.get("challenge_mapping", {})
            now = time.time()
            for local_id, mapped_ctfd_id in mapping.items():
                _whaley_id_cache[str(mapped_ctfd_id)] = (local_id, now)
            if key in _whaley_id_cache:
                return _whaley_id_cache[key][0]
    except Exception:
        pass
    return key


def _get_user_token():
    from CTFd.models import Tokens
    user = get_current_user()
    if not user:
        return None
    token = Tokens.query.filter_by(user_id=user.id).first()
    return token.value if token else None


# ── Flask plugin loader ─────────────────────────────────────────────────────────

def load(app):
    with app.app_context():
        db.create_all()

    plugin_bp = Blueprint("whaley", __name__, template_folder="templates")
    register_plugin_assets_directory(app, base_path="/plugins/whaley_ctfd_plugin/assets/")

    # ── Guard principal de submissions ────────────────────────────────────────
    @app.before_request
    def whaley_submission_guard():
        """
        Intercepta POST /api/v1/challenges/attempt antes de que CTFd procese la flag.

        Lógica:
          1. Si el equipo del usuario está en teams_red_flag activo → bloquear.
          2. Si la flag empieza con el prefijo Whaley (H4L{) → consultar a Whaley quién la
             posee. Si el dueño es otro equipo → ban de 4h a AMBOS equipos + revocar logros
             + eliminar solve robado.
          3. Si el reto tiene instancias Whaley y el equipo NO tiene ninguna → ban 4h al
             equipo tramposo.
        """
        if not is_anticheat_enabled():
            return

        if request.path != "/api/v1/challenges/attempt" or request.method != "POST":
            return

        user = get_current_user()
        if not user or user.type == "admin":
            return

        # ── 1. Verificar ban de equipo ────────────────────────────────────────
        if user.team_id:
            active_ban = _is_team_banned(user.team_id)
            if active_ban:
                team = Teams.query.get(user.team_id)
                team_name = team.name if team else f"equipo#{user.team_id}"
                return jsonify({"success": False, "data": {
                    "status": "incorrect",
                    "message": (
                        f"🚨 Tu equipo '{team_name}' está baneado por {active_ban.remaining_str()}. "
                        f"Motivo: {active_ban.reason}"
                    ),
                }}), 200

        # Verificar también ban individual (WhaleyPenalty)
        now = datetime.utcnow()
        active_penalty = (
            WhaleyPenalty.query
            .filter(WhaleyPenalty.user_id == user.id, WhaleyPenalty.expires_at > now)
            .order_by(WhaleyPenalty.expires_at.desc())
            .first()
        )
        if active_penalty:
            return jsonify({"success": False, "data": {
                "status": "incorrect",
                "message": f"🚨 Estás baneado por {active_penalty.remaining_str()}.",
            }}), 200

        # ── 2. Leer cuerpo del request ────────────────────────────────────────
        body         = request.get_json(silent=True, force=True) or {}
        challenge_id = body.get("challenge_id")
        submission   = (body.get("submission") or "").strip()

        if not challenge_id or not submission:
            return

        # ── 3. Detección por flag dinámica Whaley ────────────────────────────
        # Detecta cualquier flag con formato PREFIX{hex} — no depende del prefijo
        # exacto para cubrir flags generadas con prefijos anteriores (HL4{, H4L{, etc.)
        _DYNAMIC_FLAG_RE = re.compile(r'^[A-Za-z0-9_]+\{[0-9a-fA-F]{16,64}\}$')
        if WHALEY_ADMIN_KEY and _DYNAMIC_FLAG_RE.match(submission):
            ownership = _check_flag_ownership(submission)
            if ownership.get("found"):
                owner_team_id_str = ownership.get("owner_team_id")
                owner_team_id = int(owner_team_id_str) if owner_team_id_str else None

                submitter_team_id = user.team_id

                is_stolen = False
                if owner_team_id and submitter_team_id:
                    is_stolen = (owner_team_id != submitter_team_id)
                elif owner_team_id and not submitter_team_id:
                    # Usuario sin equipo intenta usar flag de equipo
                    is_stolen = True

                if is_stolen:
                    chal = Challenges.query.get(int(challenge_id))
                    chal_name = chal.name if chal else f"reto#{challenge_id}"

                    _apply_full_cheat_penalty(
                        cheater_team_id = submitter_team_id,
                        owner_team_id   = owner_team_id,
                        challenge_id    = int(challenge_id),
                        challenge_name  = chal_name,
                        flag_truncated  = submission[:20] + "...",
                    )

                    return jsonify({"success": False, "data": {
                        "status": "incorrect",
                        "message": (
                            "🚨 Flag perteneciente a otro equipo. "
                            f"Tu equipo y el equipo propietario han sido baneados por {get_ban_hours()}h. "
                            "Todos los logros han sido revocados."
                        ),
                    }}), 200

        # ── 4. Detección por ausencia de instancia Whaley ─────────────────────
        any_instance = WhaleyInstanceLog.query.filter_by(challenge_id=challenge_id).first()
        if not any_instance:
            return  # No es un reto Whaley, CTFd valida normalmente

        # ¿El equipo del usuario tiene instancia para este reto?
        if user.team_id:
            team_instance = (
                db.session.query(WhaleyInstanceLog)
                .join(Users, WhaleyInstanceLog.user_id == Users.id)
                .filter(
                    Users.team_id == user.team_id,
                    WhaleyInstanceLog.challenge_id == challenge_id,
                )
                .first()
            )
            has_instance = team_instance is not None
        else:
            has_instance = WhaleyInstanceLog.query.filter_by(
                user_id=user.id, challenge_id=challenge_id
            ).first() is not None

        if has_instance:
            return  # OK

        # DB dice no tiene instancia — verificar en vivo con Whaley antes de banear
        try:
            member_ids = {str(uid) for uid in _get_team_member_ids(user.team_id)} if user.team_id else {str(user.id)}
            live_resp = requests.get(
                get_whaley_url() + "/admin/api/instances",
                headers=_whaley_service_headers(),
                timeout=5,
            )
            if live_resp.status_code == 200:
                live_instances = live_resp.json().get("instances", [])
                for inst in live_instances:
                    if str(inst.get("user_id", "")) in member_ids and str(inst.get("challenge_id", "")) == str(challenge_id):
                        return  # Tiene instancia activa en Whaley — no banear
        except Exception as e:
            print(f"[Whaley] check instancia live falló ({e}) — fail open, no ban")
            return  # No se puede confirmar → beneficio de la duda

        # Sin instancia en reto Whaley → ban
        chal = Challenges.query.get(int(challenge_id))
        chal_name = chal.name if chal else f"reto#{challenge_id}"

        if user.team_id:
            team = Teams.query.get(user.team_id)
            team_name = team.name if team else f"equipo#{user.team_id}"

            existing_ban = _is_team_banned(user.team_id)
            if not existing_ban:
                _ban_team(
                    team_id      = user.team_id,
                    reason       = f"Intentó usar flag del reto '{chal_name}' sin tener instancia activa",
                    challenge_id = int(challenge_id),
                    hours        = get_ban_hours(),
                )
                _revoke_achievements_for_team(user.team_id)
                _nullify_all_fast_resolves(user.team_id)
                _kill_team_instances(user.team_id)
                _emit_siem_event(
                    event_type="team_ban",
                    severity="critical",
                    team=team_name,
                    team_id=user.team_id,
                    player=user.name,
                    player_id=user.id,
                    challenge=chal_name,
                    challenge_id=int(challenge_id),
                    message=f"🚨 Equipo '{team_name}' baneado {get_ban_hours()}h — intentó flag en '{chal_name}' sin instancia activa",
                    metadata={"ban_hours": get_ban_hours(), "reason": "no_instance"},
                )
                _discord_no_instance_ban(team_name, chal_name, get_ban_hours())
                print(f"[Whaley] Equipo '{team_name}' baneado {get_ban_hours()}h — sin instancia en '{chal_name}'")

            ban_record = _is_team_banned(user.team_id)
            remaining  = ban_record.remaining_str() if ban_record else f"{get_ban_hours()}h"
        else:
            # Usuario sin equipo — ban individual
            existing = WhaleyPenalty.query.filter(
                WhaleyPenalty.user_id == user.id,
                WhaleyPenalty.expires_at > now,
            ).first()
            if not existing:
                penalty = WhaleyPenalty(
                    user_id=user.id,
                    penalty_type="ban",
                    reason=f"Intentó usar flag del reto '{chal_name}' sin instancia propia",
                    challenge_id=int(challenge_id),
                    expires_at=now + timedelta(hours=get_ban_hours()),
                )
                db.session.add(penalty)
                db.session.commit()
            remaining = f"{get_ban_hours()}h"

        return jsonify({"success": False, "data": {
            "status": "incorrect",
            "message": (
                f"🚨 Tu equipo no tiene instancia de este reto. "
                f"Ban de {remaining}. Todos los logros del equipo revocados."
            ),
        }}), 200

    # ── Inject JS en páginas HTML ─────────────────────────────────────────────
    @app.after_request
    def inject_whaley_script(response):
        if response.content_type and "text/html" in response.content_type:
            data = response.get_data(as_text=True)
            if "</head>" in data and "whaley.js" not in data:
                data = data.replace("</head>", INJECT_SCRIPT + "</head>", 1)
                response.set_data(data)
        return response

    # ── API: Spawn ────────────────────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/spawn", methods=["POST"])
    @authed_only
    def whaley_spawn():
        data = request.get_json()
        ctfd_challenge_id = data.get("challenge_id")
        if not ctfd_challenge_id:
            return jsonify({"success": False, "message": "challenge_id requerido"}), 400

        token = _get_user_token()
        if not token:
            return jsonify({
                "success": False,
                "message": "No tienes Access Token. Ve a Settings → Access Tokens y crea uno.",
            }), 403

        # Bloquear spawn si el equipo está baneado
        _spawn_user = get_current_user()
        if _spawn_user and _spawn_user.team_id:
            _active_ban = _is_team_banned(_spawn_user.team_id)
            if _active_ban:
                return jsonify({
                    "success": False,
                    "message": f"Tu equipo está suspendido. Tiempo restante: {_active_ban.remaining_str()}.",
                }), 403

        whaley_challenge_id = _resolve_whaley_id(ctfd_challenge_id, token)
        whaley_base = get_whaley_url()

        # Evitar doble spawn concurrente del mismo usuario para el mismo reto
        _spawn_user = get_current_user()
        _lock_key = f"{_spawn_user.id}:{ctfd_challenge_id}"
        with _spawn_lock_mutex:
            if _lock_key in _spawn_in_progress:
                return jsonify({"success": False, "message": "Ya hay un spawn en proceso para este reto, espera un momento."}), 429
            _spawn_in_progress.add(_lock_key)

        try:
            resp = requests.post(
                f"{whaley_base}/instances/spawn",
                json={"challenge_id": whaley_challenge_id},
                headers=_whaley_user_headers(token),
                timeout=30,
            )
            result = resp.json()

            if resp.status_code == 200 and result.get("success"):
                try:
                    user = get_current_user()
                    if user:
                        log = WhaleyInstanceLog(user_id=user.id, challenge_id=ctfd_challenge_id)
                        db.session.add(log)
                        db.session.commit()
                except Exception as e:
                    print(f"[Whaley] Error registrando log de instancia: {e}")

                instance    = result.get("instance", {})
                first_url   = instance.get("public_url", "")
                host = port = ""
                if first_url and ":" in first_url:
                    parts = first_url.rsplit(":", 1)
                    host, port = parts[0], parts[1]
                return jsonify({
                    "success":    True,
                    "host":       host,
                    "port":       port,
                    "public_url": first_url,
                    "public_urls": instance.get("public_urls", {}),
                    "instance_id": instance.get("instance_id", ""),
                    "expires_in": 3600,
                    "expires_at": instance.get("expires_at", ""),
                })
            return jsonify({"success": False, "message": result.get("detail", str(result))}), resp.status_code

        except requests.exceptions.ConnectionError:
            return jsonify({
                "success": False,
                "message": f"No se puede conectar a Whaley en {whaley_base}. ¿Está corriendo?",
            }), 503
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            with _spawn_lock_mutex:
                _spawn_in_progress.discard(_lock_key)

    # ── API: Status ───────────────────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/status/<challenge_id>", methods=["GET"])
    @authed_only
    def whaley_status(challenge_id):
        token = _get_user_token()
        if not token:
            return jsonify({"running": False}), 200

        current_user       = get_current_user()
        whaley_challenge_id = _resolve_whaley_id(challenge_id, token)
        whaley_base        = get_whaley_url()
        try:
            resp = requests.get(f"{whaley_base}/instances", headers=_whaley_user_headers(token), timeout=10)
            if resp.status_code != 200:
                return jsonify({"running": False}), 200

            for inst in resp.json().get("instances", []):
                if str(inst.get("challenge_id", "")) in (str(whaley_challenge_id), str(challenge_id)):
                    public_url = inst.get("public_url", "")
                    host = port = ""
                    if public_url and ":" in public_url:
                        parts = public_url.rsplit(":", 1)
                        host, port = parts[0], parts[1]
                    is_mine = str(inst.get("user_id", "")) == str(current_user.id) if current_user else False
                    return jsonify({
                        "running":     True,
                        "host":        host,
                        "port":        port,
                        "public_url":  public_url,
                        "public_urls": inst.get("public_urls", {}),
                        "instance_id": inst.get("instance_id", ""),
                        "expires_at":  inst.get("expires_at", ""),
                        "spawned_by":  inst.get("username", ""),
                        "is_mine":     is_mine,
                    })
            return jsonify({"running": False}), 200
        except Exception:
            return jsonify({"running": False}), 200

    # ── API: Lista de instancias ──────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/instances", methods=["GET"])
    @authed_only
    def whaley_list_instances():
        token = _get_user_token()
        if not token:
            return jsonify({"instances": []}), 200

        current_user = get_current_user()
        whaley_base  = get_whaley_url()
        try:
            resp = requests.get(f"{whaley_base}/instances", headers=_whaley_user_headers(token), timeout=10)
            if resp.status_code == 200:
                instances = resp.json().get("instances", [])
                for inst in instances:
                    inst["is_mine"] = str(inst.get("user_id", "")) == str(current_user.id) if current_user else False
                    inst.setdefault("spawned_by", inst.get("username", ""))
                return jsonify({"instances": instances}), 200
            return jsonify({"instances": []}), 200
        except Exception:
            return jsonify({"instances": []}), 200

    # ── API: Estadísticas del reto (first blood + fastest) ───────────────────
    @plugin_bp.route("/api/whaley/stats/<int:challenge_id>", methods=["GET"])
    def whaley_stats(challenge_id):
        from CTFd.utils import get_config as _cfg
        first_blood = fastest = None
        mode = _cfg("user_mode")

        first_solve = Solves.query.filter_by(challenge_id=challenge_id).order_by(Solves.date.asc()).first()
        if first_solve:
            name = ""
            if mode == "teams" and first_solve.team:
                name = first_solve.team.name
            else:
                name = first_solve.user.name
            first_blood = {"user_name": name, "date": first_solve.date.isoformat() if first_solve.date else None}

        fastest_log = (
            WhaleyInstanceLog.query
            .filter(WhaleyInstanceLog.challenge_id == challenge_id,
                    WhaleyInstanceLog.duration_seconds.isnot(None))
            .order_by(WhaleyInstanceLog.duration_seconds.asc())
            .first()
        )
        if fastest_log:
            duration = int(fastest_log.duration_seconds)
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            if hours:    time_str = f"{hours}h {mins}m {secs}s"
            elif mins:   time_str = f"{mins}m {secs}s"
            else:        time_str = f"{secs}s"
            u = Users.query.get(fastest_log.user_id)
            if u:
                display_name = u.name
                if mode == "teams" and u.team:
                    display_name = u.team.name
                fastest = {"user_name": display_name, "time_str": time_str, "seconds": duration}

        return jsonify({"first_blood": first_blood, "fastest": fastest}), 200

    # ── API: Extender instancia ───────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/extend", methods=["POST"])
    @authed_only
    def whaley_extend():
        data         = request.get_json()
        instance_id  = data.get("instance_id")
        extra_minutes = int(data.get("extra_minutes", 30))
        if not instance_id:
            return jsonify({"success": False, "message": "instance_id requerido"}), 400

        token = _get_user_token()
        if not token:
            return jsonify({"success": False, "message": "Sin token"}), 403

        whaley_base = get_whaley_url()
        try:
            resp = requests.post(
                f"{whaley_base}/instances/{instance_id}/extend",
                json={"extra_minutes": extra_minutes},
                headers=_whaley_user_headers(token),
                timeout=15,
            )
            result = resp.json()
            if resp.status_code == 200:
                return jsonify({"success": True, "message": result.get("message", "Extendida")})
            return jsonify({"success": False, "message": result.get("detail", str(result))}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ── API: Detener instancia ────────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/stop", methods=["POST"])
    @authed_only
    def whaley_stop():
        data        = request.get_json()
        instance_id = data.get("instance_id")
        challenge_id = data.get("challenge_id")
        token       = _get_user_token()

        if not token:
            return jsonify({"success": False, "message": "Sin token"}), 403

        whaley_base = get_whaley_url()

        if not instance_id and challenge_id:
            whaley_challenge_id = _resolve_whaley_id(challenge_id, token)
            try:
                resp = requests.get(f"{whaley_base}/instances", headers=_whaley_user_headers(token), timeout=10)
                if resp.status_code == 200:
                    for inst in resp.json().get("instances", []):
                        if str(inst.get("challenge_id", "")) in (str(whaley_challenge_id), str(challenge_id)):
                            instance_id = inst.get("instance_id")
                            break
            except Exception:
                pass

        if not instance_id:
            return jsonify({"success": False, "message": "Instancia no encontrada"}), 404

        try:
            resp = requests.delete(
                f"{whaley_base}/instances/{instance_id}",
                headers=_whaley_user_headers(token),
                timeout=15,
            )
            if resp.status_code in (200, 204):
                return jsonify({"success": True})
            return jsonify({"success": False, "message": resp.text}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ── API: Penalización activa del usuario ──────────────────────────────────
    @plugin_bp.route("/api/whaley/my-penalty", methods=["GET"])
    @authed_only
    def whaley_my_penalty():
        user = get_current_user()
        if not user:
            return jsonify({"active": False}), 200

        # Verificar ban de equipo primero
        if user.team_id:
            team_ban = _is_team_banned(user.team_id)
            if team_ban:
                return jsonify({
                    "active":           True,
                    "type":             "team_ban",
                    "reason":           team_ban.reason,
                    "remaining_seconds": team_ban.remaining_seconds(),
                    "remaining_str":    team_ban.remaining_str(),
                    "expires_at":       team_ban.expires_at.isoformat(),
                }), 200

        # Verificar ban individual
        now = datetime.utcnow()
        penalty = (
            WhaleyPenalty.query
            .filter(WhaleyPenalty.user_id == user.id, WhaleyPenalty.expires_at > now)
            .order_by(WhaleyPenalty.expires_at.desc())
            .first()
        )
        if not penalty:
            return jsonify({"active": False}), 200
        return jsonify({
            "active":           True,
            "type":             penalty.penalty_type,
            "reason":           penalty.reason,
            "remaining_seconds": penalty.remaining_seconds(),
            "remaining_str":    penalty.remaining_str(),
            "expires_at":       penalty.expires_at.isoformat(),
        }), 200

    # ── API: Actividad del equipo ─────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/team-activity", methods=["GET"])
    @authed_only
    def whaley_team_activity():
        user = get_current_user()
        if not user:
            return jsonify({"events": []})

        if user.team_id:
            team = Teams.query.get(user.team_id)
            member_ids = [m.id for m in team.members] if team else [user.id]
        else:
            member_ids = [user.id]

        logs = (
            WhaleyInstanceLog.query
            .filter(WhaleyInstanceLog.user_id.in_(member_ids))
            .order_by(WhaleyInstanceLog.start_time.desc())
            .limit(40)
            .all()
        )
        events = []
        for log in logs:
            u = Users.query.get(log.user_id)
            c = Challenges.query.get(log.challenge_id)
            username  = u.name if u else f"user#{log.user_id}"
            chal_name = c.name if c else f"reto#{log.challenge_id}"
            is_me     = (log.user_id == user.id)

            if log.solve_time and log.duration_seconds is not None:
                mins, secs = divmod(int(log.duration_seconds), 60)
                duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                events.append({
                    "type": "solved", "username": username,
                    "challenge": chal_name, "time": log.solve_time.isoformat() + "Z",
                    "duration": duration_str, "is_me": is_me,
                })
            if log.start_time:
                events.append({
                    "type": "started", "username": username,
                    "challenge": chal_name, "time": log.start_time.isoformat() + "Z",
                    "is_me": is_me,
                })

        events.sort(key=lambda x: x["time"], reverse=True)
        return jsonify({"events": events[:20]})

    # ════════════════════════════════════════════════════════════════════════════
    # ADMIN ENDPOINTS
    # ════════════════════════════════════════════════════════════════════════════

    # ── Admin: Configuración del plugin ──────────────────────────────────────
    @plugin_bp.route("/admin/whaley", methods=["GET", "POST"])
    @admins_only
    def whaley_admin_config():
        saved = conn_status = None
        conn_ok = False
        if request.method == "POST":
            set_config("whaley_url", request.form.get("whaley_url", "").rstrip("/"))
            new_hours = request.form.get("ban_hours", "")
            try:
                set_config("ban_hours", str(max(1, int(new_hours)))) if new_hours else None
            except (ValueError, TypeError):
                pass
            # Checkbox: presente = activo, ausente = desactivado
            anticheat_val = "1" if request.form.get("anticheat_enabled") else "0"
            set_config("anticheat_enabled", anticheat_val)
            saved = True
        if request.args.get("test"):
            try:
                resp = requests.get(get_whaley_url() + "/health", timeout=5)
                conn_ok = resp.status_code < 400
                conn_status = (
                    f"Whaley responde en {get_whaley_url()} (HTTP {resp.status_code})"
                    if conn_ok else f"Whaley respondió HTTP {resp.status_code}"
                )
            except Exception as e:
                conn_status = f"No se pudo conectar: {e}"

        def _reason_type(reason: str) -> str:
            r = (reason or "").lower()
            if "robada" in r or "robó" in r or "rob" in r:
                return "steal"
            if "filtrada" in r or "leak" in r or "comprometida" in r:
                return "leak"
            if "sin instancia" in r or "instancia" in r or "no_instance" in r:
                return "noinstance"
            return "manual"

        def _build_ban_dict(b, include_remaining=True):
            team         = Teams.query.get(b.team_id)
            related_team = Teams.query.get(b.related_team_id) if b.related_team_id else None
            chal         = Challenges.query.get(b.challenge_id) if b.challenge_id else None
            d = {
                "id":                b.id,
                "team_name":         team.name if team else f"equipo#{b.team_id}",
                "reason":            b.reason,
                "reason_type":       _reason_type(b.reason),
                "challenge_name":    chal.name if chal else None,
                "related_team_name": related_team.name if related_team else None,
                "offending_flag":    b.offending_flag,
                "banned_at":         b.banned_at.strftime("%Y-%m-%d %H:%M"),
                "expires_at":        b.expires_at.strftime("%Y-%m-%d %H:%M"),
                "lifted_at":         b.lifted_at.strftime("%Y-%m-%d %H:%M") if b.lifted_at else None,
            }
            if include_remaining:
                d["remaining_str"] = b.remaining_str()
            return d

        now = datetime.utcnow()

        # Bans activos
        active_bans = [
            _build_ban_dict(b)
            for b in TeamRedFlag.query.filter(
                TeamRedFlag.expires_at > now,
                TeamRedFlag.lifted_at.is_(None),
            ).order_by(TeamRedFlag.banned_at.desc()).all()
        ]

        # Historial (expirados o levantados, últimos 100)
        history_bans = [
            _build_ban_dict(b, include_remaining=False)
            for b in TeamRedFlag.query.filter(
                db.or_(
                    TeamRedFlag.expires_at <= now,
                    TeamRedFlag.lifted_at.isnot(None),
                )
            ).order_by(TeamRedFlag.banned_at.desc()).limit(100).all()
        ]

        # Todos los equipos para el formulario de ban manual
        all_teams = Teams.query.order_by(Teams.name.asc()).all()

        return render_template_string(
            ADMIN_PAGE,
            current_url=get_whaley_url(),
            ban_hours=get_ban_hours(),
            anticheat_enabled=is_anticheat_enabled(),
            saved=saved,
            conn_status=conn_status,
            conn_ok=conn_ok,
            active_bans=active_bans,
            history_bans=history_bans,
            all_teams=all_teams,
            nonce=session.get("nonce"),
        )

    # ── Admin: Ver penalizaciones individuales ────────────────────────────────
    @plugin_bp.route("/api/whaley/admin/penalties", methods=["GET"])
    @admins_only
    def whaley_admin_penalties():
        active_only = request.args.get("active") == "1"
        now = datetime.utcnow()
        q   = WhaleyPenalty.query
        if active_only:
            q = q.filter(WhaleyPenalty.expires_at > now)
        penalties = q.order_by(WhaleyPenalty.created_at.desc()).limit(200).all()
        result = []
        for p in penalties:
            u = Users.query.get(p.user_id)
            result.append({
                "id":           p.id,
                "username":     u.name if u else f"user#{p.user_id}",
                "type":         p.penalty_type,
                "reason":       p.reason,
                "challenge_id": p.challenge_id,
                "created_at":   p.created_at.isoformat(),
                "expires_at":   p.expires_at.isoformat(),
                "active":       p.is_active(),
                "remaining_str": p.remaining_str() if p.is_active() else "expirada",
            })
        return jsonify({"penalties": result}), 200

    @plugin_bp.route("/api/whaley/admin/penalties/<int:penalty_id>/lift", methods=["POST"])
    @admins_only
    def whaley_admin_lift_penalty(penalty_id):
        penalty = WhaleyPenalty.query.get(penalty_id)
        if not penalty:
            return jsonify({"success": False, "message": "No encontrada"}), 404
        penalty.expires_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True}), 200

    # ── Admin: Ver equipos en Red Flag ────────────────────────────────────────
    @plugin_bp.route("/api/whaley/admin/red-flags", methods=["GET"])
    @admins_only
    def whaley_admin_red_flags():
        """Lista todos los equipos baneados (activos e históricos)."""
        active_only = request.args.get("active") == "1"
        now = datetime.utcnow()
        q   = TeamRedFlag.query
        if active_only:
            q = q.filter(TeamRedFlag.expires_at > now, TeamRedFlag.lifted_at.is_(None))
        records = q.order_by(TeamRedFlag.banned_at.desc()).limit(500).all()

        result = []
        for r in records:
            team         = Teams.query.get(r.team_id)
            related_team = Teams.query.get(r.related_team_id) if r.related_team_id else None
            chal         = Challenges.query.get(r.challenge_id) if r.challenge_id else None
            result.append({
                "id":                r.id,
                "team_id":           r.team_id,
                "team_name":         team.name if team else f"equipo#{r.team_id}",
                "reason":            r.reason,
                "challenge_id":      r.challenge_id,
                "challenge_name":    chal.name if chal else None,
                "related_team_id":   r.related_team_id,
                "related_team_name": related_team.name if related_team else None,
                "offending_flag":    r.offending_flag,
                "banned_at":         r.banned_at.isoformat(),
                "expires_at":        r.expires_at.isoformat(),
                "lifted_at":         r.lifted_at.isoformat() if r.lifted_at else None,
                "active":            r.is_active(),
                "remaining_str":     r.remaining_str() if r.is_active() else "expirado",
                "members": [
                    {"id": u.id, "name": u.name}
                    for u in Users.query.filter_by(team_id=r.team_id).all()
                ],
            })
        return jsonify({"red_flags": result, "total": len(result)}), 200

    # ── Admin: Levantar ban de equipo manualmente ─────────────────────────────
    @plugin_bp.route("/api/whaley/admin/red-flags/<int:record_id>/lift", methods=["POST"])
    @admins_only
    def whaley_admin_lift_red_flag(record_id):
        record = TeamRedFlag.query.get(record_id)
        if not record:
            return jsonify({"success": False, "message": "Registro no encontrado"}), 404
        admin = get_current_user()
        record.lifted_at = datetime.utcnow()
        record.lifted_by = admin.id if admin else None
        db.session.commit()
        team = Teams.query.get(record.team_id)
        return jsonify({
            "success":   True,
            "message":   f"Ban del equipo '{team.name if team else record.team_id}' levantado.",
        }), 200

    # ── Admin: Levantar TODOS los bans activos ───────────────────────────────
    @plugin_bp.route("/api/whaley/admin/red-flags/lift-all", methods=["POST"])
    @admins_only
    def whaley_admin_lift_all_red_flags():
        admin = get_current_user()
        now = datetime.utcnow()
        active = TeamRedFlag.query.filter(
            TeamRedFlag.lifted_at.is_(None),
            TeamRedFlag.expires_at > now,
        ).all()
        count = len(active)
        for record in active:
            record.lifted_at = now
            record.lifted_by = admin.id if admin else None
        db.session.commit()
        return jsonify({"success": True, "message": f"{count} ban(s) levantado(s).", "lifted": count}), 200

    # ── Admin: Ban manual de un equipo ────────────────────────────────────────
    @plugin_bp.route("/api/whaley/admin/red-flags/ban", methods=["POST"])
    @admins_only
    def whaley_admin_manual_ban():
        data     = request.get_json() or {}
        team_id  = data.get("team_id")
        reason   = data.get("reason", "Ban manual por administrador")
        hours    = int(data.get("hours", BAN_HOURS))
        if not team_id:
            return jsonify({"success": False, "message": "team_id requerido"}), 400
        team = Teams.query.get(int(team_id))
        if not team:
            return jsonify({"success": False, "message": "Equipo no encontrado"}), 404
        record = _ban_team(team_id=int(team_id), reason=reason, hours=hours)
        return jsonify({
            "success":    True,
            "message":    f"Equipo '{team.name}' baneado por {hours}h.",
            "expires_at": record.expires_at.isoformat(),
        }), 200

    # ── Service: Banned teams (para SIEM, autenticación con X-Admin-Key) ────────
    @plugin_bp.route("/api/whaley/service/banned-teams", methods=["GET"])
    def whaley_service_banned_teams():
        key = request.headers.get("X-Admin-Key", "")
        if not WHALEY_ADMIN_KEY or key != WHALEY_ADMIN_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        now = datetime.utcnow()
        bans = TeamRedFlag.query.filter(
            TeamRedFlag.expires_at > now,
            TeamRedFlag.lifted_at.is_(None),
        ).order_by(TeamRedFlag.banned_at.desc()).all()
        result = []
        for b in bans:
            team = Teams.query.get(b.team_id)
            result.append({
                "id":               b.id,
                "team_id":          b.team_id,
                "team_name":        team.name if team else f"equipo#{b.team_id}",
                "reason":           b.reason,
                "banned_at":        b.banned_at.isoformat(),
                "expires_at":       b.expires_at.isoformat(),
                "remaining_seconds": b.remaining_seconds(),
            })
        return jsonify({"banned_teams": result}), 200

    app.register_blueprint(plugin_bp)

    print(f"[Whaley Plugin] Cargado. URL: {get_whaley_url()}")
    print(f"[Whaley Plugin] Anti-cheat activo: ban de equipo {BAN_HOURS}h · flag prefix '{WHALEY_FLAG_PREFIX}'")
    print(f"[Whaley Plugin] Tabla teams_red_flag habilitada.")
