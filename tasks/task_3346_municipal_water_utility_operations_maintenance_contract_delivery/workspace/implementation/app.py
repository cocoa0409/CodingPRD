"""Entry point: registers every route module and serves the API.

Storage is in-memory only.  A fresh process starts with empty collections and
the fixed default logical instant of 2026-09-01T00:00:00Z; nothing is seeded.
"""
import os

from core import app  # noqa: F401  (the Flask application object)

# Importing these modules registers their routes on the shared app.
import routes_contracts  # noqa: F401
import routes_standards  # noqa: F401
import routes_staffing  # noqa: F401
import routes_assets  # noqa: F401
import routes_pm  # noqa: F401
import routes_workorders  # noqa: F401
import routes_permits  # noqa: F401
import routes_emergency  # noqa: F401
import routes_renewal  # noqa: F401
import routes_misc  # noqa: F401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
