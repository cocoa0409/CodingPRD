from routes import accounts, advisors, loans, misc, payouts, retention, settlements


def register(app):
    for module in (misc, advisors, accounts, payouts, loans, settlements, retention):
        app.register_blueprint(module.bp)