"""Voter Guide Production & Candidate Questionnaire Administration API.

Flask bootstrap: registers the per-domain blueprints and translates errors
into the standard envelope (PRD 2.2). The store is process-local memory and
starts empty on every boot; the logical clock starts at 2026-09-01T00:00:00Z.
"""
import os
import traceback

from flask import Flask

import respond
from errors import ApiError
from routes import (clock, contests, cycles, editions, filings, forums,
                    incidents, measures, questionnaires, responses,
                    volunteers)

app = Flask(__name__)

for module in (clock, cycles, contests, filings, questionnaires, responses,
               measures, editions, forums, volunteers, incidents):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return respond.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return respond.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return respond.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return respond.error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
