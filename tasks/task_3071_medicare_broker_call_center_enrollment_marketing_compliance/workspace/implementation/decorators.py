"""Endpoint decorator: authenticates, then authorizes against the allow-list."""

import functools

from flask import g

import middleware


def requires(*roles):
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = middleware.authenticate(allowed)
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator