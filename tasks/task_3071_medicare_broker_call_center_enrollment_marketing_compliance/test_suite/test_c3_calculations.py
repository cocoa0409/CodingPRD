"""Calculation behaviour: input-set filtering, table order, variant divergence and the
agency-scoped windows that feed derived values.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_complaint_payload, create_call_session_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, drop_call, get_call,
    submit_enrollment, acknowledge_enrollment, effectuate_enrollment,
    setup_master_data, CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def test_earned_commission_bills_a_rapid_disenrolled_row_exactly_one_month():
    """PRD §3.5: "An enrollment that ended as a `RAPID_DISENROLLED` always contributes
    exactly 1 billed month, because the plan never ran a full month."
    PRD §3.5: "it is 0 for any enrollment that is not `EFFECTUATED`."

    Design: Corner/calculations/earned_commission_bills_a_rapid_disenrolled_row_exactly_one_month
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    enrollment = submit_enrollment(agent["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])

    set_clock("2026-11-10T00:00:00Z")
    result = validate_success(api_client.disenroll_enrollment(
        enrollment["id"],
        {"disenrollment_date": "2026-11-10T00:00:00Z",
         "disenrollment_reason": "BENEFICIARY_REQUEST"}, CARRIER_INT), 200)

    assert result["disenrollment_status"] == "RAPID_DISENROLLED"
    assert result["disenrolled_day_number"] == 9
    # preimum 1500 x 1 billed month x the 0.20 initial rate
    assert result["final_commission_cents"] == pytest.approx(300.00, abs=0.01)

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    types = {r["entry_type"] for r in rows}
    assert "INITIAL" in types and "RENEWAL" in types and "CHARGEBACK" in types

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    # two positive entries (3600.00 + 1800.00) plus the FINALIZED -3600.00 chargeback
    assert agency["commission_balance_cents"] == pytest.approx(1800.00, abs=0.01)


def test_risk_score_ignores_a_live_call_and_counts_a_dropped_call():
    """PRD §3.10: "Calls still in `RINGING` or `IN_PROGRESS` contribute nothing, since the
    conduct is not yet finished."
    PRD §3.10: "The per-session component walks every one of the agent's call sessions
    whose status is `COMPLETED` or `DROPPED` and, for each, sums three conditional
    penalties: 3.0 points when the call has no `recording_id` or its derived
    `recording_status` reads `MISSING`; 7.0 points when `disclaimer_delivered` is false".

    Design: Corner/calculations/risk_score_ignores_a_live_call_and_counts_a_dropped_call
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    # A WRITTEN scope is the one route that waives the recording and disclaimer
    # obligations, so a recording-less call can legitimately go live.
    scope = capture_scope(member["id"], agent["id"], version,
                          capture_channel="WRITTEN", plan_types_authorized=["MAPD"])
    call = open_call(agent["id"], member["id"], scope["id"],
                     started_at="2026-10-01T09:00:00Z",
                     scheduled_end_at="2026-10-01T09:30:00Z",
                     recording_id=None, disclaimer_script_code=None,
                     disclaimer_delivered=False, marketing_rule_set_version=None)
    connect_call(agent["id"], call["id"], recording_id=None, disclaimer_delivered=False)

    live = get_success_data(api_client.get_agent(agent["id"], COMPLIANCE))
    assert live["compliance_risk_score"] == pytest.approx(0.00, abs=0.01), (
        "RINGING and IN_PROGRESS contribute nothing"
    )

    drop_call(agent["id"], call["id"])
    dropped = get_success_data(api_client.get_agent(agent["id"], COMPLIANCE))
    assert dropped["compliance_risk_score"] == pytest.approx(10.00, abs=0.01), (
        "3.0 for the null recording_id plus 7.0 for disclaimer_delivered false"
    )


def test_risk_score_drops_nothing_for_a_clean_completed_call():
    """PRD §3.10: "3.0 points when the call has no `recording_id` or its derived
    `recording_status` reads `MISSING`; 7.0 points when `disclaimer_delivered` is false;
    and 2.0 points when the call has no `scope_of_appointment_id` or the scope it attaches
    to has an empty `plan_types_authorized` list."

    Design: Corner/calculations/risk_score_ignores_a_live_call_and_counts_a_dropped_call
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    complete_call(agent["id"], call["id"])

    row = get_success_data(api_client.get_agent(agent["id"], COMPLIANCE))
    assert row["compliance_risk_score"] == pytest.approx(0.00, abs=0.01)


def test_complaint_finding_code_follows_table_order_for_a_shopper():
    """PRD §3.9: "A secret-shopper complaint whose `soa_requested_correctly` is false yields
    `SHOPPER_SOA_FAILURE`."
    PRD §3.9: "The table's row order is the priority order, so a secret-shopper complaint
    with a low score and a failed disclaimer is a `SHOPPER_DISCLAIMER_FAILURE`, not a
    `SHOPPER_LOW_SCORE`."

    Design: Corner/calculations/complaint_finding_code_follows_table_order_for_a_shopper
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])

    shopper_soa = get_success_data(api_client.create_complaint({
        "agent_id": agent["id"], "complaint_type": "SOA_MISSING",
        "source": "SECRET_SHOPPER", "severity": "HIGH",
        "filed_on": "2026-09-28T00:00:00Z", "shopper_score": 55,
        "soa_requested_correctly": False, "disclaimer_played": False,
        "approved_marketing_used": False,
    }, COMPLIANCE))
    api_client.begin_review(shopper_soa["id"], COMPLIANCE)
    first = validate_success(
        api_client.substantiate_complaint(shopper_soa["id"], COMPLIANCE), 200)
    assert first["finding_code"] == "SHOPPER_SOA_FAILURE"
    assert first["finding_code"] != "SHOPPER_LOW_SCORE"
    assert first["finding_code"] != "SHOPPER_DISCLAIMER_FAILURE"


def test_shopper_low_score_is_the_only_failing_condition():
    """PRD §3.9: "Failing that, a secret-shopper complaint whose `shopper_score` is below
    70 yields `SHOPPER_LOW_SCORE`."

    Design: Corner/calculations/complaint_finding_code_follows_table_order_for_a_shopper
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])

    shopper_score = get_success_data(api_client.create_complaint({
        "agent_id": agent["id"], "complaint_type": "PLAN_MISREPRESENTATION",
        "source": "SECRET_SHOPPER", "severity": "MEDIUM",
        "filed_on": "2026-09-29T00:00:00Z", "shopper_score": 65,
        "soa_requested_correctly": True, "disclaimer_played": True,
        "approved_marketing_used": True,
    }, COMPLIANCE))
    api_client.begin_review(shopper_score["id"], COMPLIANCE)
    second = validate_success(
        api_client.substantiate_complaint(shopper_score["id"], COMPLIANCE), 200)

    assert second["finding_code"] == "SHOPPER_LOW_SCORE"
    assert second["finding_code"] != "MARKETING_VIOLATION"

    rows, _meta = validate_paginated(api_client.list_agent_coaching_assignments(
        agent["id"], DIRECTOR))
    assert len(rows) == 1
    assert get_success_data(api_client.get_agent(
        agent["id"], DIRECTOR))["open_coaching_count"] == 1


