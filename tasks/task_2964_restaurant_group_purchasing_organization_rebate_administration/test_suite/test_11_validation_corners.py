"""Validation-ladder corners: uniqueness, balance, temporal and cross-entity gates.

Each test below translates exactly one instance of the corner design's
``validations`` section. The themes are the ordered ladder of PRD 2.7 and the
error catalogue of PRD 5: a rejected request must carry the right error_id AND
the right HTTP status, and must leave the target record byte-identical — same
status, same version, same counters.

Every precondition is built through the API because the database is empty
before every test.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_accrual,
    assert_contracted_item,
    assert_deal,
    assert_dispute,
    assert_distributor,
    assert_member,
    assert_program_tier,
    assert_purchase_batch,
    assert_purchase_line,
    assert_rate_card,
    make_distributor_feed_headers,
    make_member_operator_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.types import (
    AccrualBlockReason,
    AccrualStatus,
    AuditStatus,
    ClaimStatus,
    DealStatus,
    DisputeReasonCode,
    DisputeStatus,
    DistributorStatus,
    ItemStatus,
    LetterScope,
    MatchStatus,
    NormalizationStatus,
    RateCardStatus,
    RateType,
    RecoveryOutcome,
    TierCode,
)

# The clock starts at exactly 2026-08-01T00:00:00.000Z, so an accrual posted
# before any clock move carries that instant as its created_at.
DISPUTE_WINDOW_LAST_LEGAL_DAY = "2026-09-15T00:00:00.000Z"   # 45 whole days on
DISPUTE_WINDOW_FIRST_CLOSED_DAY = "2026-09-16T00:00:00.000Z"  # 46 whole days on

# 30 cases * 150 cents = 4500 gross; fee 300 bps -> 135; net 4365;
# member share round_half_up(4365 * 7500 / 10000) == 3274.
LINE_A_MEMBER_SHARE_CENTS = 3274


# --------------------------------------------------------------------------
# instance: duplicate_dba_code_on_a_second_distributor_is_rejected
# --------------------------------------------------------------------------

METRO_01 = "METRO-01"
METRO_02 = "METRO-02"


def _incumbent_metro_distributor() -> dict:
    """One registered distributor holding dba_code METRO-01."""
    return fx.create_distributor(
        name="Metro Foodservice", dba_code=METRO_01, contracted_markup_bps=900
    )


def test_duplicate_dba_code_on_a_second_distributor_is_rejected():
    """A second distributor reusing METRO-01 under a different name is refused,
    and the incumbent row survives untouched with its own markup.

    PRD 3.1: "a `dba_code` of 3 to 20 characters drawn only from uppercase
    letters, digits and the hyphen that must be unique across all distributors
    — a reused code is rejected with `ERR_DUPLICATE_DBA_CODE`".

    Design: Corner/validations/duplicate_dba_code_on_a_second_distributor_is_rejected
    """
    incumbent = _incumbent_metro_distributor()
    assert_distributor(incumbent)
    incumbent_version = incumbent["version"]

    response = api_client.create_distributor(
        F.distributor_payload(
            name="Metro Foodservice of New England",
            dba_code=METRO_01,
            contracted_markup_bps=450,
        ),
        fx.ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DBA_CODE, 409)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["message"].strip() != "", "data.message must be non-empty"

    _, meta = validate_paginated(api_client.list_distributors(fx.ADMIN))
    assert meta["total_count"] == 1, "the refusal must not create a row"
    survivor = fx.read_distributor(incumbent["id"])
    assert survivor["name"] == "Metro Foodservice"
    assert survivor["contracted_markup_bps"] == 900
    assert survivor["dba_code"] == METRO_01
    assert survivor["status"] == DistributorStatus.ACTIVE.value
    assert survivor["version"] == incumbent_version, "a rejected create mutates nothing"


def test_a_distinct_dba_code_is_accepted_after_the_duplicate_was_refused():
    """The rejection was about the code, not the name: a third create carrying
    METRO-02 succeeds even though its name repeats the incumbent's.

    PRD 3.1: "A newly registered distributor's `status` is `ACTIVE`, with
    `active_letter_count` and `overbilled_recovered_cents` both at 0."

    Design: Corner/validations/duplicate_dba_code_on_a_second_distributor_is_rejected
    """
    _incumbent_metro_distributor()
    validate_error(
        api_client.create_distributor(
            F.distributor_payload(
                name="Metro Foodservice of New England",
                dba_code=METRO_01,
                contracted_markup_bps=450,
            ),
            fx.ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_DBA_CODE,
        409,
    )

    response = api_client.create_distributor(
        F.distributor_payload(
            name="Metro Foodservice", dba_code=METRO_02, contracted_markup_bps=450
        ),
        fx.ADMIN,
    )
    third = validate_success(response, 201)
    assert_distributor(third)
    assert third["dba_code"] == METRO_02
    assert third["contracted_markup_bps"] == 450
    assert third["status"] == DistributorStatus.ACTIVE.value
    assert third["active_letter_count"] == 0
    assert third["overbilled_recovered_cents"] == 0

    _, meta = validate_paginated(api_client.list_distributors(fx.ADMIN))
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------
# instance: tier_split_that_balances_to_exactly_10000_bps_is_accepted
# --------------------------------------------------------------------------
# The design's tier_code literals EDGE-LOW / OVER / UNDER are not members of the
# PRD's declared set ("a `tier_code` — one of `CORE`, `PLUS` or `ELITE`"), so a
# request carrying them would be refused at ladder rung 7 as ERR_INVALID_REQUEST
# and never reach rung 27. The PRD's own symbols are used instead: the balanced
# pair takes ELITE and PLUS, and both unbalanced probes take CORE (a rejected
# create stores nothing, so the code stays free).


def _balanced_split_pair() -> tuple:
    """The exact-equality pair: 7500+2500 and the degenerate 1+9999."""
    elite = validate_success(
        api_client.create_program_tier(
            F.program_tier_payload(
                tier_code=TierCode.ELITE.value,
                member_share_bps=7500,
                gpo_retention_bps=2500,
            ),
            fx.ADMIN,
        ),
        201,
    )
    edge_low = validate_success(
        api_client.create_program_tier(
            F.program_tier_payload(
                tier_code=TierCode.PLUS.value,
                member_share_bps=1,
                gpo_retention_bps=9999,
            ),
            fx.ADMIN,
        ),
        201,
    )
    return elite, edge_low


def test_tier_split_that_balances_to_exactly_10000_bps_is_accepted():
    """Both a conventional 7500/2500 split and the degenerate 1/9999 split are
    legal, because the rule is an exact equality rather than a range.

    PRD 3.1: "Those two must add up to exactly 10000 basis points; anything else
    is rejected with `ERR_TIER_SPLIT_NOT_BALANCED`."

    Design: Corner/validations/tier_split_that_balances_to_exactly_10000_bps_is_accepted
    """
    elite, edge_low = _balanced_split_pair()

    assert_program_tier(elite)
    assert elite["member_share_bps"] == 7500
    assert elite["gpo_retention_bps"] == 2500

    assert_program_tier(edge_low)
    assert edge_low["member_share_bps"] == 1
    assert edge_low["gpo_retention_bps"] == 9999

    for tier in (elite, edge_low):
        assert tier["admin_fee_bps_low"] == 300
        assert tier["admin_fee_bps_high"] == 150
        assert tier["compliance_min_ratio_bps"] == 8000
        assert tier["markup_cap_bps"] == 700
        assert tier["dispute_window_days"] == 45

    _, meta = validate_paginated(api_client.list_program_tiers(fx.ADMIN))
    assert meta["total_count"] == 2


def test_tier_split_one_basis_point_over_or_under_the_whole_is_rejected():
    """7500+2501 and 7500+2499 both fail: an implementation checking `<= 10000`
    would wrongly accept the under case, so both sides are probed.

    PRD 2.7 rung 27: "A tier's two shares add up to the whole — otherwise
    `ERR_TIER_SPLIT_NOT_BALANCED`."

    Design: Corner/validations/tier_split_that_balances_to_exactly_10000_bps_is_accepted
    """
    _balanced_split_pair()

    over = api_client.create_program_tier(
        F.program_tier_payload(
            tier_code=TierCode.CORE.value,
            member_share_bps=7500,
            gpo_retention_bps=2501,
        ),
        fx.ADMIN,
    )
    validate_error(over, ApiErrorId.ERR_TIER_SPLIT_NOT_BALANCED, 422)

    under = api_client.create_program_tier(
        F.program_tier_payload(
            tier_code=TierCode.CORE.value,
            member_share_bps=7500,
            gpo_retention_bps=2499,
        ),
        fx.ADMIN,
    )
    validate_error(under, ApiErrorId.ERR_TIER_SPLIT_NOT_BALANCED, 422)

    rows, meta = validate_paginated(api_client.list_program_tiers(fx.ADMIN, fx.WIDE))
    assert meta["total_count"] == 2, "neither unbalanced tier was stored"
    assert {row["tier_code"] for row in rows} == {
        TierCode.ELITE.value,
        TierCode.PLUS.value,
    }


# --------------------------------------------------------------------------
# instance: p11_invalid_state_beats_p36_no_accruable_lines
# --------------------------------------------------------------------------

UNCONTRACTED_KEY = "POTATO-FRY-CS6"


def _received_batch_with_one_uncontractable_line() -> dict:
    """An ACTIVE member's June feed holding one line whose reported key no
    ContractedItem owns. No deal or item exists at all, and the batch has never
    been normalized, so rungs 11 and 36 are both live on an accrue call.
    """
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    batch = fx.create_batch(distributor["id"])
    line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        distributor_sku="MF-55300",
        vendor_item_description="Shoestring fries 6ct",
        normalized_item_key_reported=UNCONTRACTED_KEY,
        cases_shipped=20,
        invoice_unit_cost_cents=8300,
        distributor_base_cost_cents=8000,
        invoice_date="2026-06-08",
    )
    return {
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "batch_id": batch["id"],
        "line_id": line["id"],
    }


def test_invalid_state_outranks_no_accruable_lines_on_a_received_batch():
    """One accrue call violates rung 11 (still RECEIVED) and rung 36 (no
    accruable line) at once; the 409 state error must be the only one reported.

    PRD 2.7: "Requests are validated as an ordered ladder, and the **first**
    check that fails determines the response. No later check runs, so a request
    that would fail three ways reports only the earliest failure."
    PRD 3.4: "A batch in any other normalization state is refused with
    `ERR_INVALID_STATE`".

    Design: Corner/validations/p11_invalid_state_beats_p36_no_accruable_lines
    """
    ctx = _received_batch_with_one_uncontractable_line()

    response = api_client.accrue_batch(ctx["batch_id"], fx.ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["accrued_by_user_id"] is None

    _, meta = validate_paginated(api_client.list_accruals(fx.ANALYST))
    assert meta["total_count"] == 0
    assert fx.read_member(ctx["member_id"])["accrued_member_share_cents"] == 0


def test_no_accruable_lines_surfaces_once_the_batch_is_normalized():
    """Repairing only the state gate lets the identical accrue call fall through
    to rung 36's 422, proving both violations were live in the first call.

    PRD 3.4: "a normalized batch in which not one `MATCHED` line resolves an
    approved rate card for its own `invoice_date` is refused with
    `ERR_NO_ACCRUABLE_LINES`, because an accrual run that would produce nothing
    should not advance the batch's state."

    Design: Corner/validations/p11_invalid_state_beats_p36_no_accruable_lines
    """
    ctx = _received_batch_with_one_uncontractable_line()
    validate_error(
        api_client.accrue_batch(ctx["batch_id"], fx.ANALYST),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    normalized = validate_success(
        api_client.normalize_batch(ctx["batch_id"], fx.ANALYST), 200
    )
    assert normalized["normalization_status"] == NormalizationStatus.NORMALIZED.value
    line = fx.read_line(ctx["line_id"])
    assert_purchase_line(line)
    assert line["match_status"] == MatchStatus.UNMATCHED.value
    assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value

    response = api_client.accrue_batch(ctx["batch_id"], fx.ANALYST)
    validate_error(response, ApiErrorId.ERR_NO_ACCRUABLE_LINES, 422)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert batch["accrued_by_user_id"] is None
    _, meta = validate_paginated(api_client.list_accruals(fx.ANALYST))
    assert meta["total_count"] == 0
    assert fx.read_member(ctx["member_id"])["accrued_member_share_cents"] == 0


# --------------------------------------------------------------------------
# instance: invoice_date_outside_the_batch_period_is_rejected
# --------------------------------------------------------------------------


def _june_batch_awaiting_lines() -> dict:
    """An ACTIVE member, an ACTIVE letter for METRO-01 and a RECEIVED June feed
    whose closed period is 2026-06-01 through 2026-06-30."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    fx.activate_member(member["id"])
    batch = fx.create_batch(distributor["id"])
    return {
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "batch_id": batch["id"],
        "distributor_headers": make_distributor_feed_headers(distributor["id"]),
    }


