"""Flask entry point: dispatcher, error handlers and route registration.

The store is process-local and starts empty: nothing is seeded, preloaded or
registered at boot. Every resource any caller needs is created through the
declared API surface.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify  # noqa: E402

import dispatcher  # noqa: E402

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = False
dispatcher.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)