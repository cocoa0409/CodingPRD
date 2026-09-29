"""The gates that refuse a request: priority order, exact amounts, solvency and windows.

Each gate in this file is checked against a setup where it is the only thing
standing in the way, or — where two gates are violated at once — against a setup
that proves which of the two owns the answer.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_county,
    create_brokerage,
    create_license,
    create_listing,
    create_seller,
    create_disclosure_payload,
    create_license_payload,
    create_protest_payload,
    create_transfer_application_payload,
    decide_application,
    decision_payload,
    escrow_deposit_payload,
    escrow_settlement_payload,
    file_disclosure,
    fund_escrow,
    acknowledge_as_seller,
    activate_listing,
    ledger_rows,
    make_broker_headers,
    make_regulator_analyst_headers,
    read_agreement,
    read_application,
    read_county,
    read_disclosure,
    read_license,
    read_listing,
    read_premises,
    read_protest,
    set_clock,
    setup_scenario,
    setup_closed_agreement,
    file_protest,
    verify_zoning,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)


def test_a_post_execution_resurvey_answers_with_distance_before_unsuitability():
    """A 500-foot school distance violates priority 12 and priority 13 at once.

    The filing must report the distance code, because the fixed order of refusal
    reaches the distance check first, even though the re-survey has also made the
    premises UNSUITABLE.

    PRD: "Many endpoints are guarded by several rules at once, and which rule a
    caller sees when more than one is violated is part of the contract, not an
    implementation detail. Checks are evaluated in the following order, and the
    first violated check ends the request:"

    PRD: "12. **Distance restriction** — `ERR_DISTANCE_RESTRICTION_VIOLATION`
    (422), on transfer-application filing and notice posting."

    PRD: "13. **Premises suitability** — `ERR_PREMISES_UNSUITABLE` (422), on
    agreement execution, transfer-application filing and notice posting."

    PRD: "The premises must clear the county's distance minima — both the school
    distance and the church distance must be at least the county's respective
    minimum — or the filing is refused with
    `ERR_DISTANCE_RESTRICTION_VIOLATION`. The premises must not be `UNSUITABLE`,
    or `ERR_PREMISES_UNSUITABLE`."

    Design: Corner/validations/distance_correction_after_execution_blocks_application_before_suitability
    """
    scenario = setup_scenario(stage="executed")
    resurveyed = verify_zoning(scenario["premises_id"], "GRANTED",
                               distance_to_nearest_school_feet=500)
    assert resurveyed["distance_to_nearest_school_feet"] == 500
    assert resurveyed["suitability_status"] == "UNSUITABLE"
    assert resurveyed["suitability_reason_code"] == "SCHOOL_DISTANCE"

    refused = api_client.create_transfer_application(
        create_transfer_application_payload(scenario["agreement_id"], 173250),
        scenario["broker_headers"],
    )
    error = validate_error(
        refused, ApiErrorId.ERR_DISTANCE_RESTRICTION_VIOLATION.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_PREMISES_UNSUITABLE.value

    _, meta = validate_paginated(api_client.list_transfer_applications(
        ADMIN, params={"agreement_id": scenario["agreement_id"]}
    ))
    assert meta["total_count"] == 0

    untouched = read_agreement(scenario["agreement_id"])
    assert untouched["agreement_status"] == "EXECUTED"
    assert untouched["escrow_status"] == "HELD"
    assert read_premises(scenario["premises_id"])["suitability_status"] == "UNSUITABLE"


def test_a_deposit_one_cent_short_is_refused_and_credits_nothing():
    """2405000 against a frozen requirement of 2405001 leaves AWAITING_DEPOSIT.

    The near miss is neither rounded away nor partially credited: no ledger row
    is written, and the exact amount tendered afterwards funds the escrow.

    PRD: "The amount must equal the agreement's frozen `required_deposit_cents`
    exactly; partial funding and over-funding are equally refused, with
    `ERR_DEPOSIT_AMOUNT_MISMATCH`, and a discrepancy of a single cent is enough."

    PRD: "Funding is a separate act, performed by the `Buyer` or by the
    `EscrowOfficer`, and it advances only the money dimension: `escrow_status`
    moves `AWAITING_DEPOSIT → HELD` while `agreement_status` is still `DRAFT`."

    Design: Corner/validations/deposit_amount_one_cent_below_requirement_rejected
    """
    scenario = setup_scenario(stage="disclosure_acked")
    agreement = scenario["agreement"]
    assert agreement["required_deposit_cents"] == 2405001

    refused = api_client.escrow_deposit(
        agreement["id"], escrow_deposit_payload(2405000), scenario["escrow_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH.value, 422)

    unfunded = read_agreement(agreement["id"])
    assert unfunded["escrow_status"] == "AWAITING_DEPOSIT"
    assert unfunded["escrow_balance_cents"] == 0
    assert unfunded["version"] == agreement["version"]
    _, meta = validate_paginated(api_client.list_escrow_ledger_entries(
        ADMIN, params={"agreement_id": agreement["id"]}
    ))
    assert meta["total_count"] == 0

    funded = fund_escrow(agreement["id"], 2405001)
    assert funded["escrow_status"] == "HELD"
    assert funded["escrow_balance_cents"] == 2405001
    assert funded["agreement_status"] == "DRAFT"


def test_a_release_whose_buckets_outrun_the_deposit_writes_no_ledger_row():
    """A 135000 county fee plus a 517500 commission cannot come out of 500000 held.

    Each bucket is lawful on its own; only their sum is impossible, so the
    residual would be negative and the whole release is refused with the escrow
    left exactly as it was found.

    PRD: "Next, `county_transfer_fee_cents` is the `purchase_price_cents`
    multiplied by the county's `transfer_fee_bps` and divided by ten thousand,
    rounded half up to whole cents. The waterfall then takes the county fee as
    bucket one, the commission total as bucket two, and leaves `seller_net_cents`
    as bucket three: the escrow balance held at settlement time, less the county
    fee, less the commission total. If that residual would be negative, the
    entire release is refused with `ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT` and
    **no ledger row is written at all** — the escrow is left exactly as it was
    found."

    PRD: "When `commission_mode` is `SINGLE_AGENCY` there is only one line: the
    seller-side line is the gross rounded half up to whole cents, the buyer-side
    line is zero, and `commission_total_cents` equals the single rounded line."

    PRD: "That raw amount is rounded half up to whole cents, and only then is it
    clamped: the result is at least 500000 cents and at most 7500000 cents."

    Design: Corner/validations/release_refused_when_fee_and_commission_buckets_exceed_the_deposit
    """
    scenario = setup_closed_agreement(
        license_overrides={"license_number": "SON-41-1",
                           "license_class": "CLASS_41_ONSALE_BEER_WINE",
                           "annual_gross_receipts_cents": 20000000},
        listing_overrides={"ask_price_cents": 9000000},
        agreement_overrides={"purchase_price_cents": 9000000,
                             "deposit_pct_bps": 500},
        application_fee=91800,
    )
    closed = scenario["agreement"]
    assert closed["required_deposit_cents"] == 500000
    assert closed["escrow_balance_cents"] == 500000
    assert closed["agreement_status"] == "CLOSED"
    assert closed["commission_mode"] == "SINGLE_AGENCY"

    refused = api_client.escrow_settlement(
        scenario["agreement_id"], escrow_settlement_payload("RELEASE"),
        scenario["escrow_headers"],
    )
    validate_error(
        refused, ApiErrorId.ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT.value, 422
    )

    intact = read_agreement(scenario["agreement_id"])
    assert intact["escrow_status"] == "HELD"
    assert intact["escrow_balance_cents"] == 500000
    assert intact["settled_at"] is None
    assert intact["seller_net_cents"] is None

    rows = ledger_rows(scenario["agreement_id"])
    assert [row["entry_type"] for row in rows] == ["DEPOSIT"]
    _, meta = validate_paginated(api_client.list_escrow_ledger_entries(
        ADMIN, params={"agreement_id": scenario["agreement_id"],
                       "entry_type": "RELEASE_COMMISSION"}
    ))
    assert meta["total_count"] == 0

    assert read_license(scenario["license_id"])["status"] == "TRANSFERRED"
    assert intact["agreement_status"] == "CLOSED"


def test_the_last_quota_slot_refuses_a_counted_license_but_not_an_exempt_one():
    """A one-slot county takes one counted license, then 409s, then takes an exempt one.

    A license created with `counts_against_quota` false never consumes a slot, so
    it is admitted while the quota is fully exhausted and leaves the counters
    untouched.

    PRD: "Creation is refused with `ERR_COUNTY_QUOTA_EXHAUSTED` when the license
    would count against quota and the county's `quota_available` is not at least
    1; on success the county's four counters are rewritten and the county's
    `version` advances by one."

    PRD: "and `counts_against_quota`, which defaults to true and is set false
    only for grandfathered non-quota licenses whose rows the quota arithmetic
    ignores."

    Design: Corner/validations/quota_exhausted_when_the_last_slot_is_already_counted
    """
    county = create_county(county_code="MAR", name="Marin", quota_licenses_total=1)
    seller = create_seller()
    create_license(county["id"], seller["id"], license_number="MAR-1",
                   annual_gross_receipts_cents=40000000)

    refused = api_client.create_license(
        create_license_payload(county["id"], seller["id"], license_number="MAR-2",
                              annual_gross_receipts_cents=40000000),
        ADMIN,
    )
    validate_error(refused, ApiErrorId.ERR_COUNTY_QUOTA_EXHAUSTED.value, 409)

    exhausted = read_county(county["id"])
    assert exhausted["quota_licenses_counted"] == 1
    assert exhausted["quota_available"] == 0
    assert exhausted["quota_utilization_bps"] == 10000

    exempt = validate_success(api_client.create_license(
        create_license_payload(county["id"], seller["id"], license_number="MAR-3",
                               license_class="CLASS_41_ONSALE_BEER_WINE",
                               annual_gross_receipts_cents=40000000,
                               counts_against_quota=False),
        ADMIN,
    ), 201)
    assert exempt["counts_against_quota"] is False
    assert exempt["status"] == "ACTIVE"

    still_one = read_county(county["id"])
    assert still_one["quota_licenses_counted"] == 1
    assert still_one["quota_available"] == 0

    _, meta = validate_paginated(api_client.list_licenses(
        ADMIN, params={"county_id": county["id"]}
    ))
    assert meta["total_count"] == 2


def test_the_protest_door_shuts_on_the_shorter_of_the_two_county_spans():
    """With protest_window_days 15 the deadline is 2026-08-16 though posting runs to 08-31.

    A protest offered on 2026-08-17 is one day late and is refused, leaving the
    application POSTED rather than PROTESTED.

    PRD: "`protest_deadline_at` is `posting_started_at` advanced by whichever is
    smaller of the county's `posting_period_days` and its `protest_window_days`,
    so a county that accepts protests for a shorter span than it publishes closes
    the protest door before the publication window ends."

    PRD: "The application must be `POSTED`, and the current logical instant must
    be at or before that application's `protest_deadline_at` — the deadline
    instant itself is still open; anything later is refused with
    `ERR_PROTEST_WINDOW_CLOSED`."

    Design: Corner/validations/protest_filed_one_day_after_protest_deadline_rejected
    """
    scenario = setup_scenario(
        stage="application_posted",
        county_overrides={"posting_period_days": 30, "protest_window_days": 15},
    )
    posted = scenario["application"]
    assert_instant_equals(posted["protest_deadline_at"], "2026-08-16T00:00:00Z",
                          "protest_deadline_at")
    assert_instant_equals(posted["posting_ends_at"], "2026-08-31T00:00:00Z",
                          "posting_ends_at")

    set_clock("2026-08-17T00:00:00Z")
    refused = api_client.create_protest(
        create_protest_payload(posted["id"], protestant_name="Neighborhood Council"),
        make_regulator_analyst_headers("analyst-3"),
    )
    validate_error(refused, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value, 409)

    unmoved = read_application(posted["id"])
    assert unmoved["status"] == "POSTED"
    assert unmoved["version"] == posted["version"]
    _, meta = validate_paginated(api_client.list_protests(
        ADMIN, params={"application_id": posted["id"]}
    ))
    assert meta["total_count"] == 0


def test_an_unanswered_protest_leaves_denial_as_the_only_lawful_decision():
    """Posting elapsed answers first; once it passes, APPROVED is refused and DENIED lands.

    At 2026-08-20 the publication has not run out, so the earlier check speaks.
    At 2026-09-01 it has, and the OPEN protest whose answer was due 2026-08-15
    makes approval unlawful while denial sustains the protest straight from OPEN.

    PRD: "The publication period must have fully elapsed: the logical clock must
    be **strictly later** than `posting_ends_at`, and equality is explicitly not
    elapsed, so a decision at the exact posting end instant is refused with
    `ERR_POSTING_PERIOD_NOT_ELAPSED`."

    PRD: "If any protest is still `OPEN` and the clock has moved strictly past
    its `response_due_at`, the broker has simply failed to answer, and the only
    lawful outcome is denial: an `APPROVED` decision in that situation is refused
    with `ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL`."

    PRD: "Every protest on the application that is `OPEN` or `RESPONDED` moves to
    `SUSTAINED` — a `RESPONDED` protest is sustained unconditionally, and an
    `OPEN` one is sustained precisely because its response deadline has already
    passed. No license field, no listing field and no agreement field is touched:
    the license stays `IN_ESCROW` until the escrow officer refunds, because
    denial alone never moves the license."

    Design: Corner/validations/unanswered_protest_past_response_due_forces_denied_decision
    """
    scenario = setup_scenario(stage="application_posted")
    application = scenario["application"]
    assert_instant_equals(application["posting_ends_at"], "2026-08-31T00:00:00Z",
                          "posting_ends_at")

    set_clock("2026-08-05T00:00:00Z")
    protest = file_protest(application["id"], analyst_id="analyst-3",
                          grounds="UNDUE_CONCENTRATION", response_due_days=10)
    assert protest["status"] == "OPEN"
    assert_instant_equals(protest["response_due_at"], "2026-08-15T00:00:00Z",
                          "response_due_at")

    set_clock("2026-08-20T00:00:00Z")
    early = api_client.decide_application(
        application["id"], decision_payload("APPROVED"),
        scenario["analyst_two_headers"],
    )
    validate_error(early, ApiErrorId.ERR_POSTING_PERIOD_NOT_ELAPSED.value, 409)

    set_clock("2026-09-01T00:00:00Z")
    unlawful = api_client.decide_application(
        application["id"], decision_payload("APPROVED"),
        scenario["analyst_two_headers"],
    )
    validate_error(
        unlawful, ApiErrorId.ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL.value, 409
    )

    denied = decide_application(application["id"], "DENIED")
    assert denied["status"] == "DENIED"
    assert denied["decision"] == "DENIED"
    assert_instant_equals(denied["decided_at"], "2026-09-01T00:00:00Z", "decided_at")

    sustained = read_protest(protest["id"])
    assert sustained["status"] == "SUSTAINED"
    assert sustained["response_submitted_at"] is None
    assert sustained["response_text_ref"] is None

    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"
    agreement = read_agreement(scenario["agreement_id"])
    assert agreement["escrow_status"] == "HELD"
    assert agreement["agreement_status"] == "EXECUTED"


def test_a_prohibited_firm_may_still_file_a_one_sided_disclosure():
    """Both-sides is dual agency and refused; neither-side is unrepresented; seller-only lands.

    The check is conditional on the firm's own policy and on which booleans were
    asserted, so one prohibited firm meets two different refusals and one
    success on the same agreement.

    PRD: "A disclosure asserting both representations is dual agency, and filing
    one for a brokerage whose `dual_agency_policy` is `PROHIBITED` is refused
    outright with `ERR_DUAL_AGENCY_PROHIBITED`. A disclosure asserting neither
    representation is meaningless and is refused with
    `ERR_PARTY_NOT_REPRESENTED`. A newly filed disclosure carries `status` of
    `PENDING_ACKS` — the enumeration being `PENDING_ACKS`, `FULLY_ACKED` and
    `VOID` — with `seller_ack_at` and `buyer_ack_at` both null."

    PRD: "Its `dual_agency_policy` is either `PROHIBITED` or
    `ALLOWED_WITH_DISCLOSURE` and defaults to `ALLOWED_WITH_DISCLOSURE`; a firm
    on the prohibited policy may never file a disclosure that represents both
    sides of the same agreement."

    Design: Corner/validations/dual_agency_disclosure_refused_only_for_prohibited_policy_firms
    """
    scenario = setup_scenario(
        stage="agreement_draft",
        brokerage_overrides={"dual_agency_policy": "PROHIBITED"},
    )
    agreement_id = scenario["agreement_id"]

    both_sides = api_client.create_disclosure(
        create_disclosure_payload(agreement_id, represents_seller=True,
                                  represents_buyer=True),
        scenario["broker_headers"],
    )
    validate_error(both_sides, ApiErrorId.ERR_DUAL_AGENCY_PROHIBITED.value, 422)

    neither_side = api_client.create_disclosure(
        create_disclosure_payload(agreement_id, represents_seller=False,
                                  represents_buyer=False),
        scenario["broker_headers"],
    )
    validate_error(neither_side, ApiErrorId.ERR_PARTY_NOT_REPRESENTED.value, 422)

    disclosure = file_disclosure(agreement_id, scenario["brokerage_id"],
                                represents_seller=True, represents_buyer=False)
    assert disclosure["status"] == "PENDING_ACKS"
    assert disclosure["seller_ack_at"] is None
    assert disclosure["buyer_ack_at"] is None

    _, meta = validate_paginated(api_client.list_disclosures(
        ADMIN, params={"agreement_id": agreement_id}
    ))
    assert meta["total_count"] == 1

    acked = acknowledge_as_seller(disclosure["id"], scenario["seller_id"])
    assert acked["status"] == "FULLY_ACKED"
    assert read_disclosure(disclosure["id"])["status"] == "FULLY_ACKED"
    assert read_agreement(agreement_id)["agreement_status"] == "DRAFT"


def test_activation_reads_tax_clearance_off_the_licensee_not_the_listing():
    """The PENDING-owner listing is refused; the CLEARED-owner twin activates.

    Two listings identical apart from whose license they carry separate the
    refusal's true source: the omitted `tax_clearance_status` defaulted to
    PENDING on one seller only.

    PRD: "Its `tax_clearance_status` is drawn from `PENDING`, `CLEARED` or
    `DELINQUENT` and defaults to `PENDING`. That single field gates two later
    operations: neither a listing activation nor a transfer-application filing
    may proceed while the selling licensee's clearance is anything other than
    `CLEARED`, and both refuse with `ERR_SELLER_TAX_CLEARANCE_MISSING`."

    PRD: "The selling licensee's `tax_clearance_status` must be `CLEARED`, or the
    activation is refused with `ERR_SELLER_TAX_CLEARANCE_MISSING`."

    Design: Corner/validations/activate_blocked_while_selling_licensee_tax_clearance_is_pending
    """
    county = create_county()
    pending_seller = get_success_data(api_client.create_seller_profile(
        {"legal_name": "Pending Vines LLC", "contact_email": "pending@example.com"},
        ADMIN,
    ))
    assert pending_seller["tax_clearance_status"] == "PENDING"
    cleared_seller = create_seller(legal_name="Cleared Vines LLC",
                                   contact_email="cleared@example.com")
    assert cleared_seller["tax_clearance_status"] == "CLEARED"
    brokerage = create_brokerage()

    pending_license = create_license(county["id"], pending_seller["id"],
                                     license_number="SON-P-1")
    cleared_license = create_license(county["id"], cleared_seller["id"],
                                     license_number="SON-C-1")
    pending_listing = create_listing(pending_license["id"], brokerage["id"])
    cleared_listing = create_listing(cleared_license["id"], brokerage["id"])

    refused = api_client.activate_listing(
        pending_listing["id"], make_broker_headers(brokerage["id"])
    )
    validate_error(refused, ApiErrorId.ERR_SELLER_TAX_CLEARANCE_MISSING.value, 422)

    unpublished = read_listing(pending_listing["id"])
    assert unpublished["status"] == "DRAFT"
    assert unpublished["market_price_cents"] is None
    assert unpublished["activated_at"] is None
    assert unpublished["version"] == 1
    assert read_license(pending_license["id"])["status"] == "ACTIVE"

    published = activate_listing(cleared_listing["id"], brokerage["id"])
    assert published["status"] == "ACTIVE"
    assert published["market_price_cents"] is not None
