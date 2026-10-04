"""Authentication, endpoint authorization and request-shape validation.

Priority order (PRD 2.1, 2.8 / SCAFFOLD 1.4):
  1  auth            ERR_UNAUTHENTICATED / ERR_INVALID_REQUEST
  2  auth            ERR_UNAUTHORIZED
  3  existence       ERR_RESOURCE_NOT_FOUND (path resources, left to right)
  4  existence       ERR_RESOURCE_NOT_FOUND (body foreign keys, declared order)
  ...
"""

from flask import request

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

ROLES = (
    "HubOpsManager",
    "SortSupervisor",
    "SortOperator",
    "LoadPlanner",
    "CommitmentController",
    "FeederCoordinator",
    "GatewayCoordinator",
    "HazmatCertifier",
    "WeatherOfficer",
    "RefundAdjuster",
)

# --- endpoint map ------------------------------------------------------------
# key: (METHOD, path template with <name> placeholders)
# value: (allowed roles tuple, {"path": [table,...], "body": [table or ('table', field)]})
#
# ALL_ROLES is the ten-role read set; the claim append is the one endpoint that
# is shared by exactly three roles.
ALL_ROLES = ROLES

ENDPOINTS = {}


def register(method, path, roles, path_tables=(), body_checks=(), body_order=None,
             inputs=None):
    ENDPOINTS[(method, path)] = {
        "roles": tuple(roles),
        "path_tables": tuple(path_tables),
        "body_checks": tuple(body_checks),
        "body_order": tuple(body_order or ()),
        "inputs": None if inputs is None else frozenset(inputs),
    }


_ALL = ALL_ROLES

register("POST", "/_clock/set_current_utc", ["HubOpsManager"])

register("POST", "/airhub/hubs", ["HubOpsManager"])
register("GET", "/airhub/hubs", _ALL)
register("GET", "/airhub/hubs/<hub_id>", _ALL, path_tables=[("hubs", "hub_id")])
register("POST", "/airhub/hubs/<hub_id>/declare-contingency", ["WeatherOfficer"], path_tables=[("hubs", "hub_id")])
register("POST", "/airhub/hubs/<hub_id>/clear-contingency", ["HubOpsManager"], path_tables=[("hubs", "hub_id")])
register("POST", "/airhub/hubs/<hub_id>/ground-stop", ["HubOpsManager"], path_tables=[("hubs", "hub_id")])
register("POST", "/airhub/hubs/<hub_id>/run-ops", ["HubOpsManager"], path_tables=[("hubs", "hub_id")])
register("POST", "/airhub/hubs/<hub_id>/volume-override", ["HubOpsManager"], path_tables=[("hubs", "hub_id")])
register("GET", "/airhub/hubs/<hub_id>/refund-summary",
         ["HubOpsManager", "RefundAdjuster", "CommitmentController", "WeatherOfficer"],
         path_tables=[("hubs", "hub_id")])
register("GET", "/airhub/hubs/<hub_id>/triage", ["HubOpsManager", "SortSupervisor"],
         path_tables=[("hubs", "hub_id")])

register("POST", "/airhub/banks", ["HubOpsManager"], body_checks=["hubs"], body_order=["hub_id"])
register("GET", "/airhub/banks", _ALL)
register("GET", "/airhub/banks/<bank_id>", _ALL, path_tables=[("banks", "bank_id")])
register("POST", "/airhub/banks/<bank_id>/begin-unload", ["SortSupervisor"], path_tables=[("banks", "bank_id")])
register("POST", "/airhub/banks/<bank_id>/abandon", ["HubOpsManager"], path_tables=[("banks", "bank_id")])

