"""Entry point: wire the blueprints, install the error handlers, serve.

Nothing is seeded here.  The in-memory store is empty at import time and stays
empty until a test builds its own preconditions through the declared endpoints,
which is what makes every per-test reboot a genuinely fresh boot.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from response import register_error_handlers
from routes.elements import bp as elements_bp
from routes.exit_inspections import bp as exit_inspections_bp
from routes.fusion_orders import bp as fusion_orders_bp
from routes.launch_queues import bp as launch_queues_bp
from routes.members import bp as members_bp
from routes.minifigure_builds import bp as minifigure_builds_bp
from routes.replacement_requests import bp as replacement_requests_bp
from routes.reservations import bp as reservations_bp
from routes.store_events import bp as store_events_bp
from routes.stores import bp as stores_bp
from routes.theme_launches import bp as theme_launches_bp
from routes.wall_bins import bp as wall_bins_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    register_error_handlers(app)

    app.register_blueprint(stores_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(elements_bp)
    app.register_blueprint(wall_bins_bp)
    app.register_blueprint(fusion_orders_bp)
    app.register_blueprint(exit_inspections_bp)
    app.register_blueprint(minifigure_builds_bp)
    app.register_blueprint(theme_launches_bp)
    app.register_blueprint(launch_queues_bp)
    app.register_blueprint(store_events_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(replacement_requests_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)