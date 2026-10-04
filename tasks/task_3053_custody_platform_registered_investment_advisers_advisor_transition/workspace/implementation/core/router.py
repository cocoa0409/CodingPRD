"""Route registry: records each rule's roles and If-Match participation so the
dispatch layer can enforce priorities 2 and 13 before any handler runs."""

from core.context import IF_MATCH_MAP, ROLE_MAP

REGISTRY = []


class Api:
    def __init__(self, app):
        self.app = app

    def route(self, rule, methods=("GET",), roles=None, if_match=False):
        def decorator(fn):
            methods_tuple = tuple(methods)
            for method in methods_tuple:
                ROLE_MAP[(method, rule)] = tuple(roles or ())
                IF_MATCH_MAP[(method, rule)] = if_match
            REGISTRY.append((rule, methods_tuple, fn))
            self.app.add_url_rule(rule, endpoint=None, view_func=fn, methods=list(methods_tuple))
            return fn
        return decorator


def build(app):
    return Api(app)