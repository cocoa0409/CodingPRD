"""Application entrypoint.

Boots a fresh, empty in-memory marketplace on every launch: the store and the
logical clock are module-level singletons with no import-time seeding, so
re-invoking start.sh wipes every byte of state.
"""

import os

from flask import Flask

from routes import catalog, learning, money, onboarding, ops, trust


def create_app():
    app = Flask(__name__)
    # Preserve the envelope's key order (meta, response_type, data).
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(onboarding.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(learning.bp)
    app.register_blueprint(money.bp)
    app.register_blueprint(trust.bp)
    app.register_blueprint(ops.bp)

    @app.errorhandler(404)
    def _not_found(_exc):
        # An unrouted path is still reported through the declared envelope.
        from core import envelope

        return envelope.error("ERR_NOT_FOUND", "No such endpoint"), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        from core import envelope

        return envelope.error("ERR_NOT_FOUND", "Method not allowed for this endpoint"), 405

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
