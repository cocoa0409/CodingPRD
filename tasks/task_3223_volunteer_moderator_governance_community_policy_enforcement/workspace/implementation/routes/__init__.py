"""routes package — one module per resource group."""

from routes.communities import bp as communities_bp
from routes.rules import bp as rules_bp
from routes.moderators import bp as moderators_bp
from routes.successions import bp as successions_bp
from routes.posts import bp as posts_bp
from routes.detection import bp as detection_bp
from routes.accounts import bp as accounts_bp
from routes.brigades import bp as brigades_bp
from routes.protests import bp as protests_bp
from routes.administration import bp as administration_bp

BLUEPRINTS = (
    communities_bp,
    rules_bp,
    moderators_bp,
    successions_bp,
    posts_bp,
    detection_bp,
    accounts_bp,
    brigades_bp,
    protests_bp,
    administration_bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app