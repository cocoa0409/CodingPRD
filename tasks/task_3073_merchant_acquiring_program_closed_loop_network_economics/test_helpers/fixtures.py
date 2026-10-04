"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only the endpoints the
requirements declare. All setup uses ``get_success_data()`` (the lenient
validator) so a broken precondition surfaces as a clear "setup failed" error
rather than a confusing assertion failure inside a test.

Entity-backed roles (``Merchant``, ``CardMember``) are always threaded through
their per-instance header builders — a shared constant would carry an
``X-User-ID`` that never equals a real row's ``id`` and every ownership check
would reject.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC,
    VOLUME_THRESHOLD_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    create_industry_category_payload,
    create_merchant_payload,
    create_settlement_payload,
    create_cardmember_payload,
    create_offer_payload,
    create_redemption_pool_payload,
    create_annual_fee_statement_payload,
    create_dispute_payload,
    create_complaint_payload,
    create_declined_attempt_payload,
    rollup_acceptance_gap_payload,
    accept_merchant_payload,
    set_monthly_spend_payload,
    offer_consent_payload,
)
from .test_users import TEST_USERS, make_merchant_headers, make_cardmember_headers


# ═══ Convenience header aliases ═════════════════════════

ACQ = TEST_USERS["network_acquirer_headers"]
SETTLE = TEST_USERS["network_settlement_ops_headers"]
COMPLIANCE = TEST_USERS["network_compliance_headers"]
STEWARD = TEST_USERS["network_data_steward_headers"]
DISPUTE_OPS = TEST_USERS["network_dispute_ops_headers"]
SERVICE = TEST_USERS["network_service_headers"]
ISSUER = TEST_USERS["network_issuer_headers"]


# ═══ Tier 0: Clock ═══════════════════════════════════════

def set_clock(current_utc: str = DEFAULT_CLOCK_UTC) -> dict:
    """Advance the logical clock to ``current_utc``."""
    res = api_client.set_current_utc({"current_utc": current_utc}, ISSUER)
    return get_success_data(res)


# ═══ Tier 1: State progression ═══════════════════════════

def create_industry_category(**overrides) -> dict:
    """Create an IndustryCategory. Defaults to a MEDIUM-tier 250 bps category."""
    res = api_client.create_industry_category(
        create_industry_category_payload(**overrides), ACQ)
    return get_success_data(res)


def create_unique_industry_category(**overrides) -> dict:
    """Create an IndustryCategory with a distinct generated `industry_code`.

    `industry_code` is unique across the category population, so a single test
    that needs several categories must mint a fresh code per call.
    """
    overrides.setdefault("industry_code", "MCC-" + uuid.uuid4().hex[:12])
    return create_industry_category(**overrides)


def create_merchant(industry_category_id: str, **overrides) -> dict:
    """Create a Merchant, landing in PROSPECT.

    `merchant_name` is unique across the merchant population, so a test that
    creates more than one merchant gets a distinct name unless it pins one.
    """
    overrides.setdefault("merchant_name", "Merchant " + uuid.uuid4().hex[:12])
    res = api_client.create_merchant(
        create_merchant_payload(industry_category_id, **overrides), ACQ)
    return get_success_data(res)


def accept_merchant(merchant: dict) -> dict:
    """PROSPECT → ACCEPTED, passing the merchant's current version as the
    expected version."""
    res = api_client.accept_merchant(
        merchant["id"],
        accept_merchant_payload(merchant["version"]),
        ACQ,
    )
    return get_success_data(res)


def activate_merchant(merchant: dict) -> dict:
    """ACCEPTED → ACTIVE."""
    res = api_client.activate_merchant(merchant["id"], ACQ)
    return get_success_data(res)


def mark_merchant_dormant(merchant: dict) -> dict:
    """ACTIVE → DORMANT."""
    res = api_client.mark_merchant_dormant(merchant["id"], ACQ)
    return get_success_data(res)


def suppress_merchant(merchant_id: str) -> dict:
    """Suppress a merchant (terminal).

    Returns the raw ``requests.Response`` so tests that need the whole
    response (e.g. calling ``validate_success`` on it) can pass it straight
    through; callers that only want the body use ``get_success_data``.
    """
    return api_client.suppress_merchant(merchant_id, COMPLIANCE)


