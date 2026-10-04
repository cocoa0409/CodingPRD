"""Route registry: exact path templates, role sets and declared inputs."""

from __future__ import annotations

import re

ROUTES = []
_STATIC = []
_DYNAMIC = []


class Route:
    __slots__ = ("method", "path", "regex", "handler", "roles", "status", "inputs", "name")

    def __init__(self, method, path, handler, roles, status, inputs, name):
        self.method = method
        self.path = path
        self.handler = handler
        self.roles = roles
        self.status = status
        self.inputs = inputs
        self.name = name
        self.regex = re.compile("^" + re.sub(r"\{([a-zA-Z_]+)\}", r"(?P<\1>[^/]+)", path) + "$")


def register(method, path, handler, roles, status, inputs=(), name=None):
    route = Route(method, path, handler, list(roles), status, list(inputs), name or (method + " " + path))
    ROUTES.append(route)
    if "{" in path:
        _DYNAMIC.append(route)
    else:
        _STATIC.append(route)


def resolve(method, path):
    """Return (route, path_params) matching the request, static paths first."""
    for route in _STATIC:
        if route.method == method and route.path == path:
            return route, {}
    for route in _DYNAMIC:
        if route.method != method:
            continue
        match = route.regex.match(path)
        if match:
            return route, match.groupdict()
    # Method-mismatch fallback: give the caller a deterministic not-found.
    for route in _STATIC + _DYNAMIC:
        if route.path == path:
            return route, {}
    for route in _DYNAMIC:
        match = route.regex.match(path)
        if match:
            return route, match.groupdict()
    return None, {}


def registered_paths():
    return [(r.method, r.path) for r in ROUTES]