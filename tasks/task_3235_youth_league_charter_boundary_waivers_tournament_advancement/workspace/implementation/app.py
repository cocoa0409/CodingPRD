"""Flask entry point: registers blueprints and error handlers."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

import routes_leagues
import routes_players
import routes_waivers
import routes_volunteers
import routes_rosters
import routes_games
import routes_misc

for bp in (routes_misc.bp, routes_leagues.bp, routes_players.bp, routes_waivers.bp,
           routes_volunteers.bp, routes_rosters.bp, routes_games.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
