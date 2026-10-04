"""Endpoint registry and request dispatch.

The spec never ships a usable OpenAPI document, so the routing table is built by
the route modules themselves: each handler declares its method, path template
and the roles permitted for that operation, and the registry matches a request
against the templates at dispatch time.

The role set for each operation is looked up by (method, path template) in
roles_table.py, which pins the scaffold's S1.5 endpoint table verbatim, so the
per-handler declarations in the route modules cannot drift from the contract.
"""

import re

import roles_table

ROUTES = []
_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def route(method, path, roles=None, status=200, write=False):
    """Register a handler. Paths use {param} placeholders. `roles` is accepted
    for readability at the call site; the authoritative set is the pinned
    endpoint table."""

    def decorate(fn):
        regex = "^" + _PARAM_RE.sub(lambda m: "(?P<%s>[^/]+)" % m.group(1), path) + "$"
        ROUTES.append(
            {
                "method": method.upper(),
                "path": path,
                "regex": re.compile(regex),
                "param_names": [m.group(1) for m in _PARAM_RE.finditer(path)],
                "roles": roles_table.roles_for(method, path),
                "status": status,
                "write": write,
                "fn": fn,
                "order": len(ROUTES),
            }
        )
        return fn

    return decorate


def match(method, path):
    """Resolve a request to (route, path_params). Literal segments win over
    parameterised ones, then declaration order breaks any remaining tie."""
    method = method.upper()
    exact = []
    partial = []
    for r in ROUTES:
        if r["method"] != method:
            continue
        m = r["regex"].match(path)
        if not m:
            continue
        params = m.groupdict()
        (exact if not params else partial).append((r, params))
    if exact:
        return exact[0]
    if partial:
        partial.sort(key=lambda item: (len(item[0]["param_names"]), item[0]["order"]))
        return partial[0]
    return None, None


def unknown_path(method, path):
    """True when the path is claimed by some route but not for this method."""
    for r in ROUTES:
        if r["regex"].match(path):
            return True
    return False