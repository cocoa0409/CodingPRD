"""Auth: X-User-Role header must name a declared role; per-endpoint role lists."""

from flask import request

from errors import err_unauthenticated, err_unauthorized

ROLES = {
    "PlantOperator",
    "ContractsManager",
    "EnergyTrader",
    "EnvironmentalOfficer",
    "Regulator",
}

ALL = ["PlantOperator", "ContractsManager", "EnergyTrader", "EnvironmentalOfficer", "Regulator"]


def require_role(allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    if role not in allowed:
        raise err_unauthorized()
    return role
