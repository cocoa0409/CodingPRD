"""Cross-entity state dependencies and per-resource temporal windows.

Two families of rule live here, and they are deliberately adjacent because each
one is easy to implement in a way that quietly breaks the other:

  * cross_entity_state_dependency — the entity under change reads the *state of
    a third entity* that its own payload never names: a purchase line reads the
    (member, distributor) authorization letter, and an accrual's own transition
    reads the manufacturer claim it cites.
  * resource_temporal_overlap — two windowed resources with *opposite* interval
    semantics: an authorization letter's window is half-open, so touching
    windows coexist, while a rate card's window is closed, so windows touching
    on a single calendar date collide.

Every precondition is built through the API: the database is empty before each
test and no state is shared between tests.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_1,
    AccrualStatus,
    ApiErrorId,
    ClaimStatus,
    LetterScope,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    api_client,
    assert_accrual,
    assert_authorization_letter,
    assert_contracted_item,
    assert_instants_equal,
    assert_member,
    assert_purchase_batch,
    assert_purchase_line,
    assert_rate_card,
    assert_split,
    make_analyst_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers()

# --------------------------------------------------------------- literals ----
# Instance literals, copied from the design and re-derived from the PRD.

# cross_entity_state_dependency / purchase_line_create_depends_on_third_party_letter_state
FIRST_LINE_CASES = C.LINE_A_CASES            # 30, ingested while the letter was ACTIVE
SECOND_LINE_CASES = C.LINE_B_CASES           # 40, attempted after the revoke

# cross_entity_state_dependency / accrual_validation_depends_on_claim_reconciliation_state
JUNE_CLAIMED_UNITS = 70                      # 30 + 40 cases
JUNE_ACCRUED_CENTS = 10500                   # 4500 + 6000 gross
CLAIM_V1_AMOUNT_CENTS = 12000
CLAIM_V1_VARIANCE_BPS = 1428                 # floor(1500 * 10000 / 10500)
CLAIM_V2_AMOUNT_CENTS = 10500
ACCRUAL_A_GROSS_CENTS = 4500                 # 30 cases * 150 cents
ACCRUAL_A_ADMIN_FEE_BPS = 300                # ytd_net_snapshot_cents 0 < 5_000_000
ACCRUAL_A_ADMIN_FEE_CENTS = 135
ACCRUAL_A_NET_CENTS = 4365
ACCRUAL_A_MEMBER_SHARE_CENTS = 3274          # round_half_up(4365 * 7500 / 10000)
ACCRUAL_A_RETENTION_CENTS = 1091             # residual: 4365 - 3274
MEMBER_SHARE_TOTAL_CENTS = 7639              # 3274 + 4365

# resource_temporal_overlap / letter_windows_half_open_touching_allowed_overlap_rejected
L1_FROM = "2026-01-01T00:00:00.000Z"
L1_TO = "2027-01-01T00:00:00.000Z"
L2_FROM = "2027-01-01T00:00:00.000Z"         # touches L1's exclusive end
L2_TO = "2028-01-01T00:00:00.000Z"
OVERLAP_FROM = "2026-12-31T23:59:59.999Z"    # one millisecond earlier
OVERLAP_TO = "2028-01-01T00:00:00.000Z"
L3_FROM = "2028-01-01T00:00:00.000Z"         # touches L2's exclusive end
L3_TO = "2029-01-01T00:00:00.000Z"
INSIDE_L2_FROM = "2027-06-01T00:00:00.000Z"  # overlaps the SUBMITTED L2 only
INSIDE_L2_TO = "2027-12-01T00:00:00.000Z"

# resource_temporal_overlap / rate_card_windows_closed_interval_touching_date_rejected
C1_FROM = "2026-01-01"
C1_TO = "2026-06-30"
TOUCHING_FROM = "2026-06-30"                 # the single shared calendar date
TOUCHING_TO = "2026-12-31"
NEXT_DAY_FROM = "2026-07-01"
NEXT_DAY_TO = "2026-12-31"
INSIDE_C1_FROM = "2026-06-01"
INSIDE_C1_TO = "2026-06-15"
TRUNCATED_C1_TO = "2026-05-31"               # INSIDE_C1_FROM minus one day
SECOND_CARD_RATE_CENTS = 180


# ============================================================== helpers ======
# Local composites the shared fixtures do not provide. Each performs one phase
# and returns, so a test can interpose its own call between two phases.


def _authorized_june_feed() -> dict:
    """An ACTIVE member holding an ACTIVE PURCHASE_DATA_AND_PRICING letter for
    METRO-01, plus that distributor's June feed sitting at RECEIVED. No line has
    been ingested yet, so the caller owns the first ingest."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    batch = fx.create_batch(distributor["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "letter": letter,
        "batch": batch,
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "batch_id": batch["id"],
        "letter_id": letter["id"],
    }


