"""Corner coverage — RBAC denials and entity-backed technician identity
(PRD §2.1, §3.4, §4).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS,
    create_site, create_site_payload, create_assessment_payload,
    create_technician, create_approved_assessment, create_scheduled_plan,
    create_event, make_conversion_technician_headers,
    MANAGER, SAFETY, BILLING,
)


def test_technician_cannot_create_site(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`ConversionTechnician` executes conversion events assigned to
    their own technician identity."

    Design: Corner/rbac/technician_cannot_create_site
    """
    resp = api.create_site(create_site_payload(
        code="S-RB1", name="RBAC Site", address="1 RBAC Rd",
        baseline_labor_rate_per_hour=30.0),
        TEST_USERS["conversion_technician_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_billing_operator_cannot_approve_assessment(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`SafetyOfficer` approves or rejects site assessments and
    inspects training records."

    Design: Corner/rbac/billing_operator_cannot_approve_assessment
    """
    site = create_site(code="S-RB2")
    ass = get_success_data(api.create_assessment(
        site["id"], create_assessment_payload(
            forklift_count=2, duty_cycle_hours_per_day=4.0, peak_shift_hours=6),
        MANAGER))
    validate_success(api.submit_assessment(site["id"], ass["id"], MANAGER))
    resp = api.approve_assessment(site["id"], ass["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_technician_identity_ownership_on_event_start(api):
    """PRD §2.1: "When `X-User-Role` is `ConversionTechnician`, `X-User-ID` is
    the `id` of the acting `Technician`; ownership checks on any resource that
    references a `Technician` compare the resource's foreign-key field to
    `X-User-ID`."
    PRD §3.4: "Events are executed by the assigned `ConversionTechnician` and
    no one else — the acting `X-User-ID` must equal the event's
    `technician_id`."

    Design: Corner/rbac/technician_identity_ownership_on_event_start
    """
    site = create_site(code="S-RB3")
    t1 = create_technician(name="Tech One")
    t2 = create_technician(name="Tech Two")
    create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = create_scheduled_plan(
        site["id"], name="Wave RB", target_forklift_count=1,
        baseline_productivity_units_per_hour=40.0,
        expected_productivity_gain_pct=5)
    ev = create_event(plan["id"], t1["id"], forklift_id="FL-RB",
                      scheduled_start="2026-10-02T08:00:00Z",
                      scheduled_end="2026-10-02T10:00:00Z")
    # t2 attempts to start the event assigned to t1.
    resp = api.start_event(
        plan["id"], ev["id"], make_conversion_technician_headers(t2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = get_success_data(api.get_conversion_event(ev["id"], MANAGER))
    assert after["status"] == "SCHEDULED", "the rejected start changes nothing"
