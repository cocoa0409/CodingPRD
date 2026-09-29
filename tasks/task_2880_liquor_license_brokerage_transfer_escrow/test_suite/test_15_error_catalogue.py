"""The catalogue in use: entity-specific 404s, one 400 for four shapes, and the guards.

Every error in this file is provoked on a setup where it is the documented
answer, and where a plausible neighbouring code exists the test also asserts the
neighbour was not returned.
"""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    acknowledge_as_seller,
    acknowledge_disclosure_payload,
    activate_listing,
    answer_protest,
    api_client,
    assert_error_payload_shape,
    assert_instant_equals,
    create_county,
    create_license_payload,
    create_listing,
    create_safekeeping_filing_payload,
    create_seller,
    decide_application,
    decide_safekeeping,
    escrow_settlement_payload,
    execute_agreement,
    file_protest,
    file_safekeeping,
    ledger_rows,
    make_broker_headers,
    make_buyer_headers,
    protest_response_payload,
    read_agreement,
    read_application,
    read_county,
    read_disclosure,
    read_license,
    read_listing,
    read_protest,
    review_buyer,
    set_clock,
    setup_safekeeping_bench,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_dangling_read_answers_with_its_own_not_found_code():
    """All twelve single-entity reads carry their own error_id, never one shared code.

    PRD: "The resource-specific not-found codes are `ERR_COUNTY_NOT_FOUND`,
    `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and
    `ERR_FILING_NOT_FOUND`, each carrying HTTP 404."

    PRD: "Where a path carries more than one identifier, identifiers are resolved
    strictly left to right, and the response reports the first identifier that
    resolves to nothing."

    Design: Corner/errors/not_found_errors_are_entity_specific_not_generic
    """
    reads = [
        (api_client.get_county, ApiErrorId.ERR_COUNTY_NOT_FOUND),
        (api_client.get_seller_profile, ApiErrorId.ERR_SELLER_NOT_FOUND),
        (api_client.get_buyer_profile, ApiErrorId.ERR_BUYER_NOT_FOUND),
        (api_client.get_brokerage, ApiErrorId.ERR_BROKERAGE_NOT_FOUND),
        (api_client.get_license, ApiErrorId.ERR_LICENSE_NOT_FOUND),
        (api_client.get_premises, ApiErrorId.ERR_PREMISES_NOT_FOUND),
        (api_client.get_listing, ApiErrorId.ERR_LISTING_NOT_FOUND),
        (api_client.get_purchase_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api_client.get_disclosure, ApiErrorId.ERR_DISCLOSURE_NOT_FOUND),
        (api_client.get_transfer_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api_client.get_protest, ApiErrorId.ERR_PROTEST_NOT_FOUND),
        (api_client.get_safekeeping_filing, ApiErrorId.ERR_FILING_NOT_FOUND),
    ]
    seen = []
    for read, expected in reads:
        error = validate_error(read(NON_EXISTENT_UUID, ADMIN), expected.value, 404)
        assert_error_payload_shape(error)
        assert error["message"]
        seen.append(error["error_id"])

    assert len(set(seen)) == 12