def archive_merchant(merchant_id: str) -> dict:
    """Operator archive: move the merchant to the terminal SUPPRESSED state.

    Returns the raw ``requests.Response`` so ``validate_success`` can be
    applied to it; body-only callers use ``get_success_data``.
    """
    return api_client.archive_merchant(merchant_id, COMPLIANCE)


def return_offer_to_draft(offer_id: str) -> dict:
    """PRIVACY_REVIEW → DRAFT, resetting the audience figures."""
    return get_success_data(api_client.return_offer_to_draft(offer_id, STEWARD))


def suspend_offer(offer_id: str) -> dict:
    """LIVE → MERCHANT_CONSENT."""
    return get_success_data(api_client.suspend_offer(offer_id, STEWARD))


def pay_offer_acceptance(acceptance_id: str) -> dict:
    return get_success_data(api_client.pay_offer_acceptance(acceptance_id, STEWARD))


def reverse_offer_acceptance(acceptance_id: str) -> dict:
    return get_success_data(api_client.reverse_offer_acceptance(acceptance_id, STEWARD))


def take_down_offer(offer_id: str) -> dict:
    """Alias for suspending a live offer."""
    return suspend_offer(offer_id)


def create_and_accept_merchant(industry_category_id: str, **overrides) -> dict:
    """Create a Merchant and drive it to ACCEPTED. Returns the merchant."""
    merchant = create_merchant(industry_category_id, **overrides)
    return accept_merchant(merchant)


def create_and_activate_merchant(industry_category_id: str, **overrides) -> dict:
    """Create a Merchant and drive it PROSPECT → ACCEPTED → ACTIVE."""
    merchant = create_and_accept_merchant(industry_category_id, **overrides)
    return activate_merchant(merchant)


def create_merchant_in_state(industry_category_id: str, target_state: str,
                             **overrides) -> dict:
    """Walk the acceptance machine to ``target_state``.

    Supported targets: PROSPECT, ACCEPTED, ACTIVE, DORMANT.
    """
    merchant = create_merchant(industry_category_id, **overrides)
    if target_state == "PROSPECT":
        return merchant
    merchant = accept_merchant(merchant)
    if target_state == "ACCEPTED":
        return merchant
    merchant = activate_merchant(merchant)
    if target_state == "ACTIVE":
        return merchant
    merchant = mark_merchant_dormant(merchant)
    if target_state == "DORMANT":
        return merchant
    raise ValueError(f"Unsupported target_state: {target_state}")


# ═══ Tier 1b: Card member progression ════════════════════

def create_cardmember(**overrides) -> dict:
    """Register a CardMember (lands in PENDING)."""
    res = api_client.create_cardmember(create_cardmember_payload(**overrides), ISSUER)
    return get_success_data(res)


def activate_cardmember(cardmember: dict) -> dict:
    """PENDING → ACTIVE."""
    res = api_client.activate_cardmember(cardmember["id"], ISSUER)
    return get_success_data(res)


def set_member_spend(cardmember_id: str, cents: int) -> dict:
    """Set the member's trailing lowest calendar-month spend."""
    res = api_client.set_cardmember_monthly_spend(
        cardmember_id, set_monthly_spend_payload(cents), ISSUER)
    return get_success_data(res)


def create_active_cardmember(**overrides) -> dict:
    """Register a CardMember and activate it. Returns the member."""
    member = create_cardmember(**overrides)
    return activate_cardmember(member)


def create_active_member_with_spend(cents: int = TEST_DEFAULTS["MEMBER_TRAILING_SPEND_CENTS"],
                                    **overrides) -> dict:
    """An ACTIVE member whose trailing lowest-month spend is ``cents``."""
    member = create_active_cardmember(**overrides)
    return set_member_spend(member["id"], cents)


# ═══ Tier 2: Merchant + category + member composite ══════

def setup_merchant_and_member(risk_tier: str = "MEDIUM",
                              base_discount_rate_bps: int = 250,
                              high_risk_flag: bool = False,
                              merchant_state: str = "ACTIVE",
                              merchant_overrides: dict = None,
                              member_spend_cents: int = None,
                              member_overrides: dict = None):
    """An IndustryCategory, a merchant in ``merchant_state``, and an active
    card member. Returns (category, merchant, member)."""
    category = create_unique_industry_category(
        risk_tier=risk_tier,
        base_discount_rate_bps=base_discount_rate_bps,
        high_risk_flag=high_risk_flag,
    )
    merchant = create_merchant_in_state(
        category["id"], merchant_state, **(merchant_overrides or {}))
    member = create_active_cardmember(**(member_overrides or {}))
    if member_spend_cents is not None:
        member = set_member_spend(member["id"], member_spend_cents)
    return category, merchant, member


