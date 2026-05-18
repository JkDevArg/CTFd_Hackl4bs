"""
HackL4bs Scoreboard Plugin
Muestra Top 10 de equipos en la home con: puntos, retos resueltos, first bloods y fast solves.
"""
from flask import Blueprint, jsonify, render_template_string, request, session
from CTFd.models import Teams, Users, Solves, Challenges, db
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils.scores import get_standings
from CTFd.utils.user import is_admin, get_current_user
from CTFd.plugins import register_plugin_assets_directory, register_plugin_script, register_plugin_stylesheet
from sqlalchemy import func


def load(app):
    bp = Blueprint("hackl4bs_scoreboard", __name__)

    CFG_ENABLE = "hackl4bs_score_enable"
    CFG_TITLE  = "hackl4bs_score_title"
    CFG_LIMIT  = "hackl4bs_score_limit"

    def _cfg(key, default=""):
        val = get_config(key)
        return val if val is not None else default

    # ── Admin config ──────────────────────────────────────────────────────────
    @bp.route("/admin/hackl4bs_scoreboard", methods=["GET", "POST"])
    @admins_only
    def admin_config():
        saved = False
        if request.method == "POST":
            set_config(CFG_ENABLE, request.form.get("enable", "0"))
            set_config(CFG_TITLE,  request.form.get("title",  "🏆 TOP 10 LEADERBOARD 🏆"))
            set_config(CFG_LIMIT,  request.form.get("limit",  "10"))
            saved = True

        return render_template_string("""
        {% extends "admin/base.html" %}
        {% block content %}
        <div class="jumbotron">
          <div class="container">
            <h1>🏆 HackL4bs <span style="color:var(--primary)">Top 10 Scoreboard</span></h1>
            <p class="lead">Widget animado en la home con puntos, retos, first bloods y fast solves.</p>
          </div>
        </div>
        <div class="container">
          {% if saved %}<div class="alert alert-success">✅ Configuración guardada</div>{% endif %}
          <form method="POST">
            <input type="hidden" name="nonce" value="{{ nonce }}">
            <div class="card"><div class="card-body">
              <div class="form-group">
                <label>Título del Widget</label>
                <input type="text" name="title" value="{{ title }}" class="form-control">
              </div>
              <div class="form-group">
                <label>Cantidad de equipos (máximo)</label>
                <input type="number" name="limit" value="{{ limit }}" class="form-control" min="1" max="50">
              </div>
              <div class="form-check">
                <input type="checkbox" class="form-check-input" name="enable" value="1"
                       {% if enable == '1' %}checked{% endif %} id="enableCheck">
                <label class="form-check-label" for="enableCheck">Habilitar widget en la home</label>
              </div>
            </div></div>
            <button type="submit" class="btn btn-primary mt-3">Guardar</button>
          </form>
        </div>
        {% endblock %}
        """, saved=saved,
             enable=_cfg(CFG_ENABLE, "1"),
             title=_cfg(CFG_TITLE, "🏆 TOP 10 LEADERBOARD 🏆"),
             limit=_cfg(CFG_LIMIT, "10"),
             nonce=session.get("nonce"))

    # ── API Top 10 ────────────────────────────────────────────────────────────
    @bp.route("/api/v1/hackl4bs/top10")
    def api_top10():
        """
        Devuelve el Top N de equipos con:
          - score         : puntos totales
          - solve_count   : retos distintos resueltos por el equipo
          - first_blood   : retos donde el equipo fue el primero en resolver
          - fast_solve    : retos donde algún miembro tuvo el solve más rápido (Whaley)
          - members       : lista de miembros con puntos individuales
        No requiere autenticación para que sea visible en la home sin login.
        """
        if _cfg(CFG_ENABLE, "1") != "1":
            return jsonify({"success": False, "error": "disabled"})

        mode  = get_config("user_mode") or "teams"
        limit = max(1, min(50, int(_cfg(CFG_LIMIT, "10"))))

        standings = get_standings(count=limit, admin=True)
        if not standings:
            return jsonify({"success": True, "data": {
                "title": _cfg(CFG_TITLE, "🏆 TOP 10 LEADERBOARD 🏆"),
                "standings": [],
            }})

        # Pre-calcular first-blood subquery (una sola vez para todos los equipos)
        fb_sub = (
            db.session.query(
                Solves.challenge_id,
                func.min(Solves.date).label("first_date"),
            )
            .group_by(Solves.challenge_id)
            .subquery()
        )

        # Pre-calcular fast-solve subquery si Whaley está disponible
        fast_sub = None
        WhaleyLog = None
        try:
            from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
            WhaleyLog = WhaleyInstanceLog
            fast_sub = (
                db.session.query(
                    WhaleyInstanceLog.challenge_id,
                    func.min(WhaleyInstanceLog.duration_seconds).label("min_dur"),
                )
                .filter(WhaleyInstanceLog.duration_seconds.isnot(None))
                .group_by(WhaleyInstanceLog.challenge_id)
                .subquery()
            )
        except Exception:
            pass

        result = []
        for i, s in enumerate(standings):
            # Miembros del equipo
            if mode == "teams":
                members_q = Users.query.filter_by(
                    team_id=s.account_id, hidden=False, banned=False
                ).all()
            else:
                u = Users.query.get(s.account_id)
                members_q = [u] if u else []

            member_ids = [m.id for m in members_q]
            if not member_ids:
                member_ids = [-1]  # evita IN ()

            # ── Retos resueltos (distintos) ───────────────────────────────────
            solve_count = (
                db.session.query(func.count(func.distinct(Solves.challenge_id)))
                .filter(Solves.user_id.in_(member_ids))
                .scalar() or 0
            )

            # ── First bloods ──────────────────────────────────────────────────
            first_blood = (
                db.session.query(func.count())
                .select_from(Solves)
                .join(fb_sub, (Solves.challenge_id == fb_sub.c.challenge_id) &
                               (Solves.date == fb_sub.c.first_date))
                .filter(Solves.user_id.in_(member_ids))
                .scalar() or 0
            )

            # ── Fast solves (solo si Whaley está activo) ──────────────────────
            fast_solve = 0
            if fast_sub is not None and WhaleyLog is not None:
                try:
                    fast_solve = (
                        db.session.query(func.count())
                        .select_from(WhaleyLog)
                        .join(fast_sub,
                              (WhaleyLog.challenge_id == fast_sub.c.challenge_id) &
                              (WhaleyLog.duration_seconds == fast_sub.c.min_dur))
                        .filter(WhaleyLog.user_id.in_(member_ids))
                        .scalar() or 0
                    )
                except Exception:
                    pass

            # ── Puntos por miembro ────────────────────────────────────────────
            members_data = []
            for m in sorted(members_q, key=lambda x: x.id):
                pts = (
                    db.session.query(func.sum(Challenges.value))
                    .join(Solves, Solves.challenge_id == Challenges.id)
                    .filter(Solves.user_id == m.id)
                    .scalar() or 0
                )
                m_solves = Solves.query.filter_by(user_id=m.id).count()
                members_data.append({
                    "id": m.id,
                    "name": m.name,
                    "score": int(pts),
                    "solves": m_solves,
                })

            result.append({
                "rank": i + 1,
                "id": s.account_id,
                "name": s.name,
                "score": int(s.score),
                "solve_count": solve_count,
                "first_blood": first_blood,
                "fast_solve": fast_solve,
                "members": sorted(members_data, key=lambda x: -x["score"]),
            })

        return jsonify({
            "success": True,
            "data": {
                "title": _cfg(CFG_TITLE, "🏆 TOP 10 LEADERBOARD 🏆"),
                "standings": result,
            },
        })

    app.register_blueprint(bp)
    register_plugin_assets_directory(app, base_path="/plugins/hackl4bs_scoreboard/assets")
    register_plugin_script("/plugins/hackl4bs_scoreboard/assets/scoreboard.js")
    register_plugin_stylesheet("/plugins/hackl4bs_scoreboard/assets/hackl4bs.css")

    print("[HackL4bs Scoreboard] Plugin cargado.")
