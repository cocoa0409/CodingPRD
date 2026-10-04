"""RBAC, segregation of duties, optimistic concurrency, and conditional
actions (pool lifecycle, departure settle gating)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_pool,
    create_practice_in,
    create_statement,
    draft_agreement,
    enter_allocation,
    finalize_statement,
    make_market_committee_chair_headers,
    make_practice_executive_headers,
    onboard_practice,
    post_batch,
    set_clock,
    settle_batch,
    setup_affiliated,
    setup_departure_settlement_pending,
    setup_practice_onboarding,
    setup_wave_in_cutover,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
DA = TEST_USERS["distribution_accountant_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# RBAC (corner queue)
# ---------------------------------------------------------------------------

def test_distribution_accountant_cannot_finalize_statement(api):
    """PRD §2.1: "A `DistributionAccountant` posts, settles, and adjusts
    collection batches and drafts distribution statements but may never
    finalize a statement;"
    PRD §2.1: "a caller whose `X-User-Role` is not in the permitted set for
    that endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/distribution_accountant_cannot_finalize_statement
    """
    ctx = setup_affiliated()
    batch = post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=100000)
    settle_batch(batch, 0)
    statement = create_statement(ctx["practice"], period="2026-09")

    resp = api.finalize_distribution_statement(statement["id"], DA)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    after = validate_success(api.get_distribution_statement(statement["id"], GA))
    assert after["status"] == "PROVISIONAL_ISSUED"


def test_practice_executive_cannot_touch_another_practices_agreement(api):
    """PRD §2.1: "When `X-User-Role` is `PracticeExecutive`, `X-User-ID` is
    the `id` of the acting `Practice`;"
    PRD §2.1: "a mismatch is rejected with `ERR_PRACTICE_OWNERSHIP_MISMATCH`
    (HTTP 403)."

    Design: Corner/rbac/practice_executive_cannot_touch_another_practices_agreement
    """
    ctx = setup_wave_in_cutover()
    practice_a = create_practice_in(ctx["group"], ctx["market"])
    practice_b = create_practice_in(
        ctx["group"], ctx["market"],
        legal_name="Bishop Arts Pediatrics", legacy_tin="75-8888888", org_npi="2234567891",
    )

    # Practice A's executive tries to draft an agreement for practice B.
    resp = api.create_affiliation_agreement(
        {
            "practice_id": practice_b["id"],
            "distribution_model": "NET_OF_SHARED_SERVICES",
            "non_compete_accepted": True,
            "expected_practice_version": practice_b["version"],
        },
        make_practice_executive_headers(practice_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRACTICE_OWNERSHIP_MISMATCH, expected_status=403)

    rows, meta = validate_paginated(api.list_affiliation_agreements(GA))
    assert len(rows) == 0


def test_committee_chair_cannot_cast_ballot(api):
    """PRD §2.1: "A `MarketCommitteeChair` opens governance motions but
    never votes; a `PhysicianBoardMember` votes but never opens motions."
    PRD §2.1: "a caller whose `X-User-Role` is not in the permitted set for
    that endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/committee_chair_cannot_cast_ballot
    """
    from test_helpers import (
        add_provider,
        create_contract,
        create_committee_vote_payload,
        get_success_data,
    )

    ctx = setup_practice_onboarding()
    provider = add_provider(ctx["practice"])
    contract = create_contract(ctx["group"])

    vote = get_success_data(api.create_committee_vote(
        create_committee_vote_payload(ctx["market"]["id"], contract["id"]),
        make_market_committee_chair_headers(provider["id"]),
    ))

    resp = api.cast_committee_vote(
        vote["id"], {"ballot": "FOR"}, make_market_committee_chair_headers(provider["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    after = validate_success(api.get_committee_vote(vote["id"], GA))
    assert after["votes_for"] == 0
    assert after["status"] == "OPEN"


# ---------------------------------------------------------------------------
# OCC (corner queue, cross_cutting_layers)
# ---------------------------------------------------------------------------

def test_occ_stale_practice_version_rejected_on_agreement_create(api):
    """PRD §2.7: "Drafting an affiliation agreement requires the request to
    carry `expected_practice_version` matching the target practice's current
    `version`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Because drafting mutates the practice — each new draft
    increments the practice's `version` by one — the draft request must carry
    `expected_practice_version` per §2.7."

    Design: Corner/cross_cutting_layers/occ_stale_practice_version_rejected_on_agreement_create
    """
    ctx = setup_wave_in_cutover()
    practice = create_practice_in(ctx["group"], ctx["market"])

    # First draft succeeds and bumps the practice version.
    draft_agreement(practice)

    # A second create still carrying the pre-draft version is stale.
    resp = api.create_affiliation_agreement(
        {
            "practice_id": practice["id"],
            "distribution_model": "NET_OF_SHARED_SERVICES",
            "non_compete_accepted": True,
            "expected_practice_version": practice["version"],
        },
        make_practice_executive_headers(practice["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    rows, meta = validate_paginated(api.list_affiliation_agreements(GA))
    assert len(rows) == 1


def test_occ_stale_statement_version_rejected_on_amend(api):
    """PRD §2.7: "Amending a distribution statement requires
    `expected_statement_version` matching the statement's current `version`;"
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),"
    PRD §2.7: "Each successful amendment increments the statement's `version`
    by one."
    PRD §3.6: "Repeated amendment directly from `AMENDED` to `AMENDED` is
    permitted without an intervening reissue, still under the same OCC rule."

    Design: Corner/cross_cutting_layers/occ_stale_statement_version_rejected_on_amend
    """
    ctx = setup_affiliated()
    batch = post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=100000)
    settle_batch(batch, 0)
    statement = create_statement(ctx["practice"], period="2026-09")
    finalized = finalize_statement(statement)

    first = validate_success(api.amend_distribution_statement(
        statement["id"], {"expected_statement_version": finalized["version"]}, GFC
    ))
    assert first["status"] == "AMENDED"
    assert first["version"] == finalized["version"] + 1

    # Stale: still carrying the pre-amend version.
    resp = api.amend_distribution_statement(
        statement["id"], {"expected_statement_version": finalized["version"]}, GFC
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # AMENDED -> AMENDED re-amend with the current version succeeds.
    third = validate_success(api.amend_distribution_statement(
        statement["id"], {"expected_statement_version": first["version"]}, GFC
    ))
    assert third["status"] == "AMENDED"
    assert third["version"] == first["version"] + 1


# ---------------------------------------------------------------------------
# Conditional actions (corner queue, endpoints)
# ---------------------------------------------------------------------------

def test_pool_void_is_a_conditional_action_only_from_distributed(api):
    """PRD §3.7: "Voiding unwinds a `DISTRIBUTED` pool to `VOIDED`: each
    `PAYABLE` allocation becomes `VOIDED`,"
    PRD §5: "`ERR_INVALID_TRANSITION` | 409 Conflict |"

    Design: Corner/endpoints/pool_void_is_a_conditional_action_only_from_distributed
    """
    ctx = setup_affiliated()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    assert pool["status"] == "OPEN"

    resp = api.void_incentive_pool(pool["id"], GFC)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    after = validate_success(api.get_incentive_pool(pool["id"], GA))
    assert after["status"] == "OPEN"


def test_departure_settle_before_earliest_exit_rejected(api):
    """PRD §3.8: "A `ComplianceOfficer` settles a `SETTLEMENT_PENDING`
    case, but only once the logical clock date has reached
    `earliest_exit_date`; an early settle is rejected with
    `ERR_EXIT_DATE_NOT_REACHED`."

    Design: Corner/endpoints/departure_settle_before_earliest_exit_rejected
    """
    # Notice at 2027-06-01 -> earliest exit 2027-11-28; clock still 2027-06-01.
    ctx = setup_departure_settlement_pending(requested_exit_date="2027-09-01")

    resp = api.settle_departure_case(ctx["case"]["id"], CO)
    validate_error(resp, ApiErrorId.ERR_EXIT_DATE_NOT_REACHED, expected_status=422)

    case_after = validate_success(api.get_departure_case(ctx["case"]["id"], GA))
    assert case_after["status"] == "SETTLEMENT_PENDING"

    practice_after = validate_success(api.get_practice(ctx["practice"]["id"], GA))
    assert practice_after["status"] == "DEPARTING"
