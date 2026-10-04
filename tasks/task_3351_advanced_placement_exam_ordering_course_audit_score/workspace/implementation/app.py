"""Entry point: registers every route module and serves the API.

The store is empty at boot and the logical clock starts at 2026-09-01T00:00:00Z;
nothing is seeded, so each fresh process begins from a clean database.
"""

import os

import clock
from core import app

import routes_audits          # noqa: F401
import routes_accommodations  # noqa: F401
import routes_alternates      # noqa: F401
import routes_clock           # noqa: F401
import routes_irregularities  # noqa: F401
import routes_orders          # noqa: F401
import routes_readers         # noqa: F401
import routes_registrations   # noqa: F401
import routes_schools         # noqa: F401
import routes_scores          # noqa: F401
import routes_sends           # noqa: F401
import routes_shipments       # noqa: F401
import routes_students        # noqa: F401

clock.reset()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
