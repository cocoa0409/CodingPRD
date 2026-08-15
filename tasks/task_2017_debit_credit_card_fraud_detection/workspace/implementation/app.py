"""Fraud Ops API — Flask application entry point."""

import os

from flask import Flask

import errors
import response
from errors import ApiError
from routes import (
    accounts,
    auth_transactions,
    cards,
    chargeback_cases,
    clock,
    compromised_card_events,
    fraud_alerts,
    fraud_rings,
    loss_entries,
    recovery_filings,
    reissue_decisions,
    rule_sets,
    travel_notices,
    verification_contacts,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(clock.bp)
app.register_blueprint(rule_sets.bp)
app.register_blueprint(accounts.bp)
app.register_blueprint(cards.bp)
app.register_blueprint(auth_transactions.bp)
app.register_blueprint(fraud_alerts.bp)
app.register_blueprint(verification_contacts.bp)
app.register_blueprint(compromised_card_events.bp)
app.register_blueprint(reissue_decisions.bp)
app.register_blueprint(travel_notices.bp)
app.register_blueprint(chargeback_cases.bp)
app.register_blueprint(loss_entries.bp)
app.register_blueprint(recovery_filings.bp)
app.register_blueprint(fraud_rings.bp)


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return response.error(err)


@app.errorhandler(404)
def handle_404(err):
    return response.error(ApiError(errors.ERR_NOT_FOUND, "Not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return response.error(ApiError(errors.ERR_NOT_FOUND, "Not found", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Re-raise ApiError so it is not swallowed by the generic handler
    if isinstance(err, ApiError):
        return response.error(err)
    import traceback

    traceback.print_exc()
    return response.error(
        ApiError(errors.ERR_INVALID_REQUEST, f"Internal error: {err}", 500)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
