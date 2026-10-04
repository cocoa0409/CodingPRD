"""Flask application entry point."""
import os

from flask import Flask

from helpers import register_error_handlers


def create_app():
    app = Flask(__name__)
    register_error_handlers(app)

    import routes_core
    import routes_orgs
    import routes_seats
    import routes_editor
    import routes_projects
    import routes_reports
    import routes_invoices
    import routes_policy
    import routes_marketplace
    import routes_exports
    import routes_audits
    import routes_migration

    for mod in (
        routes_core, routes_orgs, routes_seats, routes_editor, routes_projects,
        routes_reports, routes_invoices, routes_policy, routes_marketplace,
        routes_exports, routes_audits, routes_migration,
    ):
        app.register_blueprint(mod.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
