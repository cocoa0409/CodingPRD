"""Sports Game Licensing API — entry point."""
from __future__ import annotations

import os

from flask import Flask, jsonify

import routes_agreements
import routes_athletes
import routes_audio
import routes_audits
import routes_drops
import routes_editions
import routes_grants
import routes_roster
import routes_seasons
import routes_statements
import routes_tournaments
import routes_wallets
from db import db
from errors import ApiError, err_missing_context, err_not_found
from middleware import require_roles
from response import body_json, err_resp, ok_obj, parse_datetime
import services as S


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (routes_agreements.bp, routes_athletes.bp, routes_audio.bp,
               routes_audits.bp, routes_drops.bp, routes_editions.bp,
               routes_grants.bp, routes_roster.bp, routes_seasons.bp,
               routes_statements.bp, routes_tournaments.bp, routes_wallets.bp):
        app.register_blueprint(bp)

    @app.post("/licensing/_clock/set_current_utc")
    def set_clock():
        require_roles("LicensingAdmin")
        body = body_json()
        to = body.get("to_iso8601")
        if to is None:
            from errors import err_invalid_input
            raise err_invalid_input("to_iso8601 is required")
        dt = parse_datetime(to, "to_iso8601")
        db.set_clock(dt)
        S.lazy_eval()
        out = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
        return ok_obj({"current_utc": out})

    @app.before_request
    def _lazy():
        # lazily apply time-based transitions before handling any request
        with db.lock:
            S.lazy_eval()

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return err_resp(e)

    @app.errorhandler(404)
    def _nf(e):
        return err_resp(err_not_found("Route or resource not found"))

    @app.errorhandler(405)
    def _mna(e):
        return err_resp(err_not_found("Method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        if isinstance(e, ApiError):
            return err_resp(e)
        app.logger.exception("unhandled error")
        from errors import ApiError as _AE
        return err_resp(_AE("ERR_INTERNAL", str(e), 500))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