def _ingest_line(ctx: dict, cases: int, base_cost_cents: int, invoice_date: str):
    """Attempt one more line on the context's feed, returning the raw response."""
    return api_client.create_purchase_line(
        F.purchase_line_payload(
            ctx["batch_id"],
            ctx["member_id"],
            cases_shipped=cases,
            distributor_base_cost_cents=base_cost_cents,
            invoice_date=invoice_date,
        ),
        make_distributor_feed_headers(ctx["distributor_id"]),
    )


def _letter_slot_with_active_incumbent() -> dict:
    """A (member, distributor) authorization slot holding one ACTIVE letter for
    [2026-01-01, 2027-01-01). The member stays PENDING: the overlap rule does
    not read enrollment_status."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(
        member["id"], distributor["id"], effective_from=L1_FROM, effective_to=L1_TO
    )
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "letter_1": letter,
        "member_id": member["id"],
        "distributor_id": distributor["id"],
    }


def _submit_letter_window(ctx: dict, effective_from: str, effective_to: str,
                          scope: str = LetterScope.PURCHASE_DATA_ONLY.value):
    """Submit one more letter on the context's slot, returning the raw response."""
    return api_client.create_authorization_letter(
        F.authorization_letter_payload(
            ctx["member_id"],
            ctx["distributor_id"],
            effective_from=effective_from,
            effective_to=effective_to,
            scope=scope,
        ),
        make_member_operator_headers(ctx["member_id"]),
    )


def _item_with_approved_first_half_card() -> dict:
    """A DRAFT deal whose beef item carries one APPROVED card for
    2026-01-01..2026-06-30, plus the item's freshly re-read version."""
    fx.create_tier()
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card_1 = fx.create_card(item["id"], effective_from=C1_FROM, effective_to=C1_TO)
    card_1 = fx.approve_card(card_1["id"])
    item = fx.read_item(item["id"])
    return {
        "deal": deal,
        "item": item,
        "card_1": card_1,
        "deal_id": deal["id"],
        "item_id": item["id"],
        "item_version": item["version"],
    }


def _propose_card_window(ctx: dict, effective_from: str, effective_to: str,
                         expected_version: int, supersede=None):
    """Propose one more PER_CASE card on the context's item, returning the raw
    response. The OCC token is passed explicitly so a test can prove that a
    rejected attempt did not consume it."""
    overrides = {
        "effective_from": effective_from,
        "effective_to": effective_to,
        "flat_rate_cents_per_case": SECOND_CARD_RATE_CENTS,
    }
    if supersede is not None:
        overrides["supersede"] = supersede
    return api_client.create_rate_card(
        F.flat_rate_card_payload(ctx["item_id"], expected_version, **overrides), ADMIN
    )


# ============================================================================
# cross_entity_state_dependency
#   purchase_line_create_depends_on_third_party_letter_state
# ============================================================================


