"""Center applications, audit scoring variants, and the authorization cycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_test_center,
    complete_audit,
    complete_audit_payload,
    create_authorized_center,
    create_center,
    get_center,
    schedule_audit,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS


def test_center_creation_applied_defaults(api, program_admin_headers):
    """PRD §3.1: "A new center begins life with `authorization_status` set to
    `APPLIED`, `last_audit_outcome` set to `NONE`, and `active_staff_count`
    at zero."

    Design: Corner/entities/center_creation_applied_defaults
    """
    resp = api.create_test_center(
        {
            "name": "Center Zero",
            "facility_seat_capacity": 15,
            "equipment_list": ["computers"],
        },
        program_admin_headers,
    )
    center = validate_success(resp, 201)
    assert_test_center(center)
    assert center["authorization_status"] == "APPLIED"
    assert center["last_audit_outcome"] == "NONE"
    assert center["active_staff_count"] == 0


def test_audit_scoring_announced_variant_passes(api, auditor_headers):
    """PRD §3.1: "The two variants can flip a result on identical evidence:
    findings of one facility, one staffing, and two equipment items score 82
    and pass when announced, but score 73 and fail when unannounced."
    PRD §3.1: "A `PASSED` audit moves an `APPLIED` center to `AUTHORIZED`"

    Design: Difficulty/dual_variant_calc/audit_scoring_announced_vs_unannounced
    """
    center = create_center(name="Center AN", facility_seat_capacity=30)
    audit = schedule_audit(center["id"], audit_type="ANNOUNCED")
    resp = api.complete_audit(audit["id"], complete_audit_payload(1, 1, 2, 0),
                              auditor_headers)
    completed = validate_success(resp, 200)
    assert completed["compliance_score"] == 82, "ANNOUNCED: 100 - (5+7+6) == 82"
    assert completed["outcome"] == "PASSED"
    assert get_center(center["id"])["authorization_status"] == "AUTHORIZED"


def test_audit_scoring_unannounced_variant_fails_same_findings(api, auditor_headers):
    """PRD §3.1: "The two variants can flip a result on identical evidence:
    findings of one facility, one staffing, and two equipment items score 82
    and pass when announced, but score 73 and fail when unannounced."
    PRD §3.1: "A `FAILED` audit on an `APPLIED` center is a self-loop — the
    center stays `APPLIED`, `last_audit_outcome` becomes `FAILED`, and nothing
    else fires, because a center that was never authorized has no live sessions
    to protect."

    Design: Difficulty/dual_variant_calc/audit_scoring_announced_vs_unannounced
    """
    center = create_center(name="Center UN", facility_seat_capacity=30)
    audit = schedule_audit(center["id"], audit_type="UNANNOUNCED")
    resp = api.complete_audit(audit["id"], complete_audit_payload(1, 1, 2, 0),
                              auditor_headers)
    completed = validate_success(resp, 200)
    assert completed["compliance_score"] == 73, (
        "UNANNOUNCED: 100 - round_half_up(1.5*18) == 73"
    )
    assert completed["outcome"] == "FAILED"
    stayed = get_center(center["id"])
    assert stayed["authorization_status"] == "APPLIED", (
        "FAILED on a never-authorized center does not suspend it"
    )
    assert stayed["last_audit_outcome"] == "FAILED"


def test_compliance_high_severity_overrides_perfect_score(api, auditor_headers):
    """PRD §3.1: "The `outcome` is `FAILED` whenever the `compliance_score` is
    below 80, and also whenever `high_severity_findings` is at least 1 — the
    severity branch is independent of the score, so a spotless count sheet with
    a single high-severity finding still fails at a score of 100."

    Design: Corner/calculations/compliance_high_severity_overrides_perfect_score
    """
    center = create_center(name="Center HS", facility_seat_capacity=15)
    audit = schedule_audit(center["id"], audit_type="ANNOUNCED")
    resp = api.complete_audit(audit["id"], complete_audit_payload(0, 0, 0, 1),
                              auditor_headers)
    completed = validate_success(resp, 200)
    assert completed["compliance_score"] == 100
    assert completed["outcome"] == "FAILED", (
        "high_severity_findings >= 1 forces FAILED regardless of score"
    )
    assert get_center(center["id"])["authorization_status"] == "APPLIED"


def test_audit_double_complete_rejected(api, auditor_headers):
    """PRD §2.6: "Every other from-state violation (a double completion of an
    audit, cancelling a `COMPLETED` registration, responding on an
    already-responded case, and so on) yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/audit_double_complete_rejected
    """
    center = create_center(name="Center DC", facility_seat_capacity=15)
    audit = schedule_audit(center["id"], audit_type="ANNOUNCED")
    first = validate_success(
        api.complete_audit(audit["id"], complete_audit_payload(1, 1, 2, 0),
                           auditor_headers),
        200,
    )
    assert first["compliance_score"] == 82
    resp = api.complete_audit(audit["id"], complete_audit_payload(0, 0, 0, 0),
                              auditor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # The rejection recomputes nothing: the first completion's score stands.
    audits = validate_success(
        api.list_audits(center["id"], TEST_USERS["program_admin_headers"]), 200
    )
    assert audits[0]["compliance_score"] == 82


def test_authorization_cycle_suspend_on_failed_audit(api):
    """PRD §3.1: "A `FAILED` audit on an `AUTHORIZED` center is the severe
    path: the center transitions to `SUSPENDED`, `last_audit_outcome` becomes
    `FAILED`, and a three-hop cascade runs."

    Design: Difficulty/non_linear_state_machine/test_center_authorization_cycle
    """
    center = create_authorized_center(name="Center CY", facility_seat_capacity=25)
    assert center["authorization_status"] == "AUTHORIZED"
    audit2 = schedule_audit(center["id"], scheduled_date="2026-09-20")
    completed = complete_audit(audit2["id"], {
        "facility_findings": 2,
        "staffing_findings": 1,
        "equipment_findings": 3,
        "high_severity_findings": 0,
    })
    assert completed["compliance_score"] == 74, "100 - (10+7+9) == 74"
    assert completed["outcome"] == "FAILED"
    center = get_center(center["id"])
    assert center["authorization_status"] == "SUSPENDED"
    assert center["last_audit_outcome"] == "FAILED"


def test_authorization_cycle_reinstate_on_later_pass(api):
    """PRD §3.1: "A `PASSED` audit moves an `APPLIED` center to `AUTHORIZED`,
    and a `PASSED` audit likewise reinstates a `SUSPENDED` center back to
    `AUTHORIZED`, closing the suspension cycle; in both cases
    `last_audit_outcome` becomes `PASSED`."

    Design: Difficulty/non_linear_state_machine/test_center_authorization_cycle
    """
    center = create_authorized_center(name="Center CY2", facility_seat_capacity=25)
    audit2 = schedule_audit(center["id"], scheduled_date="2026-09-20")
    complete_audit(audit2["id"], {
        "facility_findings": 2,
        "staffing_findings": 1,
        "equipment_findings": 3,
        "high_severity_findings": 0,
    })
    assert get_center(center["id"])["authorization_status"] == "SUSPENDED"
    audit3 = schedule_audit(center["id"], scheduled_date="2026-10-01")
    completed3 = complete_audit(audit3["id"], {
        "facility_findings": 0,
        "staffing_findings": 0,
        "equipment_findings": 1,
        "high_severity_findings": 0,
    })
    assert completed3["compliance_score"] == 97, "100 - 3 == 97"
    assert completed3["outcome"] == "PASSED"
    center = get_center(center["id"])
    assert center["authorization_status"] == "AUTHORIZED", "cycle closed"
    assert center["last_audit_outcome"] == "PASSED"
    assert_test_center(center)
