"""Route blueprint registration."""


def register_routes(app):
    from routes.orgs import bp as orgs_bp
    from routes.donations import bp as donations_bp
    from routes.items import bp as items_bp
    from routes.production import bp as production_bp
    from routes.salvage import bp as salvage_bp
    from routes.funding import bp as funding_bp
    from routes.contracts import bp as contracts_bp

    app.register_blueprint(orgs_bp)
    app.register_blueprint(donations_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(salvage_bp)
    app.register_blueprint(funding_bp)
    app.register_blueprint(contracts_bp)
