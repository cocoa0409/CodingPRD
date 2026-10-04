"""NAIC Model Law, Accreditation & Filings API — application entry point.

All endpoints are mounted under /naic. The logical clock starts at
2026-09-01T00:00:00Z and advances only via POST /naic/_clock/set_current_utc.
"""

import os

from flask import Flask, jsonify

from auth import authenticate, require_role, ROLE_ASSOCIATION_STAFF
from db import store, touch
from errors import ApiError
from util import get_body, req_ts, ok_object, error_body, meta_base

import routes_model_acts
import routes_exposure
import routes_states
import routes_reviews
import routes_insurers
import routes_filings
import routes_licensing
import routes_market
import routes_valuation

app = Flask(__name__)

for module in (
    routes_model_acts,
    routes_exposure,
    routes_states,
    routes_reviews,
    routes_insurers,
    routes_filings,
    routes_licensing,
    routes_market,
    routes_valuation,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err)), err.http_status


@app.errorhandler(404)
def handle_not_found(_err):
    # Undeclared path; the catalogue has no id for this, use the shape error.
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Unknown resource path"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


@app.post("/naic/_clock/set_current_utc")
def set_current_utc():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    new_clock = req_ts(body, "to_iso8601")
    store.clock = new_clock
    # License expiry sweep: advancing strictly past valid_until expires an
    # ISSUED license; valid_until == clock has not yet expired.
    for lic in store.licenses.values():
        if lic["status"] == "ISSUED" and lic["valid_until"] < new_clock:
            lic["status"] = "EXPIRED"
            touch(lic)
            producer = store.producers.get(lic["producer_id"])
            if producer is not None:
                producer["active_license_count"] -= 1
    return ok_object({}, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
