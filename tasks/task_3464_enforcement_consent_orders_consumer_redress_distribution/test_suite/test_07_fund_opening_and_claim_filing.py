"""Fund opening cascade, claimant identification, and claim-filing guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_investigation_to_state,
    api_client,
    build_user_headers,
    create_claim_payload,
    create_investigation,
    create_payment_payload,
    draft_consent_order,
    enter_judgment,
    finalize_consent_order,
    get_fund,
    get_fund_for_judgment,
    get_judgment,
    get_success_data,
    identify_claimant,
    make_claimant_headers,
    make_company_representative_headers,
    parse_iso,
    propose_consent_order,
    record_payment,
    redress_fund_transition_payload,
    setup_judgment_with_fund,
    setup_open_fund,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1


def test_payment_completion_satisfies_judgment_opens_fund_notifies_claimants():
    """PRD section 3.5: "The moment a payment or reversal leaves the fund's
    `total_collected_cents` at or above the 1,000,000-cent opening minimum
    while the fund is `ACCUMULATING`, the fund automatically transitions to
    `OPEN_FOR_CLAIMS`, every claimant of the fund still in `IDENTIFIED` is
    flipped to `NOTIFIED` with `notified_at` stamped at the logical time, and
    the fund's `version` increments."
    PRD section 3.5: "reaching exactly the full amount moves to `SATISFIED`".

    Design: Difficulty/transitive_cascade/payment_completion_satisfies_judgment_opens_fund_notifies_claimants
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]
    fund_id = bundle["fund"]["id"]
    company_id = bundle["company"]["id"]
    claimant = identify_claimant(fund_id, full_name="Ann Apple", email="ann@example.com")
    assert claimant["status"] == "IDENTIFIED"

    # Clock is at 2026-10-01T00:00:00Z after the standard pipeline.
    payment = validate_success(
        api_client.create_payment(
            judgment_id,
            create_payment_payload(amount_cents=3_000_000, kind="COLLECTION"),
            make_company_representative_headers(company_id),
        ),
        201,
    )
    assert payment["collection_status"] == "SATISFIED"
    assert payment["collected_cents"] == 3_000_000
    assert payment["outstanding_cents"] == 0

    fund = get_fund(fund_id)
    assert fund["total_collected_cents"] == 3_000_000, "fund ledger syncs from the judgment"
    assert fund["status"] == "OPEN_FOR_CLAIMS", "3,000,000 >= the 1,000,000-cent opening minimum"

    claimants = get_success_data(api_client.list_claimants(fund_id, _ADMIN))
    assert len(claimants) == 1
    assert claimants[0]["status"] == "NOTIFIED", "fund-opening cascade must notify IDENTIFIED claimants"
    assert parse_iso(claimants[0]["notified_at"]) == parse_iso("2026-10-01T00:00:00Z")


def test_fund_open_threshold_boundary_999999_then_one_cent():
    """PRD section 3.5: "The moment a payment or reversal leaves the fund's
    `total_collected_cents` at or above the 1,000,000-cent opening minimum
    while the fund is `ACCUMULATING`, the fund automatically transitions to
    `OPEN_FOR_CLAIMS`".

    Design: Corner/cross_cutting_layers/fund_open_threshold_boundary_999999_then_one_cent
    """
    bundle = setup_judgment_with_fund(judgment_amount_cents=3_000_000)
    judgment_id = bundle["judgment"]["id"]
    fund_id = bundle["fund"]["id"]
    company_id = bundle["company"]["id"]

    record_payment(judgment_id, company_id, 999_999, kind="COLLECTION")
    assert get_fund(fund_id)["status"] == "ACCUMULATING", (
        "999,999 cents is below the 1,000,000-cent opening minimum"
    )

    record_payment(judgment_id, company_id, 1, kind="COLLECTION")
    assert get_fund(fund_id)["status"] == "OPEN_FOR_CLAIMS", (
        "at exactly 1,000,000 cents the fund must auto-open (>= semantics)"
    )
    judgment = get_judgment(judgment_id)
    assert judgment["collected_cents"] == 1_000_000
    assert judgment["collection_status"] == "PARTIALLY_COLLECTED"


