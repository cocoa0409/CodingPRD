def register_all(app):
    from routes import (
        clock,
        schools,
        teachers,
        vendors,
        projects,
        donors,
        campaigns,
        orders,
        fraud,
        equity,
    )

    for module in (clock, schools, teachers, vendors, projects, donors,
                   campaigns, orders, fraud, equity):
        module.register(app)
