"""
HackL4bs Achievements — Sistema de logros para HackL4bs CTF.

Logros disponibles:
  ctf_opener     🚀  Primer solve del CTF entero
  first_step     🎯  Tu primer reto resuelto
  blood_hound    🩸  Primer solver de cualquier reto
  night_owl      🦉  Solve entre 00:00 y 05:00
  veteran        🔟  10 retos resueltos
  elite          💀  25 retos resueltos
  speed_demon    ⚡  Solve más rápido en instancia Whaley
  category_clear 🧹  Todos los retos de una categoría
"""
from datetime import datetime
from flask import Blueprint, jsonify, render_template_string, request, session
from sqlalchemy import func
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils.user import get_current_user
from CTFd.plugins import (
    register_plugin_assets_directory,
    register_plugin_script,
    register_plugin_stylesheet,
)


# ── Definición de logros ───────────────────────────────────────────────────────
ACHIEVEMENT_DEFS = [
    {"slug": "ctf_opener",     "icon": "🚀", "name": "Abridor del CTF",    "description": "El primero en resolver cualquier reto en todo el CTF"},
    {"slug": "first_step",     "icon": "🎯", "name": "Primer Paso",         "description": "Resuelve tu primer reto"},
    {"slug": "blood_hound",    "icon": "🩸", "name": "First Blood",         "description": "Primer solver de algún reto"},
    {"slug": "night_owl",      "icon": "🦉", "name": "Búho Nocturno",       "description": "Resuelve un reto entre las 00:00 y las 05:00"},
    {"slug": "veteran",        "icon": "🔟", "name": "Veterano",            "description": "Resuelve 10 retos"},
    {"slug": "elite",          "icon": "💀", "name": "Élite",               "description": "Resuelve 25 retos"},
    {"slug": "speed_demon",    "icon": "⚡", "name": "Speed Demon",         "description": "Solve más rápido de una instancia dinámica"},
    {"slug": "category_clear", "icon": "🧹", "name": "Categoría Completa",  "description": "Resuelve todos los retos de una categoría"},
]
SLUG_TO_DEF = {d["slug"]: d for d in ACHIEVEMENT_DEFS}


# ── Modelo ─────────────────────────────────────────────────────────────────────
class AchievementEarned(db.Model):
    __tablename__ = "hackl4bs_achievement_earned"
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug      = db.Column(db.String(64), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified  = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint("user_id", "slug", name="uq_hl_achievement"),)


# ── Lógica de evaluación ───────────────────────────────────────────────────────
def _has(user_id, slug):
    return bool(AchievementEarned.query.filter_by(user_id=user_id, slug=slug).first())


def _award(user_id, slug):
    if _has(user_id, slug):
        return False
    try:
        db.session.add(AchievementEarned(user_id=user_id, slug=slug))
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    try:
        from CTFd.plugins.discord_notify import notify_achievement
        from CTFd.models import Users, Teams
        user = Users.query.get(user_id)
        team = None
        if user and getattr(user, "team_id", None):
            team = Teams.query.get(user.team_id)
        defn = SLUG_TO_DEF.get(slug, {})
        if user and defn:
            notify_achievement(
                user_name=user.name,
                team_name=team.name if team else None,
                slug=slug,
                icon=defn.get("icon", "🏆"),
                ach_name=defn.get("name", slug),
                description=defn.get("description", ""),
            )
    except Exception:
        pass
    return True


def _flag_belongs_to_other_team(user, submission: str) -> bool:
    """
    Consulta Whaley para saber si la flag pertenece a un equipo diferente al del usuario.
    Retorna True si se debe bloquear el otorgamiento de logros.
    """
    try:
        import os, requests
        from CTFd.plugins.whaley_ctfd_plugin import _check_flag_ownership, get_whaley_url
        admin_key = os.environ.get("WHALEY_ADMIN_KEY", "")
        if not admin_key:
            return False
        ownership = _check_flag_ownership(submission, admin_key)
        if not ownership.get("found"):
            return False
        owner_user_id = str(ownership.get("owner_user_id", ""))
        current_user_id = str(user.id)
        if owner_user_id == current_user_id:
            return False
        # Resolver equipo del dueño desde CTFd si Whaley no lo devolvió
        owner_team_id = str(ownership.get("owner_team_id") or "")
        if not owner_team_id and owner_user_id:
            owner_obj = Users.query.get(int(owner_user_id))
            if owner_obj:
                owner_team_id = str(owner_obj.team_id or "")
        current_team_id = str(user.team_id) if user.team_id else ""
        # Mismo equipo → permitir logros
        if current_team_id and owner_team_id and current_team_id == owner_team_id:
            return False
        return True
    except Exception:
        return False


