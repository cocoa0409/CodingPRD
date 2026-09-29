"""Cross-cutting complexity layers: the two OCC parents and the posture threshold.

Three design instances live here. Two of them exercise §2.8 optimistic
concurrency on a parent record: the `ContractedItem` behind a rate card and the
`ManufacturerDeal` behind a manufacturer claim. Each parent's version moves for
more than one reason, so a token read once and reused is stale, a refused 412
must leave the parent's version and the child collection untouched, and a retry
with the freshly read version must succeed. The third instance pins the
cumulative reversal threshold: on a tier whose `reversal_posture_limit` defaults
to 2, the first upheld dispute leaves the member CLEAR and only the second flips
it to RESTRICTED, holds its payouts and flags its ACCRUED batches.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_1,
    ARBITER_1,
    REP_1,
    AccrualStatus,
    ApiErrorId,
    ComplianceResult,
    DealStatus,
    DisputeDecision,
    DisputeReasonCode,
    DisputeStatus,
    MemberEnrollmentStatus,
    RateCardStatus,
    RateType,
    ReconciliationPosture,
    ReversalReason,
    api_client,
    assert_accrual,
    assert_claim,
    assert_compliance_review,
    assert_contracted_item,
    assert_member,
    assert_member_ledger,
    assert_purchase_batch,
    assert_rate_card,
    assert_split,
    make_arbiter_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
    make_rep_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

ADMIN = make_gpo_admin_headers()
ARBITER = make_arbiter_headers(ARBITER_1)
REP = make_rep_headers(REP_1)

WIDE = {"limit": C.MAX_LIMIT}

# ----------------------------------------------- instance 1: rate cards ----
# Three non-overlapping closed quarters on one contracted item. Closed-interval
# semantics mean touching ranges DO overlap, so the quarters are cut to leave a
# clean boundary between them.
Q1_FROM, Q1_TO = "2026-01-01", "2026-03-31"
Q2_FROM, Q2_TO = "2026-04-01", "2026-06-30"
Q3_FROM, Q3_TO = "2026-07-01", "2026-09-30"
Q1_RATE, Q2_RATE, Q3_RATE = 150, 160, 170

# ---------------------------------------------------- instance 2: claims ----
AUGUST_START, AUGUST_END = "2026-08-01", "2026-08-31"
JUNE_CLAIM_UNITS, JUNE_CLAIM_CENTS = 30, 4500
JULY_CLAIM_UNITS, JULY_CLAIM_CENTS = 40, 6000
AUGUST_CLAIM_UNITS, AUGUST_CLAIM_CENTS = 10, 1500

# --------------------------------------------------- instance 3: posture ----
POSTURE_CLOCK = "2026-08-01T09:00:00.000Z"
DEFAULT_REVERSAL_POSTURE_LIMIT = 2

ADMIN_FEE_BPS_LOW = 300
# accrual A, the 30-case June line
GROSS_A, FEE_A, NET_A, SHARE_A, RETENTION_A = 4500, 135, 4365, 3274, 1091
# accrual B, the 40-case June line
GROSS_B, FEE_B, NET_B, SHARE_B, RETENTION_B = 6000, 180, 5820, 4365, 1455
# the member's ledger with both accruals posted
LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE = 7639, 2546, 315

# The July compliance window the design pins: 31 days, no July purchasing.
JULY_WINDOW_DAYS = 31
COMMITTED_PRORATED_JULY_CENTS = 1698630   # round_half_up(20000000 * 31 / 365)


# ============================================================ local helpers ====
# test_helpers/ is off limits, so the helpers these three instances need beyond
# fixtures.py live here.


def _card_body(item_id: str, expected_version: int, rate: int, eff_from: str, eff_to: str) -> dict:
    """A PER_CASE rate-card body carrying one explicit OCC token and window."""
    return F.flat_rate_card_payload(
        item_id,
        expected_version,
        flat_rate_cents_per_case=rate,
        effective_from=eff_from,
        effective_to=eff_to,
    )


def _draft_deal_with_item() -> tuple:
    """A DRAFT deal with one ACTIVE item at version 1 and no rate cards yet."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    return deal, item


def _rate_cards_for_item(item_id: str) -> tuple:
    """(rows, meta) for GET /rate-cards filtered to one contracted item."""
    params = dict(WIDE)
    params["contracted_item_id"] = item_id
    return validate_paginated(api_client.list_rate_cards(ADMIN, params))


