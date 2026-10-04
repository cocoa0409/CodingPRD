"""Route registration helpers."""

from flask import request

import middleware


def endpoint(app, method, path, roles):
    """Register a view that authenticates, authorizes and delegates to `fn`."""

    def decorator(fn):
        name = (method + "_" + path).replace("/", "_").replace("{", "").replace("}", "")
        name = name.replace("-", "_")

        def view(**kwargs):
            actor = middleware.authenticate(request.headers)
            middleware.authorize(actor, roles)
            return fn(actor, **kwargs)

        app.add_url_rule(path, endpoint=name, view_func=view, methods=[method])
        return fn

    return decorator


def q(name, default=None):
    return request.args.get(name, default)