"""Routes: orders (conversions), the five-step attribution run, order
adjustments and the attribution audit rows (PRD 3.5 and 3.6)."""

import calc
import serializers as S
import services as SV
from common import (
    ADJUSTMENT_TYPES, OTHER_CHANNELS, PRODUCT_CATEGORIES, ROLE_COMPLIANCE,
    ROLE_FIN_ANALYST, ROLE_FIN_CONTROLLER, ROLE_INGESTOR, ROLE_PARTNER_MANAGER,
    ROLE_PROGRAM_ADMIN, authorize, body, db, fail, fmt_dt, get_bool, get_enum,
    get_instant, get_int, get_str, new_row, now_iso, ordered, paginate,
    parse_instant, query_filter, respond, touch,
)

READ_ROLES = [ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
              ROLE_FIN_ANALYST, ROLE_FIN_CONTROLLER]


def register(app):

    @app.post("/conversions")
    def create_conversion():
        authorize([ROLE_INGESTOR, ROLE_PROGRAM_ADMIN])
        payload = body()
        order_ref = get_str(payload, "order_ref", min_len=1, max_len=40)
        total = get_int(payload, "order_total_cents", min_v=1)
        category = get_enum(payload, "product_category", PRODUCT_CATEGORIES)
        customer_ref = get_str(payload, "customer_ref", min_len=1, max_len=64)
        is_new = get_bool(payload, "is_new_customer")
        placed_at = get_instant(payload, "placed_at")
        device_id = get_str(payload, "device_id", min_len=1, max_len=64)
        household_id = get_str(payload, "household_id", required=False,
                               default=None, min_len=1, max_len=64)
        coupon = get_str(payload, "coupon_code_used", required=False,
                         default=None, min_len=1, max_len=64)
        channel = get_enum(payload, "other_channel_touch", OTHER_CHANNELS,
                           required=False, default="NONE")
        touch_at = get_instant(payload, "other_channel_touch_at",
                               required=False, default=None)
        if channel != "NONE" and touch_at is None:
            fail("ERR_INVALID_REQUEST",
                 "other_channel_touch_at is required when other_channel_touch "
                 "is not NONE")
        for row in db.conversions.values():
            if row["order_ref"] == order_ref:
                fail("ERR_DUPLICATE_ORDER_REF", "order_ref is already recorded")
        row = new_row(
            order_ref=order_ref, order_total_cents=total,
            product_category=category, customer_ref=customer_ref,
            is_new_customer=is_new, placed_at=fmt_dt(placed_at),
            device_id=device_id, household_id=household_id,
            coupon_code_used=coupon, other_channel_touch=channel,
            other_channel_touch_at=None if touch_at is None else fmt_dt(touch_at),
            attribution_status="UNATTRIBUTED",
            validation_status="PENDING_VALIDATION",
            attributed_affiliate_id=None, attributed_click_id=None,
            commission_policy_id=None, candidate_click_count=0,
            gross_commission_cents=0, payable_commission_cents=0,
            clawed_back_cents=0, returned_amount_cents=0,
        )
        # The candidate set is sized at creation without selecting a winner.
        row["candidate_click_count"] = len(SV.eligible_clicks(row))
        db.conversions[row["id"]] = row
        return respond(S.conversion_out(row), 201)

    @app.get("/conversions/<cid>")
    def get_conversion(cid):
        authorize(READ_ROLES + [ROLE_INGESTOR])
        return respond(S.conversion_out(SV.find_conversion(cid)))

    @app.get("/conversions")
    def list_conversions():
        authorize(READ_ROLES)
        rows = ordered(db.conversions)
        rows = query_filter(rows, "attributed_affiliate_id")
        rows = query_filter(rows, "attributed_click_id")
        rows = query_filter(rows, "commission_policy_id")
        rows = query_filter(rows, "attribution_status")
        rows = query_filter(rows, "validation_status")
        return paginate(rows, S.conversion_out)

    @app.get("/conversions/<cid>/attribution-decisions")
    def list_decisions(cid):
        authorize(READ_ROLES)
        conv = SV.find_conversion(cid)
        rows = SV.decisions_of_conversion(conv["id"])
        rows = query_filter(rows, "algorithm_variant")
        return paginate(rows, S.decision_out)

    @app.post("/conversions/<cid>/attribute")
    def attribute_conversion(cid):
        authorize([ROLE_INGESTOR, ROLE_PROGRAM_ADMIN])
        conv = SV.find_conversion(cid)
        payload = body()
        expected = get_int(payload, "expected_conversion_version")
        if conv["attribution_status"] != "UNATTRIBUTED":
            fail("ERR_CONVERSION_ALREADY_ATTRIBUTED",
                 "the order has already been resolved on the credit dimension")
        if expected != conv["version"]:
            fail("ERR_STALE_CONVERSION_VERSION",
                 "expected_conversion_version does not match the order version")

        # Step one: the eligible click set.
        candidates = SV.eligible_clicks(conv)
        conv["candidate_click_count"] = len(candidates)

        # Step two: the winner.
        if not candidates:
            _write_pair(conv, None, "NONE", 0,
                        (0, 0, "NO_ELIGIBLE_CLICK"),
                        (0, 0, "NO_ELIGIBLE_CLICK"), "LAST_CLICK_RAW")
            conv["gross_commission_cents"] = 0
            conv["payable_commission_cents"] = 0
            touch(conv)
            return respond(S.conversion_out(conv))

        click, link, match_mode = SV.rank_candidates(candidates)[0]
        winning_at = click["occurred_at"]

        # Step three: deduplication against other channels.
        if conv["other_channel_touch"] != "NONE":
            touch_at = parse_instant(conv["other_channel_touch_at"])
            click_at = parse_instant(winning_at)
            if touch_at is not None and click_at is not None and touch_at > click_at:
                conv["attribution_status"] = "DEDUPED_TO_OTHER_CHANNEL"
                conv["attributed_click_id"] = click["id"]
                conv["attributed_affiliate_id"] = None
                conv["gross_commission_cents"] = 0
                conv["payable_commission_cents"] = 0
                _write_pair(conv, winning_at, match_mode,
                            conv["candidate_click_count"],
                            (0, 0, "OTHER_CHANNEL_LATER_TOUCH"),
                            (0, 0, "OTHER_CHANNEL_LATER_TOUCH"),
                            "LAST_CLICK_RAW")
                touch(conv)
                return respond(S.conversion_out(conv))

        affiliate = db.affiliates.get(link["affiliate_id"])
        if affiliate is None or affiliate["status"] != "ACTIVE":
            fail("ERR_AFFILIATE_SUSPENDED",
                 "the winning partner is not in good standing")

        # Step four: pricing.  The rate card selection aborts the whole run.
        policy = _select_policy(conv, affiliate)
        rate = (policy["new_customer_rate_bps"] if conv["is_new_customer"]
                else policy["returning_customer_rate_bps"])
        gross = calc.gross_commission_cents(conv["order_total_cents"], rate)

        # Step five: the credit share, read from the pre-state tier.
        coupon_override = (
            affiliate["partner_type"] in ("COUPON", "LOYALTY_CASHBACK")
            and conv["coupon_code_used"] is not None)
        if affiliate["incrementality_tier"] in ("MEDIUM", "HIGH") \
                and not coupon_override:
            selected = "LAST_CLICK_RAW"
            share = calc.FULL_CREDIT_SHARE_BPS
            new_status = "AFFILIATE_ATTRIBUTED"
            adj_dedup = "NONE"
        else:
            selected = "INCREMENTALITY_ADJUSTED"
            share = calc.INCREMENTALITY_CREDIT_SHARE_BPS
            new_status = "CREDIT_REDUCED"
            adj_dedup = "LOW_INCREMENTALITY_PARTNER"
        payable = calc.payable_commission_cents(gross, share)

        conv["attribution_status"] = new_status
        conv["attributed_affiliate_id"] = affiliate["id"]
        conv["attributed_click_id"] = click["id"]
        conv["commission_policy_id"] = policy["id"]
        conv["gross_commission_cents"] = gross
        conv["payable_commission_cents"] = payable
        _write_pair(
            conv, winning_at, match_mode, conv["candidate_click_count"],
            (calc.FULL_CREDIT_SHARE_BPS,
             calc.payable_commission_cents(gross, calc.FULL_CREDIT_SHARE_BPS),
             "NONE"),
            (calc.INCREMENTALITY_CREDIT_SHARE_BPS,
             calc.payable_commission_cents(
                 gross, calc.INCREMENTALITY_CREDIT_SHARE_BPS),
             adj_dedup),
            selected)

        SV.append_entry(affiliate, "ACCRUAL", payable, conversion_id=conv["id"],
                        memo="commission accrued for order %s"
                             % conv["order_ref"])
        affiliate["attributed_conversion_count"] += 1
        if conv["is_new_customer"]:
            affiliate["new_customer_attributed_count"] += 1
        if conv["coupon_code_used"] is not None:
            affiliate["coupon_assisted_conversion_count"] += 1
        SV.recompute_incrementality(affiliate)
        touch(affiliate)
        touch(conv)
        return respond(S.conversion_out(conv))

    @app.post("/conversions/<cid>/order-adjustment")
    def adjust_conversion(cid):
        authorize([ROLE_INGESTOR, ROLE_PROGRAM_ADMIN, ROLE_FIN_ANALYST])
        conv = SV.find_conversion(cid)
        payload = body()
        adjustment_type = get_enum(payload, "adjustment_type", ADJUSTMENT_TYPES)
        returned = get_int(payload, "returned_amount_cents", min_v=0)
        get_instant(payload, "occurred_at")
        if conv["attribution_status"] == "UNATTRIBUTED":
            fail("ERR_CONVERSION_NOT_ATTRIBUTED",
                 "there is no commission to unwind on an unattributed order")
        if conv["validation_status"] in ("REVERSED", "CLAWED_BACK"):
            fail("ERR_CONVERSION_NOT_ATTRIBUTED",
                 "the order is terminal on the validation dimension")
        if conv["returned_amount_cents"] + returned > conv["order_total_cents"]:
            fail("ERR_ADJUSTMENT_EXCEEDS_ORDER",
                 "the cumulative returned amount exceeds the order total")
        if adjustment_type in ("FULL_CANCELLATION", "FULL_RETURN"):
            cumulative = conv["order_total_cents"]
        else:
            cumulative = conv["returned_amount_cents"] + returned
        affiliate = db.affiliates.get(conv["attributed_affiliate_id"])

        if conv["validation_status"] == "PENDING_VALIDATION":
            # The whole accrual is undone; the program never pro-rates a sale
            # the retailer has not yet accepted.
            magnitude = conv["payable_commission_cents"]
            if affiliate is not None:
                SV.append_entry(
                    affiliate, "REVERSAL", -magnitude,
                    conversion_id=conv["id"],
                    memo="commission reversed for order %s" % conv["order_ref"])
                affiliate["attributed_conversion_count"] -= 1
                if conv["is_new_customer"]:
                    affiliate["new_customer_attributed_count"] -= 1
                if conv["coupon_code_used"] is not None:
                    affiliate["coupon_assisted_conversion_count"] -= 1
                SV.recompute_incrementality(affiliate)
                touch(affiliate)
            conv["attribution_status"] = "DETACHED"
            conv["validation_status"] = "REVERSED"
            conv["attributed_affiliate_id"] = None
            conv["clawed_back_cents"] = magnitude
            conv["returned_amount_cents"] = cumulative
            touch(conv)
            return respond(S.conversion_out(conv))

        # Validated: the clawback is pro-rata and expressed as a target total.
        target = calc.clawback_target_cents(
            conv["payable_commission_cents"], cumulative,
            conv["order_total_cents"])
        magnitude = target - conv["clawed_back_cents"]
        accrual = SV.accrual_entry_of(conv["id"])
        batch = None
        if accrual is not None and accrual["payout_batch_id"] is not None:
            batch = db.batches.get(accrual["payout_batch_id"])
        entry_type = "ADJUSTMENT" if (batch is not None
                                      and batch["state"] == "PAID") else "CLAWBACK"
        stamped_batch = batch if (batch is not None
                                  and batch["state"] in ("DRAFT", "VALIDATED")) \
            else None
        if affiliate is not None:
            SV.append_entry(
                affiliate, entry_type, -magnitude, conversion_id=conv["id"],
                payout_batch_id=None if stamped_batch is None
                else stamped_batch["id"],
                memo="commission clawed back for order %s" % conv["order_ref"])
            touch(affiliate)
        conv["clawed_back_cents"] = target
        conv["returned_amount_cents"] = cumulative
        if cumulative >= conv["order_total_cents"]:
            conv["validation_status"] = "CLAWED_BACK"
        touch(conv)
        if stamped_batch is not None and affiliate is not None:
            line = SV.line_for(stamped_batch["id"], affiliate["id"])
            if line is not None:
                SV.recompute_line(line, stamped_batch)
        return respond(S.conversion_out(conv))