def _claims_for_deal(deal_id: str) -> tuple:
    """(rows, meta) for GET /manufacturer-claims filtered to one deal."""
    params = dict(WIDE)
    params["deal_id"] = deal_id
    return validate_paginated(api_client.list_claims(REP, params))


def _active_deal_with_approved_card() -> dict:
    """An ACTIVE deal whose beef item carries one APPROVED PER_CASE card."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.approved_card(item["id"], RateType.PER_CASE.value)
    deal = fx.activate_deal(deal["id"])
    return {"deal": deal, "deal_id": deal["id"], "item": item, "card": card}


def _submit_claim(deal_id: str, expected_deal_version: int, units: int, cents: int,
                  period_start: str, period_end: str):
    """POST /manufacturer-claims as rep-01, returned raw for status checks."""
    body = F.claim_payload(
        deal_id,
        expected_deal_version,
        units,
        cents,
        period_start=period_start,
        period_end=period_end,
    )
    return api_client.create_claim(body, REP)


def _tier_without_posture_limit() -> dict:
    """Create the ELITE tier with reversal_posture_limit omitted entirely.

    factories.program_tier_payload can only override the key, never drop it, and
    this instance needs the PRD default to be the thing under test.
    """
    payload = {k: v for k, v in C.ELITE_TIER.items() if k != "reversal_posture_limit"}
    return validate_success(api_client.create_program_tier(payload, ADMIN), 201)


def _posture_program() -> dict:
    """The accrued June feed of the posture instance, on a default-limit tier.

    Clock at 09:00 on the epoch day, ELITE tier created without
    reversal_posture_limit, one ACTIVE member with an ACTIVE
    PURCHASE_DATA_AND_PRICING letter, an ACTIVE deal with an APPROVED 150-cent
    PER_CASE card, and the 30/40-case June batch ACCRUED by analyst-01.
    """
    fx.set_clock(POSTURE_CLOCK)
    tier = _tier_without_posture_limit()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.approved_card(item["id"], RateType.PER_CASE.value)
    deal = fx.activate_deal(deal["id"])
    ctx = {
        "tier": tier,
        "tier_id": tier["id"],
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "member": member,
        "member_id": member["id"],
        "letter": letter,
        "deal": deal,
        "deal_id": deal["id"],
        "item": item,
        "item_id": item["id"],
        "card": card,
        "member_headers": make_member_operator_headers(member["id"]),
    }
    fx.ingest_june_feed(ctx)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)
    return ctx


def _decide(dispute_id: str, decision: str, note: str):
    """POST /disputes/{id}/decide as arbiter-01, returned raw.

    arbiter-01 is none of the three recorded identifiers: the dispute's
    opened_by_user_id is the member row's id, the accrual's validated_by_user_id
    is null and the batch's accrued_by_user_id is analyst-01.
    """
    return api_client.decide_dispute(
        dispute_id, {"decision": decision, "decision_note": note}, ARBITER
    )


def _uphold_full_share(ctx: dict, accrual: dict, reason_code: str, note: str):
    """Open a dispute for the accrual's whole member share and uphold it."""
    fx.open_dispute_on(ctx, accrual, reason_code)
    return _decide(ctx["dispute_id"], DisputeDecision.UPHOLD.value, note)


# ================================================== OCC on the parent item ====
# Instance: rate_card_create_with_a_stale_contracted_item_version_is_rejected


def test_rate_card_create_with_a_stale_contracted_item_version_is_refused_412():
    """A token read before a successful card create is one behind afterwards, and
    the refusal leaves the item at version 2 with only the first card stored.

    PRD §2.8: "Proposing a rate card requires `expected_contracted_item_version`
    as a non-optional body field, carrying the client's last observed `version` of
    the `ContractedItem` the card prices. If that value differs from the item's
    current `version`, the create is rejected with `ERR_STALE_PARENT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/rate_card_create_with_a_stale_contracted_item_version_is_rejected
    """
    _deal, item = _draft_deal_with_item()
    item_id = item["id"]

    # call 1: a freshly created item sits at version 1.
    item_v1 = fx.item_version(item_id)
    assert item_v1 == 1

    # call 2: the first card is accepted and bumps the parent by exactly 1.
    first = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v1, Q1_RATE, Q1_FROM, Q1_TO), ADMIN),
        201,
    )
    assert_rate_card(first)
    assert first["status"] == RateCardStatus.PROPOSED.value
    assert first["pinned_item_version"] is None
    assert fx.read_item(item_id)["version"] == 2

    # call 3: the same token is now stale, and the window it asks for is free.
    response = api_client.create_rate_card(
        _card_body(item_id, item_v1, Q2_RATE, Q2_FROM, Q2_TO), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)

    # call 4: the refused create bumped nothing and stored no RateCard row.
    item_after = fx.read_item(item_id)
    assert_contracted_item(item_after)
    assert item_after["version"] == 2
    assert item_after["approved_rate_card_count"] == 0
    rows, meta = _rate_cards_for_item(item_id)
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