def test_fund_manual_open_transition_rejected_system_only():
    """PRD section 3.5: "This opening transition is system-only: a manual
    transition request targeting `OPEN_FOR_CLAIMS` is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/fund_manual_open_transition_rejected_system_only
    """
    bundle = setup_judgment_with_fund(
        judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    fund_id = bundle["fund"]["id"]
    record_payment(bundle["judgment"]["id"], bundle["company"]["id"], 500_000, kind="COLLECTION")
    fund = get_fund(fund_id)
    assert fund["status"] == "ACCUMULATING"

    resp = api_client.transition_redress_fund(
        fund_id,
        redress_fund_transition_payload("OPEN_FOR_CLAIMS", fund["version"]),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = get_fund(fund_id)
    assert after["status"] == "ACCUMULATING"
    assert after["total_collected_cents"] == 500_000


def test_claimant_created_in_open_fund_is_notified_immediately():
    """PRD section 3.6: "if the fund is already `OPEN_FOR_CLAIMS` at
    identification time, the claimant is notified on the spot, moving straight
    to `NOTIFIED` with `notified_at` stamped."

    Design: Corner/state_machines/claimant_created_in_open_fund_is_notified_immediately
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=None,
    )
    assert bundle["fund"]["status"] == "OPEN_FOR_CLAIMS"

    claimant = identify_claimant(
        bundle["fund"]["id"],
        full_name="Dana Doe",
        email="dana@example.com",
        identified_from="CLAIMS_PROCESS",
    )
    assert claimant["status"] == "NOTIFIED", "creation response must already carry NOTIFIED"
    assert parse_iso(claimant["notified_at"]) == parse_iso("2026-10-01T00:00:00Z")
    assert claimant["identified_from"] == "CLAIMS_PROCESS"


def test_claimant_identified_from_invalid_enum_returns_invalid_request():
    """PRD section 3.6: "an `identified_from` of `COMPANY_RECORDS` or
    `CLAIMS_PROCESS`".
    PRD section 2.8: "required fields present, enum values within their
    declared sets, integer and datetime types valid, else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/claimant_identified_from_invalid_enum_returns_invalid_request
    """
    bundle = setup_judgment_with_fund(
        judgment_amount_cents=1_500_000, monetary_relief_cents=1_500_000
    )
    fund_id = bundle["fund"]["id"]

    resp = api_client.create_claimant(
        fund_id,
        {"full_name": "Eve Eagle", "email": "eve@example.com", "identified_from": "WILD_GUESS"},
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows = get_success_data(api_client.list_claimants(fund_id, _ADMIN))
    assert rows == [], "no claimant row may be left behind"


def test_claim_with_mismatched_fund_reference_rejected():
    """PRD section 3.6: "the `redress_fund_id` named must equal the claimant's
    own fund, else `ERR_CLAIM_FUND_MISMATCH`".

    Setup note: the second order's judgment is entered while the order is
    FINAL — PRD section 3.5: "enters a `MonetaryJudgment` for an order that is
    `FINAL` or already `IN_MONITORING`" — because a second IN_MONITORING order
    for the same company would trip the monitoring-window overlap rule.

    Design: Corner/validations/claim_with_mismatched_fund_reference_rejected
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=[{"full_name": "Ann Apple", "email": "ann@example.com",
                         "identified_from": "COMPANY_RECORDS"}],
    )
    company_id = bundle["company"]["id"]
    claimant_a = bundle["claimants"][0]

    inv2 = create_investigation(
        company_id, origin="COMPLAINT", summary="Second matter: refund obstruction"
    )
    advance_investigation_to_state(inv2["id"], "NEGOTIATING")
    order2 = draft_consent_order(
        inv2["id"],
        monetary_relief_cents=1_500_000,
        reporting_frequency_months=12,
        monitoring_term_years=3,
        conduct_prohibitions=["NO_REFUND_BLOCKS"],
    )
    propose_consent_order(order2["id"])
    finalize_consent_order(order2["id"])  # FINAL (no monitoring entry needed)
    judgment2 = enter_judgment(order2["id"], 1_500_000)
    fund2 = get_fund_for_judgment(judgment2["id"])
    record_payment(judgment2["id"], company_id, 1_500_000, kind="COLLECTION")
    assert get_fund(fund2["id"])["status"] == "OPEN_FOR_CLAIMS"

    resp = api_client.create_claim(
        create_claim_payload(claimant_a["id"], fund2["id"], documented_loss_cents=100_000),
        make_claimant_headers(claimant_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_FUND_MISMATCH)

    rows = get_success_data(
        api_client.list_claims(_ADMIN, params={"claimant_id": claimant_a["id"]})
    )
    assert rows == [], "the rejected filing must not persist a claim"


def test_claim_filed_by_wrong_user_rejected():
    """PRD section 3.6: "the caller's identity must equal the `claimant_id`
    being filed for — anyone else draws `ERR_CLAIMANT_IDENTITY_MISMATCH`".

    Design: Corner/validations/claim_filed_by_wrong_user_rejected
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=[{"full_name": "Ann Apple", "email": "ann@example.com",
                         "identified_from": "COMPANY_RECORDS"}],
    )
    fund_id = bundle["fund"]["id"]
    claimant_a = bundle["claimants"][0]

    resp = api_client.create_claim(
        create_claim_payload(claimant_a["id"], fund_id, documented_loss_cents=100_000),
        build_user_headers("not-claimant-a", "Claimant"),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIMANT_IDENTITY_MISMATCH)

    claimants = get_success_data(api_client.list_claimants(fund_id, _ADMIN))
    assert claimants[0]["status"] == "NOTIFIED", (
        "a rejected filing must not flip the claimant to CLAIMED"
    )