def _evaluate(user_id, chal_id):
    """Evalúa y otorga logros tras un solve correcto. Se llama desde after_request."""
    now = datetime.utcnow()

    # CTF Opener — primer solve del CTF
    if Solves.query.count() <= 1:
        _award(user_id, "ctf_opener")

    # First Blood — primer solve de este reto
    if Solves.query.filter_by(challenge_id=chal_id).count() <= 1:
        _award(user_id, "blood_hound")

    # Primer Paso / Veterano / Élite
    user_count = Solves.query.filter_by(user_id=user_id).count()
    if user_count <= 1:
        _award(user_id, "first_step")
    if user_count >= 10:
        _award(user_id, "veteran")
    if user_count >= 25:
        _award(user_id, "elite")

    # Night Owl
    if 0 <= now.hour < 5:
        _award(user_id, "night_owl")

    # Category Clear
    chal = Challenges.query.get(chal_id)
    if chal and chal.category:
        cat_total = Challenges.query.filter_by(category=chal.category, state="visible").count()
        cat_solved = (
            db.session.query(func.count(func.distinct(Solves.challenge_id)))
            .join(Challenges, Solves.challenge_id == Challenges.id)
            .filter(
                Challenges.category == chal.category,
                Challenges.state == "visible",
                Solves.user_id == user_id,
            )
            .scalar() or 0
        )
        if cat_total > 0 and cat_solved >= cat_total:
            _award(user_id, "category_clear")

    # Speed Demon — solo si Whaley está activo y registró duración
    try:
        from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
        my_dur = (
            db.session.query(func.min(WhaleyInstanceLog.duration_seconds))
            .filter(
                WhaleyInstanceLog.user_id == user_id,
                WhaleyInstanceLog.challenge_id == chal_id,
                WhaleyInstanceLog.duration_seconds.isnot(None),
            )
            .scalar()
        )
        if my_dur is not None:
            global_min = (
                db.session.query(func.min(WhaleyInstanceLog.duration_seconds))
                .filter(
                    WhaleyInstanceLog.challenge_id == chal_id,
                    WhaleyInstanceLog.duration_seconds.isnot(None),
                )
                .scalar()
            )
            if my_dur == global_min:
                _award(user_id, "speed_demon")
    except Exception:
        pass


