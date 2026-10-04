"""Route registration. Each handler module exposes API_ROUTES; they are all
attached to the single `/smart-rent` blueprint by the same decorator stack that
enforces auth and RBAC (PRD 2.1, 2.12 priorities 1-2)."""

import routes

ENDPOINT_PREFIX = "ep"


def attach_all():
    from routes import (
        alerts,
        clock_routes,
        devices,
        guests,
        installations,
        maintenance,
        portfolio,
        residents,
        tours,
        vacant,
    )

    modules = [
        clock_routes,
        portfolio,
        devices,
        residents,
        guests,
        tours,
        maintenance,
        installations,
        alerts,
        vacant,
    ]

    for module in modules:
        for index, (method, path, handler) in enumerate(module.API_ROUTES):
            endpoint = "%s_%s_%s" % (
                ENDPOINT_PREFIX,
                module.__name__.rsplit(".", 1)[-1],
                index,
            )
            routes.api.add_url_rule(
                path, endpoint=endpoint, view_func=handler, methods=[method]
            )