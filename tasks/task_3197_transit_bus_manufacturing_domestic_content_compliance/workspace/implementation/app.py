"""Entry point: Flask app assembly and error handlers."""
import os
from flask import Flask, jsonify
from errors import ApiError
from response import error_body

app = Flask(__name__)

from routes.clock import bp as clock_bp
from routes.agencies import bp as agencies_bp
from routes.contracts import bp as contracts_bp
from routes.configurations import bp as configurations_bp
from routes.components import bp as components_bp
from routes.buses import bp as buses_bp
from routes.certificates import bp as certificates_bp
from routes.audits import bp as audits_bp
from routes.production import bp as production_bp
from routes.inspections import bp as inspections_bp
from routes.warranty import bp as warranty_bp
from routes.warranty_ops import bp as warranty_ops_bp

for bp in (
    clock_bp, agencies_bp, contracts_bp, configurations_bp, components_bp,
    buses_bp, certificates_bp, audits_bp, production_bp, inspections_bp,
    warranty_bp, warranty_ops_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Referenced resource id does not exist")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    import traceback
    traceback.print_exc()
    return jsonify(error_body("ERR_VALIDATION", f"Unexpected error: {e}")), 422


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
