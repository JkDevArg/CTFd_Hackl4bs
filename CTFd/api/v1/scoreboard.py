from collections import defaultdict

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy import select

from CTFd.cache import cache, make_cache_key
from CTFd.models import Brackets, Users, db
from CTFd.utils import get_config
from CTFd.utils.decorators.visibility import (
    check_account_visibility,
    check_score_visibility,
)
from CTFd.utils.modes import TEAMS_MODE, generate_account_url, get_mode_as_word
from CTFd.utils.scoreboard import get_scoreboard_detail
from CTFd.utils.scores import get_standings, get_user_standings
from CTFd.models import Solves, Challenges
from sqlalchemy import func

scoreboard_namespace = Namespace(
    "scoreboard", description="Endpoint to retrieve scores"
)


@scoreboard_namespace.route("")
class ScoreboardList(Resource):
    @check_account_visibility
    @check_score_visibility
    @cache.cached(timeout=60, key_prefix=make_cache_key)
    def get(self):
        standings = get_standings()
        response = []
        mode = get_config("user_mode")
        account_type = get_mode_as_word()

        if mode == TEAMS_MODE:
            r = db.session.execute(
                select(
                    [
                        Users.id,
                        Users.name,
                        Users.oauth_id,
                        Users.team_id,
                        Users.hidden,
                        Users.banned,
                        Users.bracket_id,
                        Brackets.name.label("bracket_name"),
                    ]
                )
                .where(Users.team_id.isnot(None))
                .join(Brackets, Users.bracket_id == Brackets.id, isouter=True)
            )
            users = r.fetchall()
            membership = defaultdict(dict)
            for u in users:
                if u.hidden is False and u.banned is False:
                    membership[u.team_id][u.id] = {
                        "id": u.id,
                        "oauth_id": u.oauth_id,
                        "name": u.name,
                        "score": 0,
                        "bracket_id": u.bracket_id,
                        "bracket_name": u.bracket_name,
                    }

            # Get user_standings as a dict so that we can more quickly get member scores
            user_standings = get_user_standings()
            for u in user_standings:
                membership[u.team_id][u.user_id]["score"] = int(u.score)

        # --- Calcular First Bloods ---
        fb_counts = defaultdict(int)
        fb_subquery = db.session.query(
            Solves.challenge_id,
            func.min(Solves.date).label('min_date')
        ).group_by(Solves.challenge_id).subquery()
        
        acc_col = Solves.team_id if mode == TEAMS_MODE else Solves.user_id
        fb_q = db.session.query(acc_col, func.count()).join(
            fb_subquery, (Solves.challenge_id == fb_subquery.c.challenge_id) & (Solves.date == fb_subquery.c.min_date)
        ).group_by(acc_col).all()
        for acc_id, count in fb_q:
            if acc_id: fb_counts[acc_id] = count

        # --- Calcular Fast Resolves (Whaley) ---
        fast_counts = defaultdict(int)
        try:
            from CTFd.plugins.whaley_ctfd_plugin import WhaleyInstanceLog
            fast_sub = db.session.query(
                WhaleyInstanceLog.challenge_id,
                func.min(WhaleyInstanceLog.duration_seconds).label('min_dur')
            ).filter(WhaleyInstanceLog.duration_seconds != None).group_by(WhaleyInstanceLog.challenge_id).subquery()
            
            if mode == TEAMS_MODE:
                fast_q = db.session.query(Users.team_id, func.count()).join(
                    WhaleyInstanceLog, Users.id == WhaleyInstanceLog.user_id
                ).join(
                    fast_sub, (WhaleyInstanceLog.challenge_id == fast_sub.c.challenge_id) & (WhaleyInstanceLog.duration_seconds == fast_sub.c.min_dur)
                ).group_by(Users.team_id).all()
            else:
                fast_q = db.session.query(WhaleyInstanceLog.user_id, func.count()).join(
                    fast_sub, (WhaleyInstanceLog.challenge_id == fast_sub.c.challenge_id) & (WhaleyInstanceLog.duration_seconds == fast_sub.c.min_dur)
                ).group_by(WhaleyInstanceLog.user_id).all()
                
            for acc_id, count in fast_q:
                if acc_id: fast_counts[acc_id] = count
        except Exception:
            pass

        for i, x in enumerate(standings):
            entry = {
                "pos": i + 1,
                "account_id": x.account_id,
                "account_url": generate_account_url(account_id=x.account_id),
                "account_type": account_type,
                "oauth_id": x.oauth_id,
                "name": x.name,
                "score": int(x.score),
                "bracket_id": x.bracket_id,
                "bracket_name": x.bracket_name,
                "first_bloods": fb_counts.get(x.account_id, 0),
                "fast_resolves": fast_counts.get(x.account_id, 0)
            }

            if mode == TEAMS_MODE:
                entry["members"] = list(membership[x.account_id].values())

            response.append(entry)
        return {"success": True, "data": response}


@scoreboard_namespace.route("/top/<int:count>")
@scoreboard_namespace.param("count", "How many top teams to return")
class ScoreboardDetail(Resource):
    @check_account_visibility
    @check_score_visibility
    def get(self, count):
        # Restrict count to some limit
        count = max(1, min(count, 50))
        bracket_id = request.args.get("bracket_id")
        response = get_scoreboard_detail(count=count, bracket_id=bracket_id)
        return {"success": True, "data": response}