def test_rate_card_create_succeeds_with_the_freshly_read_item_version():
    """The retry of the very body that drew the 412 is accepted once the client
    reads the item again, taking the item from version 2 to version 3.

    PRD §2.4: "`version` is an integer that starts at 1 when the record is created
    and increases by exactly 1 on every mutation of that record". PRD §3.2: "the
    owning contracted item's `version` is incremented by exactly 1 for the call as
    a whole".

    Design: Corner/cross_cutting_complexity_layers/rate_card_create_with_a_stale_contracted_item_version_is_rejected
    """
    _deal, item = _draft_deal_with_item()
    item_id = item["id"]
    item_v1 = fx.item_version(item_id)
    first = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v1, Q1_RATE, Q1_FROM, Q1_TO), ADMIN),
        201,
    )
    stale_body = _card_body(item_id, item_v1, Q2_RATE, Q2_FROM, Q2_TO)
    validate_error(
        api_client.create_rate_card(stale_body, ADMIN),
        ApiErrorId.ERR_STALE_PARENT_VERSION,
        412,
    )

    # call 4: the live token is 2, not the 1 the client was holding.
    item_v2 = fx.item_version(item_id)
    assert item_v2 == 2

    # call 5: the identical body with the current token is accepted.
    second = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v2, Q2_RATE, Q2_FROM, Q2_TO), ADMIN),
        201,
    )
    assert_rate_card(second)
    assert second["status"] == RateCardStatus.PROPOSED.value
    assert second["flat_rate_cents_per_case"] == Q2_RATE
    assert second["effective_from"] == Q2_FROM
    assert second["effective_to"] == Q2_TO
    assert second["supersedes_rate_card_id"] is None
    assert fx.read_item(item_id)["version"] == 3

    rows, meta = _rate_cards_for_item(item_id)
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_approve_also_moves_the_item_token_so_a_two_write_stale_token_is_refused():
    """Approval pins the version it observed and bumps the item again, so a token
    read two writes ago is refused even though its window overlaps nothing.

    PRD §3.2: "A `GpoAdmin` approving a `PROPOSED` card moves it
    `PROPOSED → APPROVED`, stamps `pinned_item_version` with the contracted item's
    `version` as observed at that instant, increments the item's
    `approved_rate_card_count` by 1 and increments the item's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/rate_card_create_with_a_stale_contracted_item_version_is_rejected
    """
    _deal, item = _draft_deal_with_item()
    item_id = item["id"]
    item_v1 = fx.item_version(item_id)
    first = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v1, Q1_RATE, Q1_FROM, Q1_TO), ADMIN),
        201,
    )
    validate_error(
        api_client.create_rate_card(_card_body(item_id, item_v1, Q2_RATE, Q2_FROM, Q2_TO), ADMIN),
        ApiErrorId.ERR_STALE_PARENT_VERSION,
        412,
    )
    item_v2 = fx.item_version(item_id)
    assert item_v2 == 2
    second = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v2, Q2_RATE, Q2_FROM, Q2_TO), ADMIN),
        201,
    )

    # call 6: approve pins the version it observed (3) and then moves it to 4.
    approved = validate_success(api_client.approve_rate_card(first["id"], ADMIN), 200)
    assert_rate_card(approved)
    assert approved["status"] == RateCardStatus.APPROVED.value
    assert approved["pinned_item_version"] == 3
    item_after_approve = fx.read_item(item_id)
    assert item_after_approve["version"] == 4
    assert item_after_approve["approved_rate_card_count"] == 1

    # call 7: token 2 is two writes behind; the free Q3 window changes nothing.
    response = api_client.create_rate_card(
        _card_body(item_id, item_v2, Q3_RATE, Q3_FROM, Q3_TO), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)
    assert fx.read_item(item_id)["version"] == 4

    # calls 8 and 9: with the current token the same body is accepted.
    item_v4 = fx.item_version(item_id)
    assert item_v4 == 4
    third = validate_success(
        api_client.create_rate_card(_card_body(item_id, item_v4, Q3_RATE, Q3_FROM, Q3_TO), ADMIN),
        201,
    )
    assert fx.read_item(item_id)["version"] == 5

    # The two 412s created nothing: three cards exist, not five.
    rows, meta = _rate_cards_for_item(item_id)
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {first["id"], second["id"], third["id"]}


