"""
HackL4bs UX Plugin — Mejoras de experiencia de usuario para HackL4bs CTF.

Features con backend:
  3. Progreso por categoría
  2. First bloods feed
  5. Rating de dificultad (post-solve)
  6. Activity feed del equipo
  7. Stats de perfil (solve timeline + breakdown)
  8. Info del CTF para countdown
  9. "Trabajando en esto" + team working view
"""
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.models import db, Solves, Challenges, Users, Teams
from CTFd.utils import get_config
from sqlalchemy import func, desc
from sqlalchemy import event as sa_event


# ── Modelos ───────────────────────────────────────────────────────────────────

class ChallengeRating(db.Model):
    __tablename__ = "hackl4bs_rating"
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("challenge_id", "user_id", name="uq_ux_rating"),)


class ChallengeWorking(db.Model):
    __tablename__ = "hackl4bs_working"
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    team_id = db.Column(db.Integer, nullable=True)
    username = db.Column(db.String(128))
    challenge_name = db.Column(db.String(256))
    started_at = db.Column(db.DateTime, default=datetime.utcnow)


class TeamNote(db.Model):
    __tablename__ = "hackl4bs_team_notes"
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, nullable=False, unique=True)
    content = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(128))


# Al resolver, borrar automáticamente el "working on" de ese usuario
@sa_event.listens_for(Solves, "after_insert")
def clear_working_on_solve(mapper, connection, target):
    try:
        connection.execute(
            ChallengeWorking.__table__.delete().where(
                ChallengeWorking.__table__.c.user_id == target.user_id
            )
        )
    except Exception:
        pass


# ── Plugin load ───────────────────────────────────────────────────────────────

