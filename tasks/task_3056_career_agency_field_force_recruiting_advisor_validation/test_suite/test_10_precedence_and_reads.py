"""Validation precedence pairs and the derived fields observed on a read."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_advisor_invariants,
    fetch_advisor,
    get_success_data,
    md_headers,
    new_office,
    new_policy,
    any_headers,
    set_clock,
    setup_chargeback_balance_blocked,
    setup_hierarchy,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Precedence: authentication before existence
# ---------------------------------------------------------------------------
def test_a_missing_role_header_precedes_the_resource_lookup():
    """PRD §2.10: "Authentication is evaluated first: a missing, blank, or
    unrecognised `X-User-ID` or `X-User-Role` yields
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` ... both before any resource is
    even looked up."
    PRD §2.10: "Existence follows, first along the path from left to right and
    then through the body in declared input order."

    Design: Difficulty/priority_pair_validation_conflict/missing_header_beats_unknown_resource_on_scoring
    """
    set_clock()

    response = api_client.score_assessment(
        NON_EXISTENT_UUID,
        {"raw_score": 70, "competency_scores": {
            "MARKET_KNOWLEDGE": 7, "RELATIONSHIP": 7, "RESILIENCE": 7, "ETHICS": 7}},
        {})

    validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


def test_the_authentication_error_is_not_masked_by_the_resource_error():
    """PRD §2.10: "When more than one rule could reject a request, exactly one
    error is returned, chosen by this order. Authentication is evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/missing_header_beats_unknown_resource_on_scoring
    """
    set_clock()

    response = api_client.score_assessment(
        NON_EXISTENT_UUID,
        {"raw_score": 70, "competency_scores": {
            "MARKET_KNOWLEDGE": 7, "RELATIONSHIP": 7, "RESILIENCE": 7, "ETHICS": 7}},
        {})
    body = response.json()

    assert response.status_code == 400
    assert body["data"]["error_id"] != ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value
    assert body["response_type"] == "error"


# ---------------------------------------------------------------------------
# Precedence: compliance before the fiscal block
# ---------------------------------------------------------------------------
def test_licence_compliance_precedes_the_chargeback_fiscal_block():
    """PRD §2.10: "Because compliance is evaluated before the fiscal block, a
    request refused for both a licensing failure and an excessive chargeback
    balance reports the licensing failure."
    PRD §3.6: "while the writing advisor's `chargeback_balance_cents` exceeds
    `CHARGEBACK_BLOCK_CENTS`, which is 500000 cents, both writing a new policy
    and submitting a joint work case are refused with
    `ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS` at the payment-required status."

    Design: Difficulty/priority_pair_validation_conflict/licence_compliance_beats_chargeback_fiscal_on_policy_write
    """
    set_clock("2026-09-01T00:00:00Z")
    office = new_office()
    ctx = setup_chargeback_balance_blocked(office["id"], premium=1600000,
                                           lapse_date="2026-01-10T00:00:00Z")

    # Advance the clock past the licence expiry: the licence lapses, the
    # chargeback balance still stands over the block threshold.
    set_clock("2028-06-01T00:00:00Z")
    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["insurance_license_status"] == "LAPSED"
    assert advisor["chargeback_balance_cents"] > 500000

    refused = api_client.activate_policy(ctx["new_policy"]["id"], md_headers)
    validate_error(refused, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)


def test_the_fiscal_block_does_not_mask_the_compliance_error():
    """PRD §2.10: "Licensing, registration, and appointment compliance is
    evaluated first, producing `ERR_LICENSE_NOT_ACTIVE` ... Fiscal caps and
    balance blocks follow."

    Design: Difficulty/priority_pair_validation_conflict/licence_compliance_beats_chargeback_fiscal_on_policy_write
    """
    set_clock("2026-09-01T00:00:00Z")
    office = new_office()
    ctx = setup_chargeback_balance_blocked(office["id"], premium=1600000,
                                           lapse_date="2026-01-10T00:00:00Z")
    set_clock("2028-06-01T00:00:00Z")

    response = api_client.activate_policy(ctx["new_policy"]["id"], md_headers)
    body = response.json()

    assert response.status_code == 409
    assert body["data"]["error_id"] != ApiErrorId.ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS.value

    still_issued = get_success_data(api_client.get_policy(ctx["new_policy"]["id"], any_headers))
    assert still_issued["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def test_policies_can_be_filtered_to_the_orphaned_set():
    """PRD §3.8: "For every `Policy` whose `writing_advisor_id` is the
    terminated advisor and whose status is `ISSUED` or `ACTIVE`, the policy's
    `orphaned` flag is set to true" ... "A policy that was already `LAPSED`,
    `SURRENDERED`, or `TERMINATED` is not orphaned by this cascade."

    Design: Corner/endpoints/policies_can_be_filtered_to_the_orphaned_set
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000,
                          activate_policy=True)
    writer_id = ctx["advisor"]["id"]
    active_policy = ctx["policy"]

    surrendered_policy = new_policy(writer_id, annual_premium_cents=510000,
                                    policy_number="NM-E002")
    validate_success(api_client.activate_policy(surrendered_policy["id"], md_headers))
    validate_success(api_client.surrender_policy(surrendered_policy["id"], md_headers))

    validate_success(api_client.terminate_advisor(writer_id, md_headers))

    orphaned_rows = validate_success(api_client.list_policies(any_headers, {"orphaned": True}))
    orphaned_rows = orphaned_rows if isinstance(orphaned_rows, list) else orphaned_rows.get("data", [])
    assert len(orphaned_rows) == 1
    assert orphaned_rows[0]["id"] == active_policy["id"]

    assert get_success_data(api_client.get_policy(active_policy["id"], any_headers))["orphaned"] is True
    assert get_success_data(api_client.get_policy(surrendered_policy["id"], any_headers))["orphaned"] is False

    by_writer = validate_success(api_client.list_policies(any_headers, {"writing_advisor_id": writer_id}))
    by_writer = by_writer if isinstance(by_writer, list) else by_writer.get("data", [])
    assert len(by_writer) == 2


def test_derived_posture_fields_reconcile_on_the_read_after_a_cascade():
    """PRD §2.9: "The derived `validation_posture` ... is recomputed on every
    child mutation and it is what gates the advisor's economics."
    PRD §2.7: "The third is that `DistrictOffice.override_paid_cents` is always
    the sum of `override_income_cents` over every advisor whose
    `district_office_id` is that office, recomputed whenever any member
    advisor's override income changes."

    Design: Corner/cross_cutting_complexity_layers/derived_posture_fields_are_reconciled_on_read_after_a_cascade
    """
    set_clock()
    office = new_office()
    ctx = setup_hierarchy(office["id"], premium=510000, required_production_cents=100000)

    # No reconcile call was issued between the cascade and these reads.
    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["validation_posture"] == "VALIDATED"
    assert advisor["team_production_cents"] == 204000
    assert_advisor_invariants(advisor)

    refreshed_office = get_success_data(api_client.get_district_office(office["id"], any_headers))
    assert refreshed_office["override_paid_cents"] == 10200

    dd = fetch_advisor(ctx["dd"]["id"])
    md = fetch_advisor(ctx["md"]["id"])
    assert dd["override_income_cents"] == 6120
    assert md["override_income_cents"] == 4080
    assert refreshed_office["override_paid_cents"] == dd["override_income_cents"] + md["override_income_cents"]