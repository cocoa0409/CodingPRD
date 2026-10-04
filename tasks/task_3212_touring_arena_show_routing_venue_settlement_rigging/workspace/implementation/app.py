"""Entry point: Flask app with all route blueprints."""
import os

from flask import Flask

from response import register_error_handlers
from routes import tours, venues, engagements, rigging, labor, trucks, tickets, settlements, licenses, inspections, flat


def create_app():
    app = Flask(__name__)
    register_error_handlers(app)
    for mod in (tours, venues, engagements, rigging, labor, trucks, tickets,
                settlements, licenses, inspections, flat):
        app.register_blueprint(mod.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