# ================================================== OCC on the parent deal ====
# Instance: claim_restatement_with_a_stale_deal_version_is_rejected


def test_claim_submission_with_a_stale_deal_version_is_refused_412():
    """The rep's own June filing invalidates the deal token it was holding, so the
    July filing on that token is refused and stores no claim.

    PRD §2.8: "Submitting a manufacturer claim requires `expected_deal_version` as
    a non-optional body field, carrying the client's last observed `version` of the
    `ManufacturerDeal` the claim is filed against. If that value differs from the
    deal's current `version`, the create is rejected with
    `ERR_STALE_PARENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/claim_restatement_with_a_stale_deal_version_is_rejected
    """
    ctx = _active_deal_with_approved_card()
    deal_id = ctx["deal_id"]

    # call 1: the rep reads the deal it is about to file against.
    deal_v1 = fx.deal_version(deal_id)

    # call 2: the June claim is stored SUBMITTED and moves its parent deal.
    june = validate_success(
        _submit_claim(deal_id, deal_v1, JUNE_CLAIM_UNITS, JUNE_CLAIM_CENTS,
                      C.JUNE_START, C.JUNE_END),
        201,
    )
    assert_claim(june)
    assert june["status"] == "SUBMITTED"
    assert june["accrued_amount_cents"] == 0
    assert june["variance_bps"] == 0
    assert june["reconciled_at"] is None
    assert fx.deal_version(deal_id) == deal_v1 + 1

    # call 3: the July filing still carries the pre-June token.
    response = _submit_claim(deal_id, deal_v1, JULY_CLAIM_UNITS, JULY_CLAIM_CENTS,
                             C.JULY_START, C.JULY_END)
    validate_error(response, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)

    # call 4: the refusal neither bumped the deal nor stored a second claim.
    deal_v2 = fx.deal_version(deal_id)
    assert deal_v2 == deal_v1 + 1
    rows, meta = _claims_for_deal(deal_id)
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [june["id"]]


def test_claim_submission_succeeds_with_the_freshly_read_deal_version():
    """The same July body is accepted once the rep refreshes the token, and the
    accepted filing advances the deal's version by exactly one again.

    PRD §3.5: "A filing that survives those checks stores a claim with `status` of
    `SUBMITTED`, `accrued_amount_cents` of 0, `variance_bps` of 0 and
    `reconciled_at` null, and it advances the owning deal's `version` by exactly 1
    for the call as a whole."

    Design: Corner/cross_cutting_complexity_layers/claim_restatement_with_a_stale_deal_version_is_rejected
    """
    ctx = _active_deal_with_approved_card()
    deal_id = ctx["deal_id"]
    deal_v1 = fx.deal_version(deal_id)
    june = validate_success(
        _submit_claim(deal_id, deal_v1, JUNE_CLAIM_UNITS, JUNE_CLAIM_CENTS,
                      C.JUNE_START, C.JUNE_END),
        201,
    )
    validate_error(
        _submit_claim(deal_id, deal_v1, JULY_CLAIM_UNITS, JULY_CLAIM_CENTS,
                      C.JULY_START, C.JULY_END),
        ApiErrorId.ERR_STALE_PARENT_VERSION,
        412,
    )

    # call 5: the identical July body with the current token is accepted.
    deal_v2 = fx.deal_version(deal_id)
    july = validate_success(
        _submit_claim(deal_id, deal_v2, JULY_CLAIM_UNITS, JULY_CLAIM_CENTS,
                      C.JULY_START, C.JULY_END),
        201,
    )
    assert_claim(july)
    assert july["status"] == "SUBMITTED"
    assert july["claimed_units"] == JULY_CLAIM_UNITS
    assert july["claimed_amount_cents"] == JULY_CLAIM_CENTS
    assert july["period_start"] == C.JULY_START
    assert july["period_end"] == C.JULY_END
    assert fx.deal_version(deal_id) == deal_v2 + 1

    # A different period is a fresh filing, so June is not superseded by July.
    rows, meta = _claims_for_deal(deal_id)
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {june["id"], july["id"]}
    assert {row["status"] for row in rows} == {"SUBMITTED"}


