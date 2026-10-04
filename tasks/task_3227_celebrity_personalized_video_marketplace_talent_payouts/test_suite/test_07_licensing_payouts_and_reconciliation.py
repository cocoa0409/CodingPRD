"""Licensing window conventions, the payout sweep minimum, reverse
reachability listings, dispute RBAC, and derived-field reconciliation."""

from test_helpers import (
    ApiErrorId,
    create_active_talent,
    create_confirmed_order,
    create_delivered_order,
    license_grant_payload,
    lines_for_order,
    make_admin_headers,
    make_buyer_headers,
    make_moderator_headers,
    make_talent_headers,
    open_dispute,
    read_buyer,
    read_order,
    read_talent,
    register_buyer,
    register_talent,
    submit_tax_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_adjacent_license_grants_allowed_overlap_rejected(api):
    """PRD §3.7: "The grant carries a `license_type` of `BUSINESS` or
    `ADVERTISING`, a `territory` of `DOMESTIC` or `GLOBAL`, a non-empty
    `channels` list drawn from `SOCIAL`, `WEB`, `TV`, and `OOH`, and a usage
    window from `starts_at` (inclusive) to `ends_at` (exclusive)."
    PRD §3.7: "Overlap is checked per license type on the same order: a new
    `BUSINESS` grant must not overlap, under half-open interval intersection,
    any `ACTIVE` `BUSINESS` grant on that order, and likewise for
    `ADVERTISING`; cross-type overlaps are allowed. A violating overlap is
    rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/same_type_license_overlap_rejected
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=True)
    order, _video = create_confirmed_order(api, talent, buyer, use_type="BUSINESS_USE")
    buyer_h = make_buyer_headers(buyer["id"])

    first = validate_success(
        api.create_license_grant(
            order["id"],
            license_grant_payload(
                license_type="BUSINESS",
                territory="DOMESTIC",
                channels=["SOCIAL"],
                starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-10-01T00:00:00Z",
            ),
            headers=buyer_h,
        ),
        expected_status=201,
    )
    assert first["status"] == "ACTIVE"

    # Back-to-back: new.starts_at == existing.ends_at — half-open intervals
    # with an empty intersection.
    second = validate_success(
        api.create_license_grant(
            order["id"],
            license_grant_payload(
                license_type="BUSINESS",
                territory="DOMESTIC",
                channels=["WEB"],
                starts_at="2026-10-01T00:00:00Z",
                ends_at="2026-11-01T00:00:00Z",
            ),
            headers=buyer_h,
        ),
        expected_status=201,
    )
    assert second["status"] == "ACTIVE"

    # One day earlier genuinely overlaps the second grant.
    response = api.create_license_grant(
        order["id"],
        license_grant_payload(
            license_type="BUSINESS",
            territory="DOMESTIC",
            channels=["WEB"],
            starts_at="2026-09-30T00:00:00Z",
            ends_at="2026-10-30T00:00:00Z",
        ),
        headers=buyer_h,
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP.value)


def test_cross_type_license_overlap_allowed(api):
    """PRD §3.7: "Overlap is checked per license type on the same order: a
    new `BUSINESS` grant must not overlap, under half-open interval
    intersection, any `ACTIVE` `BUSINESS` grant on that order, and likewise
    for `ADVERTISING`; cross-type overlaps are allowed."

    Design: Difficulty/resource_temporal_overlap/same_type_license_overlap_rejected
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=True)
    order, _video = create_confirmed_order(
        api, talent, buyer, use_type="ADVERTISING_USE"
    )
    buyer_h = make_buyer_headers(buyer["id"])

    validate_success(
        api.create_license_grant(
            order["id"],
            license_grant_payload(
                license_type="BUSINESS",
                territory="DOMESTIC",
                channels=["SOCIAL"],
                starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-10-01T00:00:00Z",
            ),
            headers=buyer_h,
        ),
        expected_status=201,
    )
    # Same window, ADVERTISING type: cross-type overlaps are allowed.
    response = api.create_license_grant(
        order["id"],
        license_grant_payload(
            license_type="ADVERTISING",
            territory="DOMESTIC",
            channels=["SOCIAL"],
            starts_at="2026-09-01T00:00:00Z",
            ends_at="2026-10-01T00:00:00Z",
        ),
        headers=buyer_h,
    )
    grant = validate_success(response, expected_status=201)
    assert grant["license_type"] == "ADVERTISING"


