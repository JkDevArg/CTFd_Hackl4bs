import requests
import os
from flask import Blueprint, request, jsonify, session, render_template_string
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils import get_config, set_config
from CTFd.utils.user import get_current_user

# URL de Whaley (configurable via variable de entorno o config de CTFd)
WHALEY_URL = os.environ.get("WHALEY_URL", "http://localhost:8001")
WHALEY_ADMIN_KEY = os.environ.get("WHALEY_ADMIN_KEY", "")

def get_whaley_url():
    """Obtiene la URL de Whaley desde config de CTFd o variable de entorno."""
    url = get_config("whaley_url")
    return url if url else WHALEY_URL

def get_user_token():
    """Obtiene el token de acceso del usuario actual desde la sesión/DB."""
    from CTFd.models import Tokens
    user = get_current_user()
    if not user:
        return None
    token = Tokens.query.filter_by(user_id=user.id).first()
    if token:
        return token.value
    return None

# ── Template del snippet HTML que inyectamos en el <head> de cada página ──────
INJECT_SCRIPT = """
<script>
  // Configuración de Whaley inyectada por el plugin
  window.__WHALEY_API__ = "/api/whaley";
</script>
<script defer src="/plugins/whaley_ctfd_plugin/assets/whaley.js"></script>
"""

ADMIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>Whaley Plugin Config</title>
  <link rel="stylesheet" href="/themes/core/static/css/main.min.css">
  <style>
    body { padding: 40px; max-width: 600px; margin: auto; }
    .card { padding: 24px; border-radius: 8px; border: 1px solid #dee2e6; margin-top: 20px; }
    .status { padding: 10px; border-radius: 6px; margin-top: 16px; font-family: monospace; font-size: 13px; }
    .status.ok { background: #d4edda; color: #155724; }
    .status.err { background: #f8d7da; color: #721c24; }
  </style>
</head>
<body>
  <h2>🐳 Whaley Plugin</h2>
  <div class="card">
    <h5>Configuración</h5>
    <form method="POST">
      <div style="margin-bottom:16px">
        <label><strong>URL de Whaley</strong></label><br>
        <input type="text" name="whaley_url" value="{{ current_url }}"
               style="width:100%;padding:8px;margin-top:6px;border:1px solid #ccc;border-radius:4px">
        <small style="color:#666">Ej: http://host.docker.internal:8001 o http://whaley:8001</small>
      </div>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </form>
    {% if saved %}
    <div class="status ok">✓ Configuración guardada correctamente.</div>
    {% endif %}
    {% if conn_status %}
    <div class="status {{ 'ok' if conn_ok else 'err' }}">
      {{ conn_status }}
    </div>
    {% endif %}
  </div>
  <div class="card" style="margin-top:16px">
    <h5>Test de conexión</h5>
    <form method="GET">
      <input type="hidden" name="test" value="1">
      <button type="submit" class="btn btn-secondary">Probar conexión con Whaley</button>
    </form>
  </div>
</body>
</html>
"""
from CTFd.models import db, Solves
from sqlalchemy import event
from sqlalchemy.sql import text
from datetime import datetime, timedelta

# ── Modelos de base de datos ──────────────────────────────────────────────────

class WhaleyInstanceLog(db.Model):
    __tablename__ = "whaley_instance_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id', ondelete='CASCADE'))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    solve_time = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)


class WhaleyPenalty(db.Model):
    """Penalizaciones activas por uso de flags ajenas."""
    __tablename__ = "whaley_penalty"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    penalty_type = db.Column(db.String(32), nullable=False)   # 'block' | 'ban'
    reason = db.Column(db.String(255))
    offending_flag = db.Column(db.String(512))
    challenge_id = db.Column(db.Integer, nullable=True)
    offender_team_id = db.Column(db.Integer, nullable=True)
    owner_user_id = db.Column(db.String(64), nullable=True)   # quien generó la flag
    owner_team_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    def is_active(self):
        return datetime.utcnow() < self.expires_at

    def remaining_seconds(self):
        delta = (self.expires_at - datetime.utcnow()).total_seconds()
        return max(0, int(delta))

    def remaining_str(self):
        secs = self.remaining_seconds()
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"


# ── Helpers Discord ───────────────────────────────────────────────────────────

def _discord_color(penalty_type: str) -> int:
    return 0xFF0000 if penalty_type == "ban" else 0xFFA500


def _send_discord_penalty(
    webhook_url: str,
    username: str,
    team_name: str,
    challenge_name: str,
    owner_username: str,
    owner_team_name: str,
    penalty_type: str,
    remaining_str: str,
):
    """
    Envía un embed a Discord notificando la penalización.
    Recibe solo datos primitivos para que sea seguro ejecutar en un thread separado
    sin depender de la sesión SQLAlchemy del request original.
    """
    if not webhook_url:
        return

    if penalty_type == "ban":
        title = "🚨 Ban por uso de flag de otro equipo"
        description = (
            f"**{username}** (equipo: **{team_name or 'sin equipo'}**) intentó usar "
            f"la flag de **{owner_username}** (equipo: **{owner_team_name or '?'}**) "
            f"en el reto **{challenge_name}**.\n\n"
            f"**Sanción:** Ban de **{remaining_str}**."
        )
    else:
        title = "⚠️ Penalización por compartir flag de equipo"
        description = (
            f"**{username}** (equipo: **{team_name or 'sin equipo'}**) usó la flag de su "
            f"compañero **{owner_username}** en el reto **{challenge_name}**.\n\n"
            f"**Sanción:** Bloqueado por **{remaining_str}**. No se otorgaron puntos."
        )

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": _discord_color(penalty_type),
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Whaley Anti-Cheat"},
        }]
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Whaley] Discord webhook error: {e}")


# ── Check flag ownership en Whaley ────────────────────────────────────────────

def _check_flag_ownership(flag_string: str, admin_token: str) -> dict:
    """
    Consulta el endpoint /admin/api/check-flag de Whaley.
    Retorna el dict de respuesta o {} en caso de error.
    """
    try:
        resp = requests.post(
            get_whaley_url() + "/admin/api/check-flag",
            json={"flag": flag_string},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[Whaley] check-flag error: {e}")
    return {}


@event.listens_for(Solves, 'after_insert')
def record_whaley_solve_time(mapper, connection, target):
    try:
        query = text("SELECT id, start_time FROM whaley_instance_log WHERE user_id = :u AND challenge_id = :c AND solve_time IS NULL ORDER BY start_time DESC LIMIT 1")
        result = connection.execute(query, {"u": target.user_id, "c": target.challenge_id}).fetchone()
        if result:
            log_id, start_time = result
            solve_date = target.date or datetime.utcnow()
            
            # Convierte strings a datetime si la DB (como SQLite) retorna strings
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
                update_q = text("UPDATE whaley_instance_log SET solve_time = :st, duration_seconds = :d WHERE id = :id")
                connection.execute(update_q, {"st": solve_date, "d": diff, "id": log_id})
    except Exception as e:
        print("Error en record_whaley_solve_time:", e)

def load(app):
    with app.app_context():
        db.create_all()

    plugin_bp = Blueprint("whaley", __name__, template_folder="templates")

    register_plugin_assets_directory(app, base_path="/plugins/whaley_ctfd_plugin/assets/")

    # ─── Guard de submissions: penaliza uso de flags ajenas en tiempo real ────
    @app.before_request
    def whaley_submission_guard():
        """
        Intercepta intentos de submit en /api/v1/challenges/attempt.
        Reglas:
          - Flag propia            → deja pasar (CTFd valida normalmente)
          - Flag de compañero      → bloquea 10 min, no suma puntos, log Discord
          - Flag de otro equipo    → ban 2 horas, log Discord
        Solo actúa cuando DYNAMIC_FLAGS_ENABLED está activo en Whaley.
        """
        from flask import g
        if request.path != "/api/v1/challenges/attempt" or request.method != "POST":
            return

        user = get_current_user()
        if not user or user.type == "admin":
            return

        # 1. Bloquear si hay una penalización vigente
        now = datetime.utcnow()
        active_penalty = (
            WhaleyPenalty.query
            .filter(WhaleyPenalty.user_id == user.id, WhaleyPenalty.expires_at > now)
            .order_by(WhaleyPenalty.expires_at.desc())
            .first()
        )
        if active_penalty:
            rem = active_penalty.remaining_str()
            if active_penalty.penalty_type == "ban":
                msg = f"Estás baneado por compartir flags. Tiempo restante: {rem}."
            else:
                msg = f"Estás bloqueado por usar la flag de un compañero. Tiempo restante: {rem}."
            return jsonify({"success": False, "data": {"status": "incorrect", "message": msg}}), 200

        # 2. Leer el flag del body (sin consumir el stream)
        body = request.get_json(silent=True, force=True)
        if not body:
            return
        submission = (body.get("submission") or "").strip()
        challenge_id = body.get("challenge_id")
        if not submission or not challenge_id:
            return

        # 3. Consultar Whaley para saber de quién es la flag
        admin_key = WHALEY_ADMIN_KEY
        if not admin_key:
            return  # Sin clave admin no podemos verificar, dejamos pasar

        ownership = _check_flag_ownership(submission, admin_key)
        if not ownership.get("found"):
            return  # No es una flag dinámica de Whaley → CTFd la maneja normalmente

        owner_user_id = str(ownership.get("owner_user_id", ""))
        owner_team_id = str(ownership.get("owner_team_id") or "")
        owner_username = ownership.get("owner_username", "desconocido")
        owner_team_name = ownership.get("owner_team_name", "")

        current_user_id = str(user.id)
        current_team_id = str(user.team_id) if user.team_id else ""

        # Flag propia → deja pasar
        if owner_user_id == current_user_id:
            return

        # Recopilar datos primitivos para el thread de Discord (antes de cualquier commit)
        import threading
        from CTFd.models import Challenges, Teams as CTFdTeams
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        _user_name = user.name
        _user_team_name = ""
        if user.team_id:
            try:
                t = CTFdTeams.query.get(user.team_id)
                if t:
                    _user_team_name = t.name
            except Exception:
                pass
        _chal_name = str(challenge_id)
        try:
            chal = Challenges.query.get(int(challenge_id))
            if chal:
                _chal_name = f"{chal.name} (#{challenge_id})"
        except Exception:
            pass

        # Flag de compañero de equipo → penalización 10 minutos
        if current_team_id and owner_team_id == current_team_id:
            expires = now + timedelta(minutes=10)
            penalty = WhaleyPenalty(
                user_id=user.id,
                penalty_type="block",
                reason="Usó flag de su compañero de equipo",
                offending_flag=submission,
                challenge_id=challenge_id,
                offender_team_id=user.team_id,
                owner_user_id=owner_user_id,
                owner_team_id=owner_team_id,
                expires_at=expires,
            )
            db.session.add(penalty)
            db.session.commit()
            threading.Thread(
                target=_send_discord_penalty,
                args=(webhook_url, _user_name, _user_team_name, _chal_name,
                      owner_username, owner_team_name, "block", penalty.remaining_str()),
                daemon=True,
            ).start()
            return jsonify({
                "success": False,
                "data": {
                    "status": "incorrect",
                    "message": (
                        "⚠️ Esa flag fue generada para tu compañero de equipo. "
                        "No se otorgan puntos. Bloqueado por 10 minutos."
                    ),
                },
            }), 200

        # Flag de otro equipo → ban 2 horas
        if owner_team_id and owner_team_id != current_team_id:
            expires = now + timedelta(hours=2)
            penalty = WhaleyPenalty(
                user_id=user.id,
                penalty_type="ban",
                reason="Usó flag de otro equipo",
                offending_flag=submission,
                challenge_id=challenge_id,
                offender_team_id=user.team_id,
                owner_user_id=owner_user_id,
                owner_team_id=owner_team_id,
                expires_at=expires,
            )
            db.session.add(penalty)
            db.session.commit()
            threading.Thread(
                target=_send_discord_penalty,
                args=(webhook_url, _user_name, _user_team_name, _chal_name,
                      owner_username, owner_team_name, "ban", penalty.remaining_str()),
                daemon=True,
            ).start()
            return jsonify({
                "success": False,
                "data": {
                    "status": "incorrect",
                    "message": (
                        "🚨 Esa flag pertenece a otro equipo. "
                        "Esto ha sido registrado. Ban de 2 horas."
                    ),
                },
            }), 200

    # ─── Inyectar script en TODAS las páginas via after_request ──────────────
    @app.after_request
    def inject_whaley_script(response):
        """Inyecta el JS de Whaley en páginas HTML antes de </head>."""
        if response.content_type and "text/html" in response.content_type:
            data = response.get_data(as_text=True)
            if "</head>" in data and "whaley.js" not in data:
                data = data.replace("</head>", INJECT_SCRIPT + "</head>", 1)
                response.set_data(data)
        return response

    def whaley_headers(token):
        """Cabeceras correctas para autenticar contra Whaley con token de CTFd."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    # Caché del mapeo CTFd numeric ID → Whaley local ID
    # Formato: {ctfd_id_str: (local_id, timestamp)}
    _whaley_id_cache: dict = {}
    _WHALEY_CACHE_TTL = 60  # segundos

    def resolve_whaley_id(ctfd_challenge_id, token):
        """
        Convierte el ID numérico de CTFd al ID de texto local de Whaley.
        Usa caché en memoria con TTL de 60 s para evitar una llamada HTTP
        a /admin/api/flags en cada spawn/status/stop.
        """
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
                headers=whaley_headers(token),
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                mapping = data.get("challenge_mapping", {})
                # Refrescar toda la tabla de caché de una sola vez
                now = time.time()
                for local_id, mapped_ctfd_id in mapping.items():
                    _whaley_id_cache[str(mapped_ctfd_id)] = (local_id, now)
                if key in _whaley_id_cache:
                    return _whaley_id_cache[key][0]
        except Exception:
            pass
        return key

    # ─── API: Spawn de instancia ──────────────────────────────────────────────
    # Ruta real de Whaley: POST /instances/spawn
    @plugin_bp.route("/api/whaley/spawn", methods=["POST"])
    @authed_only
    def whaley_spawn():
        data = request.get_json()
        ctfd_challenge_id = data.get("challenge_id")
        if not ctfd_challenge_id:
            return jsonify({"success": False, "message": "challenge_id requerido"}), 400

        token = get_user_token()
        if not token:
            return jsonify({
                "success": False,
                "message": "No tienes un Access Token. Ve a Settings \u2192 Access Tokens y crea uno."
            }), 403

        # Convertir ID numérico de CTFd → ID texto local de Whaley
        whaley_challenge_id = resolve_whaley_id(ctfd_challenge_id, token)

        whaley_base = get_whaley_url()
        try:
            resp = requests.post(
                f"{whaley_base}/instances/spawn",
                json={"challenge_id": whaley_challenge_id},
                headers=whaley_headers(token),
                timeout=30
            )
            result = resp.json()

            # Normalizar la respuesta para el JS del frontend
            if resp.status_code == 200 and result.get("success"):
                try:
                    user = get_current_user()
                    if user:
                        # Guardar en base de datos la fecha de inicio
                        log = WhaleyInstanceLog(user_id=user.id, challenge_id=ctfd_challenge_id)
                        db.session.add(log)
                        db.session.commit()
                except Exception as e:
                    print("Error registrando log de instancia Whaley:", e)
                    
                instance = result.get("instance", {})
                public_urls = instance.get("public_urls", {})
                # Tomar el primer puerto disponible
                first_url = instance.get("public_url", "")
                host, port = ("", "")
                if first_url and ":" in first_url:
                    parts = first_url.rsplit(":", 1)
                    host, port = parts[0], parts[1]

                expires_at = instance.get("expires_at", "")
                return jsonify({
                    "success": True,
                    "host": host,
                    "port": port,
                    "public_url": first_url,
                    "public_urls": public_urls,
                    "instance_id": instance.get("instance_id", ""),
                    "expires_in": 3600,
                    "expires_at": expires_at
                })
            return jsonify({"success": False, "message": result.get("detail", str(result))}), resp.status_code

        except requests.exceptions.ConnectionError:
            return jsonify({
                "success": False,
                "message": f"No se puede conectar a Whaley en {whaley_base}. ¿Está corriendo?"
            }), 503
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ─── API: Estado de instancia ─────────────────────────────────────────────
    # Ruta real de Whaley: GET /instances  (lista y filtramos por challenge_id)
    @plugin_bp.route("/api/whaley/status/<challenge_id>", methods=["GET"])
    @authed_only
    def whaley_status(challenge_id):
        token = get_user_token()
        if not token:
            return jsonify({"running": False}), 200

        current_user = get_current_user()
        whaley_challenge_id = resolve_whaley_id(challenge_id, token)
        whaley_base = get_whaley_url()
        try:
            resp = requests.get(
                f"{whaley_base}/instances",
                headers=whaley_headers(token),
                timeout=10
            )
            if resp.status_code != 200:
                return jsonify({"running": False}), 200

            instances = resp.json().get("instances", [])
            for inst in instances:
                if str(inst.get("challenge_id", "")) == str(whaley_challenge_id) or str(inst.get("challenge_id", "")) == str(challenge_id):
                    public_url = inst.get("public_url", "")
                    host, port = ("", "")
                    if public_url and ":" in public_url:
                        parts = public_url.rsplit(":", 1)
                        host, port = parts[0], parts[1]
                    owner_user_id = str(inst.get("user_id", ""))
                    is_mine = (owner_user_id == str(current_user.id)) if current_user else False
                    return jsonify({
                        "running": True,
                        "host": host,
                        "port": port,
                        "public_url": public_url,
                        "public_urls": inst.get("public_urls", {}),
                        "instance_id": inst.get("instance_id", ""),
                        "expires_at": inst.get("expires_at", ""),
                        "spawned_by": inst.get("username", ""),
                        "is_mine": is_mine,
                    })
            return jsonify({"running": False}), 200
        except Exception:
            return jsonify({"running": False}), 200

    # ─── API: Lista de instancias ───────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/instances", methods=["GET"])
    @authed_only
    def whaley_list_instances():
        token = get_user_token()
        if not token:
            return jsonify({"instances": []}), 200

        current_user = get_current_user()
        whaley_base = get_whaley_url()
        try:
            resp = requests.get(
                f"{whaley_base}/instances",
                headers=whaley_headers(token),
                timeout=10
            )
            if resp.status_code == 200:
                instances = resp.json().get("instances", [])
                for inst in instances:
                    owner_id = str(inst.get("user_id", ""))
                    inst["is_mine"] = (owner_id == str(current_user.id)) if current_user else False
                    inst.setdefault("spawned_by", inst.get("username", ""))
                return jsonify({"instances": instances}), 200
            return jsonify({"instances": []}), 200
        except Exception:
            return jsonify({"instances": []}), 200

    @plugin_bp.route("/api/whaley/stats/<int:challenge_id>", methods=["GET"])
    def whaley_stats(challenge_id):
        from CTFd.models import Users, Teams
        from CTFd.utils import get_config
        first_blood = None
        fastest = None
        
        mode = get_config("user_mode")
        
        # 1. First Blood
        # Removemos filtros de hidden para que los admin aparezcan en sus pruebas
        first_solve = Solves.query.filter_by(challenge_id=challenge_id).order_by(Solves.date.asc()).first()
        
        if first_solve:
            # Obtener nombre según el modo (Equipo o Usuario)
            name = ""
            if mode == "teams" and first_solve.team:
                name = first_solve.team.name
            else:
                name = first_solve.user.name
                
            first_blood = {
                "user_name": name,
                "date": first_solve.date.isoformat() if first_solve.date else None
            }
            
        # 2. Fastest Solve (Instancia Whaley)
        fastest_log = WhaleyInstanceLog.query.filter(
            WhaleyInstanceLog.challenge_id == challenge_id,
            WhaleyInstanceLog.duration_seconds != None
        ).order_by(WhaleyInstanceLog.duration_seconds.asc()).first()
        
        if fastest_log:
            duration = int(fastest_log.duration_seconds)
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                time_str = f"{hours}h {mins}m {secs}s"
            elif mins > 0:
                time_str = f"{mins}m {secs}s"
            else:
                time_str = f"{secs}s"
                
            user = Users.query.get(fastest_log.user_id)
            if user:
                # Si estamos en modo equipos, queremos el nombre del equipo para que coincida con la tabla de Solves
                display_name = user.name
                if mode == "teams" and user.team:
                    display_name = user.team.name
                    
                fastest = {
                    "user_name": display_name,
                    "time_str": time_str,
                    "seconds": duration
                }
            
        return jsonify({
            "first_blood": first_blood,
            "fastest": fastest
        }), 200

    # ─── API: Extender instancia (+N minutos) ────────────────────────────────
    @plugin_bp.route("/api/whaley/extend", methods=["POST"])
    @authed_only
    def whaley_extend():
        data = request.get_json()
        instance_id = data.get("instance_id")
        extra_minutes = int(data.get("extra_minutes", 30))
        if not instance_id:
            return jsonify({"success": False, "message": "instance_id requerido"}), 400

        token = get_user_token()
        if not token:
            return jsonify({"success": False, "message": "Sin token"}), 403

        whaley_base = get_whaley_url()
        try:
            resp = requests.post(
                f"{whaley_base}/instances/{instance_id}/extend",
                json={"extra_minutes": extra_minutes},
                headers=whaley_headers(token),
                timeout=15
            )
            result = resp.json()
            if resp.status_code == 200:
                return jsonify({"success": True, "message": result.get("message", "Extendida")})
            return jsonify({"success": False, "message": result.get("detail", str(result))}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ─── API: Terminar instancia ──────────────────────────────────────────────
    # Ruta real de Whaley: DELETE /instances/{instance_id}
    @plugin_bp.route("/api/whaley/stop", methods=["POST"])
    @authed_only
    def whaley_stop():
        data = request.get_json()
        instance_id = data.get("instance_id")
        challenge_id = data.get("challenge_id")
        token = get_user_token()

        if not token:
            return jsonify({"success": False, "message": "Sin token"}), 403

        whaley_base = get_whaley_url()

        # Si no tenemos instance_id directo, buscarlo primero
        if not instance_id and challenge_id:
            whaley_challenge_id = resolve_whaley_id(challenge_id, token)
            try:
                resp = requests.get(
                    f"{whaley_base}/instances",
                    headers=whaley_headers(token),
                    timeout=10
                )
                if resp.status_code == 200:
                    for inst in resp.json().get("instances", []):
                        if str(inst.get("challenge_id", "")) == str(whaley_challenge_id) or str(inst.get("challenge_id", "")) == str(challenge_id):
                            instance_id = inst.get("instance_id")
                            break
            except Exception:
                pass

        if not instance_id:
            return jsonify({"success": False, "message": "Instancia no encontrada"}), 404

        try:
            resp = requests.delete(
                f"{whaley_base}/instances/{instance_id}",
                headers=whaley_headers(token),
                timeout=15
            )
            if resp.status_code in (200, 204):
                return jsonify({"success": True})
            return jsonify({"success": False, "message": resp.text}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    # ─── Admin: Configuración (visible en /admin/whaley) ─────────────────────
    @plugin_bp.route("/admin/whaley", methods=["GET", "POST"])
    @admins_only
    def whaley_admin_config():
        saved = False
        conn_status = None
        conn_ok = False

        if request.method == "POST":
            set_config("whaley_url", request.form.get("whaley_url", "").rstrip("/"))
            saved = True

        # Test de conexión — usa /health (ruta real de Whaley)
        if request.args.get("test"):
            try:
                resp = requests.get(get_whaley_url() + "/health", timeout=5)
                conn_ok = resp.status_code < 400
                conn_status = f"✓ Whaley responde en {get_whaley_url()} (HTTP {resp.status_code})" if conn_ok \
                              else f"✗ Whaley respondió HTTP {resp.status_code}"
            except Exception as e:
                conn_status = f"✗ No se pudo conectar: {e}"
                conn_ok = False

        return render_template_string(
            ADMIN_PAGE,
            current_url=get_whaley_url(),
            saved=saved,
            conn_status=conn_status,
            conn_ok=conn_ok
        )

    # ─── API: Penalizaciones activas (para el usuario actual) ────────────────
    @plugin_bp.route("/api/whaley/my-penalty", methods=["GET"])
    @authed_only
    def whaley_my_penalty():
        """Devuelve la penalización activa del usuario actual, si existe."""
        user = get_current_user()
        if not user:
            return jsonify({"active": False}), 200
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
            "active": True,
            "type": penalty.penalty_type,
            "reason": penalty.reason,
            "remaining_seconds": penalty.remaining_seconds(),
            "remaining_str": penalty.remaining_str(),
            "expires_at": penalty.expires_at.isoformat(),
        }), 200

    # ─── API Admin: Ver todas las penalizaciones ──────────────────────────────
    @plugin_bp.route("/api/whaley/admin/penalties", methods=["GET"])
    @admins_only
    def whaley_admin_penalties():
        """Lista todas las penalizaciones (activas e históricas)."""
        from CTFd.models import Users
        active_only = request.args.get("active") == "1"
        now = datetime.utcnow()
        q = WhaleyPenalty.query
        if active_only:
            q = q.filter(WhaleyPenalty.expires_at > now)
        penalties = q.order_by(WhaleyPenalty.created_at.desc()).limit(200).all()
        result = []
        for p in penalties:
            u = Users.query.get(p.user_id)
            result.append({
                "id": p.id,
                "username": u.name if u else f"user#{p.user_id}",
                "type": p.penalty_type,
                "reason": p.reason,
                "challenge_id": p.challenge_id,
                "created_at": p.created_at.isoformat(),
                "expires_at": p.expires_at.isoformat(),
                "active": p.is_active(),
                "remaining_str": p.remaining_str() if p.is_active() else "expirada",
            })
        return jsonify({"penalties": result}), 200

    # ─── API Admin: Levantar penalización manualmente ────────────────────────
    @plugin_bp.route("/api/whaley/admin/penalties/<int:penalty_id>/lift", methods=["POST"])
    @admins_only
    def whaley_admin_lift_penalty(penalty_id):
        """El admin puede levantar una penalización antes de que expire."""
        penalty = WhaleyPenalty.query.get(penalty_id)
        if not penalty:
            return jsonify({"success": False, "message": "Penalización no encontrada"}), 404
        penalty.expires_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True, "message": "Penalización levantada"}), 200

    # ─── API: Actividad del equipo ────────────────────────────────────────────
    @plugin_bp.route("/api/whaley/team-activity", methods=["GET"])
    @authed_only
    def whaley_team_activity():
        from CTFd.models import Teams, Users, Challenges

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
            username = u.name if u else f"user#{log.user_id}"
            chal_name = c.name if c else f"reto#{log.challenge_id}"
            is_me = (log.user_id == user.id)

            if log.solve_time and log.duration_seconds is not None:
                mins, secs = divmod(int(log.duration_seconds), 60)
                duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                events.append({
                    "type": "solved",
                    "username": username,
                    "challenge": chal_name,
                    "time": log.solve_time.isoformat() + "Z",
                    "duration": duration_str,
                    "is_me": is_me,
                })

            if log.start_time:
                events.append({
                    "type": "started",
                    "username": username,
                    "challenge": chal_name,
                    "time": log.start_time.isoformat() + "Z",
                    "is_me": is_me,
                })

        events.sort(key=lambda x: x["time"], reverse=True)
        return jsonify({"events": events[:20]})

    app.register_blueprint(plugin_bp)

    print("[Whaley Plugin] Cargado correctamente. Whaley URL:", get_whaley_url())
    print("[Whaley Plugin] Anti-cheat guard activo: penalizaciones en tiempo real")
    print("[Whaley Plugin] Panel de admin disponible en: /admin/whaley")
