"""Trading-card licensing, print-run and redemption-fulfilment API.

Entry point.  Binds 0.0.0.0:$PORT (default 10000) and runs in the foreground.

The store is in-memory and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded here or in any module imported at startup.
"""

import os

from core import app  # noqa: F401  (the shared Flask instance)

# Route registration.  Each module imports the shared `app` from `core` and
# attaches its own url rules.
import routes.clock            # noqa: E402,F401
import routes.licenses         # noqa: E402,F401
import routes.product_lines    # noqa: E402,F401
import routes.card_sets        # noqa: E402,F401
import routes.pack_configs     # noqa: E402,F401
import routes.signing          # noqa: E402,F401
import routes.artwork          # noqa: E402,F401
import routes.print_runs       # noqa: E402,F401
import routes.redemptions      # noqa: E402,F401
import routes.notifications    # noqa: E402,F401
import routes.distributions    # noqa: E402,F401
import routes.quality          # noqa: E402,F401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))