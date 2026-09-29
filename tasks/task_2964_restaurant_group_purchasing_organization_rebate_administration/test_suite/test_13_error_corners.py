"""Error-catalogue corners: the rejection sweeps of the §errors design section.

Six sweeps live here, each one a family of rejections that must all report the
same error id (and the same HTTP status from §5) while their nearest legal
neighbours still succeed:

  * the four authentication header defects that are all 401
  * the four out-of-bounds pagination arguments that are all 400, against the
    inclusive 1..100 limit bounds and the declared defaults
  * the four duplicate business keys, two global and two scoped, each contrasted
    with the positive control that proves the scope
  * ERR_PERIOD_BOUNDS_INVALID over two different inequalities plus the review
    window that may not run past the logical clock's calendar date
  * the three write paths a written-off recovery closes to a suspended
    distributor, and the two it leaves open
  * the dispute amount bounded on both sides by one error id, and the two
    dispute statuses that block a second filing
  * the one unaccrued-batch gate that guards both reconcile and close-period

Every precondition is built through the API: the database is empty before each
test and the server is relaunched between them.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_1,
    ARBITER_1,
    GPO_ADMIN_1,
    ApiErrorId,
    api_client,
    assert_accrual,
    assert_authorization_letter,
    assert_compliance_review,
    assert_contracted_item,
    assert_deal,
    assert_dispute,
    assert_distributor,
    assert_error_meta_is_minimal,
    assert_instants_equal,
    assert_member,
    assert_member_ledger,
    assert_program_tier,
    assert_purchase_batch,
    assert_purchase_line,
    assert_request_meta,
    assert_split,
    make_analyst_headers,
    make_arbiter_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.types import (
    AccrualBasis,
    AccrualStatus,
    AuditStatus,
    ClaimStatus,
    ComplianceResult,
    CountersignDecision,
    DealStatus,
    DisputeDecision,
    DisputeReasonCode,
    DisputeStatus,
    DistributorStatus,
    LetterScope,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RecoveryOutcome,
    ReconciliationPosture,
)

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers(ANALYST_1)
ARBITER = make_arbiter_headers(ARBITER_1)

# The design parks the logical clock at 09:00 on the epoch's own calendar date,
# so "today" is 2026-08-01 for every review-window and dispute-window rule.
CLOCK_0900 = "2026-08-01T09:00:00.000Z"

WIDE = {"limit": C.MAX_LIMIT}


def _raw_headers(user_id=None, role=None) -> dict:
    """Build an auth header pair where either key may be absent or empty.

    A MISSING header means the key is not in the dict at all. An EMPTY header is
    sent as "" — never as a space — so that a server which trims before checking
    and one which checks before trimming must agree on the outcome.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


def _assert_unauthenticated(response):
    """Every 401 still carries the standard minimal error envelope."""
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert response.json()["response_type"] == "error"
    assert_error_meta_is_minimal(response)
    assert_request_meta(response)