def test_sweep_skips_below_minimum_and_pays_qualifier(api):
    """PRD §3.8: "When a talent's net total is at least 2500 cents, the sweep
    creates a `Payout` in `SCHEDULED` status carrying that `total_cents` and
    the window's `period_start` and `period_end`, and attaches every swept
    line to it by setting each line's `payout_id`; each line's `kind`
    distinguishes a `VIDEO_EARNING` from a `LICENSE_FEE_CREDIT` and a
    `CLAWBACK` within the sum."
    PRD §3.8: "Talents whose swept total falls below the 2500-cent minimum
    are skipped entirely — no payout is created for them."

    Design: Corner/calculations/payout_sweep_skips_below_minimum_and_orders_by_created_at
    """
    admin = make_admin_headers()
    talent_a = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 6000,
            "business_rate_cents": 24000,
            "advertising_rate_cents": 48000,
        },
    )
    talent_b = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2000,
            "business_rate_cents": 8000,
            "advertising_rate_cents": 16000,
        },
    )
    buyer = register_buyer(api)
    create_confirmed_order(api, talent_a, buyer)   # net 4500 >= 2500
    create_confirmed_order(api, talent_b, buyer)   # net 1500 < 2500

    response = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    )
    payouts, meta = validate_paginated(response)
    assert len(payouts) == 1, "only the qualifying talent gets a payout"
    assert payouts[0]["talent_id"] == talent_a["id"]
    assert payouts[0]["total_cents"] == 4500
    assert payouts[0]["status"] == "SCHEDULED"

    # The skipped talent keeps its UNSETTLED line for a future sweep.
    talent_b_now = read_talent(api, talent_b["id"])
    assert talent_b_now["pending_balance_cents"] == 1500


def test_sweep_with_no_qualifying_talent_rejected(api):
    """PRD §3.8: "Talents whose swept total falls below the 2500-cent minimum
    are skipped entirely — no payout is created for them. If the sweep as a
    whole yields no qualifying talent at all, it is rejected with
    `ERR_PAYOUT_BELOW_MINIMUM` (HTTP 422); when at least one talent
    qualifies, the sweep succeeds and returns the created payouts as a
    paginated list."

    Design: Corner/calculations/payout_sweep_skips_below_minimum_and_orders_by_created_at
    """
    admin = make_admin_headers()
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2000,
            "business_rate_cents": 8000,
            "advertising_rate_cents": 16000,
        },
    )
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)  # net 1500 < 2500

    response = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    )
    validate_error(response, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM.value)


def test_reverse_listings_for_new_talent(api):
    """PRD §3.1: "A rejected document is immutable, but the talent may simply
    submit a new one; a talent's document history is readable as a list
    filterable by `status`."
    PRD §3.8: "Payouts and their lines are inspectable from several angles. A
    talent's payouts are listable and filterable by `status`; a single payout
    is fetchable, as are the lines swept into it. A talent's payout lines are
    listable and filterable by `settlement_status`, and a `PlatformAdmin` may
    list payout lines across the marketplace filtered by `payout_id`,
    `order_id`, `talent_id`, or `settlement_status`."

    Design: Corner/endpoints/fk_reverse_reachability_list_endpoints
    """
    talent = register_talent(api)
    submit_tax_document(api, talent, decision=None)  # left SUBMITTED
    headers = make_talent_headers(talent["id"])

    docs, meta = validate_paginated(api.list_tax_documents(talent["id"], headers=headers))
    assert len(docs) == 1
    assert docs[0]["status"] == "SUBMITTED"

    payouts, meta = validate_paginated(api.list_talent_payouts(talent["id"], headers=headers))
    assert payouts == []
    assert meta["total_count"] == 0

    lines, meta = validate_paginated(
        api.list_talent_payout_lines(talent["id"], headers=headers)
    )
    assert lines == []
    assert meta["total_count"] == 0