def test_line_ingested_while_letter_active_is_untouched_by_the_later_revoke():
    """A 30-case line accepted while the letter was ACTIVE stays exactly as it
    was ingested after the letter is revoked: the revocation moves the letter and
    the two active_letter_count figures, and nothing else.

    PRD 3.1: "A `MemberOperator` or a `GpoAdmin` may withdraw an authorization,
    moving it `ACTIVE → REVOKED` and decrementing both `active_letter_count`
    figures by 1."

    Design: Difficulty/cross_entity_state_dependency/purchase_line_create_depends_on_third_party_letter_state
    """
    ctx = _authorized_june_feed()

    ingested = validate_success(
        _ingest_line(
            ctx, FIRST_LINE_CASES, C.LINE_A_BASE_COST_CENTS, C.LINE_A_INVOICE_DATE
        ),
        201,
    )
    assert_purchase_line(ingested)
    assert ingested["cases_shipped"] == FIRST_LINE_CASES
    assert ingested["match_status"] == MatchStatus.UNMATCHED.value
    assert ingested["contracted_item_id"] is None
    assert ingested["accrual_block_reason"] == "NONE"

    batch_before = fx.read_batch(ctx["batch_id"])
    assert batch_before["line_count"] == 1
    assert batch_before["total_cases_ingested"] == FIRST_LINE_CASES
    assert batch_before["unmatched_cases"] == FIRST_LINE_CASES
    assert batch_before["normalization_status"] == NormalizationStatus.RECEIVED.value

    revoked = validate_success(
        api_client.revoke_letter(
            ctx["letter_id"], make_member_operator_headers(ctx["member_id"])
        ),
        200,
    )
    assert_authorization_letter(revoked)
    assert revoked["status"] == LetterStatus.REVOKED.value

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["active_letter_count"] == 0
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 0

    # Revocation is not retroactive: the already-ingested line did not move.
    after = fx.read_line(ingested["id"])
    for field in (
        "cases_shipped",
        "match_status",
        "contracted_item_id",
        "accrual_block_reason",
        "invoice_extended_cents",
        "overbilled_cents",
        "version",
        "updated_at",
    ):
        assert after[field] == ingested[field], f"{field} moved on the stored line"

    batch_after = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch_after)
    for field in ("line_count", "total_cases_ingested", "unmatched_cases",
                  "matched_cases", "normalization_status", "version"):
        assert batch_after[field] == batch_before[field], f"{field} moved on the batch"


