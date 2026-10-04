"""Blueprint registration for every route module."""

from routes.accident_cases import bp as accident_cases_bp
from routes.clock_routes import bp as clock_bp
from routes.designations import bp as designations_bp
from routes.groups import bp as groups_bp
from routes.investigations import bp as investigations_bp
from routes.meetings import bp as meetings_bp
from routes.party_orgs import bp as party_orgs_bp
from routes.recommendations import bp as recommendations_bp
from routes.recorders import bp as recorders_bp


def register_routes(app):
    app.register_blueprint(clock_bp)
    app.register_blueprint(accident_cases_bp)
    app.register_blueprint(investigations_bp)
    app.register_blueprint(party_orgs_bp)
    app.register_blueprint(designations_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(recorders_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(meetings_bp)
