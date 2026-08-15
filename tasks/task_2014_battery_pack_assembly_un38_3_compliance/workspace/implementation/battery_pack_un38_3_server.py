"""Battery Pack Assembly & UN38.3 Compliance API — Flask entry point.

Business resources live under /api; the logical-clock capability sits outside
that prefix (PRD §2.13). The store starts empty on every boot — no seeding."""

import os

from flask import Flask

from errors import ApiError, err_not_found, err_invalid_request
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_programs
import routes_lots
import routes_boms
import routes_packs
import routes_firmware
import routes_storage
import routes_shipments
import routes_rma
import routes_recalls
import routes_flat

for module in (
    routes_lots,
    routes_boms,
    routes_packs,
    routes_firmware,
    routes_storage,
    routes_shipments,
    routes_rma,
    routes_recalls,
    routes_flat,
):
    app.register_blueprint(module.bp, url_prefix="/api")

app.register_blueprint(routes_programs.bp, url_prefix="/api")
app.register_blueprint(routes_programs.bp_clock)  # /_clock — outside /api


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _http_404(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def _http_405(err):
    return error_response(err_not_found("Method not allowed"))


@app.errorhandler(Exception)
def _http_500(err):
    if isinstance(err, ApiError):
        return error_response(err)
    import traceback
    traceback.print_exc()
    return error_response(err_invalid_request("Unhandled server error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