def test_line_ingested_after_the_revoke_is_rejected_with_loa_not_active():
    """The next line on the same feed, with the same otherwise-legal shape, is
    rejected because a third entity the payload never names — the (member,
    distributor) letter — left ACTIVE. The batch counters do not move.

    PRD 3.3: "the member must hold at least one authorization letter whose
    `status` is `ACTIVE`, whose `distributor_id` is the batch's distributor, and
    whose half-open window contains the current logical-clock instant, and a line
    lacking one is rejected with `ERR_LOA_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/purchase_line_create_depends_on_third_party_letter_state
    """
    ctx = _authorized_june_feed()

    first = validate_success(
        _ingest_line(
            ctx, FIRST_LINE_CASES, C.LINE_A_BASE_COST_CENTS, C.LINE_A_INVOICE_DATE
        ),
        201,
    )

    fx.revoke_letter(ctx["letter_id"], ctx["member_id"])
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 0

    rejected = _ingest_line(
        ctx, SECOND_LINE_CASES, C.LINE_B_BASE_COST_CENTS, C.LINE_B_INVOICE_DATE
    )
    # Not ERR_MEMBER_NOT_ENROLLED: the member is still ACTIVE and the batch is
    # still RECEIVED, so only the letter's state explains the rejection.
    validate_error(rejected, ApiErrorId.ERR_LOA_NOT_ACTIVE, 409)
    assert (
        fx.read_member(ctx["member_id"])["enrollment_status"]
        == MemberEnrollmentStatus.ACTIVE.value
    )

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["line_count"] == 1
    assert batch["total_cases_ingested"] == FIRST_LINE_CASES
    assert batch["unmatched_cases"] == FIRST_LINE_CASES
    assert batch["matched_cases"] == 0
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value

    rows, meta = validate_paginated(
        api_client.list_purchase_lines(ANALYST, {"limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 1, "the rejected ingest stored nothing"
    assert [row["id"] for row in rows] == [first["id"]]


# ============================================================================
# cross_entity_state_dependency
#   accrual_validation_depends_on_claim_reconciliation_state
# ============================================================================


def _june_accrued_with_flagged_claim() -> dict:
    """The canonical June accrual pair plus claim v1 (70 units / 12000 cents)
    reconciled into VARIANCE_FLAGGED at 1428 bps."""
    ctx = fx.setup_june_accrued()
    claim_v1 = fx.create_claim(ctx["deal_id"], JUNE_CLAIMED_UNITS, CLAIM_V1_AMOUNT_CENTS)
    ctx["claim_v1"] = fx.reconcile_claim(claim_v1["id"])
    return ctx


def _assert_accrual_a_money(accrual: dict):
    """The 30-case accrual's split, which validation may never rewrite."""
    assert_accrual(accrual)
    assert_split(
        accrual,
        ACCRUAL_A_GROSS_CENTS,
        ACCRUAL_A_ADMIN_FEE_BPS,
        ACCRUAL_A_ADMIN_FEE_CENTS,
        ACCRUAL_A_NET_CENTS,
        ACCRUAL_A_MEMBER_SHARE_CENTS,
        ACCRUAL_A_RETENTION_CENTS,
    )


def test_validate_is_blocked_while_the_cited_claim_is_variance_flagged():
    """The accrual is ACCRUED and its member is unheld, so the only thing barring
    validation is the state of the claim it cites — an entity the accrual does not
    own. Nothing on the accrual moves.

    PRD 3.5: "a cited claim whose `status` is `SUBMITTED`, `VARIANCE_FLAGGED` or
    `SUPERSEDED` rather than `RECONCILED` is refused with
    `ERR_CLAIM_NOT_RECONCILED`".

    Design: Difficulty/cross_entity_state_dependency/accrual_validation_depends_on_claim_reconciliation_state
    """
    ctx = _june_accrued_with_flagged_claim()

    claim_v1 = ctx["claim_v1"]
    assert claim_v1["accrued_amount_cents"] == JUNE_ACCRUED_CENTS
    assert claim_v1["variance_bps"] == CLAIM_V1_VARIANCE_BPS
    assert claim_v1["status"] == ClaimStatus.VARIANCE_FLAGGED.value
    assert claim_v1["reconciled_at"] is None

    accrual_before = fx.read_accrual(ctx["accrual_a"]["id"])
    _assert_accrual_a_money(accrual_before)
    assert accrual_before["status"] == AccrualStatus.ACCRUED.value

    blocked = api_client.validate_accrual(
        ctx["accrual_a"]["id"], {"claim_id": claim_v1["id"]}, ANALYST
    )
    validate_error(blocked, ApiErrorId.ERR_CLAIM_NOT_RECONCILED, 409)

    accrual_after = fx.read_accrual(ctx["accrual_a"]["id"])
    assert accrual_after["status"] == AccrualStatus.ACCRUED.value
    assert accrual_after["validated_by_user_id"] is None
    assert accrual_after["reversal_reason"] == "NONE"
    _assert_accrual_a_money(accrual_after)
    for field in ("gross_rebate_cents", "admin_fee_cents", "net_distributable_cents",
                  "member_share_cents", "gpo_retention_cents", "version"):
        assert accrual_after[field] == accrual_before[field], f"{field} moved"

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == MEMBER_SHARE_TOTAL_CENTS


def test_validate_succeeds_once_a_restated_claim_reconciles_the_period():
    """The identical validate call is refused and then accepted, with nothing
    changing on the accrual in between: claim v2 supersedes the flagged v1,
    reconciles at 0 bps, and only then does the gate open. Validation moves state
    only.

    PRD 3.5: "neither branch changes a single money field — validation is an
    assertion about agreement, not a correction."

    Design: Difficulty/cross_entity_state_dependency/accrual_validation_depends_on_claim_reconciliation_state
    """
    ctx = _june_accrued_with_flagged_claim()
    accrual_id = ctx["accrual_a"]["id"]
    claim_v1_id = ctx["claim_v1"]["id"]

    validate_error(
        api_client.validate_accrual(accrual_id, {"claim_id": claim_v1_id}, ANALYST),
        ApiErrorId.ERR_CLAIM_NOT_RECONCILED,
        409,
    )
    accrual_before = fx.read_accrual(accrual_id)
    _assert_accrual_a_money(accrual_before)

    # The restatement: same (deal, period), a claim of exactly the GPO's figure.
    claim_v2 = fx.create_claim(
        ctx["deal_id"], JUNE_CLAIMED_UNITS, CLAIM_V2_AMOUNT_CENTS,
        expected_deal_version=fx.deal_version(ctx["deal_id"]),
    )
    assert fx.read_claim(claim_v1_id)["status"] == ClaimStatus.SUPERSEDED.value

    claim_v2 = fx.reconcile_claim(claim_v2["id"])
    assert claim_v2["accrued_amount_cents"] == JUNE_ACCRUED_CENTS
    assert claim_v2["variance_bps"] == 0
    assert claim_v2["status"] == ClaimStatus.RECONCILED.value
    assert_instants_equal(claim_v2["reconciled_at"], C.CLOCK_EPOCH)

    validated = validate_success(
        api_client.validate_accrual(accrual_id, {"claim_id": claim_v2["id"]}, ANALYST),
        200,
    )
    assert validated["status"] == AccrualStatus.VALIDATED.value
    assert validated["validated_by_user_id"] == ANALYST_1

    # Money is identical before and after both attempts.
    _assert_accrual_a_money(validated)
    for field in ("gross_rebate_cents", "admin_fee_cents", "net_distributable_cents",
                  "member_share_cents", "gpo_retention_cents", "final_adjustment_cents"):
        assert validated[field] == accrual_before[field], f"{field} moved on validate"

    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == MEMBER_SHARE_TOTAL_CENTS


# ============================================================================
# resource_temporal_overlap
#   letter_windows_half_open_touching_allowed_overlap_rejected
# ============================================================================


def test_letter_window_touching_the_incumbent_end_instant_is_accepted():
    """The authorization slot is half-open, so a letter starting at the exact
    instant the ACTIVE letter ends is accepted — and it lands SUBMITTED, so the
    member's active_letter_count does not move.

    PRD 3.1: "Windows that merely touch, where one ends exactly where the next
    begins, do not overlap and are both accepted."

    Design: Difficulty/resource_temporal_overlap/letter_windows_half_open_touching_allowed_overlap_rejected
    """
    ctx = _letter_slot_with_active_incumbent()
    assert ctx["letter_1"]["status"] == LetterStatus.ACTIVE.value
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1

    letter_2 = validate_success(_submit_letter_window(ctx, L2_FROM, L2_TO), 201)
    assert_authorization_letter(letter_2)
    assert letter_2["status"] == LetterStatus.SUBMITTED.value
    assert_instants_equal(letter_2["effective_from"], L2_FROM)
    assert_instants_equal(letter_2["effective_to"], L2_TO)
    assert letter_2["countersigned_at"] is None

    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["active_letter_count"] == 1, (
        "a SUBMITTED letter does not increment the active counter"
    )
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1

    # Touching is allowed at every boundary, not just the first one.
    letter_3 = validate_success(_submit_letter_window(ctx, L3_FROM, L3_TO), 201)
    assert letter_3["status"] == LetterStatus.SUBMITTED.value
    assert_instants_equal(letter_3["effective_from"], L3_FROM)
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_authorization_letters(ADMIN, {"limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {
        ctx["letter_1"]["id"], letter_2["id"], letter_3["id"]
    }


def test_letter_window_one_millisecond_earlier_is_rejected_as_overlap():
    """One millisecond before the incumbent's exclusive end is an overlap, and the
    scope of the check spans SUBMITTED letters too, so the uncountersigned
    touching letter blocks a third window of its own.

    PRD 3.1: "a submission is rejected with `ERR_LOA_PERIOD_OVERLAP` when some
    existing letter for the same member and distributor whose `status` is
    `SUBMITTED` or `ACTIVE` overlaps the requested window under half-open
    semantics".

    Design: Difficulty/resource_temporal_overlap/letter_windows_half_open_touching_allowed_overlap_rejected
    """
    ctx = _letter_slot_with_active_incumbent()
    letter_2 = validate_success(_submit_letter_window(ctx, L2_FROM, L2_TO), 201)
    assert letter_2["status"] == LetterStatus.SUBMITTED.value

    validate_error(
        _submit_letter_window(ctx, OVERLAP_FROM, OVERLAP_TO),
        ApiErrorId.ERR_LOA_PERIOD_OVERLAP,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_authorization_letters(ADMIN, {"limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 2, "the rejected submission created nothing"
    assert {row["id"] for row in rows} == {ctx["letter_1"]["id"], letter_2["id"]}

    # A window that can only collide with the SUBMITTED letter is rejected too.
    validate_error(
        _submit_letter_window(ctx, INSIDE_L2_FROM, INSIDE_L2_TO),
        ApiErrorId.ERR_LOA_PERIOD_OVERLAP,
        409,
    )
    _, meta_again = validate_paginated(
        api_client.list_authorization_letters(ADMIN, {"limit": C.MAX_LIMIT})
    )
    assert meta_again["total_count"] == 2
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1


# ============================================================================
# resource_temporal_overlap
#   rate_card_windows_closed_interval_touching_date_rejected
# ============================================================================


def test_rate_card_touching_the_incumbent_end_date_is_rejected_without_bumping_the_item():
    """A rate card's range is closed at both ends, so a card starting on the
    incumbent's own end date collides — the opposite of the letter rule. The
    rejection is not a mutation, so the item's version does not move.

    PRD 3.2: "because both ends of a rate card's range are inclusive, two ranges
    that touch on a single calendar date **do** overlap and the later one is
    refused."

    Design: Difficulty/resource_temporal_overlap/rate_card_windows_closed_interval_touching_date_rejected
    """
    ctx = _item_with_approved_first_half_card()
    item_version = ctx["item_version"]
    assert ctx["card_1"]["status"] == RateCardStatus.APPROVED.value
    assert ctx["item"]["approved_rate_card_count"] == 1

    validate_error(
        _propose_card_window(ctx, TOUCHING_FROM, TOUCHING_TO, item_version),
        ApiErrorId.ERR_RATE_CARD_PERIOD_OVERLAP,
        409,
    )
    item = fx.read_item(ctx["item_id"])
    assert_contracted_item(item)
    assert item["version"] == item_version, "a rejected proposal is not a mutation"
    assert item["approved_rate_card_count"] == 1

    # A window entirely inside the incumbent's range collides for the same reason.
    validate_error(
        _propose_card_window(ctx, INSIDE_C1_FROM, INSIDE_C1_TO, item_version),
        ApiErrorId.ERR_RATE_CARD_PERIOD_OVERLAP,
        409,
    )
    assert fx.read_item(ctx["item_id"])["version"] == item_version

    rows, meta = validate_paginated(api_client.list_rate_cards(ADMIN, {"limit": C.MAX_LIMIT}))
    assert meta["total_count"] == 1, "neither rejected proposal stored a card"
    assert rows[0]["id"] == ctx["card_1"]["id"]
    assert rows[0]["status"] == RateCardStatus.APPROVED.value
    assert rows[0]["effective_to"] == C1_TO


def test_rate_card_next_day_window_is_accepted_and_bumps_the_item_version_once():
    """The day after the incumbent's end date does not collide, and the same OCC
    token the rejected attempt carried is still live — proof the rejection did not
    advance the parent. The accepted create advances it by exactly one.

    PRD 3.2: "the owning contracted item's `version` is incremented by exactly 1
    for the call as a whole".

    Design: Difficulty/resource_temporal_overlap/rate_card_windows_closed_interval_touching_date_rejected
    """
    ctx = _item_with_approved_first_half_card()
    item_version = ctx["item_version"]

    validate_error(
        _propose_card_window(ctx, TOUCHING_FROM, TOUCHING_TO, item_version),
        ApiErrorId.ERR_RATE_CARD_PERIOD_OVERLAP,
        409,
    )

    # The very next call reuses the identical expected_contracted_item_version.
    card_2 = validate_success(
        _propose_card_window(ctx, NEXT_DAY_FROM, NEXT_DAY_TO, item_version), 201
    )
    assert_rate_card(card_2)
    assert card_2["status"] == RateCardStatus.PROPOSED.value
    assert card_2["effective_from"] == NEXT_DAY_FROM
    assert card_2["effective_to"] == NEXT_DAY_TO
    assert card_2["supersedes_rate_card_id"] is None
    assert card_2["pinned_item_version"] is None

    item = fx.read_item(ctx["item_id"])
    assert item["version"] == item_version + 1
    assert item["approved_rate_card_count"] == 1, "a PROPOSED card is not counted"

    rows, meta = validate_paginated(api_client.list_rate_cards(ADMIN, {"limit": C.MAX_LIMIT}))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {ctx["card_1"]["id"], card_2["id"]}
    incumbent = validate_success(api_client.get_rate_card(ctx["card_1"]["id"], ADMIN), 200)
    assert incumbent["status"] == RateCardStatus.APPROVED.value
    assert incumbent["effective_to"] == C1_TO


def test_rate_card_supersede_true_skips_the_overlap_rule_and_truncates_the_incumbent():
    """The identical colliding window is refused without supersede and accepted
    with it: supersede routes past the overlap rule to the incumbent rule, which
    finds exactly one qualifying APPROVED card and truncates it.

    PRD 3.2: "the incumbent's `effective_to` is rewritten to the new card's
    `effective_from` minus one calendar day, the incumbent moves `APPROVED →
    SUPERSEDED`, the new card's `supersedes_rate_card_id` is set to the
    incumbent's `id`, and the item's `approved_rate_card_count` is decremented by
    1."

    Design: Difficulty/resource_temporal_overlap/rate_card_windows_closed_interval_touching_date_rejected
    """
    ctx = _item_with_approved_first_half_card()
    item_version = ctx["item_version"]

    validate_error(
        _propose_card_window(ctx, INSIDE_C1_FROM, INSIDE_C1_TO, item_version),
        ApiErrorId.ERR_RATE_CARD_PERIOD_OVERLAP,
        409,
    )

    superseding = validate_success(
        _propose_card_window(
            ctx, INSIDE_C1_FROM, INSIDE_C1_TO, item_version, supersede=True
        ),
        201,
    )
    assert_rate_card(superseding)
    assert superseding["status"] == RateCardStatus.PROPOSED.value
    assert superseding["effective_from"] == INSIDE_C1_FROM
    assert superseding["supersedes_rate_card_id"] == ctx["card_1"]["id"]

    incumbent = validate_success(api_client.get_rate_card(ctx["card_1"]["id"], ADMIN), 200)
    assert incumbent["status"] == RateCardStatus.SUPERSEDED.value
    assert incumbent["effective_to"] == TRUNCATED_C1_TO

    item = fx.read_item(ctx["item_id"])
    assert item["approved_rate_card_count"] == 0
    assert item["version"] == item_version + 1, (
        "once per call, not once per card touched"
    )
