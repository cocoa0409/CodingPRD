"""Resource temporal overlap: payroll periods and rating-table intervals."""

from test_helpers import (
    RATING_TABLES, TEST_USERS, api_client, class_code_entry,
    create_and_bind_policy, create_employer, payroll_line, set_clock,
    setup_rating_table, submit_report, validate_error, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]


def _overlap_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Overlap Outfitters",
                               fein="44-1111222",
                               contact_email="pr@overlap.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-OVL-012",
        class_codes=[class_code_entry("CA", "8810", 1000000)])
    submit_report(policy["id"], "ovl-run-1",
                  period_start="2026-09-01T00:00:00Z",
                  period_end="2026-09-15T00:00:00Z",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])
    return policy


def test_straddling_report_is_rejected_as_period_overlap(api):
    """PRD §3.3: "must not overlap, under half-open interval semantics, any
    existing SUBMITTED or ACCEPTED report for the policy; either violation is
    ERR_PAYROLL_PERIOD_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/payroll_report_half_open_overlap_detection
    """
    policy = _overlap_policy()
    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-08T00:00:00Z",
        "period_end": "2026-09-22T00:00:00Z",
        "idempotency_key": "ovl-run-2",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=10000000)],
    }, PROVIDER)
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["failure_code"] == "ERR_PAYROLL_PERIOD_OVERLAP", (
        "the report intersects the existing [09-01, 09-15) window by seven days")


def test_touching_report_at_prior_period_end_is_accepted(api):
    """PRD §3.3: "covering the half-open pay period from period_start (inclusive)
    to period_end (exclusive)".

    Design: Difficulty/resource_temporal_overlap/payroll_report_half_open_overlap_detection
    """
    policy = _overlap_policy()
    report = submit_report(policy["id"], "ovl-run-3",
                           period_start="2026-09-15T00:00:00Z",
                           period_end="2026-09-22T00:00:00Z",
                           lines=[payroll_line("CA", "8810",
                                               gross_wages_cents=10000000)])
    assert report["status"] == "ACCEPTED", (
        "the intersection at the boundary instant is empty under half-open "
        "semantics, so the touching report is allowed")


def _ca_table_payload(effective_from, effective_to, **overrides):
    payload = dict(RATING_TABLES["CA"])
    payload["effective_from"] = effective_from
    payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


def test_same_state_interior_overlap_rejected_cross_state_free(api):
    """PRD §3.1: "the effective intervals of tables for one state must never
    overlap — adjacent intervals that merely touch are permitted because the
    intervals are half-open — and each class_code may appear at most once within
    a single table's class_rates."

    Design: Difficulty/resource_temporal_overlap/rating_table_same_state_overlap_but_cross_state_free
    """
    setup_rating_table("CA")  # [2026-01-01, 2027-01-01)

    # A different state's table may freely overlap CA's window.
    nv = dict(RATING_TABLES["NV"])
    nv["effective_from"] = "2026-06-01T00:00:00Z"
    nv["effective_to"] = "2026-12-01T00:00:00Z"
    validate_success(api.create_state_rating_table(nv, ADMIN), 201)

    # The same state's table may not.
    res = api.create_state_rating_table(
        _ca_table_payload("2026-06-01T00:00:00Z", "2026-12-01T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_RATING_TABLE_OVERLAP", expected_status=409)


def test_adjacent_rating_table_touching_at_boundary_is_allowed(api):
    """PRD §3.1: "adjacent intervals that merely touch are permitted because the
    intervals are half-open".

    Design: Difficulty/resource_temporal_overlap/rating_table_same_state_overlap_but_cross_state_free
    """
    setup_rating_table("CA")  # [2026-01-01, 2027-01-01)
    res = api.create_state_rating_table(
        _ca_table_payload("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
                          per_capita_admin_fee_cents=260), ADMIN)
    created = validate_success(res, 201)
    # PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
    assert created["effective_from"] == "2027-01-01T00:00:00.000Z"
