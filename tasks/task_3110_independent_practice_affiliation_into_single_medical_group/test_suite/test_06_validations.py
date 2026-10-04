"""Validation rules: fixed validation order, business-safety acknowledgements,
temporal sanity, capacity, cross-linkage, and fiscal gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    add_provider,
    add_rate,
    approve_enrollment,
    create_affiliation_agreement_payload,
    create_collection_batch_payload,
    create_contract,
    create_market_for,
    create_pool,
    create_practice_in,
    create_practice_payload,
    create_statement,
    create_wave_for,
    draft_agreement,
    enter_allocation,
    get_success_data,
    make_market_committee_chair_headers,
    make_physician_board_member_headers,
    make_practice_executive_headers,
    move_wave_to_in_cutover,
    onboard_practice,
    open_and_pass_ratification_vote,
    post_batch,
    set_clock,
    setup_affiliated,
    setup_group_market,
    setup_onboarding_with_active_contract,
    setup_practice_onboarding,
    setup_wave_in_cutover,
    submit_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
PCO = TEST_USERS["payer_officer_headers"]
CC = TEST_USERS["credentialing_coordinator_headers"]
DA = TEST_USERS["distribution_accountant_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]


def test_missing_headers_returns_user_context_error(api):
    """PRD §2.1: "A request missing either header, or presenting a
    malformed value, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.9: "Because this order is fixed, an earlier failure always masks a
    later one — for example, a missing header surfaces as
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even when the request would
    also have failed a state check."

    Design: Corner/validations/missing_headers_returns_user_context_error
    """
    set_clock()
    # No auth headers at all; the path id does not exist either — the header
    # check must fire first (400, not 404).
    resp = api.get_practice("00000000-0000-4000-8000-000000000000", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400)


def test_required_field_error_precedes_not_found(api):
    """PRD §2.9: "Fourth, request shape: every required input field must be
    present, types must match, enum values must lie in their declared sets,
    amounts must be positive where required, periods must match the `YYYY-MM`
    format, and dates must match ISO `YYYY-MM-DD`; violations are rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.9: "Fifth, existence: identifiers in the URL path are resolved left
    to right, and then foreign keys in the request body in the order they are
    declared for that endpoint,"

    Design: Corner/validations/required_field_error_precedes_not_found
    """
    set_clock()
    # Missing required period AND unknown practice/contract ids: shape wins.
    resp = api.create_collection_batch(
        {
            "practice_id": "00000000-0000-4000-8000-000000000001",
            "payer_contract_id": "00000000-0000-4000-8000-000000000002",
            "posted_amount_cents": 1000,
        },
        DA,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    assert err["error_id"] != "ERR_PRACTICE_NOT_FOUND"


def test_agreement_without_non_compete_ack_rejected_as_business_safety(api):
    """PRD §3.2: "a `non_compete_accepted` acknowledgement that must be
    true: the group's non-compete and departure terms are a condition of
    affiliation, and a draft submitted without the acknowledgement is rejected
    with `ERR_NON_COMPETE_ACK_REQUIRED`."

    Design: Corner/validations/agreement_without_non_compete_ack_rejected_as_business_safety
    """
    ctx = setup_group_market()
    practice = get_success_data(api.create_practice(
        create_practice_payload(ctx["group"]["id"], ctx["market"]["id"]), GA
    ))
    resp = api.create_affiliation_agreement(
        create_affiliation_agreement_payload(
            practice["id"], practice["version"], non_compete_accepted=False
        ),
        make_practice_executive_headers(practice["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NON_COMPETE_ACK_REQUIRED, expected_status=422)

    rows, meta = validate_paginated(api.list_affiliation_agreements(GA))
    assert len(rows) == 0


def test_expedited_enrollment_span_over_45_days_rejected(api):
    """PRD §3.4: "for the `EXPEDITED` channel it must additionally fall
    within 45 days of the `application_date` — a longer span is rejected with
    `ERR_EXPEDITED_WINDOW_EXCEEDED`, while other shape violations are
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/expedited_enrollment_span_over_45_days_rejected
    """
    ctx = setup_onboarding_with_active_contract()
    provider = ctx["provider"]
    contract = ctx["contract"]

    # 46 days after application (2026-09-01): rejected.
    resp = api.create_credentialing_enrollment(
        {
            "provider_id": provider["id"],
            "payer_contract_id": contract["id"],
            "channel": "EXPEDITED",
            "requested_effective_date": "2026-10-17",
        },
        CC,
    )
    validate_error(resp, ApiErrorId.ERR_EXPEDITED_WINDOW_EXCEEDED, expected_status=422)

    # Exactly 45 days after application: accepted.
    ok = validate_success(api.create_credentialing_enrollment(
        {
            "provider_id": provider["id"],
            "payer_contract_id": contract["id"],
            "channel": "EXPEDITED",
            "requested_effective_date": "2026-10-16",
        },
        CC,
    ), expected_status=201)
    assert ok["status"] == "SUBMITTED"


def test_market_capacity_rejects_exactly_at_max(api):
    """PRD §3.1: "Market capacity is enforced at practice-creation time:
    the count of the market's practices whose status is `ONBOARDING`,
    `AFFILIATED`, `SUSPENDED`, or `DEPARTING` must stay at or below
    `max_practices`, so creation is rejected with `ERR_MARKET_AT_CAPACITY`
    exactly when the occupied count already equals `max_practices`."
    PRD §3.1: "A practice in `PROSPECT` or `DEPARTED` status does not consume
    capacity."

    Design: Corner/validations/market_capacity_rejects_exactly_at_max
    """
    set_clock()
    from test_helpers import create_group
    group = create_group()
    market = create_market_for(group, max_practices=2)
    wave = create_wave_for(market)
    move_wave_to_in_cutover(wave)

    practice1 = create_practice_in(group, market)
    onboard_practice(practice1)  # ONBOARDING — occupies capacity
    practice2 = create_practice_in(
        group, market,
        legal_name="Bishop Arts Pediatrics", legacy_tin="75-8888888", org_npi="2234567891",
    )
    onboard_practice(practice2)  # ONBOARDING — occupied count now equals max

    resp = api.create_practice(
        create_practice_payload(
            group["id"], market["id"],
            legal_name="Trinity Internal Medicine", legacy_tin="75-7777777", org_npi="3234567892",
        ),
        GA,
    )
    validate_error(resp, ApiErrorId.ERR_MARKET_AT_CAPACITY, expected_status=409)

    rows, meta = validate_paginated(api.list_practices(GA))
    assert len(rows) == 2


def test_batch_posting_requires_effective_enrollment_linkage(api):
    """PRD §3.6: "at least one `EFFECTIVE` enrollment must link the
    practice — via any of its providers — to the referenced contract (else
    `ERR_NO_EFFECTIVE_ENROLLMENT`)."

    Design: Corner/validations/batch_posting_requires_effective_enrollment_linkage
    """
    ctx = setup_affiliated()
    provider = ctx["provider"]

    # Second ACTIVE contract with no enrollment for the practice's providers.
    contract_b = create_contract(
        ctx["group"], payer_name="Trinity Health", contract_type="FEE_FOR_SERVICE"
    )
    add_rate(contract_b)
    open_and_pass_ratification_vote(ctx["market"], contract_b, provider, [provider])
    contract_b = activate_contract(contract_b)

    resp = api.create_collection_batch(
        create_collection_batch_payload(
            ctx["practice"]["id"], contract_b["id"], period="2026-09", posted_amount_cents=100000
        ),
        DA,
    )
    validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_ENROLLMENT, expected_status=422)

    rows, meta = validate_paginated(api.list_collection_batches(DA))
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# Difficulty queue: priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_finalize_suspended_practice_state_error_beats_unsettled_batches_fiscal_error(api):
    """PRD §2.9: "Seventh, state-machine preconditions and cross-entity
    state gates."
    PRD §2.9: "Twelfth, fiscal gates such as the settled-batch requirement on
    statement finalization."
    PRD §2.9: "Because this order is fixed, an earlier failure always masks a
    later one"
    PRD §3.6: "the practice must be `AFFILIATED` or `DEPARTING` (else
    `ERR_PRACTICE_NOT_AFFILIATED`); every batch of the practice for the period
    must be `SETTLED` or `ADJUSTED` — a lingering `POSTED` batch fails with
    `ERR_UNSETTLED_BATCHES_EXIST`;"

    Design: Difficulty/priority_pair_validation_conflict/finalize_suspended_practice_state_error_beats_unsettled_batches_fiscal_error
    """
    ctx = setup_affiliated()
    post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=30000000)
    statement = create_statement(ctx["practice"], period="2026-09")
    validate_success(api.suspend_practice(ctx["practice"]["id"], GA))

    resp = api.finalize_distribution_statement(statement["id"], GFC)
    err = validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_AFFILIATED, expected_status=409)
    assert err["error_id"] != "ERR_UNSETTLED_BATCHES_EXIST"

    after = validate_success(api.get_distribution_statement(statement["id"], GA))
    assert after["status"] == "PROVISIONAL_ISSUED"


def test_finalize_state_gate_masks_fiscal_gate_even_after_batches_settle(api):
    """PRD §2.9: "Because this order is fixed, an earlier failure always
    masks a later one"
    PRD §3.6: "the practice must be `AFFILIATED` or `DEPARTING` (else
    `ERR_PRACTICE_NOT_AFFILIATED`)"

    Design: Difficulty/priority_pair_validation_conflict/finalize_suspended_practice_state_error_beats_unsettled_batches_fiscal_error
    """
    ctx = setup_affiliated()
    batch = post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=30000000)
    statement = create_statement(ctx["practice"], period="2026-09")
    validate_success(api.suspend_practice(ctx["practice"]["id"], GA))

    # Settle the batch so ONLY the state violation remains: the same error id
    # must be reported, proving the fiscal gate never drove the outcome.
    from test_helpers import settle_batch
    settle_batch(batch, 0)

    resp = api.finalize_distribution_statement(statement["id"], GFC)
    err = validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_AFFILIATED, expected_status=409)
    assert err["error_id"] != "ERR_UNSETTLED_BATCHES_EXIST"

    # Reinstate removes the state violation; finalize then succeeds.
    validate_success(api.reinstate_practice(ctx["practice"]["id"], GA))
    final = validate_success(api.finalize_distribution_statement(statement["id"], GFC))
    assert final["status"] == "FINAL_ISSUED"


def test_wave_create_malformed_window_temporal_error_beats_overlap_constraint_error(api):
    """PRD §2.9: "Ninth, temporal and interval sanity. Tenth, uniqueness,
    capacity, and window-overlap constraints."
    PRD §3.3: "The end date must be strictly after the start date, or creation
    fails with `ERR_INVALID_CUTOVER_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/wave_create_malformed_window_temporal_error_beats_overlap_constraint_error
    """
    ctx = setup_group_market()
    create_wave_for(ctx["market"])  # occupies [2026-08-01, 2026-12-31)

    # Malformed (end < start) AND overlapping the existing window's range:
    # the temporal error must win.
    resp = api.create_implementation_wave(
        {
            "market_id": ctx["market"]["id"],
            "wave_code": "W2-BAD",
            "cutover_start_date": "2026-10-01",
            "cutover_end_date": "2026-09-01",
        },
        GA,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_CUTOVER_WINDOW, expected_status=422)
    assert err["error_id"] != "ERR_WAVE_WINDOW_OVERLAP"

    rows, meta = validate_paginated(api.list_implementation_waves(GA))
    assert len(rows) == 1


def test_wave_create_end_equal_start_rejected_as_malformed_window(api):
    """PRD §3.3: "The end date must be strictly after the start date, or
    creation fails with `ERR_INVALID_CUTOVER_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/wave_create_malformed_window_temporal_error_beats_overlap_constraint_error
    """
    ctx = setup_group_market()
    create_wave_for(ctx["market"])

    # end == start is not "strictly after": malformed-window error, not overlap.
    resp = api.create_implementation_wave(
        {
            "market_id": ctx["market"]["id"],
            "wave_code": "W2-EQ",
            "cutover_start_date": "2026-10-01",
            "cutover_end_date": "2026-10-01",
        },
        GA,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_CUTOVER_WINDOW, expected_status=422)
    assert err["error_id"] != "ERR_WAVE_WINDOW_OVERLAP"

    rows, meta = validate_paginated(api.list_implementation_waves(GA))
    assert len(rows) == 1