def test_talent_cannot_resolve_dispute(api):
    """PRD §2.1: "Admin-scoped actions (activation, suspension, tax review,
    dispute resolution, sweeps, payout lifecycle, logical-clock control,
    forced pricing-suggestion refresh) are reserved for `PlatformAdmin`;
    video moderation may additionally be performed by a `Moderator`."
    PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint per the authorization matrix in §4 is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/talent_cannot_resolve_dispute
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate=None)
    dispute = open_dispute(api, buyer, order, reason="mismatch")

    response = api.resolve_dispute(
        dispute["id"], "FULL_REFUND", headers=make_talent_headers(talent["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    disputes = api.list_disputes(order["id"], headers=make_admin_headers()).json()["data"]
    assert disputes[0]["status"] == "OPEN"


def test_confirm_response_and_followup_agree(api):
    """PRD §3.5: "The `CONFIRMED` transition runs payout computation once,
    freezing the split at that instant. The commission rate is read from the
    talent's `commission_tier` at the exact moment of the transition: a
    `STANDARD` talent pays 25% commission, `SILVER` pays 20%, and `GOLD` pays
    15%."
    PRD §3.5: "Tier changes that happen after confirmation never
    retroactively alter a confirmed order."

    Design: Corner/consistency_model/immediate_consistency_on_confirm
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    response = api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"]))
    confirmed = validate_success(response)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["platform_commission_cents"] == 2500
    assert confirmed["talent_net_cents"] == 7500

    reloaded = read_order(api, order["id"])
    assert reloaded["status"] == "CONFIRMED"
    assert reloaded["platform_commission_cents"] == 2500
    assert reloaded["talent_net_cents"] == 7500


def test_confirm_then_reread_twice_is_stable(api):
    """PRD §3.5: "The `CONFIRMED` transition runs payout computation once,
    freezing the split at that instant. The commission rate is read from the
    talent's `commission_tier` at the exact moment of the transition: a
    `STANDARD` talent pays 25% commission, `SILVER` pays 20%, and `GOLD` pays
    15%."
    PRD §3.5: "Tier changes that happen after confirmation never
    retroactively alter a confirmed order."

    Design: Corner/consistency_model/immediate_consistency_on_confirm
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    validate_success(api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"])))

    first = read_order(api, order["id"])
    second = read_order(api, order["id"])
    for field in ("status", "platform_commission_cents", "talent_net_cents"):
        assert first[field] == second[field], (
            "re-reads of a confirmed order must be stable for {0}".format(field)
        )


def test_derived_fields_reconcile_across_refund_and_second_confirm(api):
    """PRD §2.9: "`pending_balance_cents` accumulates unsettled net earnings
    (video earnings and license fee credits) and is debited by clawbacks and
    by payout completion; `paid_out_balance_cents` accumulates lifetime net
    earnings actually transferred via paid payouts."
    PRD §3.5: "The order's `gross_amount_cents` is added to the talent's
    `trailing_gmv_cents`, which is the sum of gross amounts over the talent's
    orders whose `CONFIRMED` transition occurred within the trailing 365-day
    window — inclusive of the window start, exclusive of the window end —
    minus gross amounts refunded by full-refund dispute resolutions and minus
    buyer-refund amounts from partial-refund resolutions."
    PRD §3.8: "Talents whose swept total falls below the 2500-cent minimum
    are skipped entirely — no payout is created for them."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_layer
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)

    # Order 1: confirm, then full-refund dispute.
    order1, _ = create_confirmed_order(api, talent, buyer)
    dispute = open_dispute(api, buyer, order1, reason="bad video")
    validate_success(api.resolve_dispute(dispute["id"], "FULL_REFUND", headers=admin))

    # Order 2: confirm cleanly.
    order2, _ = create_confirmed_order(api, talent, buyer)

    # UNSETTLED lines: +7500 (order2 earning) plus the matched +7500/-7500
    # pair from order1's earning and clawback, which cancel out (PRD §3.8:
    # "earnings positive, clawbacks negative"). The qualifying net total is
    # order2's 7500 — at least the 2500-cent minimum — so the sweep creates
    # one SCHEDULED payout carrying that total.
    response = api.payout_sweep(
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", headers=admin
    )
    payouts = validate_success(response)
    assert len(payouts) == 1
    assert payouts[0]["total_cents"] == 7500
    assert payouts[0]["status"] == "SCHEDULED"

    final_talent = read_talent(api, talent["id"])
    assert final_talent["pending_balance_cents"] == 7500, (
        "7500 credited at confirm 1, -7500 clawback, +7500 at confirm 2"
    )
    assert final_talent["trailing_gmv_cents"] == 10000, (
        "10000 added at confirm 1, subtracted by the full refund, "
        "then 10000 added at confirm 2"
    )
    assert read_buyer(api, buyer["id"])["wallet_credit_cents"] == 10000