# ═══ Tier 2b: Offers ═════════════════════════════════════

def create_offer(merchant_id: str, **overrides) -> dict:
    """Create an Offer (lands in DRAFT)."""
    res = api_client.create_offer(create_offer_payload(merchant_id, **overrides), STEWARD)
    return get_success_data(res)


def submit_offer_review(offer_id: str) -> dict:
    """DRAFT → PRIVACY_REVIEW (computes the audience)."""
    return get_success_data(api_client.submit_offer_review(offer_id, STEWARD))


def request_offer_consent(offer_id: str) -> dict:
    """PRIVACY_REVIEW → MERCHANT_CONSENT."""
    return get_success_data(api_client.request_offer_consent(offer_id, STEWARD))


def consent_offer(offer_id: str, merchant_id: str, expected_version=None,
                  live_start_utc=None, live_end_utc=None) -> dict:
    """MERCHANT_CONSENT → LIVE. ``expected_version`` is optional on the
    contract; when omitted the field is left out of the body entirely."""
    payload = offer_consent_payload()
    if expected_version is not None:
        payload["expected_offer_version"] = expected_version
    if live_start_utc is not None:
        payload["live_start_utc"] = live_start_utc
    if live_end_utc is not None:
        payload["live_end_utc"] = live_end_utc
    res = api_client.consent_offer(offer_id, payload, make_merchant_headers(merchant_id))
    return get_success_data(res)


def setup_offer_in_state(merchant_id: str, target_state: str,
                         offer_overrides: dict = None,
                         live_start_utc=None, live_end_utc=None) -> dict:
    """Walk the offer privacy machine to ``target_state``.

    Supported: DRAFT, PRIVACY_REVIEW, MERCHANT_CONSENT, LIVE.
    """
    offer = create_offer(merchant_id, **(offer_overrides or {}))
    if target_state == "DRAFT":
        return offer
    offer = submit_offer_review(offer["id"])
    if target_state == "PRIVACY_REVIEW":
        return offer
    offer = request_offer_consent(offer["id"])
    if target_state == "MERCHANT_CONSENT":
        return offer
    offer = consent_offer(offer["id"], merchant_id,
                          expected_version=offer["version"],
                          live_start_utc=live_start_utc,
                          live_end_utc=live_end_utc)
    if target_state == "LIVE":
        return offer
    raise ValueError(f"Unsupported target_state: {target_state}")


# ═══ Tier 2c: Redemption pools ═══════════════════════════

def create_redemption_pool(offer_id: str, **overrides) -> dict:
    """Create the funded redemption pool for an offer."""
    res = api_client.create_redemption_pool(
        offer_id, create_redemption_pool_payload(**overrides), STEWARD)
    return get_success_data(res)


def get_offer_pool(offer_id: str) -> dict:
    """The 1:1 pool read — returns the single pool object."""
    data = get_success_data(api_client.get_offer_redemption_pool(offer_id, STEWARD))
    if isinstance(data, list):
        assert len(data) >= 1, "expected a redemption pool for this offer"
        return data[0]
    return data


# ═══ Tier 3: Full lifecycle shortcuts ════════════════════

def setup_live_offer_with_pool(merchant_state: str = "ACTIVE",
                               member_spend_cents: int = TEST_DEFAULTS["MEMBER_TRAILING_SPEND_CENTS"],
                               reward_bps: int = 1000,
                               min_segment_spend_cents: int = 10000,
                               pool_initial_funded_cents: int = TEST_DEFAULTS["POOL_INITIAL_FUNDED_CENTS"],
                               risk_tier: str = "MEDIUM",
                               member_overrides: dict = None):
    """Merchant (ACTIVE) + active member with spend + LIVE offer + funded pool.

    Returns (category, merchant, member, offer, pool)."""
    category, merchant, member = setup_merchant_and_member(
        risk_tier=risk_tier,
        merchant_state=merchant_state,
        member_spend_cents=member_spend_cents,
        member_overrides=member_overrides,
    )
    offer = create_offer(
        merchant["id"],
        reward_bps=reward_bps,
        min_segment_spend_cents=min_segment_spend_cents,
    )
    pool = create_redemption_pool(
        offer["id"], initial_funded_cents=pool_initial_funded_cents)
    offer = submit_offer_review(offer["id"])
    offer = request_offer_consent(offer["id"])
    offer = consent_offer(offer["id"], merchant["id"], expected_version=offer["version"])
    return category, merchant, member, offer, pool


