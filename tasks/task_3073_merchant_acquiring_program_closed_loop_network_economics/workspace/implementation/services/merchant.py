"""Merchant acceptance, settlement capture, funding batches and the reserve sweep."""

from datetime import timedelta
from decimal import Decimal

from clock import parse_iso
from errors import (
    ERR_BATCH_SEQ_NOT_MONOTONE,
    ERR_INVALID_STATE,
    ERR_MERCHANT_RISK_SUPPRESSED,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_SUPPRESS_ALREADY_TERMINAL,
    ApiError,
)
from services import pricing, risk

RESERVE_FLOOR_BPS = 500
WINDOW_DAYS = 90


# --------------------------------------------------------------------------
# Merchant lifecycle
# --------------------------------------------------------------------------

def recompute_pricing(store, merchant):
    """Re-derive `volume_tier` and the quoted rate, then stamp `updated_at`."""
    industry = pricing.industry_of(store, merchant)
    merchant["volume_tier"] = pricing.derive_volume_tier(merchant, industry)
    merchant["applied_discount_rate_bps"] = pricing.resolve_discount_rate(
        store, merchant, industry)
    merchant["updated_at"] = store.clock.now()
    return merchant


def touch(store, merchant):
    """Bump the merchant's version and refresh its updated_at."""
    merchant["version"] = merchant["version"] + 1
    merchant["updated_at"] = store.clock.now()


def assert_not_risk_suppressed(store, merchant):
    """Priority 7 on activation, suppression and settlement capture."""
    if risk.suppression_flag_of(store, merchant["id"]):
        raise ApiError(ERR_MERCHANT_RISK_SUPPRESSED)


def accept_merchant(store, merchant, expected_version, negotiated_rate_bps):
    if merchant["acceptance_status"] != "PROSPECT":
        raise ApiError(ERR_INVALID_STATE)
    if merchant["acquisition_channel"] == "DIRECT":
        if risk.suppression_flag_of(store, merchant["id"]):
            raise ApiError(ERR_MERCHANT_RISK_SUPPRESSED)
    if merchant["acquisition_channel"] == "THIRD_PARTY":
        if not merchant.get("channel_partner"):
            raise ApiError(ERR_INVALID_STATE)

    # OCC: this write sits on the cyclic acceptance machine.  It runs after the
    # state precondition, before the transition's side effects.
    if expected_version is not None and expected_version != merchant["version"]:
        raise ApiError(ERR_STALE_VERSION)

    if negotiated_rate_bps is not None:
        merchant["negotiated_rate_bps"] = negotiated_rate_bps

    merchant["acceptance_status"] = "ACCEPTED"
    merchant["status_version"] = merchant["status_version"] + 1
    recompute_pricing(store, merchant)
    touch(store, merchant)
    return merchant


