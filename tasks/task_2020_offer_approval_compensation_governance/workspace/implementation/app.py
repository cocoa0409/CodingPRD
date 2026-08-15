"""Flask entry point: error handlers + route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED
from response import error
from routes import requisitions, candidates, snapshots, policies, offers
from routes import approval_steps, negotiation_rounds, perks, clearance_checks, misc

app = Flask(__name__)

app.register_blueprint(requisitions.bp)
app.register_blueprint(candidates.bp)
app.register_blueprint(snapshots.bp)
app.register_blueprint(policies.bp)
app.register_blueprint(offers.bp)
app.register_blueprint(approval_steps.bp)
app.register_blueprint(negotiation_rounds.bp)
app.register_blueprint(perks.bp)
app.register_blueprint(clearance_checks.bp)
app.register_blueprint(misc.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error("ERR_INVALID_REQUEST", "Route not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_generic(err):
    return error("ERR_INVALID_REQUEST", str(err), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