def accept_and_approve_offer(offer_id: str, cardmember_id: str,
                             trigger_amount_cents: int = TEST_DEFAULTS["TRIGGER_AMOUNT_CENTS"]):
    """Card member accepts a live offer, then the steward approves it.

    Returns (acceptance, pool_before_approve, pool_after_approve)."""
    pool_before = get_offer_pool(offer_id)
    acc = get_success_data(api_client.accept_offer(
        offer_id,
        {"cardmember_id": cardmember_id, "trigger_amount_cents": trigger_amount_cents},
        make_cardmember_headers(cardmember_id),
    ))
    get_success_data(api_client.approve_offer_acceptance(acc["id"], STEWARD))
    approval = get_success_data(api_client.get_offer_acceptance(acc["id"], STEWARD))
    pool_after = get_offer_pool(offer_id)
    return approval, pool_before, pool_after


# ═══ Tier 3b: Settlements and funding batches ════════════

def capture_settlement(merchant_id: str, **overrides) -> dict:
    """Capture a settlement; the server assigns the next funding batch seq."""
    res = api_client.create_settlement(
        merchant_id, create_settlement_payload(**overrides), SETTLE)
    return get_success_data(res)


def finalize_batch(merchant_id: str, batch_seq: int) -> dict:
    """Finalize a funding batch. Returns the updated Merchant."""
    res = api_client.finalize_funding_batch(merchant_id, batch_seq, SETTLE)
    return get_success_data(res)


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, SETTLE))


def get_merchant(merchant_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, headers or ACQ))


def submit_declined_attempt(merchant_id: str, **overrides) -> dict:
    """Record a declined card attempt at a merchant."""
    res = api_client.create_declined_attempt(
        merchant_id, create_declined_attempt_payload(**overrides), ACQ)
    return get_success_data(res)


def rollup_gap(region_code: str, industry_category_id: str,
               window_start: str, window_end: str, window_days: int = 30) -> dict:
    """Roll up acceptance gaps for a region + industry over a window."""
    res = api_client.rollup_acceptance_gaps(
        rollup_acceptance_gap_payload(
            region_code, industry_category_id, window_start, window_end, window_days),
        ACQ)
    return get_success_data(res)


def stamp_sweep(sweep_index: int, rolled_at: str = "2026-09-01T00:00:00Z") -> dict:
    """Stamp the next rollup sweep generation."""
    res = api_client.stamp_sweep_index(
        {"sweep_index": sweep_index, "rolled_at": rolled_at}, ACQ)
    return get_success_data(res)


def get_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_offer(offer_id, headers or STEWARD))


def list_offers(params=None, headers=None):
    data = get_success_data(api_client.list_offers(headers or STEWARD, params=params))
    return data if isinstance(data, list) else [data]


def get_cardmember(cardmember_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cardmember(cardmember_id, headers or ISSUER))


def get_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, SERVICE))


def list_acceptance_gaps(params=None):
    data = get_success_data(api_client.list_acceptance_gaps(ACQ, params=params))
    return data if isinstance(data, list) else [data]


def list_merchants(params=None):
    data = get_success_data(api_client.list_merchants(ACQ, params=params))
    return data if isinstance(data, list) else [data]


def list_industry_categories(params=None):
    data = get_success_data(api_client.list_industry_categories(ACQ, params=params))
    return data if isinstance(data, list) else [data]


def get_merchant_risk_state(merchant_id: str) -> dict:
    """The 1:1 merchant risk-state read — returns the single row."""
    data = get_success_data(api_client.get_merchant_risk_state(merchant_id, ACQ))
    if isinstance(data, list):
        assert len(data) >= 1, "expected a risk-state row for this merchant"
        return data[0]
    return data


def risk_state_for_merchant(merchant_id: str, headers=None) -> dict:
    """Fetch the risk-state row for a merchant through the filtered collection
    read (used when the 1:1 path is not the stated interface)."""
    data = get_success_data(api_client.list_merchant_risk_states(
        headers or ACQ, params={"merchant_id": merchant_id}))
    if isinstance(data, list):
        assert len(data) >= 1, "expected a risk-state row for this merchant"
        return data[0]
    return data


