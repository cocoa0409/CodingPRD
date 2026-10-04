"""Shared route-registration helper."""

from http_util import require_auth

_counter = {"n": 0}


def route(app, rule, methods, roles):
    """Register `fn` at `rule`, wrapped in the auth middleware for `roles`."""
    def deco(fn):
        wrapped = require_auth(roles)(fn)
        _counter["n"] += 1
        endpoint = "ep_%d_%s" % (_counter["n"], fn.__name__)
        app.add_url_rule(rule, endpoint=endpoint, view_func=wrapped,
                         methods=list(methods))
        return wrapped
    return deco