def test_stale_deal_token_outranks_the_suspended_deal_state_gate():
    """On a SUSPENDED deal with a stale token the answer is the 412, and only once
    the token is current does the 409 state gate surface.

    PRD §2.7: "Requests are validated as an ordered ladder, and the **first** check
    that fails determines the response." Check 10 is "The supplied expected-version
    field matches the parent record's current `version` — otherwise
    `ERR_STALE_PARENT_VERSION`" and check 14 is "The referenced manufacturer deal
    has `status` of either `DRAFT` or `ACTIVE` — otherwise
    `ERR_DEAL_NOT_OPEN_FOR_CHANGES`".

    Design: Corner/cross_cutting_complexity_layers/claim_restatement_with_a_stale_deal_version_is_rejected
    """
    ctx = _active_deal_with_approved_card()
    deal_id = ctx["deal_id"]
    deal_v1 = fx.deal_version(deal_id)
    june = validate_success(
        _submit_claim(deal_id, deal_v1, JUNE_CLAIM_UNITS, JUNE_CLAIM_CENTS,
                      C.JUNE_START, C.JUNE_END),
        201,
    )
    deal_v2 = fx.deal_version(deal_id)
    july = validate_success(
        _submit_claim(deal_id, deal_v2, JULY_CLAIM_UNITS, JULY_CLAIM_CENTS,
                      C.JULY_START, C.JULY_END),
        201,
    )

    # call 6: the suspend is an unrelated admin write that also moves the token.
    suspended = validate_success(api_client.suspend_deal(deal_id, ADMIN), 200)
    assert suspended["status"] == DealStatus.SUSPENDED.value
    deal_v3 = fx.deal_version(deal_id)
    assert deal_v3 == deal_v2 + 2

    # call 8: both gates are live; priority 10 answers before priority 14.
    stale_on_suspended = _submit_claim(
        deal_id, deal_v2, AUGUST_CLAIM_UNITS, AUGUST_CLAIM_CENTS, AUGUST_START, AUGUST_END
    )
    validate_error(stale_on_suspended, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)

    # call 9: with a current token the state gate finally answers.
    current_on_suspended = _submit_claim(
        deal_id, deal_v3, AUGUST_CLAIM_UNITS, AUGUST_CLAIM_CENTS, AUGUST_START, AUGUST_END
    )
    validate_error(current_on_suspended, ApiErrorId.ERR_DEAL_NOT_OPEN_FOR_CHANGES, 409)

    rows, meta = _claims_for_deal(deal_id)
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {june["id"], july["id"]}


# ======================================= the cumulative posture threshold ====
# Instance: reconciliation_posture_flips_only_on_the_second_upheld_reversal


