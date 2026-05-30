import os

from flask import current_app, flash, get_flashed_messages, redirect, request, url_for
from markupsafe import Markup

from CTFd.utils import validators
from CTFd.utils.config import is_teams_mode


def markup(text):
    """
    Mark text as safe to inject as HTML into templates
    """
    return Markup(text)  # nosec B704


def info_for(endpoint, message):
    flash(message=message, category=endpoint + ".infos")


def error_for(endpoint, message):
    flash(message=message, category=endpoint + ".errors")


def get_infos():
    return get_flashed_messages(category_filter=request.endpoint + ".infos")


def get_errors():
    return get_flashed_messages(category_filter=request.endpoint + ".errors")


def post_auth_redirect(user=None):
    """Redirect users after login or registration based on user mode."""
    next_url = request.args.get("next")
    if next_url and validators.is_safe_url(next_url):
        return redirect(next_url)

    if is_teams_mode():
        return redirect(url_for("teams.private"))

    return redirect(url_for("challenges.listing"))


@current_app.url_defaults
def env_asset_url_default(endpoint, values):
    """
    Create asset URLs dependent on the current env

    In CTFd 4.0 this url_for behavior and the themes_beta
    route will be removed in favor of an improved theme system
    """
    if endpoint == "views.themes":
        path = values.get("path", "")
        static_asset = path.endswith(".js") or path.endswith(".css")
        direct_access = ".dev" in path or ".min" in path
        if static_asset and not direct_access:
            env = values.get("env", current_app.env)
            mode = ".dev" if env == "development" else ".min"
            base, ext = os.path.splitext(path)
            values["path"] = base + mode + ext


@current_app.url_defaults
def asset_cache_url_default(endpoint, values):
    """Used to cache bust per server restarts"""
    if endpoint == "views.themes":
        values["d"] = current_app.run_id
