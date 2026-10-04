"""Flask application entry point."""
import os
import json
from datetime import datetime, date
from flask import Flask

from errors import register_error_handlers


class JsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            s = o.astimezone().isoformat()
            if o.tzinfo is not None and s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
        if isinstance(o, date):
            return o.isoformat()
        return super().default(o)


def create_app():
    app = Flask(__name__)
    app.json_encoder = JsonEncoder
    try:
        app.json.default = JsonEncoder().default
    except Exception:
        pass

    register_error_handlers(app)

    import routes_core
    import routes_procurement
    import routes_grades
    import routes_heats
    import routes_quality
    import routes_campaigns
    import routes_commercial
    import routes_energy
    import routes_scorecards

    for mod in (routes_core, routes_procurement, routes_grades, routes_heats,
                routes_quality, routes_campaigns, routes_commercial,
                routes_energy, routes_scorecards):
        app.register_blueprint(mod.bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