def test_first_upheld_reversal_leaves_the_posture_clear_and_the_hold_off():
    """One upheld reversal on a default-limit tier retracts that accrual's money
    and lifts the counter to 1, and nothing else happens.

    PRD §3.1: "`reversal_posture_limit` must be at least 1 and defaults to 2 when
    the field is omitted." PRD §3.6: "Its first upheld dispute retracts one
    accrual's money and lifts `dispute_reversal_count` to 1, and nothing else
    happens."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_posture_flips_only_on_the_second_upheld_reversal
    """
    ctx = _posture_program()
    # setup: the tier payload omitted the field, so the PRD default applies.
    assert ctx["tier"]["reversal_posture_limit"] == DEFAULT_REVERSAL_POSTURE_LIMIT
    assert ctx["batch"]["accrued_by_user_id"] == ANALYST_1
    assert_member_ledger(ctx["member"], LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE)
    assert_split(ctx["accrual_a"], GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A)

    response = _uphold_full_share(
        ctx,
        ctx["accrual_a"],
        DisputeReasonCode.RATE_MISMATCH.value,
        "First reversal: wrong rate applied.",
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.UPHELD.value
    assert dispute["decided_by_user_id"] == ARBITER_1
    assert dispute["decision_note"] == "First reversal: wrong rate applied."

    accrual_a = fx.read_accrual(ctx["accrual_a"]["id"])
    assert_accrual(accrual_a)
    assert accrual_a["status"] == AccrualStatus.REVERSED.value
    assert accrual_a["reversal_reason"] == ReversalReason.DISPUTE_UPHELD.value

    # BELOW the threshold: one reversal is not enough to harden the posture.
    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["dispute_reversal_count"] == 1
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    # The counters moved by exactly the reversed accrual's own components.
    assert_member_ledger(member, SHARE_B, RETENTION_B, FEE_B)
    assert member["accrued_member_share_cents"] == LEDGER_SHARE - SHARE_A == 4365
    assert member["attributed_gpo_retention_cents"] == LEDGER_RETENTION - RETENTION_A == 1455
    assert member["attributed_admin_fee_cents"] == LEDGER_FEE - FEE_A == 180

    # Hop 4 never fired, so the ACCRUED batch carries no hold either.
    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["payout_hold"] is False


def test_second_upheld_reversal_flips_the_posture_to_restricted_and_holds_payouts():
    """The second upheld reversal reaches the limit of 2, restricting the member,
    holding its payouts and flagging the ACCRUED batch that holds its lines.

    PRD §3.6: "**Hop 4**, caused by hop 3 when the incremented
    `dispute_reversal_count` reaches the tier's `reversal_posture_limit`: the
    member's `reconciliation_posture` moves `CLEAR → RESTRICTED`, its `payout_hold`
    is set to true, and every purchase batch that holds at least one purchase line
    of that member and whose `normalization_status` is `ACCRUED` has its own
    `payout_hold` set to true with its `version` incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_posture_flips_only_on_the_second_upheld_reversal
    """
    ctx = _posture_program()
    validate_success(
        _uphold_full_share(
            ctx,
            ctx["accrual_a"],
            DisputeReasonCode.RATE_MISMATCH.value,
            "First reversal: wrong rate applied.",
        ),
        200,
    )
    assert fx.read_member(ctx["member_id"])["reconciliation_posture"] == (
        ReconciliationPosture.CLEAR.value
    )

    response = _uphold_full_share(
        ctx,
        ctx["accrual_b"],
        DisputeReasonCode.UNITS_MISMATCH.value,
        "Second reversal: units overstated.",
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.UPHELD.value
    accrual_b = fx.read_accrual(ctx["accrual_b"]["id"])
    assert accrual_b["status"] == AccrualStatus.REVERSED.value
    assert accrual_b["reversal_reason"] == ReversalReason.DISPUTE_UPHELD.value

    # AT the threshold: the flip, the hold and all three counters back to 0.
    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["dispute_reversal_count"] == 2
    assert member["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value
    assert member["payout_hold"] is True
    assert_member_ledger(member, 0, 0, 0)

    # The flip cascades to the ACCRUED batch still holding this member's lines.
    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["payout_hold"] is True
    assert batch["normalization_status"] == "ACCRUED"

    # A reversal decrements the member; it never rewrites the accrual's figures.
    assert_split(
        fx.read_accrual(ctx["accrual_a"]["id"]),
        GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A,
    )
    assert_split(accrual_b, GROSS_B, ADMIN_FEE_BPS_LOW, FEE_B, NET_B, SHARE_B, RETENTION_B)
    assert fx.read_accrual(ctx["accrual_a"]["id"])["member_share_cents"] == 3274
    assert accrual_b["member_share_cents"] == 4365


def _restricted_member(ctx: dict) -> dict:
    """Uphold both June disputes so the member is RESTRICTED and held."""
    validate_success(
        _uphold_full_share(
            ctx,
            ctx["accrual_a"],
            DisputeReasonCode.RATE_MISMATCH.value,
            "First reversal: wrong rate applied.",
        ),
        200,
    )
    validate_success(
        _uphold_full_share(
            ctx,
            ctx["accrual_b"],
            DisputeReasonCode.UNITS_MISMATCH.value,
            "Second reversal: units overstated.",
        ),
        200,
    )
    return fx.read_member(ctx["member_id"])


def test_reactivation_clears_the_payout_hold_but_never_the_restricted_posture():
    """A July compliance BREACH suspends the restricted member, and the GpoAdmin's
    reinstatement clears payout_hold while leaving the posture RESTRICTED.

    PRD §3.1: "Reinstatement is a narrow mercy: it clears the payout hold but never
    clears `reconciliation_posture`, because a `RESTRICTED` posture is one-way and
    survives every subsequent reinstatement."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_posture_flips_only_on_the_second_upheld_reversal
    """
    ctx = _posture_program()
    member = _restricted_member(ctx)
    assert member["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value

    # call 7: no July lines, so the member breaches its prorated commitment while
    # the 31-day window is too short for the deal-loss branch to fire.
    review = validate_success(
        api_client.create_compliance_review(
            F.compliance_review_payload(
                ctx["member_id"], ctx["deal_id"], C.JULY_START, C.JULY_END
            ),
            ADMIN,
        ),
        201,
    )
    assert_compliance_review(review)
    assert review["result"] == ComplianceResult.BREACH.value
    assert review["window_days"] == JULY_WINDOW_DAYS
    assert review["committed_spend_prorated_cents"] == COMMITTED_PRORATED_JULY_CENTS
    assert review["contracted_spend_cents"] == 0
    assert review["deal_wide_contracted_spend_cents"] == 0
    assert review["purchase_ratio_bps"] == 0
    assert review["triggered_deal_loss"] is False

    breached = fx.read_member(ctx["member_id"])
    assert breached["enrollment_status"] == MemberEnrollmentStatus.SUSPENDED.value
    assert breached["payout_hold"] is True
    assert breached["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value

    # call 8: reinstatement clears the hold and nothing else.
    reinstated = validate_success(api_client.activate_member(ctx["member_id"], ADMIN), 200)
    assert_member(reinstated)
    assert reinstated["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert reinstated["payout_hold"] is False
    assert reinstated["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value
    assert reinstated["dispute_reversal_count"] == 2


def test_a_third_dispute_is_still_creatable_under_a_restricted_posture():
    """RESTRICTED is a posture, not a lock: a fresh July accrual of the same member
    can still be disputed once the member is ACTIVE again.

    PRD §3.6: "From then on every attempt to validate one of its accruals is
    refused with `ERR_MEMBER_PAYOUT_HELD`, and no accrual of that member will be
    paid at period close, until a `GpoAdmin` reinstates it — which clears the hold
    but leaves the posture `RESTRICTED` forever."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_posture_flips_only_on_the_second_upheld_reversal
    """
    ctx = _posture_program()
    _restricted_member(ctx)
    validate_success(
        api_client.create_compliance_review(
            F.compliance_review_payload(
                ctx["member_id"], ctx["deal_id"], C.JULY_START, C.JULY_END
            ),
            ADMIN,
        ),
        201,
    )
    reinstated = validate_success(api_client.activate_member(ctx["member_id"], ADMIN), 200)
    assert reinstated["reconciliation_posture"] == ReconciliationPosture.RESTRICTED.value

    # A second feed for the same member, accrued after the flip.
    july_batch = fx.create_july_batch(ctx["distributor_id"])
    july_line = fx.create_line(
        july_batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        payload=F.purchase_line_payload(
            july_batch["id"], ctx["member_id"], invoice_date="2026-07-10"
        ),
    )
    fx.normalize(july_batch["id"])
    fx.accrue(july_batch["id"])
    third = fx.accrual_for_line(july_line["id"])
    assert third["status"] == AccrualStatus.ACCRUED.value
    assert third["member_share_cents"] == SHARE_A

    response = api_client.create_dispute(
        F.dispute_payload(
            third["id"], third["member_share_cents"], DisputeReasonCode.ITEM_MISMATCH.value
        ),
        ctx["member_headers"],
    )
    dispute = validate_success(response, 201)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert dispute["accrual_status_before"] == AccrualStatus.ACCRUED.value
    assert dispute["evidence_round_count"] == 0
    assert dispute["decided_by_user_id"] is None
    assert fx.read_accrual(third["id"])["status"] == AccrualStatus.DISPUTED.value
    # The posture is still the one-way RESTRICTED it became at the second reversal.
    assert fx.read_member(ctx["member_id"])["reconciliation_posture"] == (
        ReconciliationPosture.RESTRICTED.value
    )