# ═══ Tier 3c: Disputes ═══════════════════════════════════

def open_dispute(cardmember_id: str, original_merchant_id: str,
                 final_merchant_id: str = None, amount_cents: int = 100000) -> dict:
    """Open a dispute as the member."""
    if final_merchant_id is None:
        final_merchant_id = original_merchant_id
    res = api_client.create_dispute(
        create_dispute_payload(cardmember_id, original_merchant_id,
                               final_merchant_id, amount_cents),
        make_cardmember_headers(cardmember_id))
    return get_success_data(res)


def respond_to_dispute(dispute: dict, original_merchant_id: str) -> dict:
    """The originating merchant responds (requires amount >= the minimum)."""
    res = api_client.respond_to_dispute(
        dispute["id"], make_merchant_headers(original_merchant_id))
    return get_success_data(res)


def resolve_dispute(dispute_id: str, outcome: str) -> dict:
    res = api_client.resolve_dispute(dispute_id, {"outcome": outcome}, DISPUTE_OPS)
    return get_success_data(res)


def get_dispute(dispute_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_dispute(dispute_id, headers or DISPUTE_OPS))


def create_responded_dispute(merchant_id: str, cardmember_id: str,
                             amount_cents: int = 100000,
                             final_merchant_id: str = None) -> dict:
    """Open → respond. Returns the MERCHANT_RESPONDED dispute."""
    dispute = open_dispute(cardmember_id, merchant_id, final_merchant_id, amount_cents)
    return respond_to_dispute(dispute, merchant_id)


# ═══ Tier 3d: Support tickets ════════════════════════════

def file_complaint(merchant_id: str, cardmember_id: str, **overrides) -> dict:
    """File an acceptance complaint (lands in FILED)."""
    res = api_client.create_complaint(
        create_complaint_payload(merchant_id, cardmember_id, **overrides),
        make_cardmember_headers(cardmember_id))
    return get_success_data(res)


def take_up_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.take_up_complaint(complaint_id, SERVICE))


def uphold_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.uphold_complaint(complaint_id, SERVICE))


def dismiss_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.dismiss_complaint(complaint_id, SERVICE))


# ═══ Tier 3e: Annual fee statements ══════════════════════

def create_annual_fee_statement(cardmember_id: str, **overrides) -> dict:
    res = api_client.create_annual_fee_statement(
        create_annual_fee_statement_payload(cardmember_id, **overrides), ISSUER)
    return get_success_data(res)


def assess_statement(statement_id: str) -> dict:
    return get_success_data(api_client.assess_annual_fee_statement(statement_id, ISSUER))


def disburse_statement(statement_id: str) -> dict:
    return get_success_data(api_client.disburse_annual_fee_statement(statement_id, ISSUER))


def void_statement(statement_id: str) -> dict:
    return get_success_data(api_client.void_annual_fee_statement(statement_id, ISSUER))


def get_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_annual_fee_statement(statement_id, ISSUER))


def list_ledger(source_statement_id: str = None):
    params = {"source_statement_id": source_statement_id} if source_statement_id else None
    data = get_success_data(api_client.list_value_fund_ledger(ISSUER, params=params))
    return data if isinstance(data, list) else [data]


# ═══ Tier 4: Accumulation / threshold targeting ══════════

def setup_merchant_near_volume_threshold(base_discount_rate_bps: int = 250,
                                         risk_tier: str = "HIGH",
                                         high_risk_flag: bool = True,
                                         monthly_billed_below_cents: int = None,
                                         refund_volume_cents: int = 0):
    """A merchant whose month-to-date billed volume lands exactly on the
    FIXED-tier threshold once one settlement matures.

    Builds: category → merchant → accept → activate → settlement(batch 1) →
    settlement(batch 2, same gross) → finalize batch 1 → finalize batch 2.
    Exactly one of the two settlements matures; both carry the same gross so the
    resulting settled volume is the same under either promotion reading.

    Returns (category, merchant, {settlement_1_id, settlement_2_id})."""
    if monthly_billed_below_cents is None:
        monthly_billed_below_cents = VOLUME_THRESHOLD_CENTS
    category = create_industry_category(
        risk_tier=risk_tier,
        base_discount_rate_bps=base_discount_rate_bps,
        high_risk_flag=high_risk_flag,
    )
    merchant = create_and_activate_merchant(category["id"])
    s1 = capture_settlement(
        merchant["id"], settlement_cycle=1, gross_volume_cents=monthly_billed_below_cents,
        refund_volume_cents=refund_volume_cents)
    s2 = capture_settlement(
        merchant["id"], settlement_cycle=2, gross_volume_cents=monthly_billed_below_cents,
        refund_volume_cents=refund_volume_cents)
    finalize_batch(merchant["id"], 1)
    merchant = finalize_batch(merchant["id"], 2)
    return category, merchant, {"settlement_1_id": s1["id"], "settlement_2_id": s2["id"]}


