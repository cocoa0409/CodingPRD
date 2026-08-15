"""Blueprint registration."""


def register_routes(app):
    from .accounts import bp as accounts_bp
    from .wells import bp as wells_bp
    from .reports import bp as reports_bp
    from .transfers import bp as transfers_bp
    from .monitoring import bp as monitoring_bp
    from .snapshots import bp as snapshots_bp
    from .penalties import bp as penalties_bp
    from .annual import bp as annual_bp
    from .admin import bp as admin_bp

    for bp in (accounts_bp, wells_bp, reports_bp, transfers_bp, monitoring_bp,
               snapshots_bp, penalties_bp, annual_bp, admin_bp):
        app.register_blueprint(bp)