def activate_merchant(store, merchant):
    if merchant["acceptance_status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_STATE)
    if risk.suppression_flag_of(store, merchant["id"]):
        raise ApiError(ERR_MERCHANT_RISK_SUPPRESSED)

    merchant["acceptance_status"] = "ACTIVE"
    merchant["status_version"] = merchant["status_version"] + 1
    merchant["reserve_required_cents"] = reserve_required(store, merchant)
    recompute_pricing(store, merchant)
    touch(store, merchant)
    return merchant


def mark_dormant(store, merchant):
    if merchant["acceptance_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)
    merchant["acceptance_status"] = "DORMANT"
    touch(store, merchant)
    return merchant


def suppress_merchant(store, merchant, risk_gated=True):
    """The largest cascade in the system: offers, then settlements, then the
    merchant's own terminal state.  No partial cascade is permitted."""
    if merchant["acceptance_status"] == "SUPPRESSED":
        raise ApiError(ERR_SUPPRESS_ALREADY_TERMINAL)
    if risk_gated:
        assert_not_risk_suppressed(store, merchant)
    if merchant["acceptance_status"] not in ("PROSPECT", "ACCEPTED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE)

    _cascade_offers(store, merchant["id"])
    _cascade_settlements(store, merchant)
    merchant["acceptance_status"] = "SUPPRESSED"
    touch(store, merchant)
    return merchant


def _cascade_offers(store, merchant_id):
    terminal = ("DRAFT", "PRIVACY_REVIEW", "MERCHANT_CONSENT", "LIVE")
    for offer in store.offers_for(merchant_id):
        if offer["privacy_state"] in terminal:
            offer["privacy_state"] = "TERMINATED"
            offer["version"] = offer["version"] + 1
            offer["updated_at"] = store.clock.now()


def _cascade_settlements(store, merchant):
    for settlement in store.settlements_for(merchant["id"]):
        if settlement["settlement_status"] in ("CAPTURED", "IN_FUNDING"):
            settlement["settlement_status"] = "REVERSED"
            settlement["final_discount_fee_cents"] = 0
            settlement["final_reserve_withholding_cents"] = 0
            settlement["net_funding_cents"] = 0
            settlement["version"] = settlement["version"] + 1
            settlement["updated_at"] = store.clock.now()
    recompute_trailing_volume(store, merchant)


# --------------------------------------------------------------------------
# Trailing volume and reserves
# --------------------------------------------------------------------------

def recompute_trailing_volume(store, merchant, window_end=None):
    """The two trailing ninety-day figures, in parallel.

    `rolling_90d_billed_volume_cents` is the provisional, merchant-facing figure
    (CAPTURED, IN_FUNDING or SETTLED inclusive); `rolling_90d_settled_volume_cents`
    is the final, reconciliation figure (SETTLED only).  Reversed settlements are
    excluded from both.  The provisional figure is the single stored value, so it
    is recomputed from the settlement population rather than accumulated.

    The band opens ninety days before the current logical clock, inclusive at the
    start.  Its end is the clock instant itself, which a row cannot post-date, so
    the end is inclusive of it; a clock wound backwards still excludes volume
    that would then lie in the future.
    """
    window_end = window_end or store.clock.now()
    window_start = window_end - timedelta(days=WINDOW_DAYS)
    provisional = 0
    final = 0
    for settlement in store.settlements_for(merchant["id"]):
        created = parse_iso(settlement["created_at"])
        if created is None:
            continue
        if not (window_start <= created <= window_end):
            continue
        if settlement["settlement_status"] in ("CAPTURED", "IN_FUNDING", "SETTLED"):
            provisional += settlement["post_refund_volume_cents"]
        if settlement["settlement_status"] == "SETTLED":
            final += settlement["post_refund_volume_cents"]
    merchant["rolling_90d_billed_volume_cents"] = provisional
    merchant["rolling_90d_settled_volume_cents"] = final
    return merchant


def reserve_required(store, merchant):
    industry = pricing.industry_of(store, merchant)
    if industry is None or industry["risk_tier"] != "HIGH":
        return 0
    floor = pricing.round_half_up(
        Decimal(merchant["rolling_90d_settled_volume_cents"])
        * Decimal(RESERVE_FLOOR_BPS) / Decimal(10000))
    # Ratchet: never decreases.
    return max(floor, merchant["reserve_required_cents"])


def refresh_trailing(store, merchant):
    """Re-evaluate the trailing-window rule against the current logical clock.

    Advancing the clock re-evaluates every deadline and window rule, and the
    trailing ninety-day band is a window rule: the figures are therefore
    recomputed whenever a merchant is read rather than only when it is written.
    """
    return recompute_trailing_volume(store, merchant)


# --------------------------------------------------------------------------
# Settlements
# --------------------------------------------------------------------------

def capture_settlement(store, merchant, settlement_cycle, gross_volume_cents,
                       refund_volume_cents):
    assert_not_risk_suppressed(store, merchant)
    for existing in store.settlements_for(merchant["id"]):
        if existing["settlement_cycle"] == settlement_cycle:
            raise ApiError(ERR_INVALID_STATE, "settlement_cycle must be unique per merchant.")

    settlement_id = store.new_id()
    now = store.clock.now()
    post_refund = gross_volume_cents - refund_volume_cents
    discount_fee = pricing.apply_bps(gross_volume_cents,
                                        merchant["applied_discount_rate_bps"])

    batch_seq = store.next_funding_batch_seq.get(merchant["id"], 0) + 1
    store.next_funding_batch_seq[merchant["id"]] = batch_seq

    settlement = {
        "id": settlement_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": store.next_created_seq(),
        "merchant_id": merchant["id"],
        "settlement_cycle": settlement_cycle,
        "gross_volume_cents": gross_volume_cents,
        "refund_volume_cents": refund_volume_cents,
        "post_refund_volume_cents": post_refund,
        "discount_fee_cents": discount_fee,
        "net_funding_cents": post_refund - discount_fee,
        "final_discount_fee_cents": 0,
        "final_reserve_withholding_cents": 0,
        "funding_batch_seq": batch_seq,
        "finalized_at_batch_seq": 0,
        "settlement_status": "CAPTURED",
    }
    store.settlements[settlement_id] = settlement
    recompute_trailing_volume(store, merchant)
    return settlement


def finalize_batch(store, merchant, batch_seq):
    """Seal a funding batch: discount, reserve sweep, promotion, batch total."""
    last_finalized = store.last_finalized_batch_seq.get(merchant["id"], 0)
    if batch_seq <= last_finalized:
        raise ApiError(ERR_BATCH_SEQ_NOT_MONOTONE)

    batch = sorted(
        [s for s in store.settlements_for(merchant["id"])
         if s["funding_batch_seq"] == batch_seq],
        key=lambda s: s["funding_batch_seq"],
    )
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "No settlements exist in this funding batch.")

    industry = pricing.industry_of(store, merchant)
    historical_rate = pricing.historical_discount_rate(store, merchant, industry, batch_seq)
    high_risk = industry is not None and industry["risk_tier"] == "HIGH"

    # Every precondition is checked before any change is committed, so a batch
    # is never half-finalized.
    for settlement in batch:
        if settlement["settlement_status"] != "CAPTURED":
            raise ApiError(ERR_INVALID_STATE)
        if settlement["funding_batch_seq"] != batch_seq:
            raise ApiError(ERR_INVALID_STATE)

    # Funding is released only to a live merchant.
    if merchant["acceptance_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)

    # The trailing window advances to the batch's finalize instant, so the
    # settlement's post-refund volume is absorbed once by the provisional figure
    # rather than accumulated on top of a stale reading.
    merge_end = store.clock.now()

    for settlement in batch:
        settlement["settlement_version_pending"] = settlement["version"] + 1

    # The maturation hop: any strictly smaller batch sequence already IN_FUNDING
    # is promoted to SETTLED.  Its own batch never promotes it, and the whole
    # batch is iterated in ascending funding_batch_seq order so that a merchant's
    # finalize order reproduces its chronological settlement order.
    to_promote = sorted(
        [s for s in store.settlements_for(merchant["id"])
         if s["settlement_status"] == "IN_FUNDING"
         and s["funding_batch_seq"] < batch_seq],
        key=lambda s: s["funding_batch_seq"],
    )
    for settlement in to_promote:
        settlement["settlement_status"] = "SETTLED"
        settlement["version"] = settlement["version"] + 1
        settlement["updated_at"] = merge_end
        merchant["billed_volume_mtd_cents"] = (
            merchant["billed_volume_mtd_cents"]
            + settlement["post_refund_volume_cents"])
        recompute_pricing(store, merchant)

    for settlement in batch:
        settlement["settlement_status"] = "IN_FUNDING"
        final_discount = pricing.apply_bps(settlement["gross_volume_cents"],
                                           historical_rate)
        settlement["final_discount_fee_cents"] = final_discount
        settlement["final_reserve_withholding_cents"] = 0
        settlement["finalized_at_batch_seq"] = batch_seq
        settlement["version"] = settlement.pop("settlement_version_pending")
        settlement["updated_at"] = merge_end

    # The trailing-volume rule runs for the merchant, then the reserve floor is
    # recomputed and immediately swept against each settlement of the batch (the
    # scaffold's documented side-effect order: volume, then reserve, then sweep).
    recompute_trailing_volume(store, merchant, window_end=merge_end)
    merchant["reserve_required_cents"] = reserve_required(store, merchant)

    if high_risk:
        for settlement in batch:
            withholding = reserve_sweep(store, merchant, settlement,
                                        settlement["final_discount_fee_cents"])
            settlement["final_reserve_withholding_cents"] = withholding

    # net_funding is sealed after the sweep, so it reflects the final withholding.
    for settlement in batch:
        settlement["net_funding_cents"] = (
            settlement["post_refund_volume_cents"]
            - settlement["final_discount_fee_cents"]
            - settlement["final_reserve_withholding_cents"])

    # The batch total is rounded exactly once, over the whole batch.
    gross_in_batch = sum(s["gross_volume_cents"] for s in batch)
    batch_discount = pricing.apply_bps(gross_in_batch,
                                       merchant["applied_discount_rate_bps"])
    merchant["last_batch_discount_fee_cents"] = batch_discount
    store.last_batch_discount_fee_cents[merchant["id"]] = batch_discount
    store.last_finalized_batch_seq[merchant["id"]] = batch_seq

    # Reconcile the figures against the batch's own finalize instant (the PRD
    # pins the trailing window to the clock at the moment of the change).
    recompute_trailing_volume(store, merchant, window_end=merge_end)
    merchant["reserve_required_cents"] = reserve_required(store, merchant)
    touch(store, merchant)
    return merchant


def reserve_sweep(store, merchant, settlement, final_discount_fee_cents):
    """Withhold the shortfall, capped by the settlement's net-of-discount volume.

    Withholding applies strictly while the shortfall is above zero.
    """
    shortfall = merchant["reserve_required_cents"] - merchant["reserve_held_cents"]
    if shortfall <= 0:
        return 0
    headroom = settlement["post_refund_volume_cents"] - final_discount_fee_cents
    withheld = min(shortfall, headroom)
    if withheld < 0:
        withheld = 0
    merchant["reserve_held_cents"] = merchant["reserve_held_cents"] + withheld
    return withheld


def posting_reversal(store, settlement):
    if settlement["settlement_status"] != "SETTLED":
        raise ApiError(ERR_INVALID_STATE)
    merchant = store.merchants.get(settlement["merchant_id"])
    settlement["settlement_status"] = "IN_FUNDING"
    settlement["version"] = settlement["version"] + 1
    settlement["updated_at"] = store.clock.now()
    if merchant is not None:
        merchant["billed_volume_mtd_cents"] = (
            merchant["billed_volume_mtd_cents"] - settlement["post_refund_volume_cents"])
        recompute_pricing(store, merchant)
        recompute_trailing_volume(store, merchant)
        touch(store, merchant)
    return settlement


def reinstate(store, settlement):
    if settlement["settlement_status"] != "REVERSED":
        raise ApiError(ERR_INVALID_STATE)
    settlement["settlement_status"] = "CAPTURED"
    settlement["final_discount_fee_cents"] = 0
    settlement["final_reserve_withholding_cents"] = 0
    settlement["net_funding_cents"] = 0
    settlement["version"] = settlement["version"] + 1
    settlement["updated_at"] = store.clock.now()
    merchant = store.merchants.get(settlement["merchant_id"])
    if merchant is not None:
        recompute_trailing_volume(store, merchant)
    return settlement