def setup_high_risk_merchant_with_settled_volume(settled_volume_cents: int,
                                                 base_discount_rate_bps: int = 250,
                                                 risk_tier: str = "HIGH",
                                                 high_risk_flag: bool = True):
    """A HIGH-risk merchant holding exactly ``settled_volume_cents`` of trailing
    SETTLED volume.

    Builds: category → merchant → accept → activate → settlement(batch 1) →
    settlement(batch 2, zero gross) → finalize batch 2. Exactly one settlement
    matures; the zero-gross twin contributes nothing to the settled total either
    way, so the settled volume is deterministic.

    Returns (category, merchant, {settlement_1_id, settlement_2_id})."""
    category = create_industry_category(
        risk_tier=risk_tier,
        base_discount_rate_bps=base_discount_rate_bps,
        high_risk_flag=high_risk_flag,
    )
    merchant = create_and_activate_merchant(category["id"])
    s1 = capture_settlement(
        merchant["id"], settlement_cycle=1, gross_volume_cents=settled_volume_cents,
        refund_volume_cents=0)
    s2 = capture_settlement(
        merchant["id"], settlement_cycle=2, gross_volume_cents=0, refund_volume_cents=0)
    # Batch 1 must be finalized FIRST: a settlement still IN_FUNDING is promoted
    # to SETTLED only by the finalize of a strictly later batch ordinal (PRD
    # §3.3), so finalizing batch 2 alone leaves settlement 1 sitting CAPTURED and
    # the merchant's settled volume at zero.
    finalize_batch(merchant["id"], 1)
    merchant = finalize_batch(merchant["id"], 2)
    return category, merchant, {"settlement_1_id": s1["id"], "settlement_2_id": s2["id"]}


def create_captured_settlement_for_merchant(merchant_id: str, gross_volume_cents: int,
                                            settlement_cycle: int = 1):
    """Capture one settlement and return it (still CAPTURED)."""
    return capture_settlement(
        merchant_id, settlement_cycle=settlement_cycle,
        gross_volume_cents=gross_volume_cents, refund_volume_cents=0)


def setup_settlements_in_two_batches(merchant_id: str, batch1_gross_cents: int = 500000,
                                     batch2_gross_cents: int = 500000,
                                     finalize_second_batch: bool = True):
    """Two settlements in distinct funding batches; optionally finalize batch 2
    so exactly one of them matures.

    Returns (merchant_after, {settlement_1_id, settlement_2_id})."""
    s1 = capture_settlement(merchant_id, settlement_cycle=1,
                            gross_volume_cents=batch1_gross_cents, refund_volume_cents=0)
    s2 = capture_settlement(merchant_id, settlement_cycle=2,
                            gross_volume_cents=batch2_gross_cents, refund_volume_cents=0)
    merchant = get_merchant(merchant_id)
    if finalize_second_batch:
        merchant = finalize_batch(merchant_id, 2)
    return merchant, {"settlement_1_id": s1["id"], "settlement_2_id": s2["id"]}


def setup_acceptance_gap_with_declines(decline_count: int,
                                       decline_amount_cents: int = 100000,
                                       risk_tier: str = "MEDIUM",
                                       region_code: str = "US-NE",
                                       window_start: str = "2026-08-01T00:00:00Z",
                                       window_end: str = "2026-08-31T00:00:00Z",
                                       window_days: int = 30,
                                       decline_reason: str = "MERCHANT_NOT_ACCEPTED"):
    """A category plus a merchant, with ``decline_count`` declines recorded in
    the window and one rollup performed.

    Returns (category, merchant, gap)."""
    category = create_industry_category(risk_tier=risk_tier)
    merchant = create_merchant(category["id"], region_code=region_code)
    for i in range(decline_count):
        submit_declined_attempt(
            merchant["id"],
            attempted_amount_cents=decline_amount_cents,
            decline_reason=decline_reason,
            occurred_at=f"2026-08-{10 + i:02d}T00:00:00Z",
        )
    gap = rollup_gap(region_code, category["id"], window_start, window_end, window_days)
    return category, merchant, gap