def test_one_invalid_request_code_covers_four_shapes_of_malformed_input():
    """A missing field, an unknown enum, an out-of-range integer and a bad format all 400.

    PRD: "4. **Request body well-formed.** On every write endpoint: every required
    field present, every enum value drawn from its declared set, every integer
    inside its declared range, every datetime a valid ISO 8601 UTC instant, every
    date a valid `YYYY-MM-DD` value, and no value of the wrong scalar type (a
    string where an integer is declared, for instance) — `ERR_INVALID_REQUEST`
    (400)."

    PRD: "A `PlatformAdmin` registers a licensing county by supplying a
    `county_code` — a short identifier of between 2 and 8 characters that must be
    unique across all counties — a display `name`, a `state_code` of exactly two
    uppercase letters, and `quota_licenses_total`, the statutory ceiling on how
    many quota-counted licenses may exist there, which must be at least 1."

    PRD: "It carries the applicant's `legal_name`, an `entity_type` of
    `INDIVIDUAL`, `LLC` or `CORP`, and a `residency_state` of exactly two
    uppercase letters."

    Design: Corner/errors/invalid_request_covers_missing_fields_bad_enums_and_range_breaches
    """
    county = create_county()
    seller = create_seller()

    missing = api_client.create_county(
        {"county_code": "NAP", "name": "Napa", "state_code": "CA"}, ADMIN
    )
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bad_enum = api_client.create_license(
        create_license_payload(county["id"], seller["id"], license_number="X-1",
                               license_class="CLASS_99_UNKNOWN",
                               annual_gross_receipts_cents=20000000),
        ADMIN,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    out_of_range = api_client.create_county(
        {"county_code": "MAR", "name": "Marin", "state_code": "CA",
         "quota_licenses_total": 0},
        ADMIN,
    )
    validate_error(out_of_range, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bad_format = api_client.create_buyer_profile(
        {"legal_name": "Bad State LLC", "entity_type": "LLC",
         "residency_state": "California"},
        ADMIN,
    )
    validate_error(bad_format, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, license_meta = validate_paginated(api_client.list_licenses(ADMIN))
    assert license_meta["total_count"] == 0
    unchanged = read_county(county["id"])
    assert unchanged["version"] == county["version"]
    assert unchanged["quota_licenses_counted"] == 0


def test_the_unrepresented_party_and_the_repeat_signature_are_both_refused():
    """On a seller-only disclosure the buyer may not sign and the seller may not sign twice.

    PRD: "Signing as a party the disclosure does not actually represent is refused
    with `ERR_PARTY_NOT_REPRESENTED` — a `BUYER` acknowledgement requires
    `represents_buyer` to be true, and a `SELLER` acknowledgement requires
    `represents_seller` to be true — and a second acknowledgement by the same
    party is refused with `ERR_ALREADY_ACKNOWLEDGED`."

    PRD: "As soon as every party the disclosure represents carries an
    acknowledgement timestamp, `status` is promoted `PENDING_ACKS →
    FULLY_ACKED`. For a single-sided disclosure that means one signature
    suffices; for a dual-agency disclosure both are required."

    Design: Corner/errors/acknowledgement_guards_reject_unrepresented_and_repeat_parties
    """
    scenario = setup_scenario(stage="disclosure_filed", represents_seller=True,
                             represents_buyer=False)
    disclosure_id = scenario["disclosure_id"]

    wrong_party = api_client.acknowledge_disclosure(
        disclosure_id, acknowledge_disclosure_payload("BUYER"),
        make_buyer_headers(scenario["buyer_id"]),
    )
    validate_error(wrong_party, ApiErrorId.ERR_PARTY_NOT_REPRESENTED.value, 422)

    acked = acknowledge_as_seller(disclosure_id, scenario["seller_id"])
    assert acked["status"] == "FULLY_ACKED"
    assert acked["seller_ack_at"] is not None
    assert acked["buyer_ack_at"] is None
    assert acked["version"] == 2

    again = api_client.acknowledge_disclosure(
        disclosure_id, acknowledge_disclosure_payload("SELLER"),
        scenario["seller_headers"],
    )
    validate_error(again, ApiErrorId.ERR_ALREADY_ACKNOWLEDGED.value, 422)

    final = read_disclosure(disclosure_id)
    assert final["seller_ack_at"] == acked["seller_ack_at"]
    assert final["version"] == 2
    assert final["status"] == "FULLY_ACKED"


def test_a_release_is_too_early_before_closing_and_too_late_after_settling():
    """RELEASE on an EXECUTED agreement is a state error; a second RELEASE is already settled.

    PRD: "A **release** advances `HELD → RELEASED` and is the only branch that
    pays anybody. It requires the agreement's `agreement_status` to be `CLOSED`,
    or it is refused with `ERR_INVALID_AGREEMENT_STATE`, and it requires the
    agreement's transfer application to be `APPROVED`, or it is refused with
    `ERR_TRANSFER_NOT_APPROVED`."

    PRD: "In every branch the money dimension must currently be `HELD`: an
    attempt while it is still `AWAITING_DEPOSIT` is refused with
    `ERR_ESCROW_NOT_HELD`, and an attempt once it has already reached
    `RELEASED`, `REFUNDED` or `FORFEITED` is refused with
    `ERR_ESCROW_ALREADY_SETTLED`."

    PRD: "On success the three bucket figures are written to the agreement and
    three ledger rows are appended **in this pinned order**:
    `RELEASE_COUNTY_FEE`, then `RELEASE_COMMISSION`, then `RELEASE_SELLER`."

    Design: Corner/errors/settlement_is_refused_before_closing_and_again_after_settling
    """
    scenario = setup_scenario(stage="application_posted")
    agreement_id = scenario["agreement_id"]
    assert scenario["agreement"]["agreement_status"] == "EXECUTED"

    early = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("RELEASE"), scenario["escrow_headers"]
    )
    validate_error(early, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value, 409)

    set_clock("2026-09-10T00:00:00Z")
    decide_application(scenario["application_id"], "APPROVED")

    released = validate_success(api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("RELEASE"), scenario["escrow_headers"]
    ))
    assert released["escrow_status"] == "RELEASED"
    assert released["escrow_balance_cents"] == 0

    again = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("RELEASE"), scenario["escrow_headers"]
    )
    validate_error(again, ApiErrorId.ERR_ESCROW_ALREADY_SETTLED.value, 409)

    rows = ledger_rows(agreement_id)
    assert [row["entry_type"] for row in rows] == [
        "DEPOSIT", "RELEASE_COUNTY_FEE", "RELEASE_COMMISSION", "RELEASE_SELLER"
    ]
    _, meta = validate_paginated(api_client.list_escrow_ledger_entries(
        ADMIN, params={"agreement_id": agreement_id}
    ))
    assert meta["total_count"] == 4
    assert read_agreement(agreement_id)["escrow_balance_cents"] == 0