# ── Plugin load ────────────────────────────────────────────────────────────────
def load(app):
    with app.app_context():
        db.create_all()

    bp = Blueprint("hackl4bs_achievements", __name__)
    register_plugin_assets_directory(app, base_path="/plugins/hackl4bs_achievements/assets/")
    register_plugin_script("/plugins/hackl4bs_achievements/assets/achievements.js")
    register_plugin_stylesheet("/plugins/hackl4bs_achievements/assets/achievements.css")

    # Hook post-solve en after_request
    @app.after_request
    def _check_achievements_on_solve(response):
        if request.method != "POST" or "/api/v1/challenges/attempt" not in request.path:
            return response
        try:
            resp_json = response.get_json(silent=True) or {}
            if resp_json.get("data", {}).get("status") != "correct":
                return response
            user = get_current_user()
            if not user:
                return response
            req_json = request.get_json(silent=True) or {}
            chal_id = req_json.get("challenge_id")
            if not chal_id:
                return response

            # Segunda línea de defensa: verificar que la flag no pertenece a otro equipo
            submission = (req_json.get("submission") or "").strip()
            if submission and _flag_belongs_to_other_team(user, submission):
                return response

            _evaluate(user.id, int(chal_id))
        except Exception:
            pass
        return response

    # ── API endpoints ──────────────────────────────────────────────────────────

    @bp.route("/api/hackl4bs/achievements/user/<int:user_id>")
    def user_achievements(user_id):
        earned = {
            e.slug: e.earned_at.isoformat()
            for e in AchievementEarned.query.filter_by(user_id=user_id).all()
        }
        result = [
            {**d, "earned": d["slug"] in earned, "earned_at": earned.get(d["slug"])}
            for d in ACHIEVEMENT_DEFS
        ]
        return jsonify({"achievements": result})

    @bp.route("/api/hackl4bs/achievements/pending")
    @authed_only
    def pending_achievements():
        """Retorna logros no notificados aún y los marca como notificados."""
        user = get_current_user()
        pending = AchievementEarned.query.filter_by(user_id=user.id, notified=False).all()
        result = []
        for e in pending:
            defn = SLUG_TO_DEF.get(e.slug)
            if defn:
                result.append({**defn, "earned_at": e.earned_at.isoformat()})
            e.notified = True
        if pending:
            db.session.commit()
        return jsonify({"new": result})

    @bp.route("/api/hackl4bs/achievements/stats")
    def achievements_stats():
        counts = {
            r[0]: r[1]
            for r in db.session.query(
                AchievementEarned.slug, func.count()
            ).group_by(AchievementEarned.slug).all()
        }
        total_users = Users.query.filter_by(hidden=False, banned=False).count()
        return jsonify({
            "achievements": [{**d, "earned_count": counts.get(d["slug"], 0)} for d in ACHIEVEMENT_DEFS],
            "total_users": total_users,
        })

    # ── Admin panel ────────────────────────────────────────────────────────────
    @bp.route("/admin/hackl4bs_achievements")
    @admins_only
    def admin_view():
        counts = {
            r[0]: r[1]
            for r in db.session.query(
                AchievementEarned.slug, func.count()
            ).group_by(AchievementEarned.slug).all()
        }
        total_users = Users.query.filter_by(hidden=False, banned=False).count()
        defs_data = [{**d, "count": counts.get(d["slug"], 0)} for d in ACHIEVEMENT_DEFS]

        recent = (
            AchievementEarned.query
            .order_by(AchievementEarned.earned_at.desc())
            .limit(40).all()
        )
        recent_data = []
        for e in recent:
            u = Users.query.get(e.user_id)
            defn = SLUG_TO_DEF.get(e.slug, {})
            recent_data.append({
                "username": u.name if u else f"user#{e.user_id}",
                "icon": defn.get("icon", "?"),
                "name": defn.get("name", e.slug),
                "earned_at": e.earned_at.strftime("%Y-%m-%d %H:%M"),
            })

        return render_template_string("""
{% extends "admin/base.html" %}
{% block content %}
<div class="jumbotron">
  <div class="container">
    <h1>🏆 Achievements <span style="color:var(--primary)">HackL4bs</span></h1>
    <p class="lead">{{ total_users }} participantes activos — {{ defs|length }} logros definidos.</p>
  </div>
</div>
<div class="container">
  <div class="row mb-4">
    {% for a in defs %}
    <div class="col-md-4 mb-3">
      <div class="card h-100">
        <div class="card-body d-flex align-items-center" style="gap:14px">
          <div style="font-size:38px;line-height:1;flex-shrink:0">{{ a.icon }}</div>
          <div>
            <strong>{{ a.name }}</strong><br>
            <small class="text-muted">{{ a.description }}</small><br>
            <span class="badge badge-primary mt-1">{{ a.count }} / {{ total_users }}</span>
          </div>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <h5 class="mt-2">Últimos 40 logros otorgados</h5>
  <div class="table-responsive">
    <table class="table table-sm table-striped">
      <thead><tr><th>Logro</th><th>Usuario</th><th>Fecha</th></tr></thead>
      <tbody>
        {% for r in recent %}
        <tr>
          <td>{{ r.icon }} {{ r.name }}</td>
          <td>{{ r.username }}</td>
          <td><small class="text-muted">{{ r.earned_at }}</small></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
""", defs=defs_data, total_users=total_users, recent=recent_data, nonce=session.get("nonce"))

    app.register_blueprint(bp)
    print("[HackL4bs Achievements] Plugin cargado — 8 logros.")
