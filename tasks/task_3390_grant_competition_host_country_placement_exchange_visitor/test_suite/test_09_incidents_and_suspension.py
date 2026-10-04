"""Emergency incidents and the grant ACTIVE ↔ SUSPENDED cycle (PRD §3.8)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_incident,
    create_incident_payload,
    declare_incident,
    get_grant,
    resolve_incident,
    set_clock_to,
    setup_active_grant,
    setup_confirmed_grant,
    setup_suspended_grant,
    validate_error,
    validate_success,
)


def _instant(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_incident_declare_on_confirmed_grant_rejected(api, program_officer_headers):
    """PRD §3.8: "Declaration requires the grant to be ACTIVE
    (`ERR_GRANT_NOT_ACTIVE`) and at most one OPEN incident per grant
    (`ERR_ACTIVE_INCIDENT_EXISTS`)."

    Design: Corner/state_machines/incident_declare_on_confirmed_grant_rejected
    """
    bundle = setup_confirmed_grant()  # CONFIRMED, never activated

    resp = api.create_incident(
        bundle["grant"]["id"],
        create_incident_payload(
            category="SECURITY", description="Civil unrest near host site",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

    incidents = validate_success(
        api.list_incidents(bundle["grant"]["id"], program_officer_headers)
    )
    assert incidents == [], "a rejected declaration must not persist an incident"
    assert get_grant(bundle["grant"])["status"] == "CONFIRMED"


def test_second_open_incident_rejected(api, program_officer_headers):
    """PRD §3.8: "Declaration requires the grant to be ACTIVE
    (`ERR_GRANT_NOT_ACTIVE`) and at most one OPEN incident per grant
    (`ERR_ACTIVE_INCIDENT_EXISTS`)."
    PRD §2.7: "The ordering is observable behavior: an expired offer acted on
    through a nonexistent round 404s before any temporal check runs; a
    well-formed request from the wrong role 403s before state is examined; a
    stale `expected_application_version` is detected (412) before ownership is
    examined; and the quota gate fires only after every other check has
    passed."

    With an incident already OPEN the grant sits in SUSPENDED, so both rules
    are violated; the cardinality constraint (a business constraint) is listed
    ahead of the grant-phase referential check, so its error fires.

    Design: Corner/state_machines/second_open_incident_rejected
    """
    bundle = setup_suspended_grant()  # incident 1 OPEN, grant SUSPENDED
    assert bundle["grant"]["status"] == "SUSPENDED"

    resp = api.create_incident(
        bundle["grant"]["id"],
        create_incident_payload(category="MEDICAL", description="Grantee hospitalized"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_INCIDENT_EXISTS)

    incidents = validate_success(
        api.list_incidents(bundle["grant"]["id"], program_officer_headers)
    )
    assert len(incidents) == 1
    assert get_grant(bundle["grant"])["status"] == "SUSPENDED"


def test_incident_declaration_suspends_active_grant(api, program_officer_headers):
    """PRD §3.8: "The incident's `status` begins at OPEN, its `opened_at` is
    stamped from the logical clock, and the declaration suspends the grant
    ACTIVE → SUSPENDED in the same step."

    Design: Difficulty/non_linear_state_machine/grant_suspension_cycle_extends_end_date
    """
    bundle = setup_active_grant(application_overrides={"dependents_count": 1})
    assert bundle["grant"]["status"] == "ACTIVE"

    set_clock_to("2027-11-01T00:00:00Z")
    incident = declare_incident(
        bundle["grant"], category="MEDICAL",
        description="Hospitalization of grantee",
    )
    assert_incident(incident)
    assert incident["status"] == "OPEN"
    assert incident.get("suspension_days") is None, (
        "suspension_days is computed at RESUME resolution, not at declaration"
    )

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "SUSPENDED", (
        "declaration must move the grant ACTIVE → SUSPENDED in the same step"
    )


def test_resume_resolution_extends_end_date_and_preserves_money(
    api, program_officer_headers,
):
    """PRD §3.8: "When the outcome is RESUME, the incident's
    `suspension_days` are computed as the whole calendar days between the
    declaration date and the resolution date; the grant's `end_date` is
    extended by exactly that many days, with all award amounts unchanged;
    those days are added into `suspension_days_total`; the
    `final_report_due_date` is recomputed from the shifted `end_date` as
    thirty days beyond it; the `interim_report_due_date` is left untouched;
    and the grant returns SUSPENDED → ACTIVE."

    Incident OPEN at 2027-11-01, resolved 2027-11-16: 15 suspension days;
    end 2028-07-01 → 2028-07-16; final report due 2028-08-15; interim due
    unchanged at 2028-01-01; award still 3850000.

    Design: Difficulty/non_linear_state_machine/grant_suspension_cycle_extends_end_date
    """
    bundle = setup_suspended_grant(
        application_overrides={"dependents_count": 1},
        incident_overrides={"category": "MEDICAL",
                            "description": "Hospitalization of grantee"},
        at_clock="2027-11-01T00:00:00Z",
    )
    incident = bundle["incident"]

    set_clock_to("2027-11-16T00:00:00Z")
    resolved = resolve_incident(incident, "RESUME")
    assert_incident(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "RESUME"
    assert resolved["suspension_days"] == 15, (
        f"2027-11-01 to 2027-11-16 is 15 whole days, got {resolved['suspension_days']}"
    )

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "ACTIVE", "RESUME must close the suspension cycle"
    assert _instant(grant["end_date"]) == _instant("2028-07-16T00:00:00Z"), (
        f"end_date shifts by the 15 suspension days, got {grant['end_date']}"
    )
    assert _instant(grant["final_report_due_date"]) == _instant("2028-08-15T00:00:00Z")
    assert grant["suspension_days_total"] == 15
    assert _instant(grant["interim_report_due_date"]) == _instant("2028-01-01T00:00:00Z"), (
        "the interim due date is untouched by a suspension"
    )
    assert grant["final_total_cents"] == 3850000, (
        "suspension extends time, never money"
    )
