"""Tiny route registry so every handler can be declared once and mounted under
both the documented /api/v1 prefix and the bare path."""
ROUTES = []


def route(rule, methods=("GET",)):
    def decorate(func):
        ROUTES.append((rule, tuple(methods), func))
        return func
    return decorate