def _select_policy(conv, affiliate):
    """Rate card selection: ACTIVE, same category, scope covers the partner
    type, half-open window contains placed_at.  Ranked by effective_from DESC
    then created_at ASC."""
    placed = parse_instant(conv["placed_at"])
    candidates = []
    for policy in ordered(db.policies):
        if policy["status"] != "ACTIVE":
            continue
        if policy["product_category"] != conv["product_category"]:
            continue
        if affiliate["partner_type"] not in policy["partner_type_scope"]:
            continue
        start = parse_instant(policy["effective_from"])
        end = parse_instant(policy["effective_to"])
        if start is None or end is None:
            continue
        if start <= placed < end:
            candidates.append(policy)
    if not candidates:
        fail("ERR_NO_ACTIVE_COMMISSION_POLICY",
             "no ACTIVE rate card covers this category and partner type")
    candidates.sort(key=lambda p: parse_instant(p["created_at"]))
    candidates.sort(key=lambda p: parse_instant(p["effective_from"]),
                    reverse=True)
    return candidates[0]


def _decision(conv, variant, selected, count, winning_at, mode, share, amount,
              dedup):
    row = new_row(
        mutable=False, conversion_id=conv["id"], algorithm_variant=variant,
        selected=selected, candidate_click_count=count,
        winning_click_occurred_at=winning_at, device_match_mode=mode,
        credit_share_bps=share, computed_commission_cents=amount,
        dedup_reason=dedup, evaluated_at=now_iso(),
    )
    db.decisions[row["id"]] = row
    return row


def _write_pair(conv, winning_at, mode, count, raw, adjusted, selected):
    """One audit row per declared variant, exactly one marked selected."""
    _decision(conv, "LAST_CLICK_RAW", selected == "LAST_CLICK_RAW", count,
              winning_at, mode, raw[0], raw[1], raw[2])
    _decision(conv, "INCREMENTALITY_ADJUSTED",
              selected == "INCREMENTALITY_ADJUSTED", count, winning_at, mode,
              adjusted[0], adjusted[1], adjusted[2])
