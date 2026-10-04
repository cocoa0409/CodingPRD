"""Pre-built role headers for every operational role in the PRD.

``RemoteSupportOperator`` is the only entity-backed role: its ``X-User-ID`` is
the ``id`` of the acting ``DriverProspect``, so ownership-gated calls must use
``make_remote_support_operator_headers(prospect_id)`` rather than the shared
constant. Every other role's ``X-User-ID`` is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls that do not exercise
# DriverProspect ownership.
TEST_USERS = {
    "any_headers": build_user_headers("test-any-1", "Any"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "corridor_manager_headers": build_user_headers(
        "test-corridor-manager-1", "CorridorOperationsManager"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"),
    "carrier_dispatcher_headers": build_user_headers(
        "test-carrier-dispatcher-1", "CarrierDispatcher"),
    "terminal_manager_headers": build_user_headers(
        "test-terminal-manager-1", "TerminalManager"),
    "remote_support_supervisor_headers": build_user_headers(
        "test-remote-supervisor-1", "RemoteSupportSupervisor"),
    # entity_backed role — the shared constant is a fallback only for calls that
    # do not gate on the acting DriverProspect's id.
    "remote_support_operator_headers": build_user_headers(
        "test-remote-operator-1", "RemoteSupportOperator"),
    "incident_reviewer_headers": build_user_headers(
        "test-incident-reviewer-1", "IncidentReviewer"),
    "safety_case_author_headers": build_user_headers(
        "test-safety-case-author-1", "SafetyCaseAuthor"),
    "regulatory_liaison_headers": build_user_headers(
        "test-regulatory-liaison-1", "RegulatoryLiaison"),
    "fleet_maintenance_tech_headers": build_user_headers(
        "test-fleet-tech-1", "FleetMaintenanceTech"),
    "driver_outreach_headers": build_user_headers(
        "test-driver-outreach-1", "DriverOutreachCoordinator"),
    "shipper_partnership_headers": build_user_headers(
        "test-shipper-partnership-1", "ShipperPartnershipManager"),
    "booking_clerk_headers": build_user_headers("test-booking-clerk-1", "BookingClerk"),
    "terminal_operator_headers": build_user_headers(
        "test-terminal-operator-1", "TerminalOperator"),
    "exchange_participant_headers": build_user_headers(
        "test-exchange-participant-1", "ExchangeParticipant"),
}


def make_remote_support_operator_headers(user_id: str) -> dict:
    """Headers for RemoteSupportOperator (entity_backed:DriverProspect).

    Pass the acting DriverProspect's ``id`` whenever the call is ownership-gated
    (acknowledge, interventions, safe-stop).
    """
    return build_user_headers(user_id, "RemoteSupportOperator")