def load(app):
    with app.app_context():
        db.create_all()

    ux_bp = Blueprint("hackl4bs_ux", __name__)
    register_plugin_assets_directory(app, base_path="/plugins/hackl4bs_ux/assets/")

    @app.after_request
    def inject_ux_assets(response):
        if response.content_type and "text/html" in response.content_type:
            data = response.get_data(as_text=True)
            if "</head>" in data and "hackl4bs-ux" not in data:
                snippet = (
                    '<link rel="stylesheet" href="/plugins/hackl4bs_ux/assets/ux.css">\n'
                    '<script defer src="/plugins/hackl4bs_ux/assets/ux.js"></script>\n'
                )
                data = data.replace("</head>", snippet + "</head>", 1)
                response.set_data(data)
        return response

    # ── CTF info para countdown ───────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/ctf-info")
    def ctf_info():
        return jsonify({
            "name": get_config("ctf_name") or "CTF",
            "start": str(get_config("start") or ""),
            "end": str(get_config("end") or ""),
        })

    # ── Progreso por categoría ────────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/progress")
    @authed_only
    def category_progress():
        user = get_current_user()
        mode = get_config("user_mode")

        all_chals = Challenges.query.filter_by(state="visible").all()

        if mode == "teams" and user.team_id:
            ids = [u.id for u in Users.query.filter_by(team_id=user.team_id).all()]
            solved = {s.challenge_id for s in Solves.query.filter(Solves.user_id.in_(ids)).all()}
        else:
            solved = {s.challenge_id for s in Solves.query.filter_by(user_id=user.id).all()}

        cats = {}
        for c in all_chals:
            cat = c.category or "misc"
            if cat not in cats:
                cats[cat] = {"total": 0, "solved": 0}
            cats[cat]["total"] += 1
            if c.id in solved:
                cats[cat]["solved"] += 1

        return jsonify({"categories": cats})

    # ── First bloods ──────────────────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/first-bloods")
    def first_bloods():
        sub = (
            db.session.query(
                Solves.challenge_id,
                func.min(Solves.date).label("first_date"),
            )
            .group_by(Solves.challenge_id)
            .subquery()
        )
        rows = (
            db.session.query(Solves, Challenges)
            .join(sub, (Solves.challenge_id == sub.c.challenge_id) & (Solves.date == sub.c.first_date))
            .join(Challenges, Solves.challenge_id == Challenges.id)
            .all()
        )
        result = []
        for solve, chal in rows:
            u = Users.query.get(solve.user_id)
            result.append({
                "challenge_id": chal.id,
                "challenge_name": chal.name,
                "category": chal.category,
                "solver": u.name if u else "?",
                "date": solve.date.isoformat() if solve.date else None,
            })
        return jsonify({"first_bloods": result})

    # ── Rating de dificultad ──────────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/ratings/<int:challenge_id>")
    def get_ratings(challenge_id):
        user = get_current_user()
        avg = db.session.query(func.avg(ChallengeRating.rating)).filter_by(challenge_id=challenge_id).scalar()
        count = ChallengeRating.query.filter_by(challenge_id=challenge_id).count()
        my_rating = None
        if user:
            r = ChallengeRating.query.filter_by(challenge_id=challenge_id, user_id=user.id).first()
            if r:
                my_rating = r.rating
        return jsonify({
            "average": round(float(avg), 1) if avg else None,
            "count": count,
            "my_rating": my_rating,
        })

    @ux_bp.route("/api/hackl4bs/rate/<int:challenge_id>", methods=["POST"])
    @authed_only
    def rate_challenge(challenge_id):
        user = get_current_user()
        body = request.get_json(silent=True) or {}
        rating = int(body.get("rating", 0))
        if not (1 <= rating <= 5):
            return jsonify({"success": False, "message": "Rating debe ser 1-5"}), 400

        if not Solves.query.filter_by(user_id=user.id, challenge_id=challenge_id).first():
            return jsonify({"success": False, "message": "Solo puedes valorar retos que hayas resuelto"}), 403

        existing = ChallengeRating.query.filter_by(challenge_id=challenge_id, user_id=user.id).first()
        if existing:
            existing.rating = rating
        else:
            db.session.add(ChallengeRating(challenge_id=challenge_id, user_id=user.id, rating=rating))
        db.session.commit()

        avg = db.session.query(func.avg(ChallengeRating.rating)).filter_by(challenge_id=challenge_id).scalar()
        count = ChallengeRating.query.filter_by(challenge_id=challenge_id).count()
        return jsonify({"success": True, "average": round(float(avg), 1), "count": count})

    # ── Trabajando en esto ────────────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/working/<int:challenge_id>", methods=["POST"])
    @authed_only
    def mark_working(challenge_id):
        user = get_current_user()
        chal = Challenges.query.get(challenge_id)
        if not chal:
            return jsonify({"success": False}), 404
        ChallengeWorking.query.filter_by(user_id=user.id).delete()
        db.session.add(ChallengeWorking(
            challenge_id=challenge_id, user_id=user.id,
            team_id=user.team_id, username=user.name, challenge_name=chal.name,
        ))
        db.session.commit()
        return jsonify({"success": True})

    @ux_bp.route("/api/hackl4bs/working/<int:challenge_id>", methods=["DELETE"])
    @authed_only
    def unmark_working(challenge_id):
        user = get_current_user()
        ChallengeWorking.query.filter_by(user_id=user.id, challenge_id=challenge_id).delete()
        db.session.commit()
        return jsonify({"success": True})

    @ux_bp.route("/api/hackl4bs/team-working")
    @authed_only
    def team_working():
        user = get_current_user()
        # Limpiar entradas mayores a 4 horas
        stale = datetime.utcnow() - timedelta(hours=4)
        ChallengeWorking.query.filter(ChallengeWorking.started_at < stale).delete()
        db.session.commit()

        if not user.team_id:
            return jsonify({"working": []})

        entries = ChallengeWorking.query.filter_by(team_id=user.team_id).all()
        return jsonify({"working": [{
            "user_id": e.user_id,
            "username": e.username,
            "challenge_id": e.challenge_id,
            "challenge_name": e.challenge_name,
            "started_at": e.started_at.isoformat(),
            "is_me": e.user_id == user.id,
        } for e in entries]})

    # ── Activity feed del equipo ──────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/activity")
    @authed_only
    def team_activity():
        user = get_current_user()
        mode = get_config("user_mode")

        if mode == "teams" and user.team_id:
            ids = [u.id for u in Users.query.filter_by(team_id=user.team_id).all()]
            solves = Solves.query.filter(Solves.user_id.in_(ids)).order_by(desc(Solves.date)).limit(25).all()
        else:
            solves = Solves.query.filter_by(user_id=user.id).order_by(desc(Solves.date)).limit(25).all()

        events = []
        for s in solves:
            solver = Users.query.get(s.user_id)
            chal = Challenges.query.get(s.challenge_id)
            events.append({
                "type": "solve",
                "username": solver.name if solver else "?",
                "is_me": solver.id == user.id if solver else False,
                "challenge": chal.name if chal else "?",
                "category": chal.category if chal else "?",
                "points": chal.value if chal else 0,
                "date": s.date.isoformat() if s.date else None,
            })
        return jsonify({"events": events})

    # ── Stats de perfil ───────────────────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/profile-stats/<int:user_id>")
    def profile_stats(user_id):
        solves = Solves.query.filter_by(user_id=user_id).all()

        by_cat = {}
        timeline = {}
        total_points = 0
        for s in solves:
            chal = Challenges.query.get(s.challenge_id)
            if chal:
                by_cat[chal.category] = by_cat.get(chal.category, 0) + 1
                total_points += chal.value or 0
            if s.date:
                day = s.date.strftime("%Y-%m-%d")
                timeline[day] = timeline.get(day, 0) + 1

        # ── First bloods ──────────────────────────────────────────────────────
        fb_sub = (
            db.session.query(
                Solves.challenge_id,
                func.min(Solves.date).label("first_date"),
            )
            .group_by(Solves.challenge_id)
            .subquery()
        )
        first_blood_count = (
            db.session.query(func.count())
            .select_from(Solves)
            .join(fb_sub, (Solves.challenge_id == fb_sub.c.challenge_id) &
                           (Solves.date == fb_sub.c.first_date))
            .filter(Solves.user_id == user_id)
            .scalar() or 0
        )

        # ── Fast solves (Whaley) ──────────────────────────────────────────────
        fast_solve_count = 0
        try:
            from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
            fast_sub = (
                db.session.query(
                    WhaleyInstanceLog.challenge_id,
                    func.min(WhaleyInstanceLog.duration_seconds).label("min_dur"),
                )
                .filter(WhaleyInstanceLog.duration_seconds.isnot(None))
                .group_by(WhaleyInstanceLog.challenge_id)
                .subquery()
            )
            fast_solve_count = (
                db.session.query(func.count())
                .select_from(WhaleyInstanceLog)
                .join(fast_sub,
                      (WhaleyInstanceLog.challenge_id == fast_sub.c.challenge_id) &
                      (WhaleyInstanceLog.duration_seconds == fast_sub.c.min_dur))
                .filter(WhaleyInstanceLog.user_id == user_id)
                .scalar() or 0
            )
        except Exception:
            pass

        return jsonify({
            "total_solves": len(solves),
            "total_points": total_points,
            "by_category": by_cat,
            "timeline": [{"date": d, "count": c} for d, c in sorted(timeline.items())],
            "first_blood": first_blood_count,
            "fast_solve": fast_solve_count,
        })

    # ── Notas compartidas del equipo ──────────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/team-notes", methods=["GET"])
    @authed_only
    def get_team_notes():
        user = get_current_user()
        if not user.team_id:
            return jsonify({"content": "", "updated_at": None, "updated_by": None})
        note = TeamNote.query.filter_by(team_id=user.team_id).first()
        return jsonify({
            "content": note.content if note else "",
            "updated_at": note.updated_at.isoformat() if note and note.updated_at else None,
            "updated_by": note.updated_by if note else None,
        })

    @ux_bp.route("/api/hackl4bs/team-notes", methods=["POST"])
    @authed_only
    def save_team_notes():
        user = get_current_user()
        if not user.team_id:
            return jsonify({"success": False}), 403
        body = request.get_json(silent=True) or {}
        content = (body.get("content") or "")[:10000]
        note = TeamNote.query.filter_by(team_id=user.team_id).first()
        if note:
            note.content = content
            note.updated_at = datetime.utcnow()
            note.updated_by = user.name
        else:
            db.session.add(TeamNote(
                team_id=user.team_id, content=content, updated_by=user.name
            ))
        db.session.commit()
        return jsonify({"success": True})

    # ── Stats del equipo (panel mejorado) ─────────────────────────────────────
    @ux_bp.route("/api/hackl4bs/team-stats/<int:team_id>")
    def team_stats(team_id):
        team = Teams.query.get(team_id)
        if not team:
            return jsonify({"error": "not found"}), 404

        members = Users.query.filter_by(team_id=team_id).all()
        member_ids = [m.id for m in members]
        all_solves = Solves.query.filter(Solves.user_id.in_(member_ids)).all()
        solved_ids = {s.challenge_id for s in all_solves}

        total_points = 0
        by_cat = {}
        chal_cache = {}

        def _chal(cid):
            if cid not in chal_cache:
                chal_cache[cid] = Challenges.query.get(cid)
            return chal_cache[cid]

        for s in all_solves:
            c = _chal(s.challenge_id)
            if c:
                total_points += c.value or 0
                cat = c.category or "misc"
                by_cat[cat] = by_cat.get(cat, 0) + 1

        # First bloods del equipo
        fb_sub = (
            db.session.query(
                Solves.challenge_id,
                func.min(Solves.date).label("first_date"),
            )
            .group_by(Solves.challenge_id)
            .subquery()
        )
        first_blood_count = (
            db.session.query(func.count())
            .select_from(Solves)
            .join(fb_sub, (Solves.challenge_id == fb_sub.c.challenge_id) &
                           (Solves.date == fb_sub.c.first_date))
            .filter(Solves.user_id.in_(member_ids))
            .scalar() or 0
        )

        # Categorías completadas (todos los retos de esa cat resueltos)
        all_chals = Challenges.query.filter_by(state="visible").all()
        cat_map = {}
        for c in all_chals:
            cat_map.setdefault(c.category or "misc", []).append(c.id)
        completed_cats = sum(
            1 for ids in cat_map.values() if all(i in solved_ids for i in ids)
        )

        # Stats por miembro
        member_stats = []
        for m in members:
            m_solves = [s for s in all_solves if s.user_id == m.id]
            m_pts = sum((_chal(s.challenge_id).value or 0)
                        for s in m_solves if _chal(s.challenge_id))
            member_stats.append({
                "user_id": m.id,
                "username": m.name,
                "solves": len(m_solves),
                "points": m_pts,
            })

        # Últimas soluciones
        recent = sorted(all_solves, key=lambda s: s.date or datetime.min, reverse=True)[:15]
        recent_data = []
        for s in recent:
            solver = Users.query.get(s.user_id)
            c = _chal(s.challenge_id)
            recent_data.append({
                "username": solver.name if solver else "?",
                "challenge": c.name if c else "?",
                "category": c.category if c else "?",
                "points": c.value if c else 0,
                "date": s.date.isoformat() if s.date else None,
            })

        return jsonify({
            "team_name": team.name,
            "total_points": total_points,
            "total_solves": len(all_solves),
            "first_blood": first_blood_count,
            "completed_categories": completed_cats,
            "by_category": by_cat,
            "members": member_stats,
            "recent": recent_data,
        })

    app.register_blueprint(ux_bp)

    # ── Jinja2 helpers para templates de equipos ───────────────────────────────
    # Globals: conteo por usuario
    def _get_user_fb_count(user_id):
        fb_sub = (
            db.session.query(
                Solves.challenge_id,
                func.min(Solves.date).label("first_date"),
            )
            .group_by(Solves.challenge_id)
            .subquery()
        )
        return (
            db.session.query(func.count())
            .select_from(Solves)
            .join(fb_sub, (Solves.challenge_id == fb_sub.c.challenge_id) &
                           (Solves.date == fb_sub.c.first_date))
            .filter(Solves.user_id == user_id)
            .scalar() or 0
        )

    def _get_user_fast_count(user_id):
        try:
            from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
            fast_sub = (
                db.session.query(
                    WhaleyInstanceLog.challenge_id,
                    func.min(WhaleyInstanceLog.duration_seconds).label("min_dur"),
                )
                .filter(WhaleyInstanceLog.duration_seconds.isnot(None))
                .group_by(WhaleyInstanceLog.challenge_id)
                .subquery()
            )
            return (
                db.session.query(func.count())
                .select_from(WhaleyInstanceLog)
                .join(fast_sub,
                      (WhaleyInstanceLog.challenge_id == fast_sub.c.challenge_id) &
                      (WhaleyInstanceLog.duration_seconds == fast_sub.c.min_dur))
                .filter(WhaleyInstanceLog.user_id == user_id)
                .scalar() or 0
            )
        except Exception:
            return 0

    # Globals por solve individual — cacheados en g para no hacer N queries
    def _solve_is_first_blood(challenge_id, date):
        from flask import g
        if not hasattr(g, "_hl_fb_set"):
            rows = db.session.query(
                Solves.challenge_id,
                func.min(Solves.date),
            ).group_by(Solves.challenge_id).all()
            g._hl_fb_set = {(r[0], r[1]) for r in rows}
        return (challenge_id, date) in g._hl_fb_set

    def _solve_is_fast_resolve(challenge_id, user_id):
        from flask import g
        if not hasattr(g, "_hl_fast_set"):
            g._hl_fast_set = set()
            try:
                from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
                rows = db.session.query(
                    WhaleyInstanceLog.challenge_id,
                    WhaleyInstanceLog.user_id,
                    func.min(WhaleyInstanceLog.duration_seconds),
                ).filter(
                    WhaleyInstanceLog.duration_seconds.isnot(None)
                ).group_by(
                    WhaleyInstanceLog.challenge_id
                ).all()
                for chal_id, uid, _ in rows:
                    g._hl_fast_set.add((chal_id, uid))
            except Exception:
                pass
        return (challenge_id, user_id) in g._hl_fast_set

    app.jinja_env.globals["get_user_fb_count"]      = _get_user_fb_count
    app.jinja_env.globals["get_user_fast_count"]    = _get_user_fast_count
    app.jinja_env.globals["solve_is_first_blood"]   = _solve_is_first_blood
    app.jinja_env.globals["solve_is_fast_resolve"]  = _solve_is_fast_resolve

    print("[HackL4bs UX] Plugin cargado — 10 features activas.")
