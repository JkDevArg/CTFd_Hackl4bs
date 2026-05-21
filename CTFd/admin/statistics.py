import os

import requests as http_requests
from flask import jsonify, render_template

from CTFd.admin import admin
from CTFd.cache import clear_standings
from CTFd.models import Awards, Challenges, Fails, Solves, Submissions, Teams, Tracking, Unlocks, Users, db
from CTFd.utils.decorators import admins_only
from CTFd.utils.modes import get_model
from CTFd.utils.updates import update_check


@admin.route("/admin/statistics", methods=["GET"])
@admins_only
def statistics():
    update_check()

    Model = get_model()

    teams_registered = Teams.query.count()
    users_registered = Users.query.count()

    wrong_count = (
        Fails.query.join(Model, Fails.account_id == Model.id)
        .filter(Model.banned == False, Model.hidden == False)
        .count()
    )

    solve_count = (
        Solves.query.join(Model, Solves.account_id == Model.id)
        .filter(Model.banned == False, Model.hidden == False)
        .count()
    )

    challenge_count = Challenges.query.count()

    total_points = (
        Challenges.query.with_entities(db.func.sum(Challenges.value).label("sum"))
        .filter_by(state="visible")
        .first()
        .sum
    ) or 0

    ip_count = Tracking.query.with_entities(Tracking.ip).distinct().count()

    solves_sub = (
        db.session.query(
            Solves.challenge_id, db.func.count(Solves.challenge_id).label("solves_cnt")
        )
        .join(Model, Solves.account_id == Model.id)
        .filter(Model.banned == False, Model.hidden == False)
        .group_by(Solves.challenge_id)
        .subquery()
    )

    solves = (
        db.session.query(
            solves_sub.columns.challenge_id,
            solves_sub.columns.solves_cnt,
            Challenges.name,
        )
        .join(Challenges, solves_sub.columns.challenge_id == Challenges.id)
        .all()
    )

    solve_data = {}
    for _chal, count, name in solves:
        solve_data[name] = count

    most_solved = None
    least_solved = None
    if len(solve_data):
        most_solved = max(solve_data, key=solve_data.get)
        least_solved = min(solve_data, key=solve_data.get)

    db.session.close()

    return render_template(
        "admin/statistics.html",
        user_count=users_registered,
        team_count=teams_registered,
        ip_count=ip_count,
        wrong_count=wrong_count,
        solve_count=solve_count,
        challenge_count=challenge_count,
        total_points=total_points,
        solve_data=solve_data,
        most_solved=most_solved,
        least_solved=least_solved,
    )


@admin.route("/admin/reset_stats", methods=["POST"])
@admins_only
def reset_stats():
    from CTFd.cache import cache

    # Solves tiene tabla propia con FK a submissions — borrar primero para evitar FK violation
    Solves.query.delete(synchronize_session=False)
    Submissions.query.delete(synchronize_session=False)
    Awards.query.delete(synchronize_session=False)
    Unlocks.query.delete(synchronize_session=False)
    Tracking.query.delete(synchronize_session=False)

    # Logros del plugin HackL4bs Achievements
    try:
        from CTFd.plugins.hackl4bs_achievements import AchievementEarned
        AchievementEarned.query.delete(synchronize_session=False)
    except Exception:
        pass

    # Restaurar valor inicial en retos con scoring dinámico
    db.session.query(Challenges).filter(
        Challenges.initial.isnot(None), Challenges.initial > 0
    ).update({Challenges.value: Challenges.initial}, synchronize_session=False)

    db.session.commit()
    db.session.close()

    # Limpiar toda la caché (scores memoizados por usuario/equipo)
    cache.clear()
    clear_standings()

    siem_url = os.getenv("SIEM_RESET_URL", "")
    siem_token = os.getenv("SIEM_ADMIN_TOKEN", "")
    siem_ok = False
    siem_error = None

    if siem_url:
        try:
            headers = {"Authorization": f"Bearer {siem_token}"} if siem_token else {}
            resp = http_requests.post(siem_url, headers=headers, timeout=5)
            siem_ok = resp.status_code == 200
        except Exception as exc:
            siem_error = str(exc)

    return jsonify({"success": True, "siem_reset": siem_ok, "siem_error": siem_error})