register("POST", "/airhub/aircraft", ["GatewayCoordinator"], body_checks=["banks"], body_order=["bank_id"])
register("GET", "/airhub/aircraft", _ALL)
register("GET", "/airhub/aircraft/<aircraft_id>", _ALL, path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/depart-origin", ["GatewayCoordinator"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/land", ["GatewayCoordinator"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/begin-unload", ["SortSupervisor"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/complete-unload", ["SortSupervisor"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/cancel", ["HubOpsManager"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/divert-maintenance", ["WeatherOfficer"], path_tables=[("aircraft", "aircraft_id")])
register("POST", "/airhub/aircraft/<aircraft_id>/reinstate", ["HubOpsManager"], path_tables=[("aircraft", "aircraft_id")])

register("POST", "/airhub/packages", ["SortOperator"],
         body_checks=["hubs", "aircraft"], body_order=["hub_id", "aircraft_id"])
register("GET", "/airhub/packages", _ALL)
register("GET", "/airhub/packages/<package_id>", _ALL, path_tables=[("packages", "package_id")])
register("GET", "/airhub/packages/<package_id>/failures", _ALL, path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/induct", ["SortOperator"], path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/reject-induction", ["SortOperator"], path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/primary-sort", ["SortOperator"],
         path_tables=[("packages", "package_id")], body_checks=["lanes"], body_order=["lane_id"])
register("POST", "/airhub/packages/<package_id>/secondary-sort", ["SortOperator"],
         path_tables=[("packages", "package_id")], body_checks=["lanes"], body_order=["lane_id"])
register("POST", "/airhub/packages/<package_id>/reclaim-lane", ["SortOperator"], path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/route-irregular", ["SortSupervisor"],
         path_tables=[("packages", "package_id")], body_checks=["lanes"], body_order=["lane_id"])
register("POST", "/airhub/packages/<package_id>/resolve-irregular", ["SortSupervisor"], path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/route-hazmat", ["HazmatCertifier"],
         path_tables=[("packages", "package_id")], body_checks=["lanes"], body_order=["lane_id"])
register("POST", "/airhub/packages/<package_id>/resolve-hazmat", ["HazmatCertifier"], path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/downgrade-commitment", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/ground-downgrade", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/diverge", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/upgrade-hold", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/clear-reroute", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/clear-upgrade-hold", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/void", ["CommitmentController"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/claim-indemnity", ["RefundAdjuster"],
         path_tables=[("packages", "package_id")])
register("POST", "/airhub/packages/<package_id>/assign-aircraft", ["GatewayCoordinator"],
         path_tables=[("packages", "package_id")], body_checks=["aircraft"], body_order=["aircraft_id"])

register("POST", "/airhub/lanes", ["SortSupervisor"], body_checks=["hubs"], body_order=["hub_id"])
register("GET", "/airhub/lanes", _ALL)
register("GET", "/airhub/lanes/concourse-width", ["HubOpsManager", "SortSupervisor", "SortOperator"])
register("GET", "/airhub/lanes/<lane_id>", _ALL, path_tables=[("lanes", "lane_id")])
register("POST", "/airhub/lanes/<lane_id>/close", ["SortSupervisor"], path_tables=[("lanes", "lane_id")])
register("POST", "/airhub/lanes/<lane_id>/reopen", ["SortSupervisor"], path_tables=[("lanes", "lane_id")])

register("POST", "/airhub/moves", ["LoadPlanner"],
         body_checks=["hubs", "aircraft"], body_order=["hub_id", "aircraft_id"])
register("GET", "/airhub/moves", _ALL)
register("GET", "/airhub/moves/<move_id>", _ALL, path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/plan-load", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/begin-loading", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/complete-load", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/replan", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/cancel", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/load-package", ["LoadPlanner"],
         path_tables=[("moves", "move_id")], body_checks=["packages"], body_order=["package_id"])
register("POST", "/airhub/moves/<move_id>/unload-package", ["LoadPlanner"],
         path_tables=[("moves", "move_id")], body_checks=["packages"], body_order=["package_id"])
register("POST", "/airhub/moves/<move_id>/assign-buildup", ["LoadPlanner"],
         path_tables=[("moves", "move_id")], body_checks=["packages", "buildups"],
         body_order=["package_id", "buildup_id"])
register("POST", "/airhub/moves/<move_id>/set-tier", ["LoadPlanner"], path_tables=[("moves", "move_id")])
register("POST", "/airhub/moves/<move_id>/gateway-requirements", ["LoadPlanner"], path_tables=[("moves", "move_id")])

register("POST", "/airhub/buildups", ["LoadPlanner"],
         body_checks=["hubs", "moves"], body_order=["hub_id", "load_move_id"])
register("GET", "/airhub/buildups", _ALL)
register("GET", "/airhub/buildups/<buildup_id>", _ALL, path_tables=[("buildups", "buildup_id")])
register("POST", "/airhub/buildups/<buildup_id>/seal", ["LoadPlanner"], path_tables=[("buildups", "buildup_id")])
register("POST", "/airhub/buildups/<buildup_id>/unseal", ["LoadPlanner"], path_tables=[("buildups", "buildup_id")])
register("POST", "/airhub/buildups/<buildup_id>/cancel", ["LoadPlanner"], path_tables=[("buildups", "buildup_id")])
register("POST", "/airhub/buildups/<buildup_id>/set-tier", ["LoadPlanner"], path_tables=[("buildups", "buildup_id")])

register("POST", "/airhub/feeders", ["FeederCoordinator"], body_checks=["hubs"], body_order=["hub_id"])
register("GET", "/airhub/feeders", _ALL)
register("GET", "/airhub/feeders/<feeder_id>", _ALL, path_tables=[("feeders", "feeder_id")])
register("POST", "/airhub/feeders/<feeder_id>/begin-staging", ["FeederCoordinator"], path_tables=[("feeders", "feeder_id")])
register("POST", "/airhub/feeders/<feeder_id>/stage-package", ["FeederCoordinator"],
         path_tables=[("feeders", "feeder_id")], body_checks=["packages"], body_order=["package_id"])
register("POST", "/airhub/feeders/<feeder_id>/begin-loading", ["FeederCoordinator"], path_tables=[("feeders", "feeder_id")])
register("POST", "/airhub/feeders/<feeder_id>/depart", ["FeederCoordinator"], path_tables=[("feeders", "feeder_id")])
register("POST", "/airhub/feeders/<feeder_id>/cancel", ["FeederCoordinator"], path_tables=[("feeders", "feeder_id")])

register("POST", "/airhub/shifts", ["SortSupervisor"], body_checks=["hubs"], body_order=["hub_id"])
register("GET", "/airhub/shifts", _ALL)
register("GET", "/airhub/shifts/<shift_id>", _ALL, path_tables=[("shifts", "shift_id")])
register("POST", "/airhub/shifts/<shift_id>/cancel", ["SortSupervisor"], path_tables=[("shifts", "shift_id")])
register("POST", "/airhub/shifts/<shift_id>/complete", ["SortSupervisor"], path_tables=[("shifts", "shift_id")])
register("POST", "/airhub/shifts/<shift_id>/forecast-volume", ["SortSupervisor"], path_tables=[("shifts", "shift_id")])

register("GET", "/airhub/ops-runs", _ALL)
register("GET", "/airhub/ops-runs/<ops_run_id>", _ALL, path_tables=[("ops_runs", "ops_run_id")])
register("POST", "/airhub/ops-runs/<ops_run_id>/advance", ["HubOpsManager"], path_tables=[("ops_runs", "ops_run_id")])
register("POST", "/airhub/ops-runs/<ops_run_id>/release", ["HubOpsManager"], path_tables=[("ops_runs", "ops_run_id")])

register("POST", "/airhub/failures", ["RefundAdjuster"],
         body_checks=["hubs", "packages"], body_order=["hub_id", "package_id"])
register("GET", "/airhub/failures", _ALL)
register("GET", "/airhub/failures/<failure_id>", _ALL, path_tables=[("failures", "failure_id")])
register("POST", "/airhub/failures/<failure_id>/finalize", ["RefundAdjuster"], path_tables=[("failures", "failure_id")])
register("POST", "/airhub/failures/<failure_id>/dispute", ["RefundAdjuster"], path_tables=[("failures", "failure_id")])
register("POST", "/airhub/failures/<failure_id>/reopen", ["RefundAdjuster"], path_tables=[("failures", "failure_id")])
register("POST", "/airhub/failures/<failure_id>/void", ["RefundAdjuster"], path_tables=[("failures", "failure_id")])
register("POST", "/airhub/failures/<failure_id>/claims",
         ["RefundAdjuster", "HubOpsManager", "WeatherOfficer"], path_tables=[("failures", "failure_id")])
register("GET", "/airhub/failures/<failure_id>/claims", _ALL, path_tables=[("failures", "failure_id")])
register("GET", "/airhub/service-failure-claims", _ALL)
register("GET", "/airhub/service-failure-claims/<claim_id>", _ALL, path_tables=[("claims", "claim_id")])


def authenticate():
    """Priority 1: the acting role must be declared, the identifier present."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED)
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise ApiError(ERR_UNAUTHENTICATED)
    return user_id, role


def authorize(spec, role):
    """Priority 2: the acting role must be permitted on this endpoint."""
    if role not in spec["roles"]:
        raise ApiError(ERR_UNAUTHORIZED)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def check_path_resources(store, spec, view_args):
    """Priority 3: path resources, left to right."""
    for table, arg_name in spec["path_tables"]:
        if store.get(table, view_args.get(arg_name)) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND)


def check_body_fks(store, spec, payload, hub_scope=None):
    """Priority 4: body foreign keys, in declared input order, hub-scoped."""
    for table in spec["body_checks"]:
        field = None
        singular = {
            "hubs": "hub_id",
            "banks": "bank_id",
            "aircraft": "aircraft_id",
            "packages": "package_id",
            "lanes": "lane_id",
            "moves": "load_move_id",
            "buildups": "buildup_id",
            "shifts": "shift_id",
            "failures": "service_failure_id",
        }.get(table)
        if table in ("moves",) and "move_id" in payload:
            field = "move_id"
        if table == "buildups" and "buildup_id" in payload:
            field = "buildup_id"
        if field is None:
            field = singular
        if field is None or field not in payload:
            continue
        record = store.get(table, payload.get(field))
        if record is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND)
        if hub_scope is not None and record.get("hub_id") not in (None, hub_scope):
            raise ApiError(ERR_RESOURCE_NOT_FOUND)


def require_fields(payload, required):
    for name in required:
        if name not in payload or payload[name] is None:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_enum(payload, name, allowed):
    value = payload.get(name)
    if value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid value for %s." % name)
    return value


def require_int(payload, name, minimum=None, maximum=None):
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "%s is out of range." % name)
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "%s is out of range." % name)
    return value


def require_str(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a non-empty string." % name)
    return value


def optional_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a boolean." % name)
    return value

# --- declared input field sets (SCAFFOLD 1.5 endpoints[].input) --------------
# Priority 1 rejects a body carrying any field outside the declared input list.
DECLARED_INPUTS = {
    ("POST", "/_clock/set_current_utc"): ("current_utc",),
    ("POST", "/airhub/hubs"): ("iata_code", "name", "sort_window_open_minutes",
                               "sort_window_close_minutes", "alternate_hub_id"),
    ("POST", "/airhub/banks"): ("hub_id", "bank_code", "scheduled_start_minutes",
                                "scheduled_end_minutes", "hydraulic_crew_available"),
    ("POST", "/airhub/aircraft"): ("bank_id", "tail_number", "origin_station_code",
                                   "scheduled_arrival_minutes", "capacity_weight_grams"),
    ("POST", "/airhub/aircraft/<aircraft_id>/land"): ("inbound_weight_grams",),
    ("POST", "/airhub/aircraft/<aircraft_id>/complete-unload"): ("unload_completed_minutes",),
    ("POST", "/airhub/aircraft/<aircraft_id>/cancel"): ("cause_code",),
    ("POST", "/airhub/packages"): ("hub_id", "aircraft_id", "tracking_number",
                                   "commodity_class", "destination_hub_code",
                                   "service_level", "planned_weight_grams",
                                   "dimension_weight_grams", "acknowledgement_number"),
    ("POST", "/airhub/packages/<package_id>/induct"): ("dimension_weight_grams",),
    ("POST", "/airhub/packages/<package_id>/primary-sort"): ("lane_id",),
    ("POST", "/airhub/packages/<package_id>/secondary-sort"): ("lane_id",),
    ("POST", "/airhub/packages/<package_id>/route-irregular"): ("lane_id",),
    ("POST", "/airhub/packages/<package_id>/route-hazmat"): ("lane_id",),
    ("POST", "/airhub/packages/<package_id>/downgrade-commitment"): ("expected_package_version",),
    ("POST", "/airhub/packages/<package_id>/claim-indemnity"): ("claimed_value_cents",),
    ("POST", "/airhub/packages/<package_id>/assign-aircraft"): ("aircraft_id",),
    ("POST", "/airhub/lanes"): ("hub_id", "lane_code", "lane_kind",
                                "commodity_capability", "capacity_weight_grams",
                                "certified_until_minutes", "turnout_start_minutes",
                                "turnout_end_minutes"),
    ("POST", "/airhub/moves"): ("hub_id", "aircraft_id", "weight_limit_grams"),
    ("POST", "/airhub/moves/<move_id>/load-package"): ("package_id", "buildup_id",
                                                       "expected_load_move_version",
                                                       "expected_package_version"),
    ("POST", "/airhub/moves/<move_id>/unload-package"): ("package_id",),
    ("POST", "/airhub/moves/<move_id>/assign-buildup"): ("package_id", "buildup_id"),
    ("POST", "/airhub/moves/<move_id>/set-tier"): ("load_plan_tier",),
    ("POST", "/airhub/moves/<move_id>/gateway-requirements"): ("destination_gateway_code",
                                                               "requires_container"),
    ("POST", "/airhub/buildups"): ("hub_id", "load_move_id", "destination_gateway_code",
                                   "container_limit_grams", "hazardous_cap_grams",
                                   "requires_container"),
    ("POST", "/airhub/buildups/<buildup_id>/seal"): ("expected_buildup_version",),
    ("POST", "/airhub/buildups/<buildup_id>/set-tier"): ("load_plan_tier",),
    ("POST", "/airhub/feeders"): ("hub_id", "feeder_code", "origin_station_code",
                                  "scheduled_departure_minutes", "stage_capacity_grams",
                                  "window_minutes"),
    ("POST", "/airhub/feeders/<feeder_id>/stage-package"): ("package_id",),
    ("POST", "/airhub/shifts"): ("hub_id", "shift_code", "start_minutes", "end_minutes",
                                 "headcount", "productivity_grams_per_operator_hour",
                                 "forecast_volume_grams", "certified_for_hazmat"),
    ("POST", "/airhub/shifts/<shift_id>/forecast-volume"): ("forecast_volume_grams",),
    ("POST", "/airhub/hubs/<hub_id>/run-ops"): ("minute_of_day", "level"),
    ("POST", "/airhub/hubs/<hub_id>/volume-override"): ("live_planned_package_total",),
    ("POST", "/airhub/failures"): ("hub_id", "package_id", "cause_code", "failure_minutes"),
    ("POST", "/airhub/failures/<failure_id>/claims"): ("outcome", "note"),
}


def check_body_shape(method, path, payload):
    """Priority 1: only declared input fields, correctly shaped, may appear."""
    declared = DECLARED_INPUTS.get((method, path))
    if declared is None:
        return
    for field in payload:
        if field not in declared:
            raise ApiError(ERR_INVALID_REQUEST, "Unknown field: %s" % field)