def setup_offer_pool_with_approval(reward_bps: int = 1000,
                                   trigger_amount_cents: int = TEST_DEFAULTS["TRIGGER_AMOUNT_CENTS"],
                                   pool_initial_funded_cents: int = TEST_DEFAULTS["POOL_INITIAL_FUNDED_CENTS"],
                                   member_spend_cents: int = TEST_DEFAULTS["MEMBER_TRAILING_SPEND_CENTS"]):
    """A LIVE offer with a funded pool and one APPROVED acceptance.

    Returns (category, merchant, member, offer, acceptance, pool_after_approve)."""
    category, merchant, member, offer, pool = setup_live_offer_with_pool(
        reward_bps=reward_bps,
        member_spend_cents=member_spend_cents,
        pool_initial_funded_cents=pool_initial_funded_cents,
    )
    approval, _, pool_after = accept_and_approve_offer(
        offer["id"], member["id"], trigger_amount_cents=trigger_amount_cents)
    return category, merchant, member, offer, approval, pool_after


# ═══ Tier 5: Finalization / terminal state ═══════════════

def setup_merchant_with_batches(batch_gross_list, risk_tier: str = "HIGH",
                                base_discount_rate_bps: int = 250,
                                high_risk_flag: bool = True,
                                finalize_seqs=None):
    """A merchant with one settlement per batch gross in ``batch_gross_list``.

    ``finalize_seqs`` lists which batch ordinals to finalize (default: only the
    last one). Returns (category, merchant, settlement_ids)."""
    category = create_industry_category(
        risk_tier=risk_tier,
        base_discount_rate_bps=base_discount_rate_bps,
        high_risk_flag=high_risk_flag,
    )
    merchant = create_and_activate_merchant(category["id"])
    ids = []
    for idx, gross in enumerate(batch_gross_list, start=1):
        s = capture_settlement(
            merchant["id"], settlement_cycle=idx, gross_volume_cents=gross,
            refund_volume_cents=0)
        ids.append(s["id"])
    seqs = finalize_seqs if finalize_seqs is not None else [len(batch_gross_list)]
    for seq in seqs:
        merchant = finalize_batch(merchant["id"], seq)
    return category, merchant, ids


def setup_merchant_in_prospect_after_sweep_cycle(member_spend_cents: int = None,
                                                 region_code: str = "US-NE"):
    """Drive the acceptance cycle ACTIVE → DORMANT → PROSPECT via the sweep guard.

    Builds: category → merchant → accept → activate → mark-dormant → four
    declines → one rollup (the gap qualifies PROSPECTING and the outlets it
    covers re-enter prospecting) → stamp the sweep at the merchant's
    status_version → one final decline that closes the cycle.

    Returns (category, merchant, gap, stamped_sweep_index)."""
    category = create_unique_industry_category(risk_tier="MEDIUM")
    merchant = create_and_activate_merchant(category["id"], region_code=region_code)
    merchant = mark_merchant_dormant(merchant)
    window_start = "2026-08-01T00:00:00Z"
    window_end = "2026-08-31T00:00:00Z"
    # All four declines land BEFORE the rollup: a rollup that qualifies the gap
    # re-enters every covered dormant outlet, and a rollup after the declines
    # would therefore move the outlet to PROSPECT on its own -- the single
    # rollup is what makes the sweep-generation guard the load-bearing check.
    for day in (10, 11, 12, 13):
        submit_declined_attempt(
            merchant["id"], attempted_amount_cents=100000,
            decline_reason="MERCHANT_NOT_ACCEPTED",
            occurred_at=f"2026-08-{day:02d}T00:00:00Z")
    gap = rollup_gap(region_code, category["id"], window_start, window_end, 30)
    current = get_merchant(merchant["id"])
    stamp_sweep(current["status_version"], rolled_at="2026-09-01T00:00:00Z")
    return category, get_merchant(merchant["id"]), gap, current["status_version"]