def _beef_line_payload(ctx: dict, cases: int, invoice_date: str) -> dict:
    return F.purchase_line_payload(
        ctx["batch_id"],
        ctx["member_id"],
        cases_shipped=cases,
        invoice_unit_cost_cents=C.INVOICE_UNIT_COST_CENTS,
        distributor_base_cost_cents=C.LINE_A_BASE_COST_CENTS,
        invoice_date=invoice_date,
    )


def test_invoice_date_outside_the_batch_period_is_rejected():
    """One day after period_end and one day before period_start are both refused,
    and neither rejected line contributes a case to the batch.

    PRD 3.3: "The `invoice_date` must fall inside the batch's inclusive
    `period_start` through `period_end` range, a stray date drawing
    `ERR_INVOICE_DATE_OUT_OF_PERIOD`."

    Design: Corner/validations/invoice_date_outside_the_batch_period_is_rejected
    """
    ctx = _june_batch_awaiting_lines()

    after = api_client.create_purchase_line(
        _beef_line_payload(ctx, 9, "2026-07-01"), ctx["distributor_headers"]
    )
    validate_error(after, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_PERIOD, 422)

    before = api_client.create_purchase_line(
        _beef_line_payload(ctx, 9, "2026-05-31"), ctx["distributor_headers"]
    )
    validate_error(before, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_PERIOD, 422)

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0
    _, meta = validate_paginated(
        api_client.list_purchase_lines(
            fx.ANALYST, {"purchase_batch_id": ctx["batch_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_invoice_date_on_either_period_endpoint_is_accepted():
    """The batch period is a CLOSED interval, so period_start and period_end are
    both inside it; only the two accepted lines contribute cases.

    PRD 2.11: "Deal effectivity, batch periods, claim periods, review windows
    and savings-report periods are likewise closed on both ends."

    Design: Corner/validations/invoice_date_outside_the_batch_period_is_rejected
    """
    ctx = _june_batch_awaiting_lines()
    validate_error(
        api_client.create_purchase_line(
            _beef_line_payload(ctx, 9, "2026-07-01"), ctx["distributor_headers"]
        ),
        ApiErrorId.ERR_INVOICE_DATE_OUT_OF_PERIOD,
        422,
    )
    validate_error(
        api_client.create_purchase_line(
            _beef_line_payload(ctx, 9, "2026-05-31"), ctx["distributor_headers"]
        ),
        ApiErrorId.ERR_INVOICE_DATE_OUT_OF_PERIOD,
        422,
    )

    low = validate_success(
        api_client.create_purchase_line(
            _beef_line_payload(ctx, 5, C.JUNE_START), ctx["distributor_headers"]
        ),
        201,
    )
    high = validate_success(
        api_client.create_purchase_line(
            _beef_line_payload(ctx, 7, C.JUNE_END), ctx["distributor_headers"]
        ),
        201,
    )
    assert_purchase_line(low)
    assert_purchase_line(high)
    assert low["invoice_date"] == C.JUNE_START
    assert high["invoice_date"] == C.JUNE_END

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["total_cases_ingested"] == 12, "12 == 5 + 7, the accepted lines only"
    assert batch["line_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_purchase_lines(
            fx.ANALYST, {"purchase_batch_id": ctx["batch_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {low["id"], high["id"]}


# --------------------------------------------------------------------------
# instance: dispute_window_closes_one_day_past_the_tier_allowance
# --------------------------------------------------------------------------


def _accrued_single_line_june() -> dict:
    """One 30-case beef line accrued while the clock still reads the epoch, so
    the accrual's created_at calendar date is 2026-08-01 and the ELITE tier's
    45-day dispute window runs through 2026-09-15."""
    ctx = fx.setup_flat_program()
    fx.ingest_june_feed(ctx, second_line=False)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)
    assert ctx["accrual_a"]["member_share_cents"] == LINE_A_MEMBER_SHARE_CENTS
    return ctx


def _dispute_request(ctx: dict):
    return api_client.create_dispute(
        F.dispute_payload(
            ctx["accrual_a"]["id"],
            LINE_A_MEMBER_SHARE_CENTS,
            DisputeReasonCode.RATE_MISMATCH.value,
        ),
        make_member_operator_headers(ctx["member_id"]),
    )


def test_dispute_filed_one_day_past_the_tier_window_is_rejected():
    """2026-09-16 is 46 whole days after the accrual's 2026-08-01, one past
    dispute_window_days 45, so the filing is refused and nothing moves.

    PRD 3.6: "the logical clock's current calendar date must be at most the
    tier's `dispute_window_days` whole days after the accrual's own `created_at`
    calendar date, with the boundary day itself still open. A member arriving one
    day later than that is refused with `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/validations/dispute_window_closes_one_day_past_the_tier_allowance
    """
    ctx = _accrued_single_line_june()

    moved = fx.set_clock(DISPUTE_WINDOW_FIRST_CLOSED_DAY)
    assert moved["letters_expired"] == 0, "nothing in this fixture expires before 2028"
    assert moved["rate_cards_expired"] == 0

    response = _dispute_request(ctx)
    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409)

    accrual = fx.read_accrual(ctx["accrual_a"]["id"])
    assert_accrual(accrual)
    assert accrual["status"] == AccrualStatus.ACCRUED.value
    assert accrual["version"] == ctx["accrual_a"]["version"], "a refusal mutates nothing"
    _, meta = validate_paginated(api_client.list_disputes(fx.ARBITER))
    assert meta["total_count"] == 0
    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == LINE_A_MEMBER_SHARE_CENTS


def test_dispute_filed_on_the_inclusive_boundary_day_is_accepted():
    """Walking the clock back onto 2026-09-15 — exactly 45 days on — lets the
    identical filing through, which also proves the gate reads the logical clock.

    PRD 3.6: "Critically, it also captures `accrual_status_before` — the
    accrual's `status` at that exact instant, one of `ACCRUED`, `VALIDATED` or
    `FLAGGED` — and then moves the accrual to `DISPUTED`."

    Design: Corner/validations/dispute_window_closes_one_day_past_the_tier_allowance
    """
    ctx = _accrued_single_line_june()
    fx.set_clock(DISPUTE_WINDOW_FIRST_CLOSED_DAY)
    validate_error(
        _dispute_request(ctx), ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409
    )

    fx.set_clock(DISPUTE_WINDOW_LAST_LEGAL_DAY)
    dispute = validate_success(_dispute_request(ctx), 201)
    assert_dispute(dispute)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["accrual_id"] == ctx["accrual_a"]["id"]
    assert dispute["accrual_status_before"] == AccrualStatus.ACCRUED.value
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert dispute["evidence_round_count"] == 0
    assert dispute["disputed_amount_cents"] == LINE_A_MEMBER_SHARE_CENTS

    accrual = fx.read_accrual(ctx["accrual_a"]["id"])
    assert accrual["status"] == AccrualStatus.DISPUTED.value
    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == LINE_A_MEMBER_SHARE_CENTS, (
        "opening a dispute moves no money"
    )


# --------------------------------------------------------------------------
# instance: recovered_cents_above_the_audited_total_is_rejected
# --------------------------------------------------------------------------
# The design recipe calls audit-markup straight off a RECEIVED batch; the PRD
# requires "a batch whose `audit_status` is `NOT_AUDITED` and whose
# `normalization_status` is either `NORMALIZED` or `ACCRUED`", so the setup
# normalizes first. The audited literals themselves are the design's own.


def _recovery_requested_june_batch() -> dict:
    """Two auditable lines overbilled 300 and 80, so batch.overbilled_cents is
    380 and the batch sits at RECOVERY_REQUESTED."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    fx.activate_member(member["id"])
    batch = fx.create_batch(distributor["id"])
    line_a = fx.create_line(batch["id"], member["id"], distributor["id"])
    line_b = fx.create_line_b(batch["id"], member["id"], distributor["id"])
    fx.normalize(batch["id"])
    fx.audit_markup(batch["id"])
    batch = fx.request_recovery(batch["id"])
    return {
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "batch_id": batch["id"],
        "line_a_id": line_a["id"],
        "line_b_id": line_b["id"],
    }


def _assert_per_line_overbilling(ctx: dict):
    line_a = fx.read_line(ctx["line_a_id"])
    line_b = fx.read_line(ctx["line_b_id"])
    assert line_a["overbilled_cents"] == 300
    assert line_b["overbilled_cents"] == 80
    batch = fx.read_batch(ctx["batch_id"])
    assert batch["overbilled_cents"] == 380
    return batch


def test_recovered_cents_above_the_audited_total_is_rejected():
    """381 exceeds neither line alone (300 and 80) but does exceed the aggregate
    380, so the cap can only be the batch total; the refusal credits nobody.

    PRD 3.7: "An outcome of `RECOVERED` stores the supplied `recovered_cents`,
    which must not exceed the batch's `overbilled_cents` — a larger figure is
    rejected with `ERR_RECOVERY_EXCEEDS_OVERBILLING`".

    Design: Corner/validations/recovered_cents_above_the_audited_total_is_rejected
    """
    ctx = _recovery_requested_june_batch()
    _assert_per_line_overbilling(ctx)

    response = api_client.settle_recovery(
        ctx["batch_id"],
        {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 381},
        fx.ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RECOVERY_EXCEEDS_OVERBILLING, 422)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert batch["recovered_cents"] == 0
    assert fx.read_member(ctx["member_id"])["recovery_credit_cents"] == 0
    assert (
        fx.read_distributor(ctx["distributor_id"])["overbilled_recovered_cents"] == 0
    )


def test_recovered_cents_exactly_equal_to_the_audited_total_is_accepted():
    """380 is allowed, pinning the comparison as `<=` rather than `<`, and the
    sole overbilled member takes 300+80 with no remainder cent to distribute.

    PRD 3.7: "Each member's final slice is added to its `recovery_credit_cents`,
    and the slices sum to `recovered_cents` exactly."

    Design: Corner/validations/recovered_cents_above_the_audited_total_is_rejected
    """
    ctx = _recovery_requested_june_batch()
    validate_error(
        api_client.settle_recovery(
            ctx["batch_id"],
            {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 381},
            fx.ADMIN,
        ),
        ApiErrorId.ERR_RECOVERY_EXCEEDS_OVERBILLING,
        422,
    )

    settled = validate_success(
        api_client.settle_recovery(
            ctx["batch_id"],
            {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 380},
            fx.ADMIN,
        ),
        200,
    )
    assert_purchase_batch(settled)
    assert settled["audit_status"] == AuditStatus.RECOVERED.value
    assert settled["recovered_cents"] == 380
    assert fx.read_member(ctx["member_id"])["recovery_credit_cents"] == 380
    assert (
        fx.read_distributor(ctx["distributor_id"])["overbilled_recovered_cents"] == 380
    )

    third = api_client.settle_recovery(
        ctx["batch_id"],
        {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 1},
        fx.ADMIN,
    )
    validate_error(third, ApiErrorId.ERR_INVALID_STATE, 409)
    assert fx.read_batch(ctx["batch_id"])["recovered_cents"] == 380


# --------------------------------------------------------------------------
# instance: markup_audit_skips_a_member_whose_letter_lacks_pricing_scope
# --------------------------------------------------------------------------
# As above, the batch is normalized before audit-markup so the PRD's audit
# precondition holds; every audited literal is the design's own.


def _audited_batch_with_mixed_letter_scopes() -> dict:
    """Two members on ELITE buying from METRO-01 in one June feed: Harbor Grill
    holds a PURCHASE_DATA_AND_PRICING letter, Pier 9 only PURCHASE_DATA_ONLY."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()

    m1 = fx.create_member(tier["id"])
    l1 = fx.submit_letter(
        m1["id"], distributor["id"], scope=LetterScope.PURCHASE_DATA_AND_PRICING.value
    )
    fx.countersign_letter(l1["id"], distributor["id"])
    fx.activate_member(m1["id"])

    m2 = fx.create_member(
        tier["id"],
        legal_name="Pier 9 Oyster Bar Inc",
        committed_annual_spend_cents=9_000_000,
    )
    l2 = fx.submit_letter(
        m2["id"],
        distributor["id"],
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
        signatory_name="T Okafor",
    )
    fx.countersign_letter(l2["id"], distributor["id"])
    fx.activate_member(m2["id"])

    batch = fx.create_batch(distributor["id"])
    line_a = fx.create_line(batch["id"], m1["id"], distributor["id"])
    line_b = fx.create_line_b(batch["id"], m2["id"], distributor["id"])
    fx.normalize(batch["id"])
    batch = fx.audit_markup(batch["id"])
    return {
        "m1_id": m1["id"],
        "m2_id": m2["id"],
        "distributor_id": distributor["id"],
        "batch": batch,
        "batch_id": batch["id"],
        "line_a_id": line_a["id"],
        "line_b_id": line_b["id"],
    }


def test_markup_audit_skips_a_member_whose_letter_lacks_pricing_scope():
    """Two otherwise identical lines diverge: the pricing-authorized member's is
    overbilled 300 while the PURCHASE_DATA_ONLY member's is forced to 0 even
    though its invoice exceeds the allowed 9138 by 2 cents per case.

    PRD 3.7: "A line whose member has no such letter — including a member whose
    only letter is `PURCHASE_DATA_ONLY` — has its `overbilled_cents` set to 0 and
    is skipped, because the GPO was never authorized to see that member's pricing
    from this distributor."

    Design: Corner/validations/markup_audit_skips_a_member_whose_letter_lacks_pricing_scope
    """
    ctx = _audited_batch_with_mixed_letter_scopes()

    line_a = fx.read_line(ctx["line_a_id"])
    line_b = fx.read_line(ctx["line_b_id"])
    assert_purchase_line(line_a)
    assert_purchase_line(line_b)
    assert line_a["overbilled_cents"] == 300, "(9140 - 9130) * 30"
    assert line_b["overbilled_cents"] == 0, "its member's letter carries no pricing"

    batch = fx.read_batch(ctx["batch_id"])
    assert_purchase_batch(batch)
    assert batch["overbilled_cents"] == 300, "the batch total is 300, NOT 380"
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert batch["total_cases_ingested"] == 70, "scope gates the audit, not the feed"
    assert batch["line_count"] == 2


def test_recovery_credits_only_the_member_with_positive_overbilling():
    """Settling the audited 300 credits Harbor Grill in full and leaves Pier 9 at
    0, because only members whose overbilling total is positive participate.

    PRD 3.7: "only members whose total is strictly positive participate — a
    member whose lines audited clean receives nothing even if it has other lines
    in the same feed."

    Design: Corner/validations/markup_audit_skips_a_member_whose_letter_lacks_pricing_scope
    """
    ctx = _audited_batch_with_mixed_letter_scopes()
    fx.request_recovery(ctx["batch_id"])

    settled = validate_success(
        api_client.settle_recovery(
            ctx["batch_id"],
            {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 300},
            fx.ADMIN,
        ),
        200,
    )
    assert settled["audit_status"] == AuditStatus.RECOVERED.value
    assert settled["recovered_cents"] == 300

    m1 = fx.read_member(ctx["m1_id"])
    m2 = fx.read_member(ctx["m2_id"])
    assert_member(m1)
    assert_member(m2)
    assert m1["recovery_credit_cents"] == 300
    assert m2["recovery_credit_cents"] == 0
    assert (
        fx.read_distributor(ctx["distributor_id"])["overbilled_recovered_cents"] == 300
    )


# --------------------------------------------------------------------------
# instance: supersede_without_an_approved_incumbent_is_rejected
# --------------------------------------------------------------------------

SUPERSEDING_FROM = "2026-06-01"
TRUNCATED_TO = "2026-05-31"


def _draft_deal_with_one_proposed_card() -> dict:
    """A DRAFT deal whose item carries a single card for 2026-01-01..2028-12-31
    at PER_CASE 100 that has never been approved."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    rc1 = fx.create_card(item["id"], flat_rate_cents_per_case=100)
    assert rc1["status"] == RateCardStatus.PROPOSED.value
    return {
        "deal_id": deal["id"],
        "item_id": item["id"],
        "rc1_id": rc1["id"],
        "item_v2": fx.item_version(item["id"]),
    }


def _superseding_card_payload(ctx: dict, expected_version: int, supersede=None) -> dict:
    overrides = {
        "flat_rate_cents_per_case": 150,
        "effective_from": SUPERSEDING_FROM,
        "effective_to": C.CARD_TO,
    }
    if supersede is not None:
        overrides["supersede"] = supersede
    return F.flat_rate_card_payload(ctx["item_id"], expected_version, **overrides)


def test_supersede_without_an_approved_incumbent_is_rejected():
    """The supersede flag decides which check runs: with it the overlap check is
    skipped and the failure is the missing APPROVED incumbent, while the SAME
    window without it fails the earlier overlap check instead.

    PRD 3.2: "it requires the item to have exactly one card whose `status` is
    `APPROVED` and whose `effective_to` falls on or after the new card's
    `effective_from`; when no such incumbent exists the request is rejected with
    `ERR_NO_INCUMBENT_RATE_CARD`."

    Design: Corner/validations/supersede_without_an_approved_incumbent_is_rejected
    """
    ctx = _draft_deal_with_one_proposed_card()

    with_flag = api_client.create_rate_card(
        _superseding_card_payload(ctx, ctx["item_v2"], supersede=True), fx.ADMIN
    )
    validate_error(with_flag, ApiErrorId.ERR_NO_INCUMBENT_RATE_CARD, 409)

    without_flag = api_client.create_rate_card(
        _superseding_card_payload(ctx, ctx["item_v2"]), fx.ADMIN
    )
    validate_error(without_flag, ApiErrorId.ERR_RATE_CARD_PERIOD_OVERLAP, 409)

    item = fx.read_item(ctx["item_id"])
    assert_contracted_item(item)
    assert item["version"] == ctx["item_v2"], "neither rejected call bumped the parent"
    _, meta = validate_paginated(api_client.list_rate_cards(fx.ADMIN, fx.WIDE))
    assert meta["total_count"] == 1
    assert fx.read_deal(ctx["deal_id"])["status"] == DealStatus.DRAFT.value


def test_the_same_supersede_succeeds_once_the_incumbent_is_approved():
    """Approving rc1 gives the item its one qualifying incumbent, so the very
    same supersede call now truncates it and lands PROPOSED.

    PRD 3.2: "the incumbent's `effective_to` is rewritten to the new card's
    `effective_from` minus one calendar day, the incumbent moves
    `APPROVED → SUPERSEDED`, the new card's `supersedes_rate_card_id` is set to
    the incumbent's `id`, and the item's `approved_rate_card_count` is
    decremented by 1."

    Design: Corner/validations/supersede_without_an_approved_incumbent_is_rejected
    """
    ctx = _draft_deal_with_one_proposed_card()
    validate_error(
        api_client.create_rate_card(
            _superseding_card_payload(ctx, ctx["item_v2"], supersede=True), fx.ADMIN
        ),
        ApiErrorId.ERR_NO_INCUMBENT_RATE_CARD,
        409,
    )

    fx.approve_card(ctx["rc1_id"])
    item_v3 = fx.item_version(ctx["item_id"])

    rc2 = validate_success(
        api_client.create_rate_card(
            _superseding_card_payload(ctx, item_v3, supersede=True), fx.ADMIN
        ),
        201,
    )
    assert_rate_card(rc2)
    assert rc2["status"] == RateCardStatus.PROPOSED.value
    assert rc2["supersedes_rate_card_id"] == ctx["rc1_id"]
    assert rc2["effective_from"] == SUPERSEDING_FROM

    rc1 = validate_success(api_client.get_rate_card(ctx["rc1_id"], fx.ADMIN))
    assert rc1["status"] == RateCardStatus.SUPERSEDED.value
    assert rc1["effective_to"] == TRUNCATED_TO

    item = fx.read_item(ctx["item_id"])
    assert item["approved_rate_card_count"] == 0
    assert item["version"] == item_v3 + 1, (
        "exactly one increment for the successful create, whether or not "
        "supersede fired"
    )


# --------------------------------------------------------------------------
# instance: child_writes_are_blocked_while_the_parent_deal_is_suspended
# --------------------------------------------------------------------------

BRISKET_SKU = "PBC-BRISKET-WHOLE"
BRISKET_KEY = "BEEF-BRISKET-CS20"


def _suspended_deal_with_active_children() -> dict:
    """PBC-2026 created DRAFT, given an item with an APPROVED PER_CASE 150 card,
    activated and then suspended; every child stays ACTIVE/APPROVED."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.approved_card(item["id"], RateType.PER_CASE.value)
    fx.activate_deal(deal["id"])
    deal = fx.suspend_deal(deal["id"])
    assert deal["status"] == DealStatus.SUSPENDED.value
    return {
        "deal_id": deal["id"],
        "item_id": item["id"],
        "card_id": card["id"],
        "item_v2": fx.item_version(item["id"]),
    }


def _brisket_item_payload(ctx: dict) -> dict:
    return F.contracted_item_payload(
        ctx["deal_id"],
        manufacturer_sku=BRISKET_SKU,
        normalized_item_key=BRISKET_KEY,
        pack_size=20,
        baseline_unit_cost_cents=14200,
        contract_unit_cost_cents=13100,
    )


def _future_card_payload(ctx: dict) -> dict:
    return F.flat_rate_card_payload(
        ctx["item_id"],
        ctx["item_v2"],
        flat_rate_cents_per_case=175,
        effective_from="2029-01-01",
        effective_to="2029-12-31",
    )


def test_child_writes_are_blocked_while_the_parent_deal_is_suspended():
    """Both child endpoints are gated on a DIFFERENT row's state: the payloads
    are perfectly valid and the 2029 card window overlaps nothing, yet both are
    refused because the parent deal is SUSPENDED.

    PRD 3.2: "Items may only be added while the deal's `status` is `DRAFT` or
    `ACTIVE`; a `SUSPENDED` or `LOST` deal is closed to changes and rejects the
    attempt with `ERR_DEAL_NOT_OPEN_FOR_CHANGES`."

    Design: Corner/validations/child_writes_are_blocked_while_the_parent_deal_is_suspended
    """
    ctx = _suspended_deal_with_active_children()

    item_attempt = api_client.create_contracted_item(_brisket_item_payload(ctx), fx.ADMIN)
    validate_error(item_attempt, ApiErrorId.ERR_DEAL_NOT_OPEN_FOR_CHANGES, 409)

    card_attempt = api_client.create_rate_card(_future_card_payload(ctx), fx.ADMIN)
    validate_error(card_attempt, ApiErrorId.ERR_DEAL_NOT_OPEN_FOR_CHANGES, 409)

    _, item_meta = validate_paginated(
        api_client.list_contracted_items(
            fx.ADMIN, {"deal_id": ctx["deal_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert item_meta["total_count"] == 1, "neither rejected call stored anything"
    _, card_meta = validate_paginated(api_client.list_rate_cards(fx.ADMIN, fx.WIDE))
    assert card_meta["total_count"] == 1
    assert fx.read_item(ctx["item_id"])["version"] == ctx["item_v2"]


def test_the_identical_child_write_succeeds_once_the_deal_is_resumed():
    """Resuming the deal makes the very same item payload land, so the rejection
    was purely the parent's state and never the payload.

    PRD 3.2: "a `SUSPENDED` deal can be resumed, moving `SUSPENDED → ACTIVE` and
    again incrementing `version` by 1".

    Design: Corner/validations/child_writes_are_blocked_while_the_parent_deal_is_suspended
    """
    ctx = _suspended_deal_with_active_children()
    payload = _brisket_item_payload(ctx)
    validate_error(
        api_client.create_contracted_item(payload, fx.ADMIN),
        ApiErrorId.ERR_DEAL_NOT_OPEN_FOR_CHANGES,
        409,
    )

    resumed = validate_success(api_client.resume_deal(ctx["deal_id"], fx.ADMIN), 200)
    assert_deal(resumed)
    assert resumed["status"] == DealStatus.ACTIVE.value

    item2 = validate_success(
        api_client.create_contracted_item(payload, fx.ADMIN), 201
    )
    assert_contracted_item(item2)
    assert item2["status"] == ItemStatus.ACTIVE.value
    assert item2["approved_rate_card_count"] == 0
    assert item2["manufacturer_sku"] == BRISKET_SKU

    first_item = fx.read_item(ctx["item_id"])
    assert first_item["version"] == ctx["item_v2"], "the DRAFT-era item is untouched"
    assert first_item["status"] == ItemStatus.ACTIVE.value
    assert first_item["approved_rate_card_count"] == 1


# --------------------------------------------------------------------------
# instance: a_reconciled_period_refuses_a_restated_claim
# --------------------------------------------------------------------------


def _june_period_reconciled() -> dict:
    """One 30-case line accrued at gross 4500, and a June claim of 30 units /
    4500 cents reconciled at variance_bps 0."""
    ctx = fx.setup_flat_program()
    fx.ingest_june_feed(ctx, second_line=False)
    fx.normalize_june_feed(ctx)
    fx.accrue_june_feed(ctx)
    assert ctx["accrual_a"]["gross_rebate_cents"] == 4500
    fx.reconciled_claim_for_june(ctx, 30, 4500)
    ctx["deal_v2"] = fx.deal_version(ctx["deal_id"])
    return ctx


def _restated_june_claim(ctx: dict) -> dict:
    return F.claim_payload(ctx["deal_id"], ctx["deal_v2"], 30, 4400)


def _july_claim(ctx: dict) -> dict:
    return F.claim_payload(
        ctx["deal_id"],
        ctx["deal_v2"],
        0,
        0,
        period_start=C.JULY_START,
        period_end=C.JULY_END,
    )


def test_a_reconciled_period_refuses_a_restated_claim():
    """Restatement is legal only while the incumbent is open: a second claim for
    a period already RECONCILED is refused outright rather than superseding it,
    and it does not bump the deal's version.

    PRD 3.5: "A period that has already been settled cannot be reopened: when a
    claim whose `status` is `RECONCILED` already exists for the same `deal_id`,
    `period_start` and `period_end`, the new filing is rejected with
    `ERR_CLAIM_PERIOD_ALREADY_RECONCILED`."

    Design: Corner/validations/a_reconciled_period_refuses_a_restated_claim
    """
    ctx = _june_period_reconciled()
    incumbent = fx.read_claim(ctx["claim_id"])
    assert incumbent["status"] == ClaimStatus.RECONCILED.value
    assert incumbent["accrued_amount_cents"] == 4500
    assert incumbent["variance_bps"] == 0
    assert incumbent["reconciled_at"] is not None

    response = api_client.create_claim(_restated_june_claim(ctx), fx.REP)
    validate_error(response, ApiErrorId.ERR_CLAIM_PERIOD_ALREADY_RECONCILED, 409)

    still = fx.read_claim(ctx["claim_id"])
    assert still["status"] == ClaimStatus.RECONCILED.value
    assert still["claimed_amount_cents"] == 4500
    assert fx.read_deal(ctx["deal_id"])["version"] == ctx["deal_v2"], (
        "a rejected claim create bumps nothing"
    )
    _, meta = validate_paginated(
        api_client.list_claims(fx.ANALYST, {"deal_id": ctx["deal_id"]})
    )
    assert meta["total_count"] == 1


def test_a_different_period_is_unaffected_by_the_reconciled_one():
    """A July claim on the same deal still lands SUBMITTED, and it bumps the
    deal's version by exactly 1 — the refusal above was period-scoped.

    PRD 3.5: "A filing that survives those checks stores a claim with `status` of
    `SUBMITTED`, `accrued_amount_cents` of 0, `variance_bps` of 0 and
    `reconciled_at` null, and it advances the owning deal's `version` by exactly
    1 for the call as a whole."

    Design: Corner/validations/a_reconciled_period_refuses_a_restated_claim
    """
    ctx = _june_period_reconciled()
    validate_error(
        api_client.create_claim(_restated_june_claim(ctx), fx.REP),
        ApiErrorId.ERR_CLAIM_PERIOD_ALREADY_RECONCILED,
        409,
    )

    july = validate_success(api_client.create_claim(_july_claim(ctx), fx.REP), 201)
    assert july["status"] == ClaimStatus.SUBMITTED.value
    assert july["period_start"] == C.JULY_START
    assert july["period_end"] == C.JULY_END
    assert july["accrued_amount_cents"] == 0
    assert july["reconciled_at"] is None

    assert fx.read_deal(ctx["deal_id"])["version"] == ctx["deal_v2"] + 1

    rows, meta = validate_paginated(
        api_client.list_claims(
            fx.ANALYST, {"deal_id": ctx["deal_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 2
    assert all(
        row["status"] != ClaimStatus.SUPERSEDED.value for row in rows
    ), "the reconciled claim was never superseded"
