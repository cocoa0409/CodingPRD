"""Entry point: Flask app assembly, error handling, route registration."""
import os

from flask import Flask, jsonify

from store import ApiError, err_body

import clock_route
import customers
import evaluations
import contracts
import plants
import pipeline
import tanks
import deliveries
import quality
import turnarounds
import settlements

app = Flask(__name__)
app.json.sort_keys = False

for module in (clock_route, customers, evaluations, contracts, plants,
               pipeline, tanks, deliveries, quality, turnarounds, settlements):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = err_body(err.error_id, err.message)
    return jsonify(body), err.http_status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
