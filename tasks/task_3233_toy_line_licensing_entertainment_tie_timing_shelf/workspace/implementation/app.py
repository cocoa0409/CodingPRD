import os
from flask import Flask
from util import ApiErr, err_resp, req_meta
from flask import jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

import studios, properties, agreements, lines, skus, factories, tooling, retail, commitments, shipments, safety, clockbp

for bp in (studios.bp, properties.bp, agreements.bp, lines.bp, skus.bp, factories.bp,
           tooling.bp, retail.bp, commitments.bp, shipments.bp, safety.bp, clockbp.bp):
    app.register_blueprint(bp, url_prefix="/toy-licensing")

@app.errorhandler(ApiErr)
def handle_api_err(e):
    return err_resp(e)

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}), 404

@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiErr):
        return err_resp(e)
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)}}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
