"""Route registration."""


def register_blueprints(app):
    from routes.workers import bp as workers_bp
    from routes.programs import bp as programs_bp
    from routes.units import bp as units_bp
    from routes.items import bp as items_bp
    from routes.commits import bp as commits_bp
    from routes.appeals import bp as appeals_bp
    from routes.clock import bp as clock_bp

    for blueprint in (
        workers_bp,
        programs_bp,
        units_bp,
        items_bp,
        commits_bp,
        appeals_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)