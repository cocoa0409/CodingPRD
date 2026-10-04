import os

from server_core import app
from routes import admin, agreements, vehicles, pricing, teaming, orders, billing, reporting  # noqa: F401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
