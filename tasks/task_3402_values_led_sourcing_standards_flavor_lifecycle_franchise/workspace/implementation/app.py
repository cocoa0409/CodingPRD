"""Values-Led Creamery API — Flask entry point.

All resources are mounted under /creamery. The store starts empty on every
boot (in-memory only, no seeding). Time-driven evaluations are applied
lazily before every request as well as on clock advance.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import audits
import campaigns
import certifications
import claims
import clockops
import commitments
import farms
import flavors
import orders
import payments
import revivals
import shops
import slots
import suppliers
from envelope import err
from errors import ApiError

app = Flask(__name__)


@app.before_request
def _time_sweep():
    # Lazy application of certification expiry, commitment lapse, and
    # production-slot completion whenever affected resources are touched.
    clockops.sweep()


_BLUEPRINTS = (
    clockops.bp,
    suppliers.bp,
    commitments.bp,
    certifications.bp,
    audits.bp,
    farms.bp,
    payments.bp,
    flavors.bp,
    claims.bp,
    revivals.bp,
    slots.bp,
    campaigns.bp,
    shops.bp,
    orders.bp,
)
for _bp in _BLUEPRINTS:
    app.register_blueprint(_bp, url_prefix="/creamery")


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return err(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(Exception)
def _handle_other(exc):
    if isinstance(exc, HTTPException):
        return err("ERR_INVALID_REQUEST", exc.code or 400,
                   getattr(exc, "description", "Request failed"))
    return err("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