def _assert_single_untouched_tier(tier: dict):
    """The rejected reads created and mutated nothing at all."""
    rows, meta = validate_paginated(api_client.list_program_tiers(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 1, "no rejected call may create a ProgramTier"
    assert len(rows) == 1
    assert_program_tier(rows[0])
    assert rows[0]["id"] == tier["id"]
    assert rows[0]["version"] == 1, "no rejected call may mutate the tier"


# ==========================================================================
# instance: missing_or_unknown_auth_headers_return_unauthenticated
# ==========================================================================


def test_absent_and_empty_role_header_are_both_unauthenticated():
    """A read whose X-User-Role is absent, and the same read whose X-User-Role is
    an empty string, must both be 401 ERR_UNAUTHENTICATED before any business
    logic runs.

    PRD 2.1: "Every request to every endpoint — reads, writes and the
    administrative clock alike — must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the caller's role. If
    either header is absent or present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_auth_headers_return_unauthenticated
    """
    tier = fx.create_tier()

    _assert_unauthenticated(
        api_client.list_program_tiers(_raw_headers(user_id=GPO_ADMIN_1))
    )
    _assert_unauthenticated(
        api_client.list_program_tiers(_raw_headers(user_id=GPO_ADMIN_1, role=""))
    )

    _assert_single_untouched_tier(tier)


def test_absent_and_empty_user_id_header_are_both_unauthenticated():
    """A well-formed role name is not enough on its own: with X-User-ID absent,
    and again with X-User-ID empty, the same read is 401 ERR_UNAUTHENTICATED.

    PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.7 rung 1: "`X-User-Role` and `X-User-ID` are both present and
    non-empty — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_or_unknown_auth_headers_return_unauthenticated
    """
    tier = fx.create_tier()

    _assert_unauthenticated(
        api_client.list_program_tiers(_raw_headers(role="GpoAdmin"))
    )
    _assert_unauthenticated(
        api_client.list_program_tiers(_raw_headers(user_id="", role="GpoAdmin"))
    )

    _assert_single_untouched_tier(tier)


def test_role_name_outside_the_six_is_unauthenticated_and_not_forbidden():
    """"Auditor" is not one of the six declared roles, so the read is 401
    ERR_UNAUTHENTICATED rather than 403 ERR_FORBIDDEN_ROLE.

    PRD 2.1: "The same `ERR_UNAUTHENTICATED` rejection applies when
    `X-User-Role` carries a value that is not one of the six declared role
    names, compared with exact case sensitivity."

    Design: Corner/errors/missing_or_unknown_auth_headers_return_unauthenticated
    """
    tier = fx.create_tier()

    response = api_client.list_program_tiers(
        _raw_headers(user_id=GPO_ADMIN_1, role="Auditor")
    )
    _assert_unauthenticated(response)
    assert response.status_code != 403, (
        "an unrecognized role name is authentication, not authorization"
    )

    _assert_single_untouched_tier(tier)


def test_role_name_with_the_wrong_case_is_unauthenticated_and_the_pair_then_works():
    """"gpoadmin" spells the role correctly but cases it wrongly, so it is 401;
    the very same URL succeeds once both headers are well formed.

    PRD 2.1: "The same `ERR_UNAUTHENTICATED` rejection applies when
    `X-User-Role` carries a value that is not one of the six declared role
    names, compared with exact case sensitivity."
    PRD 2.7 rung 2: "`X-User-Role` is one of the six declared role names,
    matched case-sensitively — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_or_unknown_auth_headers_return_unauthenticated
    """
    tier = fx.create_tier()

    _assert_unauthenticated(
        api_client.list_program_tiers(_raw_headers(user_id=GPO_ADMIN_1, role="gpoadmin"))
    )

    rows, meta = validate_paginated(api_client.list_program_tiers(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == tier["id"]
    assert rows[0]["version"] == 1


# ==========================================================================
# instance: pagination_arguments_outside_their_declared_bounds_are_rejected
# ==========================================================================


def _tier_with_two_members() -> dict:
    """Two members on one tier, so an unpaginated list would return 2 rows."""
    tier = fx.create_tier()
    m1 = fx.create_member(tier["id"])
    m2 = fx.create_member(
        tier["id"],
        legal_name="Pier 9 Oyster Bar Inc",
        committed_annual_spend_cents=9_000_000,
    )
    return {"tier": tier, "m1": m1, "m2": m2}


def test_limit_below_and_above_the_declared_bounds_are_rejected():
    """limit 0 and limit 101 both fall outside the inclusive 1..100 range, so both
    are 400 ERR_INVALID_PAGINATION — 0 is not silently defaulted to 10.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "A `limit` outside the range 1 through 100 inclusive, a non-integer
    `limit`, a negative `offset`, or a non-integer `offset` is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_arguments_outside_their_declared_bounds_are_rejected
    """
    _tier_with_two_members()

    low = api_client.list_members(ADMIN, {"limit": 0})
    validate_error(low, ApiErrorId.ERR_INVALID_PAGINATION, 400)
    assert_error_meta_is_minimal(low)

    high = api_client.list_members(ADMIN, {"limit": 101})
    validate_error(high, ApiErrorId.ERR_INVALID_PAGINATION, 400)
    assert_error_meta_is_minimal(high)


def test_negative_offset_and_non_integer_limit_are_pagination_errors():
    """A negative offset and a non-integer limit are both ERR_INVALID_PAGINATION,
    not ERR_INVALID_REQUEST: the rule owns query arguments even though a list
    read carries no request body.

    PRD 2.3: "`offset` controls the starting position: it defaults to 0 when
    omitted and its minimum accepted value is 0."
    PRD 2.3: "A `limit` outside the range 1 through 100 inclusive, a non-integer
    `limit`, a negative `offset`, or a non-integer `offset` is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_arguments_outside_their_declared_bounds_are_rejected
    """
    _tier_with_two_members()

    negative = api_client.list_members(ADMIN, {"offset": -1})
    validate_error(negative, ApiErrorId.ERR_INVALID_PAGINATION, 400)

    non_integer = api_client.list_members(ADMIN, {"limit": "ten"})
    validate_error(non_integer, ApiErrorId.ERR_INVALID_PAGINATION, 400)
    assert non_integer.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST


def test_the_inclusive_pagination_bounds_and_the_declared_defaults_are_accepted():
    """limit 1 and limit 100 are both inside the range, and omitting both
    arguments echoes the declared defaults of 10 and 0.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset`
    echoing the values in effect, `total_count` giving the number of records
    matching the request's filters before pagination, and `has_more` indicating
    whether any matching record remains beyond the current page."

    Design: Corner/errors/pagination_arguments_outside_their_declared_bounds_are_rejected
    """
    _tier_with_two_members()

    rows, meta = validate_paginated(api_client.list_members(ADMIN, {"limit": 1, "offset": 1}))
    assert meta["limit"] == 1 and meta["offset"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 1, "exactly one row on a one-row page at offset 1"
    assert_member(rows[0])

    rows, meta = validate_paginated(api_client.list_members(ADMIN, {"limit": 100, "offset": 0}))
    assert meta["limit"] == 100 and meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2

    rows, meta = validate_paginated(api_client.list_members(ADMIN))
    assert meta["limit"] == C.DEFAULT_LIMIT == 10
    assert meta["offset"] == C.DEFAULT_OFFSET == 0
    assert meta["total_count"] == 2
    assert len(rows) == 2


# ==========================================================================
# instance: duplicate_business_keys_are_rejected_within_their_declared_scope
# ==========================================================================


def _duplicate_key_setup() -> dict:
    """ELITE tier, two distributors, two deals, one item under the first deal and
    one June batch under the first distributor."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    distributor2 = fx.create_distributor(
        name="Sysco Northeast", dba_code="SYSCO-02", contracted_markup_bps=600
    )
    deal_a = fx.create_deal()
    deal_b = fx.create_deal(
        manufacturer_name="Rival Beef LLC",
        deal_code="RVL-2026",
        required_purchase_window_days=90,
    )
    item_a = fx.create_item(deal_a["id"])
    batch_1 = fx.create_batch(distributor["id"])
    return {
        "tier": tier,
        "distributor_id": distributor["id"],
        "distributor2_id": distributor2["id"],
        "deal_a_id": deal_a["id"],
        "deal_b_id": deal_b["id"],
        "item_a": item_a,
        "batch_1": batch_1,
    }


def test_tier_code_is_globally_unique_even_with_different_economics():
    """A second ELITE tier with a completely different split and dispute window is
    still a duplicate tier_code, and the split it carries is balanced so no
    earlier ladder rung can fire instead.

    PRD 3.1: "A `GpoAdmin` creates a tier by supplying a `tier_code` — one of
    `CORE`, `PLUS` or `ELITE`, and no two tiers may share one, a collision being
    rejected with `ERR_DUPLICATE_TIER_CODE`"

    Design: Corner/errors/duplicate_business_keys_are_rejected_within_their_declared_scope
    """
    _duplicate_key_setup()

    duplicate = F.program_tier_payload(
        member_share_bps=6000, gpo_retention_bps=4000, dispute_window_days=30
    )
    response = api_client.create_program_tier(duplicate, ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TIER_CODE, 409)
    assert_error_meta_is_minimal(response)

    _, meta = validate_paginated(api_client.list_program_tiers(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 1, "the rejected create wrote no second tier"


def test_deal_code_is_globally_unique_across_years_and_manufacturers():
    """PBC-2026 filed again for a different manufacturer name and a different
    contract year is still a duplicate deal_code.

    PRD 3.2: "Creating one takes a `manufacturer_name` of 1 to 200 characters, a
    `deal_code` of 3 to 30 characters unique across all deals — a duplicate
    drawing `ERR_DUPLICATE_DEAL_CODE`"

    Design: Corner/errors/duplicate_business_keys_are_rejected_within_their_declared_scope
    """
    _duplicate_key_setup()

    duplicate = F.deal_payload(
        manufacturer_name="Prairie Beef Co of Texas",
        deal_code=C.DEAL_CODE,
        effective_from="2027-01-01",
        effective_to="2027-12-31",
        required_purchase_window_days=30,
    )
    response = api_client.create_deal(duplicate, ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DEAL_CODE, 409)

    _, meta = validate_paginated(api_client.list_deals(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 2, "only the two setup deals exist"


def test_manufacturer_sku_is_unique_only_within_one_deal():
    """The same manufacturer_sku is refused under the deal that already uses it and
    accepted under another deal, so the uniqueness scope is (deal_id,
    manufacturer_sku) rather than global.

    PRD 3.2: "An item is created with `deal_id`, a `manufacturer_sku` of 1 to 40
    characters that must be unique among that deal's items — a repeat within the
    same deal is rejected with `ERR_DUPLICATE_ITEM_SKU`"

    Design: Corner/errors/duplicate_business_keys_are_rejected_within_their_declared_scope
    """
    ctx = _duplicate_key_setup()

    same_deal = F.contracted_item_payload(
        ctx["deal_a_id"],
        manufacturer_sku=C.BEEF_SKU,
        normalized_item_key="BEEF-PATTY-8OZ-CS20",
        pack_size=20,
        baseline_unit_cost_cents=15200,
        contract_unit_cost_cents=14100,
    )
    response = api_client.create_contracted_item(same_deal, ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ITEM_SKU, 409)

    other_deal = F.contracted_item_payload(
        ctx["deal_b_id"],
        manufacturer_sku=C.BEEF_SKU,
        normalized_item_key=C.BEEF_KEY,
        pack_size=40,
        baseline_unit_cost_cents=9700,
        contract_unit_cost_cents=8850,
    )
    accepted = validate_success(api_client.create_contracted_item(other_deal, ADMIN), 201)
    assert_contracted_item(accepted)
    assert accepted["manufacturer_sku"] == C.BEEF_SKU
    assert accepted["deal_id"] == ctx["deal_b_id"]

    _, meta = validate_paginated(api_client.list_contracted_items(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 2


def test_source_reference_is_unique_only_within_one_distributor():
    """The same source_reference is refused for the distributor that already used it
    — even for a different period — and accepted for another distributor, so the
    scope is (distributor_id, source_reference).

    PRD 3.3: "a `source_reference` of 3 to 40 characters that is the
    distributor's own file reference; that reference must be unique among that
    distributor's batches, and a repeat is rejected with
    `ERR_DUPLICATE_BATCH_REFERENCE`"

    Design: Corner/errors/duplicate_business_keys_are_rejected_within_their_declared_scope
    """
    ctx = _duplicate_key_setup()
    feed_1 = make_distributor_feed_headers(ctx["distributor_id"])
    feed_2 = make_distributor_feed_headers(ctx["distributor2_id"])

    same_distributor = F.purchase_batch_payload(
        ctx["distributor_id"],
        period_start=C.JULY_START,
        period_end=C.JULY_END,
        source_reference=C.JUNE_BATCH_REFERENCE,
    )
    response = api_client.create_purchase_batch(same_distributor, feed_1)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BATCH_REFERENCE, 409)

    other_distributor = F.purchase_batch_payload(
        ctx["distributor2_id"], source_reference=C.JUNE_BATCH_REFERENCE
    )
    accepted = validate_success(
        api_client.create_purchase_batch(other_distributor, feed_2), 201
    )
    assert_purchase_batch(accepted)
    assert accepted["source_reference"] == C.JUNE_BATCH_REFERENCE
    assert accepted["distributor_id"] == ctx["distributor2_id"]

    _, meta = validate_paginated(api_client.list_purchase_batches(ANALYST, dict(WIDE)))
    assert meta["total_count"] == 2


# ==========================================================================
# instance: period_bounds_and_future_review_windows_are_rejected
# ==========================================================================


def _bounds_setup() -> dict:
    """Clock at 09:00 on 2026-08-01, one tier, one distributor, one still-PENDING
    member and one DRAFT deal."""
    fx.set_clock(CLOCK_0900)
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    deal = fx.create_deal()
    return {
        "tier_id": tier["id"],
        "distributor_id": distributor["id"],
        "member_id": member["id"],
        "deal_id": deal["id"],
        "feed": make_distributor_feed_headers(distributor["id"]),
    }


def test_backwards_batch_period_is_rejected_while_a_single_day_period_is_accepted():
    """A batch whose period_end precedes its period_start is 422
    ERR_PERIOD_BOUNDS_INVALID, while a zero-length period — end equal to start —
    is legal because the batch rule is period_end >= period_start.

    PRD 3.3: "Either the `DistributorFeed` account itself or a `RebateAnalyst`
    opens a batch by supplying `distributor_id`, the inclusive `period_start` and
    `period_end` with the end not before the start"
    PRD 2.7 rung 22: "Every period, window or effectivity range is correctly
    ordered — otherwise `ERR_PERIOD_BOUNDS_INVALID`."

    Design: Corner/errors/period_bounds_and_future_review_windows_are_rejected
    """
    ctx = _bounds_setup()

    backwards = F.purchase_batch_payload(
        ctx["distributor_id"],
        period_start="2026-06-30",
        period_end="2026-06-01",
        source_reference="METRO-BACKWARDS",
    )
    response = api_client.create_purchase_batch(backwards, ctx["feed"])
    validate_error(response, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID, 422)
    assert_error_meta_is_minimal(response)

    one_day = F.purchase_batch_payload(
        ctx["distributor_id"],
        period_start="2026-06-15",
        period_end="2026-06-15",
        source_reference="METRO-ONE-DAY",
    )
    batch = validate_success(api_client.create_purchase_batch(one_day, ctx["feed"]), 201)
    assert_purchase_batch(batch)
    assert batch["period_start"] == batch["period_end"] == "2026-06-15"
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0

    _, meta = validate_paginated(api_client.list_purchase_batches(ANALYST, dict(WIDE)))
    assert meta["total_count"] == 1, "only the accepted single-day batch exists"


def test_letter_needs_effective_to_strictly_after_effective_from_but_a_deal_does_not():
    """One error id hides two different inequalities: equal instants are refused on
    an authorization letter, while the same equality on a deal's calendar bounds
    is accepted.

    PRD 3.1: "The window is half-open and its `effective_to` must be strictly
    after its `effective_from`; an `effective_to` equal to or before the start is
    rejected with `ERR_PERIOD_BOUNDS_INVALID`."
    PRD 3.2: "the inclusive calendar bounds `effective_from` and `effective_to`
    with the end not before the start"

    Design: Corner/errors/period_bounds_and_future_review_windows_are_rejected
    """
    ctx = _bounds_setup()

    equal_window = F.authorization_letter_payload(
        ctx["member_id"],
        ctx["distributor_id"],
        effective_from="2026-06-01T00:00:00.000Z",
        effective_to="2026-06-01T00:00:00.000Z",
        signatory_name="Dana Reyes",
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
    )
    response = api_client.create_authorization_letter(equal_window, ADMIN)
    validate_error(response, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID, 422)

    _, meta = validate_paginated(api_client.list_authorization_letters(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 0, "the rejected letter was never stored"

    equal_dates = F.deal_payload(
        manufacturer_name="One Day Foods",
        deal_code="ONEDAY-2026",
        effective_from="2026-06-01",
        effective_to="2026-06-01",
        required_purchase_window_days=30,
    )
    deal = validate_success(api_client.create_deal(equal_dates, ADMIN), 201)
    assert_deal(deal)
    assert deal["effective_from"] == deal["effective_to"] == "2026-06-01"
    assert deal["status"] == DealStatus.DRAFT.value


def test_review_window_ending_after_the_clock_date_is_rejected():
    """A window whose end is one calendar day past the logical clock's date draws
    ERR_REVIEW_WINDOW_IN_FUTURE (422), and no review row is written.

    PRD 3.8: "The window's end may not precede its start, which draws
    `ERR_PERIOD_BOUNDS_INVALID`, and it may not extend beyond the logical clock's
    current calendar date, which draws `ERR_REVIEW_WINDOW_IN_FUTURE` — a review
    of a period that has not finished happening would understate purchasing by
    construction."

    Design: Corner/errors/period_bounds_and_future_review_windows_are_rejected
    """
    ctx = _bounds_setup()

    payload = F.compliance_review_payload(
        ctx["member_id"], ctx["deal_id"], "2026-07-01", "2026-08-02"
    )
    response = api_client.create_compliance_review(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_IN_FUTURE, 422)
    assert_error_meta_is_minimal(response)

    _, meta = validate_paginated(api_client.list_compliance_reviews(ADMIN, dict(WIDE)))
    assert meta["total_count"] == 0


def test_backwards_review_window_outranks_the_future_window_rule():
    """A window that is both backwards and future-ending reports only the earlier
    ladder rung: ERR_PERIOD_BOUNDS_INVALID, never ERR_REVIEW_WINDOW_IN_FUTURE.

    PRD 2.7: "Requests are validated as an ordered ladder, and the **first**
    check that fails determines the response. No later check runs, so a request
    that would fail three ways reports only the earliest failure."
    PRD 2.7 rung 22 precedes rung 25: "Every period, window or effectivity range
    is correctly ordered — otherwise `ERR_PERIOD_BOUNDS_INVALID`."

    Design: Corner/errors/period_bounds_and_future_review_windows_are_rejected
    """
    ctx = _bounds_setup()

    payload = F.compliance_review_payload(
        ctx["member_id"], ctx["deal_id"], "2026-12-01", "2026-09-01"
    )
    response = api_client.create_compliance_review(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_REVIEW_WINDOW_IN_FUTURE


def test_a_same_day_review_window_is_accepted_and_freezes_a_breach_verdict():
    """window_end exactly equal to the clock's calendar date is not "beyond" it, so
    the review is written: one day long, a prorated commitment of 54795 cents, no
    contracted spend and therefore a BREACH that a PENDING member cannot absorb.

    PRD 3.8: "`window_days` is the number of days from `window_start` to
    `window_end` with **both endpoints counted**, so a window whose start and end
    are the same date is 1 day long."
    PRD 3.8: "`committed_spend_prorated_cents` scales the member's annual promise
    down to the window: it is `committed_annual_spend_cents` multiplied by
    `window_days`, divided by 365, and rounded half up."
    PRD 3.1: "a member goes `ACTIVE → SUSPENDED` only as a consequence of a
    compliance review returning a breach verdict"

    Design: Corner/errors/period_bounds_and_future_review_windows_are_rejected
    """
    ctx = _bounds_setup()

    payload = F.compliance_review_payload(
        ctx["member_id"], ctx["deal_id"], "2026-08-01", "2026-08-01"
    )
    review = validate_success(api_client.create_compliance_review(payload, ADMIN), 201)
    assert_compliance_review(review)
    assert review["window_days"] == 1
    assert review["committed_spend_prorated_cents"] == 54795
    assert review["contracted_spend_cents"] == 0
    assert review["deal_wide_contracted_spend_cents"] == 0
    assert review["purchase_ratio_bps"] == 0
    assert review["result"] == ComplianceResult.BREACH.value, (
        "window_days 1 is below the deal's required_purchase_window_days 60 and "
        "the deal is still DRAFT, so the DEAL_LOST branch cannot fire"
    )
    assert review["triggered_deal_loss"] is False
    assert "version" not in review, "a ComplianceReview is immutable: no version"

    fetched = validate_success(api_client.get_compliance_review(review["id"], ADMIN), 200)
    assert_compliance_review(fetched)
    assert "version" not in fetched and "updated_at" not in fetched

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    assert member["payout_hold"] is False

    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.DRAFT.value


# ==========================================================================
# instance: suspended_distributor_cannot_open_a_new_batch_or_countersign
# ==========================================================================

MAY_START = "2026-05-01"
MAY_END = "2026-05-31"
MAY_BATCH_REFERENCE = "METRO-2026-05"


def _written_off_setup() -> dict:
    """Suspend METRO-01 through a written-off recovery, leaving behind a
    NORMALIZED July feed, an empty RECEIVED May feed and a SUBMITTED letter.

    Pier 9's letter is submitted before the write-off so that this fixture never
    depends on whether letter submission itself is distributor-status gated: the
    behaviour under test is the countersignature, not the submission.
    """
    fx.set_clock(CLOCK_0900)
    ctx = fx.setup_flat_program()
    distributor_id = ctx["distributor_id"]

    m2 = fx.create_member(
        ctx["tier_id"],
        legal_name="Pier 9 Oyster Bar Inc",
        committed_annual_spend_cents=9_000_000,
    )
    l2 = fx.submit_letter(
        m2["id"],
        distributor_id,
        headers=ADMIN,
        effective_from="2026-02-01T00:00:00.000Z",
        effective_to="2027-02-01T00:00:00.000Z",
        signatory_name="Ali Ncube",
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
    )
    assert l2["status"] == LetterStatus.SUBMITTED.value

    fx.ingest_june_feed(ctx, second_line=False)
    fx.normalize_june_feed(ctx)

    b2 = fx.create_july_batch(distributor_id)
    line_b2 = fx.create_line(
        b2["id"],
        ctx["member_id"],
        distributor_id,
        cases_shipped=10,
        invoice_date="2026-07-06",
    )
    b2 = fx.normalize(b2["id"])

    b3 = fx.create_batch(
        distributor_id,
        period_start=MAY_START,
        period_end=MAY_END,
        source_reference=MAY_BATCH_REFERENCE,
    )
    assert b3["normalization_status"] == NormalizationStatus.RECEIVED.value

    audited = fx.audit_markup(ctx["batch_id"])
    assert audited["overbilled_cents"] == 300, (
        "the cap is min(distributor 900, tier 700) == 700, so allowed is "
        "8533 + round_half_up(8533*700/10000) == 8533 + 597 == 9130 and the "
        "excess is 10 cents over 30 cases"
    )
    assert audited["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    fx.request_recovery(ctx["batch_id"])
    settled = fx.settle_recovery(ctx["batch_id"], RecoveryOutcome.WRITTEN_OFF.value)
    assert settled["audit_status"] == AuditStatus.WRITTEN_OFF.value
    assert settled["recovered_cents"] == 0

    ctx["m2_id"] = m2["id"]
    ctx["l2_id"] = l2["id"]
    ctx["b2_id"] = b2["id"]
    ctx["line_b2_id"] = line_b2["id"]
    ctx["b3_id"] = b3["id"]
    ctx["feed"] = make_distributor_feed_headers(distributor_id)
    return ctx


def test_a_written_off_recovery_suspends_the_distributor_and_closes_new_feeds():
    """The write-off recovers nothing and suspends METRO-01, after which opening an
    August feed is 409 ERR_DISTRIBUTOR_SUSPENDED.

    PRD 3.7: "An outcome of `WRITTEN_OFF` forces `recovered_cents` to 0, moves the
    batch `RECOVERY_REQUESTED → WRITTEN_OFF`, credits no member at all, and
    cascades into the distributor relationship: the batch's distributor moves
    `ACTIVE → SUSPENDED`"
    PRD 3.3: "A suspended distributor cannot open a feed at all and is turned away
    with `ERR_DISTRIBUTOR_SUSPENDED`."

    Design: Corner/errors/suspended_distributor_cannot_open_a_new_batch_or_countersign
    """
    ctx = _written_off_setup()

    distributor = fx.read_distributor(ctx["distributor_id"])
    assert_distributor(distributor)
    assert distributor["status"] == DistributorStatus.SUSPENDED.value
    assert distributor["overbilled_recovered_cents"] == 0, "a write-off recovers nothing"
    assert distributor["active_letter_count"] == 1, "only Harbor Grill's letter is ACTIVE"

    august = F.purchase_batch_payload(
        ctx["distributor_id"],
        period_start="2026-08-01",
        period_end="2026-08-31",
        source_reference="METRO-2026-08",
    )
    response = api_client.create_purchase_batch(august, ctx["feed"])
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409)
    assert_error_meta_is_minimal(response)

    _, meta = validate_paginated(api_client.list_purchase_batches(ANALYST, dict(WIDE)))
    assert meta["total_count"] == 3, "June, July and May only: the August feed never opened"


def test_a_suspended_distributor_cannot_countersign_and_the_letter_stays_submitted():
    """The suspension gate runs before the countersign decision is applied, so the
    pending letter is left SUBMITTED — not DECLINED — and no counter moves.

    PRD 3.1: "Either branch requires the letter to still be `SUBMITTED`, requires
    the acting `DistributorFeed` account's `X-User-ID` to equal the letter's
    `distributor_id`, and — for the accepting branch as for the declining one —
    requires the distributor's own `status` to be `ACTIVE`, a suspended
    distributor being turned away with `ERR_DISTRIBUTOR_SUSPENDED`."

    Design: Corner/errors/suspended_distributor_cannot_open_a_new_batch_or_countersign
    """
    ctx = _written_off_setup()

    response = api_client.countersign_letter(
        ctx["l2_id"], {"decision": CountersignDecision.ACCEPT.value}, ctx["feed"]
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409)

    letter = validate_success(api_client.get_authorization_letter(ctx["l2_id"], ADMIN), 200)
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.SUBMITTED.value, "never DECLINED"
    assert letter["countersigned_at"] is None
    assert letter["version"] == 1

    assert fx.read_member(ctx["m2_id"])["active_letter_count"] == 0
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1


def test_audit_markup_still_runs_for_a_suspended_distributor_but_recovery_does_not():
    """Suspension gates the recovery demand, not the audit: the July feed still
    audits to 100 cents overbilled and then cannot be escalated.

    PRD 3.7: "A `RebateAnalyst` opens the demand, moving the batch
    `AUDIT_OVERBILLED → RECOVERY_REQUESTED` and incrementing the batch's `version`
    by 1; the batch's distributor must have `status` of `ACTIVE` for a demand to
    be opened, an already-suspended distributor drawing
    `ERR_DISTRIBUTOR_SUSPENDED`."
    PRD 3.7: "The line's `overbilled_cents` is that per-case excess multiplied by
    the line's `cases_shipped`."

    Design: Corner/errors/suspended_distributor_cannot_open_a_new_batch_or_countersign
    """
    ctx = _written_off_setup()

    audited = validate_success(api_client.audit_markup(ctx["b2_id"], ANALYST), 200)
    assert_purchase_batch(audited)
    assert audited["overbilled_cents"] == 100, "10 cents of excess over 10 cases"
    assert audited["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert fx.read_line(ctx["line_b2_id"])["overbilled_cents"] == 100
    version_after_audit = audited["version"]

    response = api_client.request_recovery(ctx["b2_id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409)

    batch = fx.read_batch(ctx["b2_id"])
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert batch["version"] == version_after_audit, "a refused demand bumps nothing"
    assert batch["recovered_cents"] == 0


def test_a_line_still_lands_in_a_feed_the_suspended_distributor_already_opened():
    """Suspension blocks only the three declared write paths: an invoice line still
    lands in the May batch that was already RECEIVED, and no member is credited.

    PRD 3.1: "The only path to `SUSPENDED` is a written-off recovery settlement,
    described in §3.7; a `SUSPENDED` distributor may neither open new purchase
    feeds nor countersign letters."
    PRD 3.3: "Its arrival increments the batch's `line_count` by 1 and adds the
    line's `cases_shipped` to both `total_cases_ingested` and `unmatched_cases`."

    Design: Corner/errors/suspended_distributor_cannot_open_a_new_batch_or_countersign
    """
    ctx = _written_off_setup()

    payload = F.purchase_line_payload(
        ctx["b3_id"],
        ctx["member_id"],
        cases_shipped=4,
        invoice_date="2026-05-12",
    )
    line = validate_success(api_client.create_purchase_line(payload, ctx["feed"]), 201)
    assert_purchase_line(line)
    assert line["cases_shipped"] == 4
    assert line["match_status"] == MatchStatus.UNMATCHED.value

    batch = fx.read_batch(ctx["b3_id"])
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["line_count"] == 1
    assert batch["total_cases_ingested"] == 4
    assert batch["unmatched_cases"] == 4
    assert batch["matched_cases"] == 0

    assert fx.read_member(ctx["member_id"])["recovery_credit_cents"] == 0, (
        "no member is credited by a write-off"
    )


# ==========================================================================
# instance: dispute_amount_outside_the_member_share_and_a_second_open_dispute
# ==========================================================================

GROSS_30_CASES = 4500
ADMIN_FEE_30_CASES = 135
NET_30_CASES = 4365
MEMBER_SHARE_30_CASES = 3274
RETENTION_30_CASES = 1091


def _accrued_single_line() -> dict:
    """One 30-case June line accrued on the flat 150-cents-per-case program.

    The whole instance turns on the accrual's member share, so the five-step
    waterfall is pinned here before any dispute is filed.
    """
    fx.set_clock(CLOCK_0900)
    ctx = fx.setup_flat_program()
    fx.ingest_june_feed(ctx, second_line=False)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)

    accrual = ctx["accrual_a"]
    assert_accrual(accrual)
    assert_split(
        accrual,
        GROSS_30_CASES,
        C.ELITE_TIER["admin_fee_bps_low"],
        ADMIN_FEE_30_CASES,
        NET_30_CASES,
        MEMBER_SHARE_30_CASES,
        RETENTION_30_CASES,
    )
    assert accrual["status"] == AccrualStatus.ACCRUED.value
    assert accrual["accrued_cases"] == C.LINE_A_CASES
    ctx["accrual_id"] = accrual["id"]
    return ctx


def _dispute_body(accrual_id: str, reason_code: str, amount: int) -> dict:
    return F.dispute_payload(accrual_id, amount, reason_code)


def test_a_dispute_one_cent_above_the_member_share_is_rejected():
    """The upper bound is the accrual's member share (3274), not its gross rebate
    (4500), so 3275 is refused with 422 ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE.

    PRD 3.6: "That amount must be at least 1 cent and must not exceed the cited
    accrual's `member_share_cents`; anything outside that range is rejected with
    `ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE`, since a member cannot claim to have been
    short-paid more than it was owed in the first place."

    Design: Corner/errors/dispute_amount_outside_the_member_share_and_a_second_open_dispute_are_rejected
    """
    ctx = _accrued_single_line()

    body = _dispute_body(
        ctx["accrual_id"], DisputeReasonCode.RATE_MISMATCH.value, MEMBER_SHARE_30_CASES + 1
    )
    response = api_client.create_dispute(body, ctx["member_headers"])
    validate_error(response, ApiErrorId.ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE, 422)
    assert_error_meta_is_minimal(response)

    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.ACCRUED.value
    _, meta = validate_paginated(api_client.list_disputes(ARBITER, dict(WIDE)))
    assert meta["total_count"] == 0, "a rejected filing stores no dispute"


def test_a_zero_cent_dispute_reports_the_same_amount_error_id():
    """The same rule carries the >= 1 lower bound, so a zero-cent grievance is
    ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE too — never a generic ERR_INVALID_REQUEST.

    PRD 3.6: "That amount must be at least 1 cent and must not exceed the cited
    accrual's `member_share_cents`; anything outside that range is rejected with
    `ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE`"
    PRD 2.7 rung 40: "A disputed amount lies within the accrual's member share —
    otherwise `ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE`."

    Design: Corner/errors/dispute_amount_outside_the_member_share_and_a_second_open_dispute_are_rejected
    """
    ctx = _accrued_single_line()

    body = _dispute_body(ctx["accrual_id"], DisputeReasonCode.RATE_MISMATCH.value, 0)
    response = api_client.create_dispute(body, ctx["member_headers"])
    validate_error(response, ApiErrorId.ERR_DISPUTE_AMOUNT_EXCEEDS_SHARE, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.ACCRUED.value


def test_the_member_share_itself_is_accepted_and_then_blocks_a_second_filing():
    """Exactly member_share_cents is inside the range, and the accepted dispute
    immediately blocks a second filing on the same accrual with 409
    ERR_DUPLICATE_OPEN_DISPUTE.

    PRD 3.6: "A successful filing stores the dispute with `status` of `OPEN`, an
    `evidence_round_count` of 0, `opened_by_user_id` set to the caller's
    `X-User-ID`, and both `decided_by_user_id` and `decision_note` null."
    PRD 3.6: "no other dispute on the same accrual may still be live, a second
    concurrent filing being rejected with `ERR_DUPLICATE_OPEN_DISPUTE` when an
    existing dispute on that accrual has `status` of `OPEN` or
    `EVIDENCE_REQUESTED`"

    Design: Corner/errors/dispute_amount_outside_the_member_share_and_a_second_open_dispute_are_rejected
    """
    ctx = _accrued_single_line()

    body = _dispute_body(
        ctx["accrual_id"], DisputeReasonCode.RATE_MISMATCH.value, MEMBER_SHARE_30_CASES
    )
    dispute = validate_success(api_client.create_dispute(body, ctx["member_headers"]), 201)
    assert_dispute(dispute)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["disputed_amount_cents"] == MEMBER_SHARE_30_CASES
    assert dispute["evidence_round_count"] == 0
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert dispute["decided_by_user_id"] is None
    assert dispute["decision_note"] is None
    assert dispute["claim_id"] is None
    assert dispute["accrual_status_before"] == AccrualStatus.ACCRUED.value
    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.DISPUTED.value

    second = _dispute_body(ctx["accrual_id"], DisputeReasonCode.UNITS_MISMATCH.value, 100)
    response = api_client.create_dispute(second, ctx["member_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OPEN_DISPUTE, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_STATE

    _, meta = validate_paginated(api_client.list_disputes(ARBITER, dict(WIDE)))
    assert meta["total_count"] == 1


def test_a_dispute_awaiting_evidence_blocks_a_second_filing_exactly_as_an_open_one():
    """EVIDENCE_REQUESTED is still live, so the duplicate gate covers two statuses,
    and answering the request returns the dispute to OPEN with one round counted.

    PRD 3.6: "A `DisputeArbiter` may send an `OPEN` dispute back for support,
    moving it `OPEN → EVIDENCE_REQUESTED` while the cited accrual stays `DISPUTED`
    throughout."
    PRD 3.6: "The member then answers with an `evidence_note` describing what it
    is supplying, which moves the dispute `EVIDENCE_REQUESTED → OPEN` and
    increments `evidence_round_count` by 1."

    Design: Corner/errors/dispute_amount_outside_the_member_share_and_a_second_open_dispute_are_rejected
    """
    ctx = _accrued_single_line()
    d1 = fx.open_dispute(
        ctx["accrual_id"],
        ctx["member_id"],
        MEMBER_SHARE_30_CASES,
        DisputeReasonCode.RATE_MISMATCH.value,
    )

    awaiting = fx.request_evidence(d1["id"])
    assert awaiting["status"] == DisputeStatus.EVIDENCE_REQUESTED.value
    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.DISPUTED.value

    second = _dispute_body(ctx["accrual_id"], DisputeReasonCode.UNITS_MISMATCH.value, 100)
    response = api_client.create_dispute(second, ctx["member_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OPEN_DISPUTE, 409)

    answered = fx.submit_evidence(
        d1["id"],
        ctx["member_id"],
        "Invoice 88213 shows 30 cases at the contracted rate.",
    )
    assert answered["status"] == DisputeStatus.OPEN.value
    assert answered["evidence_round_count"] == 1


def test_only_a_rejected_dispute_releases_the_accrual_for_a_fresh_filing():
    """A REJECT restores the accrual to its captured accrual_status_before, moves no
    money at all, and is terminal — which is what lets a second dispute open.

    PRD 3.6: "A `REJECT` decision is a pure state restore. The dispute moves
    `OPEN → REJECTED` and the accrual returns from `DISPUTED` to exactly the status
    recorded in `accrual_status_before`"
    PRD 3.6: "Not one money field and not one counter anywhere in the system
    changes."

    Design: Corner/errors/dispute_amount_outside_the_member_share_and_a_second_open_dispute_are_rejected
    """
    ctx = _accrued_single_line()
    d1 = fx.open_dispute(
        ctx["accrual_id"],
        ctx["member_id"],
        MEMBER_SHARE_30_CASES,
        DisputeReasonCode.RATE_MISMATCH.value,
    )
    fx.request_evidence(d1["id"])
    fx.submit_evidence(d1["id"], ctx["member_id"])

    decided = fx.decide_dispute(
        d1["id"],
        DisputeDecision.REJECT.value,
        "Rate card 150/case was applied correctly.",
    )
    assert decided["status"] == DisputeStatus.REJECTED.value
    assert decided["decided_by_user_id"] == ARBITER_1

    accrual = fx.read_accrual(ctx["accrual_id"])
    assert accrual["status"] == AccrualStatus.ACCRUED.value
    assert accrual["reversal_reason"] == "NONE"
    assert_split(
        accrual,
        GROSS_30_CASES,
        C.ELITE_TIER["admin_fee_bps_low"],
        ADMIN_FEE_30_CASES,
        NET_30_CASES,
        MEMBER_SHARE_30_CASES,
        RETENTION_30_CASES,
    )

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(
        member, MEMBER_SHARE_30_CASES, RETENTION_30_CASES, ADMIN_FEE_30_CASES
    )
    assert member["dispute_reversal_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False

    d2 = fx.open_dispute(
        ctx["accrual_id"], ctx["member_id"], 1, DisputeReasonCode.TIER_MISMATCH.value
    )
    assert d2["status"] == DisputeStatus.OPEN.value
    assert d2["accrual_status_before"] == AccrualStatus.ACCRUED.value
    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.DISPUTED.value

    query = dict(WIDE)
    query["accrual_id"] = ctx["accrual_id"]
    rows, meta = validate_paginated(api_client.list_disputes(ARBITER, query))
    assert meta["total_count"] == 2
    open_ids = [row["id"] for row in rows if row["status"] == DisputeStatus.OPEN.value]
    assert open_ids == [d2["id"]], "the rejected dispute is terminal"


# ==========================================================================
# instance: reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
# ==========================================================================

JUNE_FIRST_HALF_END = "2026-06-15"
JUNE_SECOND_HALF_START = "2026-06-16"
JUNE_A_REFERENCE = "METRO-2026-06A"
JUNE_B_REFERENCE = "METRO-2026-06B"

GROSS_40_CASES = 6000
ADMIN_FEE_40_CASES = 180
NET_40_CASES = 5820
MEMBER_SHARE_40_CASES = 4365
RETENTION_40_CASES = 1455

CLAIMED_UNITS = 70
CLAIMED_AMOUNT_CENTS = 10500


def _period_with_one_unaccrued_batch() -> dict:
    """Two half-June feeds: 06A is ACCRUED, 06B is left NORMALIZED, and one claim
    for the whole of June is SUBMITTED."""
    fx.set_clock(CLOCK_0900)
    ctx = fx.setup_flat_program()
    distributor_id = ctx["distributor_id"]

    b1 = fx.create_batch(
        distributor_id,
        period_start=C.JUNE_START,
        period_end=JUNE_FIRST_HALF_END,
        source_reference=JUNE_A_REFERENCE,
    )
    line_a = fx.create_line(b1["id"], ctx["member_id"], distributor_id)
    fx.normalize(b1["id"])
    b1 = fx.accrue(b1["id"])
    assert b1["normalization_status"] == NormalizationStatus.ACCRUED.value

    b2 = fx.create_batch(
        distributor_id,
        period_start=JUNE_SECOND_HALF_START,
        period_end=C.JUNE_END,
        source_reference=JUNE_B_REFERENCE,
    )
    line_b = fx.create_line(
        b2["id"],
        ctx["member_id"],
        distributor_id,
        cases_shipped=C.LINE_B_CASES,
        distributor_base_cost_cents=C.LINE_B_BASE_COST_CENTS,
        invoice_date="2026-06-22",
    )
    b2 = fx.normalize(b2["id"])
    assert b2["normalization_status"] == NormalizationStatus.NORMALIZED.value

    claim = fx.create_claim(ctx["deal_id"], CLAIMED_UNITS, CLAIMED_AMOUNT_CENTS)
    assert claim["status"] == ClaimStatus.SUBMITTED.value
    assert claim["accrued_amount_cents"] == 0
    assert claim["variance_bps"] == 0
    assert claim["reconciled_at"] is None

    ctx["b1_id"] = b1["id"]
    ctx["b2_id"] = b2["id"]
    ctx["line_a_id"] = line_a["id"]
    ctx["line_b_id"] = line_b["id"]
    ctx["claim_id"] = claim["id"]
    ctx["claim"] = claim
    return ctx


def test_reconcile_refuses_a_claim_whose_period_overlaps_a_normalized_batch():
    """The gate is scoped by period overlap, not by which batch fed the accruals:
    06B is a different batch, still NORMALIZED, and it blocks the reconciliation.

    PRD 3.5: "The comparison is only meaningful once the underlying purchase data
    has been processed, so reconciliation is rejected with
    `ERR_PERIOD_HAS_UNACCRUED_BATCHES` while any purchase batch whose own period
    overlaps the claim period still has `normalization_status` of `RECEIVED` or
    `NORMALIZED`."

    Design: Corner/errors/reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
    """
    ctx = _period_with_one_unaccrued_batch()

    response = api_client.reconcile_claim(ctx["claim_id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_PERIOD_HAS_UNACCRUED_BATCHES, 409)
    assert_error_meta_is_minimal(response)

    claim = fx.read_claim(ctx["claim_id"])
    assert claim["status"] == ClaimStatus.SUBMITTED.value
    assert claim["accrued_amount_cents"] == 0, "the comparison never ran"
    assert claim["variance_bps"] == 0
    assert claim["reconciled_at"] is None
    assert claim["version"] == ctx["claim"]["version"]


def test_close_period_refuses_the_same_period_with_the_same_error_id():
    """One gate guards two unrelated endpoints: the June close reports the very same
    ERR_PERIOD_HAS_UNACCRUED_BATCHES and leaves the deal's version alone.

    PRD 3.9: "The close is refused with `ERR_PERIOD_HAS_UNACCRUED_BATCHES` while
    any purchase batch whose own period overlaps the closing period still has
    `normalization_status` of `RECEIVED` or `NORMALIZED`, because rebasing against
    a partially processed period would produce figures that the next accrual run
    would immediately invalidate."

    Design: Corner/errors/reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
    """
    ctx = _period_with_one_unaccrued_batch()
    version_before = fx.read_deal(ctx["deal_id"])["version"]

    response = api_client.close_period(
        ctx["deal_id"],
        {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_PERIOD_HAS_UNACCRUED_BATCHES, 409)

    deal = fx.read_deal(ctx["deal_id"])
    assert_deal(deal)
    assert deal["version"] == version_before, "a refused close increments nothing"
    assert deal["status"] == DealStatus.ACTIVE.value


def test_accruing_the_second_batch_unblocks_the_reconciliation_in_one_step():
    """The already-ACCRUED 06A was never an obstacle: accruing 06B alone clears the
    gate, and the claim then reconciles at zero variance.

    PRD 3.5: "`accrued_amount_cents` is the sum of `gross_rebate_cents` over every
    accrual whose rate card belongs to a contracted item of the claim's deal and
    whose purchase line's `invoice_date` falls inside the claim's inclusive
    period, counting only accruals whose `status` is `ACCRUED`, `VALIDATED`,
    `FLAGGED` or `PAID`."
    PRD 3.5: "When `variance_bps` is at or below 200, the claim moves
    `SUBMITTED → RECONCILED` and `reconciled_at` is stamped with the current
    logical-clock instant."

    Design: Corner/errors/reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
    """
    ctx = _period_with_one_unaccrued_batch()

    accrued_batch = validate_success(api_client.accrue_batch(ctx["b2_id"], ANALYST), 200)
    assert accrued_batch["normalization_status"] == NormalizationStatus.ACCRUED.value

    accrual_b = fx.accrual_for_line(ctx["line_b_id"])
    assert_split(
        accrual_b,
        GROSS_40_CASES,
        C.ELITE_TIER["admin_fee_bps_low"],
        ADMIN_FEE_40_CASES,
        NET_40_CASES,
        MEMBER_SHARE_40_CASES,
        RETENTION_40_CASES,
    )
    assert accrual_b["accrued_cases"] == C.LINE_B_CASES

    claim = validate_success(api_client.reconcile_claim(ctx["claim_id"], ANALYST), 200)
    assert claim["status"] == ClaimStatus.RECONCILED.value
    assert claim["accrued_amount_cents"] == CLAIMED_AMOUNT_CENTS, "4500 + 6000"
    assert claim["variance_bps"] == 0
    assert_instants_equal(claim["reconciled_at"], CLOCK_0900)


def test_the_unblocked_close_rebases_both_accruals_and_pays_nothing():
    """With both June feeds ACCRUED the close proceeds: a flat PER_CASE rate has no
    ladder to rebase, so both accruals take BLENDED_PERIOD at a zero adjustment,
    neither is paid, and the member's fee snapshot is refrozen at the period net.

    PRD 3.9: "`gross_rebate_cents` becomes the blended figure,
    `final_adjustment_cents` becomes the new gross minus the old gross — a signed
    delta that is positive when combining batches lifted the member into a better
    tier and negative in the rarer case where it did not — and `basis` becomes
    `BLENDED_PERIOD`."
    PRD 3.9: "Each affected member's `ytd_net_snapshot_cents` is rewritten to that
    member's post-close attributed net total, namely its
    `accrued_member_share_cents` plus its `attributed_gpo_retention_cents` as
    those counters stand once every rebasing delta has been applied."

    Design: Corner/errors/reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
    """
    ctx = _period_with_one_unaccrued_batch()
    fx.accrue(ctx["b2_id"])
    version_before = fx.read_deal(ctx["deal_id"])["version"]

    deal = validate_success(
        api_client.close_period(
            ctx["deal_id"],
            {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
            ADMIN,
        ),
        200,
    )
    assert_deal(deal)
    assert deal["version"] == version_before + 1
    assert deal["status"] == DealStatus.ACTIVE.value

    for line_id, gross in (
        (ctx["line_a_id"], GROSS_30_CASES),
        (ctx["line_b_id"], GROSS_40_CASES),
    ):
        accrual = fx.accrual_for_line(line_id)
        assert accrual["basis"] == AccrualBasis.BLENDED_PERIOD.value
        assert accrual["final_adjustment_cents"] == 0, "a flat rate has no ladder"
        assert accrual["gross_rebate_cents"] == gross
        assert accrual["status"] == AccrualStatus.ACCRUED.value, (
            "the close pays only VALIDATED accruals"
        )

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(
        member,
        MEMBER_SHARE_30_CASES + MEMBER_SHARE_40_CASES,
        RETENTION_30_CASES + RETENTION_40_CASES,
        ADMIN_FEE_30_CASES + ADMIN_FEE_40_CASES,
    )
    assert member["ytd_net_snapshot_cents"] == 10185, "7639 share + 2546 retention"


def test_a_july_batch_left_received_does_not_reblock_a_second_june_close():
    """The overlap test is against the requested period only, so an untouched July
    feed is irrelevant to closing June a second time.

    PRD 3.9: "The close is refused with `ERR_PERIOD_HAS_UNACCRUED_BATCHES` while
    any purchase batch whose own period overlaps the closing period still has
    `normalization_status` of `RECEIVED` or `NORMALIZED`"

    Design: Corner/errors/reconcile_and_close_period_both_refuse_a_period_with_unaccrued_batches
    """
    ctx = _period_with_one_unaccrued_batch()
    fx.accrue(ctx["b2_id"])
    fx.close_period(ctx["deal_id"], C.JUNE_START, C.JUNE_END)

    july = fx.create_july_batch(ctx["distributor_id"])
    assert july["normalization_status"] == NormalizationStatus.RECEIVED.value
    version_before = fx.read_deal(ctx["deal_id"])["version"]

    deal = validate_success(
        api_client.close_period(
            ctx["deal_id"],
            {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
            ADMIN,
        ),
        200,
    )
    assert deal["version"] == version_before + 1

    reclosed = fx.accrual_for_line(ctx["line_a_id"])
    assert reclosed["basis"] == AccrualBasis.BLENDED_PERIOD.value
    assert reclosed["gross_rebate_cents"] == GROSS_30_CASES
    assert reclosed["final_adjustment_cents"] == 0