def test_ledger_entry_reversal_negates_the_current_non_reversed_total():
    """PRD §3.8: "A `REVERSAL` entry takes the negated sum of `amount_cents` over every
    entry of that same enrollment whose status is not `REVERSED`."
    PRD §3.6: "Withdrawal from `SUBMITTED` and withdrawal from `ACKNOWLEDGED` each
    additionally post a `REVERSAL` ledger entry against every non-reversed entry of that
    enrollment".

    Design: Corner/calculations/ledger_entry_reversal_negates_the_current_non_reversed_total
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    enrollment = submit_enrollment(agent["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])

    validate_success(api_client.withdraw_enrollment(
        enrollment["id"], {"reason": "BENEFICIARY_CHANGED_MIND"},
        make_licensed_agent_headers(agent["id"])), 200)

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    assert len(rows) == 3
    reversal = [r for r in rows if r["entry_type"] == "REVERSAL"][0]
    # The base is the INITIAL 3600.00 plus the RENEWAL 1800.00, not one entry alone.
    assert reversal["amount_cents"] == pytest.approx(-5400.00, abs=0.01)

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["commission_balance_cents"] == pytest.approx(0.00, abs=0.01)

    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["chargeback_tier"] == 1


def test_reconciliation_provisional_and_final_variants_diverge_on_one_period():
    """PRD §2.8: "Under `PROVISIONAL`, both `PROVISIONAL` and `FINALIZED` entries are
    summed; under `FINAL`, only `FINALIZED` entries are summed. `REVERSED` entries are
    excluded under both variants."

    Design: Corner/calculations/reconciliation_provisional_and_final_variants_diverge_on_one_period
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    enrollment = submit_enrollment(agent["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    # Effectuation is reachable straight from SUBMITTED, so no RENEWAL entry is
    # posted and the period's only FINALIZED row is the chargeback below.
    effectuate_enrollment(enrollment["id"])

    set_clock("2026-11-10T00:00:00Z")
    # A rapid disenrollment posts a FINALIZED chargeback while the INITIAL stays PROVISIONAL.
    api_client.disenroll_enrollment(
        enrollment["id"],
        {"disenrollment_date": "2026-11-10T00:00:00Z",
         "disenrollment_reason": "BENEFICIARY_REQUEST"}, CARRIER_INT)

    prov = get_success_data(api_client.create_reconciliation({
        "carrier_id": scn["carrier"]["id"], "period_month": "2026-10",
        "carrier_reported_total_cents": 0, "internal_total_variant": "PROVISIONAL",
    }, DIRECTOR))
    final = get_success_data(api_client.create_reconciliation({
        "carrier_id": scn["carrier"]["id"], "period_month": "2026-10",
        "carrier_reported_total_cents": 0, "internal_total_variant": "FINAL",
    }, DIRECTOR))

    prov_row = get_success_data(api_client.get_reconciliation(prov["id"], DIRECTOR))
    final_row = get_success_data(api_client.get_reconciliation(final["id"], DIRECTOR))

    assert prov_row["variance_variant"] == "PROVISIONAL"
    assert final_row["variance_variant"] == "FINAL"
    # The INITIAL 3600.00 stays PROVISIONAL, so the two variants differ by exactly that.
    assert (prov_row["internal_total_cents"] - final_row["internal_total_cents"]) == \
        pytest.approx(3600.00, abs=0.01)
    assert final_row["internal_total_cents"] == pytest.approx(-3600.00, abs=0.01)


def test_soa_validity_window_uses_the_agency_max_age():
    """PRD §3.1: "Because the retention and staleness windows are read through the agency
    rather than copied onto children, changing `recording_retention_days`,
    `soa_retention_days` or `soa_max_age_days` re-derives every child's
    `recording_retained_until`, `expires_on` and `retained_until` on that child's next read."
    PRD §2.5: "Its `expires_on` is the `captured_on` instant plus the owning agency's
    `soa_max_age_days`".

    Design: Corner/calculations/soa_validity_window_uses_the_agency_max_age
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])

    set_clock("2026-11-01T00:00:00Z")
    headers = make_licensed_agent_headers(agent["id"])
    # Without the edit the scope has lapsed and the submission is refused.
    resp = api_client.create_enrollment({
        "call_session_id": call["id"], "member_id": member["id"],
        "plan_id": scn["plan"]["id"], "agent_id": agent["id"],
        "scope_of_appointment_id": scope["id"],
        "effective_date": "2026-11-01T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": call["version"],
    }, headers)
    validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    updated = validate_success(api_client.update_agency(scn["agency"]["id"], {
        "soa_max_age_days": 60, "expected_agency_version": agency["version"],
    }, ADMIN), 200)
    assert updated["soa_max_age_days"] == 60
    assert updated["version"] == agency["version"] + 1

    refreshed = get_success_data(api_client.get_scope(scope["id"], headers))
    assert refreshed["expires_on"] == utc("2026-11-30T00:00:00Z")
    assert refreshed["retained_until"] == utc("2036-09-28T00:00:00Z")

    enrolled = validate_success(api_client.create_enrollment({
        "call_session_id": call["id"], "member_id": member["id"],
        "plan_id": scn["plan"]["id"], "agent_id": agent["id"],
        "scope_of_appointment_id": scope["id"],
        "effective_date": "2026-11-01T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": call["version"],
    }, headers), 201)
    assert enrolled["submission_status"] == "SUBMITTED"