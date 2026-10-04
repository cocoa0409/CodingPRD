"""Entry point: Flask app factory, global request lock, route registration.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. State lives entirely in
in-memory dicts (db.STORE); nothing is seeded at startup and the logical clock
starts at exactly 2026-09-01T00:00:00Z.
"""
import os

from flask import Flask, g

from db import LOCK
from errors import register_error_handlers
from routes_applications import bp as applications_bp
from routes_clock import bp as clock_bp
from routes_interviews import bp as interviews_bp
from routes_invitations import bp as invitations_bp
from routes_legal import bp as legal_bp
from routes_medical import bp as medical_bp
from routes_service import bp as service_bp
from routes_stage import bp as stage_bp
from routes_training import bp as training_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            LOCK.release()

    for blueprint in (stage_bp, applications_bp, interviews_bp, invitations_bp,
                      medical_bp, legal_bp, training_bp, service_bp, clock_bp):
        app.register_blueprint(blueprint)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
