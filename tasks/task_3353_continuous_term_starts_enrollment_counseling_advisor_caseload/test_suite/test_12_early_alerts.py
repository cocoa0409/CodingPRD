"""Early alert thresholds, severity computation, and the escalation loop."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, setup_registered_enrollment, set_clock,
    make_advisor_headers, assert_early_alert,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def _setup_active_enrollment():
    """REGISTERED enrollment, then the term advances into session."""
    ctx = setup_registered_enrollment(intensity="FULL_TIME",
                                      tuition_cents=100000)
    set_clock("2026-10-05T00:00:00Z")
    validate_success(api_client.advance_term(
        ctx["term"]["id"], "IN_SESSION", REGISTRAR), expected_status=200)
    ctx["enrollment"] = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert ctx["enrollment"]["status"] == "ACTIVE"
    return ctx


def test_alert_threshold_grade_boundary():
    """PRD §3.9: "A grade-based alert requires an `observed_grade_percent`
    strictly below 70.00; a lateness-based alert requires `days_late` of at
    least 3; a payload whose evidence does not meet its trigger's threshold
    is rejected with `ERR_ALERT_THRESHOLD_NOT_MET`. The alert's `severity` is
    computed rather than supplied: it is `HIGH` when the observed grade is
    below 60.00 or `days_late` is 7 or more, and `LOW` otherwise."

    Design: Corner/validations/alert_threshold_grade_boundary
    """
    ctx = _setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    # 70.00 is not strictly below 70.00 -> rejected.
    resp = api_client.create_early_alert(
        enr_id, {"trigger_type": "GRADE_THRESHOLD",
                 "observed_grade_percent": 70.0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALERT_THRESHOLD_NOT_MET)
    # 69.99 qualifies and is not below 60.00 -> LOW severity.
    resp = api_client.create_early_alert(
        enr_id, {"trigger_type": "GRADE_THRESHOLD",
                 "observed_grade_percent": 69.99}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_early_alert(data)
    assert data["status"] == "OPEN"
    assert data["severity"] == "LOW", (
        f"grade 69.99 is >= 60.00 so severity must be LOW; got "
        f"{data['severity']}")
    # days_late 2 is below the minimum of 3 -> rejected.
    resp = api_client.create_early_alert(
        enr_id, {"trigger_type": "LATE_SUBMISSION", "days_late": 2}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALERT_THRESHOLD_NOT_MET)


def test_early_alert_escalation_loop_cycle():
    """PRD §3.9: "Only the advisor who owns the enrollment may work the
    alert: every advance requires the caller's `X-User-ID` to equal the
    enrollment's `advisor_id`, with any other caller rejected as
    `ERR_FORBIDDEN`. The alert's lifecycle is `OPEN` → `ACKNOWLEDGED` →
    `INTERVENTION` → `RESOLVED`, with `RESOLVED` terminal; from
    `INTERVENTION` the advisor may instead escalate to `ESCALATED`, and an
    `ESCALATED` alert loops back to `INTERVENTION` when the escalation is
    worked down."
    PRD §3.9: "The alert's `severity` is computed rather than supplied: it is
    `HIGH` when the observed grade is below 60.00 or `days_late` is 7 or
    more, and `LOW` otherwise."

    Design: Corner/state_machines/early_alert_escalation_loop_cycle
    """
    ctx = _setup_active_enrollment()
    advisor_headers = make_advisor_headers(ctx["advisor"]["id"])
    resp = api_client.create_early_alert(
        ctx["enrollment"]["id"],
        {"trigger_type": "GRADE_THRESHOLD", "observed_grade_percent": 55.0},
        ADMIN)
    alert = validate_success(resp, expected_status=201)
    assert alert["severity"] == "HIGH", (
        f"grade 55.0 is below 60.00 so severity must be HIGH; got "
        f"{alert['severity']}")

    def advance(to_state):
        return api_client.advance_early_alert(
            alert["id"], to_state, advisor_headers)

    for to_state in ("ACKNOWLEDGED", "INTERVENTION", "ESCALATED"):
        data = validate_success(advance(to_state), expected_status=200)
        assert data["status"] == to_state
    # The escalation loop: ESCALATED -> INTERVENTION is a declared edge.
    data = validate_success(advance("INTERVENTION"), expected_status=200)
    assert data["status"] == "INTERVENTION", (
        f"ESCALATED must loop back to INTERVENTION; got {data['status']}")
    data = validate_success(advance("RESOLVED"), expected_status=200)
    assert data["status"] == "RESOLVED"
    # RESOLVED is terminal.
    resp = advance("ACKNOWLEDGED")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
