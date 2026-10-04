"""The joints of the app: a route book binding the §4 path table to the
method, role set and handler that serves it.

Paths are registered literally (the router matches the path string the PRD
prints) and interpolated segments are resolved at the head of a request, after
authentication and authorisation, so a malformed body still loses to a 404 for
a missing parent (PRD 2.12)."""

import db
import services.catalog as catalog
from errors import ApiError
from middleware import COLLECTION_OF, ROLE_SET


class Route(object):
    def __init__(self, method, path, handler, roles, segments, status=200):
        self.method = method
        self.path = path
        self.handler = handler
        self.roles = tuple(roles)
        self.segments = segments
        self.status = status


class Book(object):
    def __init__(self):
        self.routes = []

    def add(self, method, path, handler, roles, status=200):
        segments = _split(path)
        self.routes.append(Route(method, path, handler, roles, segments, status))

    def match(self, method, path):
        for route in self.routes:
            if route.method != method:
                continue
            params = _match(route.segments, _split(path))
            if params is not None:
                return route, params
        # a path that exists for another method is still a miss here
        return None, {}


def _split(path):
    return [segment for segment in path.strip("/").split("/") if segment != ""]


def _match(route_segments, path_segments):
    if len(route_segments) != len(path_segments):
        return None
    params = {}
    for expected, actual in zip(route_segments, path_segments):
        if expected.startswith("{") and expected.endswith("}"):
            params[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return params


def resolve_path_params(params):
    """Resolve every interpolated id in the request, left to right along the
    path, before any handler runs (PRD 2.10)."""
    resolved = {}
    for name, value in params.items():
        entry = COLLECTION_OF.get(name)
        if entry is None or entry[1] is None:
            if name == "fitmentId":
                resolved[name] = _lookup_fitment(value)
                continue
            if name == "interchangeId":
                resolved[name] = _lookup_interchange(value)
                continue
            resolved[name] = value
            continue
        mapping = getattr(db, entry[1])
        row = mapping.get(value)
        if row is None:
            raise ApiError(entry[2], "%s %s does not exist." % (entry[0], value))
        resolved[name] = row
    return resolved


def _lookup_fitment(row_id):
    row = db.part_fitments.get(row_id) or db.tool_fitments.get(row_id)
    if row is None:
        raise ApiError("ERR_PART_NOT_FOUND", "Fitment %s does not exist." % row_id)
    return row


def _lookup_interchange(row_id):
    row = db.part_interchanges.get(row_id)
    if row is None:
        raise ApiError("ERR_PART_NOT_FOUND", "Interchange %s does not exist." % row_id)
    return row