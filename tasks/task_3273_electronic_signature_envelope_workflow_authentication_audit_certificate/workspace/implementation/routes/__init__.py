"""Route blueprints for the esign API (api_prefix: /esign)."""

from routes.accounts import bp as accounts_bp
from routes.templates import bp as templates_bp
from routes.envelopes import bp as envelopes_bp
from routes.recipients import bp as recipients_bp
from routes.misc import bp as misc_bp


def register(app):
    app.register_blueprint(accounts_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(envelopes_bp)
    app.register_blueprint(recipients_bp)
    app.register_blueprint(misc_bp)