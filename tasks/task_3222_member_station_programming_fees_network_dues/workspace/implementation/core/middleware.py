"""Authentication, the role matrix and station-ownership pairing."""
from functools import wraps

from flask import jsonify, request

from . import base, config as C
from .errors import ApiError, ERR_STATUS
from .store import STORE

ROLES = (
    "PlatformAdmin",
    "StationManager",
    "NetworkComplianceAuditor",
    "NetworkScheduler",
    "NationalProgramEditor",
    "UnderwritingCoordinator",
    "NetworkGovernanceOfficer",
)

ALL_ROLES = ROLES

# --- per-endpoint role matrix (PRD §4) ---------------------------------------
ROUTE_ROLES = {
    # member stations
    ("POST", "/network/member-stations"): ("PlatformAdmin",),
    ("GET", "/network/member-stations"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor",
        "NationalProgramEditor", "NetworkGovernanceOfficer"),
    ("GET", "/network/member-stations/<sid>"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor",
        "NationalProgramEditor", "NetworkGovernanceOfficer"),
    ("PATCH", "/network/member-stations/<sid>"): (
        "StationManager", "NetworkComplianceAuditor"),
    ("POST", "/network/member-stations/<sid>/submit-eligibility"): ("StationManager",),
    ("POST", "/network/member-stations/<sid>/record-deficiency"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/remediation"): ("StationManager",),
    ("POST", "/network/member-stations/<sid>/approve-eligibility"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/probation"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/restore-eligibility"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/suspend"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/reinstate"): ("NetworkComplianceAuditor",),
    ("POST", "/network/member-stations/<sid>/withdraw"): ("StationManager",),
    ("POST", "/network/member-stations/<sid>/apply-contribution-credit"): ("StationManager",),
    ("POST", "/network/member-stations/<sid>/cost-efficiency-match"): ("NetworkGovernanceOfficer",),
    ("GET", "/network/member-station-standings"): (
        "PlatformAdmin", "NetworkGovernanceOfficer", "NetworkComplianceAuditor"),
    ("GET", "/network/member-stations/<sid>/assessments"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    # projections
    ("GET", "/network/dues-vote-eligibility-projections"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "NetworkComplianceAuditor"),
    ("GET", "/network/dues-vote-eligibility-projections/<pid>"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "NetworkComplianceAuditor"),
    # schedules and assessments
    ("POST", "/network/programming-fee-schedules"): ("PlatformAdmin",),
    ("GET", "/network/programming-fee-schedules"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    ("GET", "/network/programming-fee-schedules/<fid>"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    ("GET", "/network/programming-fee-schedules/<fid>/preview"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    ("GET", "/network/programming-fee-assessments"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    ("GET", "/network/programming-fee-assessments/<aid>"): (
        "PlatformAdmin", "StationManager", "NetworkComplianceAuditor"),
    ("POST", "/network/programming-fee-assessments/<aid>/finalize"): ("NetworkComplianceAuditor",),
    ("POST", "/network/programming-fee-assessments/<aid>/allocate-pool"): ("NetworkGovernanceOfficer",),
    # carriage
    ("POST", "/network/carriage-agreements"): ("StationManager",),
    ("GET", "/network/carriage-agreements"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkScheduler",
        "NationalProgramEditor"),
    ("GET", "/network/carriage-agreements/<aid>"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkScheduler",
        "NationalProgramEditor"),
    ("GET", "/network/carriage-agreements/<aid>/windows"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkScheduler"),
    ("POST", "/network/carriage-agreements/<aid>/submit"): ("StationManager",),
    ("POST", "/network/carriage-agreements/<aid>/review"): ("NetworkComplianceAuditor",),
    ("POST", "/network/carriage-agreements/<aid>/clear"): ("NetworkComplianceAuditor",),
    ("POST", "/network/carriage-agreements/<aid>/publish"): ("NetworkScheduler",),
    ("POST", "/network/carriage-agreements/<aid>/republish"): ("NetworkScheduler",),
    ("POST", "/network/carriage-agreements/<aid>/lift-publish-embargo"): ("NetworkComplianceAuditor",),
    ("POST", "/network/carriage-agreements/<aid>/expire"): ("NetworkComplianceAuditor",),
    ("POST", "/network/carriage-agreements/<aid>/terminate"): ("NetworkComplianceAuditor",),
    # windows
    ("POST", "/network/broadcast-windows"): ("StationManager",),
    ("GET", "/network/broadcast-windows"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkScheduler"),
    ("GET", "/network/broadcast-windows/<wid>"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkScheduler"),
    ("POST", "/network/broadcast-windows/<wid>/request-clearance"): ("StationManager",),
    ("POST", "/network/broadcast-windows/<wid>/clear"): ("NetworkComplianceAuditor",),
    ("POST", "/network/broadcast-windows/<wid>/reject"): ("NetworkComplianceAuditor",),
    ("POST", "/network/broadcast-windows/<wid>/remediating"): ("StationManager",),
    ("POST", "/network/broadcast-windows/<wid>/expire"): ("NetworkComplianceAuditor",),
    ("POST", "/network/series/embargo-check"): ("NetworkComplianceAuditor",),
    # feeds and slots
    ("POST", "/network/distribution-feeds"): ("NetworkScheduler",),
    ("GET", "/network/distribution-feeds"): (
        "NetworkScheduler", "NetworkComplianceAuditor", "PlatformAdmin"),
    ("GET", "/network/distribution-feeds/<fid>"): (
        "NetworkScheduler", "NetworkComplianceAuditor", "PlatformAdmin"),
    ("GET", "/network/distribution-feeds/<fid>/uplink-slots"): (
        "NetworkScheduler", "NetworkComplianceAuditor"),
    ("POST", "/network/distribution-feeds/<fid>/bring-online"): ("NetworkScheduler",),
    ("POST", "/network/distribution-feeds/<fid>/maintenance"): ("NetworkScheduler",),
    ("POST", "/network/distribution-feeds/<fid>/restore"): ("NetworkScheduler",),
    ("POST", "/network/distribution-feeds/<fid>/take-offline"): ("NetworkScheduler",),
    ("POST", "/network/distribution-feeds/<fid>/replan"): ("NetworkScheduler",),
    ("POST", "/network/distribution-feeds/<fid>/suspend"): ("PlatformAdmin",),
    ("GET", "/network/uplink-slots"): (
        "NetworkScheduler", "StationManager", "NetworkComplianceAuditor"),
    ("POST", "/network/uplink-slots"): ("StationManager",),
    ("POST", "/network/uplink-slots/block"): ("StationManager",),
    ("GET", "/network/uplink-slots/<sid>"): (
        "NetworkScheduler", "StationManager", "NetworkComplianceAuditor"),
    ("POST", "/network/uplink-slots/<sid>/air"): ("NetworkScheduler",),
    ("POST", "/network/uplink-slots/<sid>/release"): ("NetworkScheduler",),
    ("POST", "/network/uplink-slots/<sid>/preemption-review"): ("NetworkScheduler",),
    # underwriting
    ("POST", "/network/underwriting-agreements"): ("UnderwritingCoordinator",),
    ("GET", "/network/underwriting-agreements"): (
        "UnderwritingCoordinator", "NetworkComplianceAuditor", "StationManager"),
    ("GET", "/network/underwriting-agreements/<uid>"): (
        "UnderwritingCoordinator", "NetworkComplianceAuditor", "StationManager"),
    ("POST", "/network/underwriting-agreements/<uid>/submit-for-review"): ("UnderwritingCoordinator",),
    ("POST", "/network/underwriting-agreements/<uid>/approve"): ("NetworkComplianceAuditor",),
    ("POST", "/network/underwriting-agreements/<uid>/reject"): ("NetworkComplianceAuditor",),
    ("POST", "/network/underwriting-agreements/<uid>/schedule"): ("UnderwritingCoordinator",),
    ("POST", "/network/underwriting-agreements/<uid>/air-segment"): ("UnderwritingCoordinator",),
    # contributions
    ("POST", "/network/content-contributions"): ("StationManager",),
    ("GET", "/network/content-contributions"): (
        "StationManager", "NationalProgramEditor", "NetworkComplianceAuditor"),
    ("GET", "/network/content-contributions/<cid>"): (
        "StationManager", "NationalProgramEditor", "NetworkComplianceAuditor"),
    ("POST", "/network/content-contributions/<cid>/submit"): ("StationManager",),
    ("POST", "/network/content-contributions/<cid>/shortlist"): ("NationalProgramEditor",),
    ("POST", "/network/content-contributions/<cid>/request-resubmission"): ("NationalProgramEditor",),
    ("POST", "/network/content-contributions/<cid>/license"): ("NationalProgramEditor",),
    ("POST", "/network/content-contributions/<cid>/mark-used"): ("NationalProgramEditor",),
    ("POST", "/network/content-contributions/<cid>/reject"): ("NationalProgramEditor",),
    ("POST", "/network/content-contributions/<cid>/withdraw"): ("StationManager",),
    # programs
    ("POST", "/network/national-programs"): ("NationalProgramEditor",),
    ("GET", "/network/national-programs"): (
        "NationalProgramEditor", "NetworkScheduler", "NetworkComplianceAuditor",
        "PlatformAdmin"),
    ("GET", "/network/national-programs/<pid>"): (
        "NationalProgramEditor", "NetworkScheduler", "NetworkComplianceAuditor",
        "PlatformAdmin"),
    ("GET", "/network/national-programs/<pid>/contributions"): (
        "NationalProgramEditor", "StationManager", "NetworkComplianceAuditor"),
    ("GET", "/network/national-programs/<pid>/carriage-agreements"): (
        "NationalProgramEditor", "NetworkComplianceAuditor", "NetworkScheduler"),
    ("POST", "/network/national-programs/<pid>/move-to-production"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/schedule"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/premiere"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/publish"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/premiere-embargo"): ("NetworkComplianceAuditor",),
    ("POST", "/network/national-programs/<pid>/reschedule-airings"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/return-to-development"): ("NationalProgramEditor",),
    ("POST", "/network/national-programs/<pid>/retire"): ("NationalProgramEditor",),
    # drives and reports
    ("POST", "/network/membership-drives"): ("StationManager",),
    ("GET", "/network/membership-drives"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkGovernanceOfficer"),
    ("GET", "/network/membership-drives/<did>"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkGovernanceOfficer"),
    ("POST", "/network/membership-drives/<did>/open"): ("StationManager",),
    ("POST", "/network/membership-drives/<did>/pledge"): ("StationManager",),
    ("POST", "/network/membership-drives/<did>/close"): ("StationManager",),
    ("POST", "/network/membership-drives/<did>/report"): ("StationManager",),
    ("POST", "/network/membership-drives/<did>/settle"): ("NetworkComplianceAuditor",),
    ("POST", "/network/membership-drives/<did>/cancel"): ("NetworkComplianceAuditor",),
    ("POST", "/network/audience-reports"): ("StationManager",),
    ("GET", "/network/audience-reports"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkGovernanceOfficer"),
    ("GET", "/network/audience-reports/<rid>"): (
        "StationManager", "NetworkComplianceAuditor", "NetworkGovernanceOfficer"),
    # dues proposals and votes
    ("POST", "/network/dues-proposals"): ("NetworkGovernanceOfficer",),
    ("GET", "/network/dues-proposals"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("GET", "/network/dues-proposals/<pid>"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("GET", "/network/dues-proposals/<pid>/votes"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager",
        "NetworkComplianceAuditor"),
    ("POST", "/network/dues-proposals/<pid>/open"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/dues-proposals/<pid>/votes"): ("StationManager",),
    ("POST", "/network/dues-proposals/<pid>/tally"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/dues-proposals/<pid>/table"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/dues-proposals/<pid>/enact"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/dues-proposals/<pid>/close-enactment"): ("NetworkGovernanceOfficer",),
    ("GET", "/network/station-votes"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager",
        "NetworkComplianceAuditor"),
    ("GET", "/network/station-votes/<vid>"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager",
        "NetworkComplianceAuditor"),
    ("POST", "/network/station-votes/<vid>/supersede"): ("StationManager",),
    ("POST", "/network/station-votes/<vid>/restore"): ("NetworkGovernanceOfficer",),
    # elections, candidacies, seats
    ("POST", "/network/board-elections"): ("NetworkGovernanceOfficer",),
    ("GET", "/network/board-elections"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("GET", "/network/board-elections/<eid>"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("GET", "/network/board-elections/<eid>/candidates"): (
        "NetworkGovernanceOfficer", "StationManager"),
    ("POST", "/network/board-elections/<eid>/close"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/certify"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/contest"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/reopen"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/hold-over"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/vacate-seat"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-elections/<eid>/finalize"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-candidates"): ("StationManager",),
    ("GET", "/network/board-candidates"): ("NetworkGovernanceOfficer", "StationManager"),
    ("GET", "/network/board-candidates/<cid>"): ("NetworkGovernanceOfficer", "StationManager"),
    ("POST", "/network/board-candidates/<cid>/qualify"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-candidates/<cid>/lapse"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-candidates/<cid>/record-votes"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-candidates/<cid>/withdraw"): ("StationManager",),
    ("POST", "/network/board-seats"): ("NetworkGovernanceOfficer",),
    ("GET", "/network/board-seats"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("GET", "/network/board-seats/<sid>"): (
        "NetworkGovernanceOfficer", "PlatformAdmin", "StationManager"),
    ("POST", "/network/board-seats/<sid>/deallocate"): ("NetworkGovernanceOfficer",),
    ("POST", "/network/board-seats/<sid>/recall"): ("NetworkGovernanceOfficer",),
    # clock
    ("POST", "/_clock/set_current_utc"): ("PlatformAdmin",),
}


def roles_for(rule, method):
    return ROUTE_ROLES.get((method, rule))


def principal():
    """Resolve the acting role and identity, or raise the 401."""
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    if role is None or ident is None:
        raise ApiError("ERR_MISSING_AUTH")
    if not isinstance(role, str) or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH")
    return role, ident


def require_role(rule, method):
    role, ident = principal()
    allowed = roles_for(rule, method)
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return role, ident


def owned_station_id(rec):
    """The foreign key that pairs a resource to an acting station."""
    if rec is None:
        return None
    return rec.get("station_id")


def check_station_ownership(role, ident, station_id):
    """A StationManager may only act for the station it owns."""
    if role == "StationManager":
        if station_id != ident:
            raise ApiError("ERR_FORBIDDEN_ROLE")
    return True


def check_station_attribution(role, ident, body, field="station_id"):
    """The pairing rule for endpoints carrying an acting-station attribution."""
    if role == "StationManager":
        named = base.get_body(body).get(field)
        if named is not None and named != ident:
            raise ApiError("ERR_FORBIDDEN_ROLE")
    return True


def station_for(ident):
    return STORE.member_stations.get(ident)


def route(rule, method):
    """Decorator: resolve authority, then hand the handler its principal.

    Flask invokes a view with the URL variables as keyword arguments only, so
    the wrapper accepts **kwargs and passes the principal positionally.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            require_role(rule, method)
            return fn(**kwargs)
        return wrapper
    return decorator


def install_error_handlers(app):
    from . import config as C

    def error_response(err):
        payload = {
            "meta": {
                "api_request_id": C.new_request_id(),
                "api_request_timestamp": C.envelope_ts(),
            },
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        }
        return jsonify(payload), err.http_status

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "no such route"))

    @app.errorhandler(405)
    def _no_method(_err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "method not allowed for this route", 405)
        )

    @app.errorhandler(Exception)
    def _unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        import traceback
        traceback.print_exc()
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "the request could not be processed", 400)
        )