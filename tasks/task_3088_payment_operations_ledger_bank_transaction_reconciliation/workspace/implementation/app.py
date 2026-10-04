"""Flask entry point.

Route registration is driven by the ROUTES table produced by routes.py and
routes_ops.py; the table mirrors the declared path set of PRD S4 exactly, so the
route surface can never drift from the endpoint list.

The store is created empty in main().  No entity is constructed at import time.
"""

import os
import sys
import threading

from flask import Flask, g, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db                       # noqa: E402
import routes                   # noqa: E402  (populates ROUTES)
import routes_ops               # noqa: E402  (populates ROUTES, F401)
import serializer as ser        # noqa: E402
from errors import ApiError     # noqa: E402
from services import Ctx, ROLES  # noqa: E402
from utils import iso_from_ms, new_request_id  # noqa: E402

STORE = None


def _clock_ms():
    if STORE is None:
        return 0
    return STORE.clock_ms


def _meta(include_pagination=False, limit=None, offset=None, total=None, has_more=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_from_ms(_clock_ms()),
    }
    if include_pagination:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total
        meta["has_more"] = has_more
    return meta


def build_app(store):
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.url_map.strict_slashes = False
    # The store is process-wide mutable state and the server runs threaded, so
    # every request is served under one lock.  That makes each request atomic
    # with respect to the store, which is what the optimistic-concurrency rules
    # assume: a stale expected_*_version can never be observed mid-write.
    app.store_lock = threading.RLock()

    table = {}          # (method, path) -> entry
    endpoint_index = {}  # endpoint name -> (method, path)

    def make_view(key):
        entry = table[key]

        def view(**kwargs):
            ctx = Ctx(store)
            query = request.args.to_dict(flat=True)
            body = g.body
            actor = g.actor
            result = entry["handler"](ctx, kwargs, body, query, actor)
            if result.rtype == "array":
                meta = _meta(True, result.limit, result.offset, result.total,
                             (result.offset + len(result.data)) < result.total)
            else:
                meta = _meta()
            return jsonify({"meta": meta,
                            "response_type": result.rtype,
                            "data": result.data}), entry["code"]

        view.__name__ = "view_" + key[1].replace("/", "_").replace("{", "").replace("}", "")
        return view

    for (method, path), entry in routes.ROUTES.items():
        if (method, path) in table:
            continue
        table[(method, path)] = entry
        endpoint = "%s|%s" % (method, path)
        endpoint_index[endpoint] = (method, path)
        app.add_url_rule(path, endpoint, make_view((method, path)), methods=[method])

    app.endpoint_index = endpoint_index

    @app.before_request
    def _prepare():
        g.store = store
        g.store_lock = app.store_lock
        g.store_lock.acquire()
        g.body = {}
        if request.method in ("POST", "PUT", "PATCH") and request.get_data(cache=True):
            try:
                parsed = request.get_json(force=True, silent=False)
            except Exception:
                parsed = None
            if parsed is None:
                raise ApiError("ERR_INVALID_REQUEST", "Request body is not parseable JSON.")
            if not isinstance(parsed, dict):
                raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
            g.body = parsed

        user_id = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if not user_id or not role or role not in ROLES:
            raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
        if role == "CounterpartyUser" and user_id not in store.counterparties:
            raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                           "A CounterpartyUser identity must be an existing Counterparty id.")
        g.actor = (user_id, role)

        rule = request.url_rule
        if rule is not None:
            key = endpoint_index.get(rule.endpoint)
            entry = table.get(key) if key else None
            if entry is not None and role not in entry["roles"]:
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE")

    @app.teardown_request
    def _release(exc):
        lock = getattr(g, "store_lock", None)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify({"meta": _meta(),
                        "response_type": "error",
                        "data": {"error_id": exc.error_id, "message": exc.message}}), \
            exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_INVALID_REQUEST",
                                 "message": "No declared endpoint matches this method and path."}}), 400

    @app.errorhandler(405)
    def _bad_method(exc):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_INVALID_REQUEST",
                                 "message": "This method is not declared for the path."}}), 400

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        import traceback
        traceback.print_exc()
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_INVALID_REQUEST",
                                 "message": "Unhandled server error: %s" % exc}}), 400

    return app


def main():
    global STORE
    STORE = db.new_store()
    app = build_app(STORE)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()