def test_execution_waits_on_the_buyers_review_and_nothing_else():
    """A NOT_REVIEWED buyer blocks execute; the identical call lands once FINAL_REVIEW scores him.

    PRD: "The buyer's stored qualification must satisfy section 3.2, or
    `ERR_BUYER_NOT_QUALIFIED`."

    PRD: "A newly registered buyer has never been scored, so
    `qualification_status` reads `NOT_REVIEWED`, while `qualification_score`,
    `qualification_mode` and `qualification_reviewed_at` are all null."

    PRD: "Both agreement execution and transfer-application filing require a
    buyer whose stored `qualification_status` is `QUALIFIED` or
    `PROVISIONALLY_QUALIFIED` and whose stored `qualification_mode` is
    `FINAL_REVIEW`; a buyer who has never been reviewed, one whose latest review
    was only a `PRE_CHECK`, and one who came out `UNQUALIFIED` or `DISQUALIFIED`
    are all refused with `ERR_BUYER_NOT_QUALIFIED`."

    Design: Corner/errors/execute_refused_while_the_buyer_is_unreviewed
    """
    scenario = setup_scenario(stage="escrow_held", review_step=False)
    assert scenario["buyer"]["qualification_status"] == "NOT_REVIEWED"

    refused = api_client.execute_agreement(
        scenario["agreement_id"], scenario["broker_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_BUYER_NOT_QUALIFIED.value, 422)

    blocked = read_agreement(scenario["agreement_id"])
    assert blocked["agreement_status"] == "DRAFT"
    assert blocked["escrow_status"] == "HELD"
    assert blocked["executed_at"] is None

    reviewed = review_buyer(scenario["buyer_id"], scenario["premises_id"],
                           "FINAL_REVIEW")
    assert reviewed["qualification_status"] == "QUALIFIED"
    assert reviewed["qualification_mode"] == "FINAL_REVIEW"

    executed = execute_agreement(scenario["agreement_id"], scenario["brokerage_id"])
    assert executed["agreement_status"] == "EXECUTED"
    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"


def test_an_answer_one_day_past_the_response_deadline_is_refused():
    """A protest due 2026-08-15 cannot be answered on 2026-08-16 and stays OPEN.

    PRD: "The `Broker` answers a protest by supplying `response_text_ref`, moving
    the protest `OPEN → RESPONDED`. This requires the current logical instant to
    be at or before that protest's `response_due_at`, with a late answer refused
    by `ERR_PROTEST_RESPONSE_WINDOW_CLOSED`, and requires the parent application
    to be in `PROTESTED` status."

    PRD: "An optional `response_due_days` sets how long the broker has to answer
    and defaults to 15 days."

    Design: Corner/errors/protest_response_after_its_due_date_is_refused
    """
    scenario = setup_scenario(stage="application_posted")
    set_clock("2026-08-05T00:00:00Z")
    protest = file_protest(scenario["application_id"], analyst_id="analyst-3",
                          grounds="PUBLIC_WELFARE", response_due_days=10)
    assert_instant_equals(protest["response_due_at"], "2026-08-15T00:00:00Z",
                          "response_due_at")
    assert read_application(scenario["application_id"])["status"] == "PROTESTED"

    set_clock("2026-08-16T00:00:00Z")
    late = api_client.respond_to_protest(
        protest["id"], protest_response_payload("resp-late-1"),
        scenario["broker_headers"],
    )
    validate_error(late, ApiErrorId.ERR_PROTEST_RESPONSE_WINDOW_CLOSED.value, 409)

    unanswered = read_protest(protest["id"])
    assert unanswered["status"] == "OPEN"
    assert unanswered["response_submitted_at"] is None
    assert unanswered["response_text_ref"] is None
    assert unanswered["version"] == protest["version"]
    assert read_application(scenario["application_id"])["status"] == "PROTESTED"


def test_a_second_answer_on_a_responded_protest_is_a_state_error_not_a_terminal_one():
    """RESPONDED is not terminal, so the repeat is refused by the state code and nothing moves.

    PRD: "The accepted protest carries `status` of `OPEN` — its enumeration being
    `OPEN`, `RESPONDED`, `SUSTAINED` and `OVERRULED`, of which the last two are
    terminal — with `filed_at` set to the current logical instant,
    `response_due_at` set to `filed_at` advanced by `response_due_days` days, and
    `response_text_ref` and `response_submitted_at` both null."

    PRD: "A protest that is not `OPEN` refuses the answer with
    `ERR_INVALID_PROTEST_STATE`. A successful answer stamps
    `response_submitted_at` with the current logical instant, stores the supplied
    reference, and advances the protest's `version`."

    Design: Corner/errors/second_response_on_an_answered_protest_is_refused
    """
    scenario = setup_scenario(stage="application_posted")
    set_clock("2026-08-05T00:00:00Z")
    protest = file_protest(scenario["application_id"], analyst_id="analyst-3",
                          grounds="ZONING", response_due_days=10)

    set_clock("2026-08-10T00:00:00Z")
    answered = answer_protest(protest["id"], scenario["brokerage_id"], "resp-first")
    assert answered["status"] == "RESPONDED"
    assert answered["response_text_ref"] == "resp-first"
    assert_instant_equals(answered["response_submitted_at"], "2026-08-10T00:00:00Z",
                          "response_submitted_at")
    assert answered["version"] == 2

    duplicate = api_client.respond_to_protest(
        protest["id"], protest_response_payload("resp-second"),
        scenario["broker_headers"],
    )
    error = validate_error(duplicate, ApiErrorId.ERR_INVALID_PROTEST_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ALREADY_TERMINAL.value

    intact = read_protest(protest["id"])
    assert intact["response_text_ref"] == "resp-first"
    assert intact["version"] == 2
    assert read_application(scenario["application_id"])["status"] == "PROTESTED"


def test_a_decision_waits_for_an_answer_window_that_outlives_the_posting():
    """A protest answerable to 2026-09-09 makes a 2026-09-01 decision premature.

    The publication has already elapsed at that instant, so the refusal proves
    the response-pending rule speaks after the posting rule rather than instead
    of it, and the approval lands as soon as the broker answers.

    PRD: "If any protest on the application is still `OPEN` and the logical clock
    is at or before that protest's `response_due_at`, the protestant's answer
    window has not run out and any decision is premature, refused with
    `ERR_PROTEST_RESPONSE_PENDING`."

    PRD: "Put positively: an approval from `PROTESTED` requires every protest on
    the application to be `RESPONDED`, whereas a denial from `PROTESTED` is
    lawful either when every protest is `RESPONDED` or when at least one is
    `OPEN` with its response deadline already past."

    PRD: "Every protest on the application still `OPEN` or `RESPONDED` moves to
    `OVERRULED`."

    Design: Corner/errors/decision_is_premature_while_a_protest_answer_is_still_due
    """
    scenario = setup_scenario(stage="application_posted")
    assert_instant_equals(scenario["application"]["posting_ends_at"],
                          "2026-08-31T00:00:00Z", "posting_ends_at")

    set_clock("2026-08-25T00:00:00Z")
    protest = file_protest(scenario["application_id"], analyst_id="analyst-3",
                          grounds="UNDUE_CONCENTRATION", response_due_days=15)
    assert_instant_equals(protest["response_due_at"], "2026-09-09T00:00:00Z",
                          "response_due_at")

    set_clock("2026-09-01T00:00:00Z")
    premature = api_client.decide_application(
        scenario["application_id"], {"decision": "APPROVED"},
        scenario["analyst_two_headers"],
    )
    error = validate_error(
        premature, ApiErrorId.ERR_PROTEST_RESPONSE_PENDING.value, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_POSTING_PERIOD_NOT_ELAPSED.value

    answered = answer_protest(protest["id"], scenario["brokerage_id"], "resp-in-time")
    assert answered["status"] == "RESPONDED"

    approved = decide_application(scenario["application_id"], "APPROVED")
    assert approved["status"] == "APPROVED"
    assert read_protest(protest["id"])["status"] == "OVERRULED"
    assert read_license(scenario["license_id"])["status"] == "TRANSFERRED"
    assert read_listing(scenario["listing_id"])["status"] == "SOLD"


def test_a_forfeiture_is_refused_while_the_contingency_still_has_a_day_to_run():
    """Contingency 30 days from 2026-09-01 makes 2026-10-01 too early and 2026-10-02 lawful.

    PRD: "The `contingency_deadline_at` is computed as `closing_window_start`
    advanced by `contingency_days` days, and it is the exclusive end of the
    transfer window this agreement reserves on the license."

    PRD: "It requires the logical clock to be **strictly past**
    `contingency_deadline_at`, and an attempt at or before that instant is
    refused with `ERR_CONTINGENCY_STILL_OPEN`."

    PRD: "It appends exactly one ledger row of `entry_type` `FORFEIT_SELLER`
    whose `amount_cents` is the negative of the whole held balance and whose
    `balance_after_cents` is 0, and it too leaves all three settlement buckets
    null."

    Design: Corner/errors/forfeit_before_the_contingency_deadline_is_refused_then_allowed
    """
    scenario = setup_scenario(stage="application_filed",
                             agreement_overrides={"contingency_days": 30})
    agreement_id = scenario["agreement_id"]
    assert_instant_equals(scenario["agreement"]["contingency_deadline_at"],
                          "2026-10-01T00:00:00Z", "contingency_deadline_at")
    assert read_application(scenario["application_id"])["status"] == "SUBMITTED"

    too_early = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("FORFEIT"), scenario["escrow_headers"]
    )
    validate_error(too_early, ApiErrorId.ERR_CONTINGENCY_STILL_OPEN.value, 409)

    set_clock("2026-10-01T00:00:00Z")
    on_the_deadline = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("FORFEIT"), scenario["escrow_headers"]
    )
    validate_error(on_the_deadline, ApiErrorId.ERR_CONTINGENCY_STILL_OPEN.value, 409)
    still_held = read_agreement(agreement_id)
    assert still_held["escrow_status"] == "HELD"
    assert still_held["escrow_balance_cents"] == 2405001

    set_clock("2026-10-02T00:00:00Z")
    forfeited = validate_success(api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("FORFEIT"), scenario["escrow_headers"]
    ))
    assert forfeited["escrow_status"] == "FORFEITED"
    assert forfeited["agreement_status"] == "TERMINATED"
    assert forfeited["termination_reason"] == "ESCROW_FORFEITED"
    assert forfeited["escrow_balance_cents"] == 0
    assert forfeited["county_transfer_fee_cents"] is None
    assert forfeited["commission_total_cents"] is None
    assert forfeited["seller_net_cents"] is None
    assert_instant_equals(forfeited["settled_at"], "2026-10-02T00:00:00Z", "settled_at")

    rows = ledger_rows(agreement_id)
    assert [row["entry_type"] for row in rows] == ["DEPOSIT", "FORFEIT_SELLER"]
    assert rows[1]["amount_cents"] == -2405001
    assert rows[1]["balance_after_cents"] == 0


def test_execution_on_the_contingency_deadline_is_already_too_late():
    """Equality with the deadline refuses the execution and leaves every party where it was.

    PRD: "And the logical clock must be strictly before
    `contingency_deadline_at`, or the attempt is refused with
    `ERR_CONTINGENCY_DEADLINE_PASSED` — equality with the deadline is already too
    late."

    Design: Corner/errors/execute_after_the_contingency_deadline_is_refused
    """
    scenario = setup_scenario(stage="escrow_held",
                             agreement_overrides={"contingency_days": 30})
    agreement_id = scenario["agreement_id"]
    assert_instant_equals(scenario["agreement"]["contingency_deadline_at"],
                          "2026-10-01T00:00:00Z", "contingency_deadline_at")

    set_clock("2026-10-01T00:00:00Z")
    at_the_deadline = api_client.execute_agreement(agreement_id, scenario["broker_headers"])
    validate_error(at_the_deadline, ApiErrorId.ERR_CONTINGENCY_DEADLINE_PASSED.value, 409)

    set_clock("2026-10-02T00:00:00Z")
    past_it = api_client.execute_agreement(agreement_id, scenario["broker_headers"])
    validate_error(past_it, ApiErrorId.ERR_CONTINGENCY_DEADLINE_PASSED.value, 409)

    unexecuted = read_agreement(agreement_id)
    assert unexecuted["agreement_status"] == "DRAFT"
    assert unexecuted["escrow_status"] == "HELD"
    assert unexecuted["executed_at"] is None
    assert unexecuted["commission_mode"] is None
    assert read_license(scenario["license_id"])["status"] == "ACTIVE"
    assert read_listing(scenario["listing_id"])["status"] == "ACTIVE"
    assert read_county(scenario["county_id"])["escrow_committed_count"] == 0


def test_the_pending_flag_blocks_activation_and_a_third_extension_is_refused_outright():
    """A pending filing stops publication; the granted window is activatable; the fourth is not.

    PRD: "The pending flag has two consequences beyond the filing itself. While it
    is set, a listing on that license cannot be activated, refused with
    `ERR_SAFEKEEPING_FILING_PENDING`."

    PRD: "The underlying license must be in `ACTIVE` or `SAFEKEEPING` status — an
    `IN_ESCROW` license cannot be listed, and a `TRANSFERRED` one is terminal —
    and a violation reports `ERR_INVALID_LICENSE_STATE`."

    PRD: "It is admissible only while the license's
    `safekeeping_extensions_count` is less than 2, so a license may hold an
    initial window and at most two extensions; a petition for a fourth window is
    refused with `ERR_SAFEKEEPING_EXTENSION_LIMIT`."

    Design: Corner/errors/safekeeping_filing_guards_block_activation_and_a_third_extension
    """
    bench = setup_safekeeping_bench(license_number="SAFE-1")
    license_id = bench["license_id"]
    listing = create_listing(license_id, bench["brokerage_id"], ask_price_cents=9000000)

    initial = file_safekeeping(license_id, read_license(license_id)["version"],
                              brokerage_id=bench["brokerage_id"])
    assert initial["status"] == "PENDING"
    assert initial["fee_cents"] == 20000
    assert read_license(license_id)["safekeeping_filing_pending"] is True

    blocked = api_client.activate_listing(listing["id"], bench["broker_headers"])
    validate_error(blocked, ApiErrorId.ERR_SAFEKEEPING_FILING_PENDING.value, 409)
    assert read_listing(listing["id"])["status"] == "DRAFT"

    granted = decide_safekeeping(initial["id"], "GRANT")
    assert granted["status"] == "GRANTED"
    assert_instant_equals(granted["expires_at"], "2027-08-01T00:00:00Z", "expires_at")
    in_safekeeping = read_license(license_id)
    assert in_safekeeping["status"] == "SAFEKEEPING"
    assert in_safekeeping["safekeeping_filing_pending"] is False
    assert in_safekeeping["safekeeping_extensions_count"] == 0

    published = activate_listing(listing["id"], bench["brokerage_id"])
    assert published["status"] == "ACTIVE"

    first = file_safekeeping(license_id, read_license(license_id)["version"],
                            filing_type="EXTENSION", requested_months=9,
                            brokerage_id=bench["brokerage_id"])
    assert first["extension_index"] == 1
    assert first["granted_months"] == 6
    assert first["fee_cents"] == 40000
    assert_instant_equals(first["effective_from"], "2027-08-01T00:00:00Z", "effective_from")
    assert_instant_equals(first["expires_at"], "2028-02-01T00:00:00Z", "expires_at")
    decide_safekeeping(first["id"], "GRANT")

    second = file_safekeeping(license_id, read_license(license_id)["version"],
                             filing_type="EXTENSION", requested_months=6,
                             brokerage_id=bench["brokerage_id"])
    assert second["extension_index"] == 2
    assert second["fee_cents"] == 80000
    assert_instant_equals(second["effective_from"], "2028-02-01T00:00:00Z", "effective_from")
    assert_instant_equals(second["expires_at"], "2028-08-01T00:00:00Z", "expires_at")
    decide_safekeeping(second["id"], "GRANT")

    extended = read_license(license_id)
    assert extended["status"] == "SAFEKEEPING"
    assert extended["safekeeping_extensions_count"] == 2
    assert_instant_equals(extended["safekeeping_expires_at"], "2028-08-01T00:00:00Z",
                          "safekeeping_expires_at")

    fourth = api_client.create_safekeeping_filing(
        create_safekeeping_filing_payload(license_id, extended["version"],
                                          filing_type="EXTENSION", requested_months=6),
        make_broker_headers(bench["brokerage_id"]),
    )
    validate_error(fourth, ApiErrorId.ERR_SAFEKEEPING_EXTENSION_LIMIT.value, 409)
    assert read_license(license_id)["version"] == extended["version"]
    assert read_license(license_id)["safekeeping_filing_pending"] is False

    filings, meta = validate_paginated(
        api_client.list_license_safekeeping_filings(license_id, ADMIN)
    )
    assert meta["total_count"] == 3
    assert [f["extension_index"] for f in filings] == [0, 1, 2]


def test_a_second_listing_cannot_be_published_once_the_license_left_active():
    """With the license IN_ESCROW the replacement listing is refused on license state.

    PRD: "The underlying license must be in `ACTIVE` or `SAFEKEEPING` status — an
    `IN_ESCROW` license cannot be listed, and a `TRANSFERRED` one is terminal —
    and a violation reports `ERR_INVALID_LICENSE_STATE`."

    Design: Corner/errors/activating_a_second_listing_after_the_licence_left_active_is_refused
    """
    scenario = setup_scenario(stage="executed")
    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"
    assert read_listing(scenario["listing_id"])["status"] == "UNDER_CONTRACT"

    replacement = create_listing(scenario["license_id"], scenario["brokerage_id"],
                                ask_price_cents=19000000)
    assert replacement["status"] == "DRAFT"

    refused = api_client.activate_listing(replacement["id"], scenario["broker_headers"])
    validate_error(refused, ApiErrorId.ERR_INVALID_LICENSE_STATE.value, 409)

    still_draft = read_listing(replacement["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["market_price_cents"] is None
    assert still_draft["valuation_basis"] is None
    assert still_draft["activated_at"] is None
    assert still_draft["version"] == 1

    listings, meta = validate_paginated(
        api_client.list_listings(ADMIN, params={"license_id": scenario["license_id"]})
    )
    assert meta["total_count"] == 2
    assert sum(1 for row in listings if row["status"] == "UNDER_CONTRACT") == 1
