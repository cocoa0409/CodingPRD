"""Quarantine release: the re-entrant cycle, its moving gate and the referral cascade."""
from test_helpers import (
    ApiErrorId,
    add_strike,
    add_watercraft,
    api_client,
    assert_instant_equals,
    assert_seal_inventory_conserved,
    assert_strike_posture,
    decide_release,
    fetch_decon_order,
    fetch_quarantine_order,
    fetch_record,
    fetch_station,
    fetch_watercraft,
    make_inspector_headers,
    make_release_verifier_headers,
    order_decon,
    release_decision_payload,
    release_request_payload,
    request_release,
    set_clock,
    setup_program,
    setup_quarantined_record,
    treat_order,
    validate_error,
    validate_success,
    verify_dry,
)

ISSUED_AT = "2026-08-05T09:00:00Z"
BASE_HOLD_UNTIL = "2026-08-10T09:00:00Z"


def _sealed_extreme_record(*, seal_number="MT-SEAL-0001", ctx=None, watercraft=None,
                           **kwargs):
    """A vessel screened at 80 (EXTREME) on 2026-08-05T09:00:00Z and sealed.

    `hold_hours_required` is the EXTREME base of 120 hours, so `hold_until` is
    2026-08-10T09:00:00Z.
    """
    return setup_quarantined_record(
        ctx,
        seal_number=seal_number,
        arrived_at=ISSUED_AT,
        screen_at=ISSUED_AT,
        watercraft=watercraft,
        **kwargs,
    )


def _request_release_call(order_id, inspector_id):
    return api_client.request_quarantine_release(
        order_id, release_request_payload(), make_inspector_headers(inspector_id)
    )


class TestQuarantineReleaseCycleRevisitsSealed:
    """The order returns to SEALED, and the hold gate moves when it does."""

    def test_the_extreme_base_hold_admits_the_first_release_request(self):
        """A 120-hour hold from issuance opens SEALED to RELEASE_REQUESTED.

        PRD: "`hold_hours_required` is the band's base hold — 24 hours for `LOW`,
        48 hours for `MODERATE`, 72 hours for `HIGH`, 120 hours for `EXTREME` —
        plus 24 hours for each entry in `rejected_release_count`."  PRD: "the
        current logical time must have reached or passed `hold_until`, a time
        exactly equal to `hold_until` being sufficient; earlier is
        `ERR_HOLD_PERIOD_NOT_ELAPSED`."

        Design: Difficulty/non_linear_state_machine/quarantine_release_cycle_revisits_sealed_then_release_requested
        """
        ctx = _sealed_extreme_record(seal_stock_initial_count=3)
        order = ctx["quarantine_order"]
        assert order["band_at_issue"] == "EXTREME"
        assert order["hold_hours_required"] == 120
        assert order["rejected_release_count"] == 0
        assert_instant_equals(order["hold_until"], BASE_HOLD_UNTIL, "hold_until")
        set_clock(BASE_HOLD_UNTIL)

        requested = request_release(order["id"], ctx["inspector_a"]["id"])

        assert requested["status"] == "RELEASE_REQUESTED"

    def test_a_rejection_reseals_the_order_and_recomputes_the_hold_from_issued_at(self):
        """The extended hold is issued_at plus 144 hours, not the old hold plus 24.

        PRD: "It sets `status` back to `SEALED` and
        `release_verified_by_inspector_id` from `X-User-ID`, increments
        `rejected_release_count` by 1, and — caused by that increment — re-runs
        the hold computation, overwriting `hold_hours_required` and recomputing
        `hold_until` from `issued_at`, then writing the new `hold_until` onto the
        vessel's `quarantine_hold_until`."

        Design: Difficulty/non_linear_state_machine/quarantine_release_cycle_revisits_sealed_then_release_requested
        """
        ctx = _sealed_extreme_record(seal_stock_initial_count=3)
        set_clock(BASE_HOLD_UNTIL)
        request_release(ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"])

        order = decide_release(
            ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"], "REJECTED"
        )

        assert order["status"] == "SEALED"
        assert order["rejected_release_count"] == 1
        assert order["hold_hours_required"] == 144
        assert_instant_equals(order["hold_until"], "2026-08-11T09:00:00Z", "hold_until")
        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert_instant_equals(
            watercraft["quarantine_hold_until"], "2026-08-11T09:00:00Z",
            "quarantine_hold_until",
        )
        record = fetch_record(ctx["record"]["id"])
        assert record["enforcement_status"] == "NONE"
        assert watercraft["compliance_strikes"] == 0

    def test_the_moving_gate_blocks_the_next_request_until_the_longer_hold_elapses(self):
        """One second after the original hold the re-sealed order is still held.

        PRD: "Note that `hold_until` is always recomputed from `issued_at` and
        never from the previous `hold_until`, so a vessel that has had two
        releases rejected sits under exactly its base hold plus 48 hours measured
        from issuance."

        Design: Difficulty/non_linear_state_machine/quarantine_release_cycle_revisits_sealed_then_release_requested
        """
        ctx = _sealed_extreme_record(seal_stock_initial_count=3)
        order_id = ctx["quarantine_order"]["id"]
        set_clock(BASE_HOLD_UNTIL)
        request_release(order_id, ctx["inspector_a"]["id"])
        decide_release(order_id, ctx["inspector_c"]["id"], "REJECTED")
        set_clock("2026-08-10T09:00:01Z")

        early = _request_release_call(order_id, ctx["inspector_a"]["id"])

        validate_error(early, ApiErrorId.ERR_HOLD_PERIOD_NOT_ELAPSED)
        assert fetch_quarantine_order(order_id)["status"] == "SEALED"
        set_clock("2026-08-11T09:00:00Z")
        reopened = validate_success(
            _request_release_call(order_id, ctx["inspector_a"]["id"]), 200
        )
        assert reopened["status"] == "RELEASE_REQUESTED"


def _vessel_with_one_strike_sealed_and_once_rejected():
    """One strike preloaded from a refusal, then a sealed order already rejected once.

    Returns the context plus the refused sibling record, so the cascade can be
    read against a vessel that is one strike short of the watchlist.
    """
    ctx = setup_program(infestation_status="SUSPECT", seal_stock_initial_count=3)
    vessel = add_watercraft(ctx)
    refusal = add_strike(ctx, watercraft=vessel)
    ctx = _sealed_extreme_record(
        ctx=ctx, watercraft=vessel, seal_number="MT-SEAL-0100"
    )
    set_clock(BASE_HOLD_UNTIL)
    request_release(ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"])
    decide_release(ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"], "REJECTED")
    return ctx, refusal["record"]


class TestSecondRejectedReleaseCascade:
    """The second rejection travels from the order to the vessel's decon obligation."""

    def test_the_second_rejection_extends_the_hold_to_the_base_plus_forty_eight_hours(self):
        """rejected_release_count reaches 2 and the hold runs 168 hours from issuance.

        PRD: "`hold_until` is then `issued_at` advanced by `hold_hours_required`
        hours, forming the inclusive end of the hold, and the same instant is
        written onto the vessel as `quarantine_hold_until`, which is null whenever
        the vessel is under no hold."

        Design: Difficulty/transitive_cascade/second_rejected_release_cascades_through_referral_to_mandatory_decon_flag
        """
        ctx, _refused = _vessel_with_one_strike_sealed_and_once_rejected()
        set_clock("2026-08-11T09:00:00Z")
        request_release(ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"])

        order = decide_release(
            ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"], "REJECTED"
        )

        assert order["status"] == "SEALED"
        assert order["rejected_release_count"] == 2
        assert order["hold_hours_required"] == 168
        assert_instant_equals(order["hold_until"], "2026-08-12T09:00:00Z", "hold_until")
        assert_instant_equals(
            fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"],
            "2026-08-12T09:00:00Z", "quarantine_hold_until",
        )

    def test_the_second_rejection_refers_the_record_and_watchlists_the_vessel(self):
        """The referral adds the second strike, which flips the watchlist and the flag.

        PRD: "When `rejected_release_count` reaches 2, the same increment drives a
        further cascade: the parent record's enforcement dimension moves `NONE →
        REFERRED` with `referral_reason` set to `QUARANTINE_RELEASE_FAILURE`, that
        referral in turn increments the vessel's `compliance_strikes` and flips
        `watchlist_status` to `WATCHLISTED` once the strike count reaches 2, and
        that watchlist flip in turn sets the vessel's `mandatory_decon_flag` true."

        Design: Difficulty/transitive_cascade/second_rejected_release_cascades_through_referral_to_mandatory_decon_flag
        """
        ctx, _refused = _vessel_with_one_strike_sealed_and_once_rejected()
        before = fetch_watercraft(ctx["watercraft"]["id"])
        assert_strike_posture(before, 1)
        assert fetch_record(ctx["record"]["id"])["enforcement_status"] == "NONE"
        set_clock("2026-08-11T09:00:00Z")
        request_release(ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"])

        decide_release(
            ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"], "REJECTED"
        )

        record = fetch_record(ctx["record"]["id"])
        assert record["enforcement_status"] == "REFERRED"
        assert record["referral_reason"] == "QUARANTINE_RELEASE_FAILURE"
        assert_strike_posture(fetch_watercraft(ctx["watercraft"]["id"]), 2)

    def test_the_cascade_leaves_the_inspection_dimension_and_the_sibling_record_alone(self):
        """Only the enforcement dimension moves, and the earlier refusal is untouched.

        PRD: "`enforcement_status` advances on its own transition set with no
        reference whatsoever to `inspection_status`, and neither dimension gates
        the other."  PRD: "`risk_score`, `advisory_risk_score`,
        `dry_credit_points`, `reciprocity_credit_points`, `inspection_fee_cents`,
        `decon_fee_cents`, `surcharge_cents`, `total_fee_cents`,
        `fee_refunded_cents` and `penalty_cents` all sit at their declared
        defaults of 0"

        Design: Difficulty/transitive_cascade/second_rejected_release_cascades_through_referral_to_mandatory_decon_flag
        """
        ctx, refused = _vessel_with_one_strike_sealed_and_once_rejected()
        set_clock("2026-08-11T09:00:00Z")
        request_release(ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"])

        decide_release(
            ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"], "REJECTED"
        )

        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_status"] == "DECON_REQUIRED"
        assert record["penalty_cents"] == 0
        sibling = fetch_record(refused["id"])
        assert sibling["enforcement_status"] == "REFERRED"
        assert sibling["referral_reason"] == "INSPECTION_REFUSAL"
        assert sibling["inspection_status"] == "REFUSED"


def _release_requested_with_a_treated_decon_order():
    """An EXTREME sealed record whose sibling decon order is TREATED but unverified.

    The station carries two seals, so after issuance the counters read 1 / 1 / 0.
    """
    ctx = _sealed_extreme_record(seal_number="MT-SEAL-0300")
    record = fetch_record(ctx["record"]["id"])
    ctx["decon_order"] = order_decon(
        record["id"], ctx["inspector_a"]["id"], record["version"]
    )
    set_clock("2026-08-05T10:00:00Z")
    ctx["decon_order"] = treat_order(
        ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 180
    )
    set_clock(BASE_HOLD_UNTIL)
    ctx["quarantine_order"] = request_release(
        ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"]
    )
    return ctx


def _approve_release(order_id, verifier_id):
    return api_client.decide_quarantine_release(
        order_id, release_decision_payload("APPROVED"),
        make_release_verifier_headers(verifier_id),
    )


class TestApprovedReleaseNeedsAVerifiedSiblingDeconOrder:
    """The release reads the sibling decontamination order of the same record."""

    def test_an_approval_is_refused_while_the_sibling_order_is_only_treated(self):
        """Treatment alone does not release the boat; verification does.

        PRD: "The current logical time must again be at or after `hold_until`, and
        when the parent record's `decon_mandatory` is true, some decontamination
        order belonging to that record must have reached `VERIFIED`, or the
        approval is refused with `ERR_DECON_REQUIRED_BEFORE_RELEASE`."

        Design: Difficulty/cross_entity_state_dependency/approved_release_depends_on_a_verified_decon_order_of_the_same_record
        """
        ctx = _release_requested_with_a_treated_decon_order()
        assert fetch_record(ctx["record"]["id"])["decon_mandatory"] is True

        response = _approve_release(
            ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"]
        )

        validate_error(response, ApiErrorId.ERR_DECON_REQUIRED_BEFORE_RELEASE)
        order = fetch_quarantine_order(ctx["quarantine_order"]["id"])
        assert order["status"] == "RELEASE_REQUESTED"
        assert order["rejected_release_count"] == 0
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 1
        assert station["seals_in_circulation_count"] == 1
        assert station["seals_retired_count"] == 0
        assert_seal_inventory_conserved(station)
        assert_instant_equals(
            fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"],
            BASE_HOLD_UNTIL, "quarantine_hold_until",
        )

    def test_the_extreme_band_fixes_the_sibling_orders_dry_obligation_and_charge(self):
        """The EXTREME base of 120 hours leaves 30 hours of dry time after a perfect pass.

        PRD: "Step four sets `required_dry_hours` to the base dry hours minus that
        credit, but never below 6 hours, which is the absolute floor no treatment
        quality can undercut. Step five sets `dry_until` to `treated_at` advanced
        by `required_dry_hours` hours."  PRD: "on a treatment call it is 450 cents
        for each minute of nozzle dwell, where the dwell in minutes is the recorded
        `dwell_seconds` divided by 60 and rounded **up** to a whole minute — a
        90-second pass is billed as two minutes."

        Design: Difficulty/cross_entity_state_dependency/approved_release_depends_on_a_verified_decon_order_of_the_same_record
        """
        ctx = _release_requested_with_a_treated_decon_order()

        order = fetch_decon_order(ctx["decon_order"]["id"])

        assert order["status"] == "TREATED"
        assert order["band_at_order"] == "EXTREME"
        assert order["base_dry_hours"] == 120
        assert order["required_dry_hours"] == 30
        assert_instant_equals(order["dry_until"], "2026-08-06T16:03:00Z", "dry_until")
        record = fetch_record(ctx["record"]["id"])
        assert record["decon_fee_cents"] == 1350
        assert record["total_fee_cents"] == 3850

    def test_verifying_the_sibling_order_unblocks_the_release_and_retires_the_seal(self):
        """Once the decon order is VERIFIED the identical approval succeeds.

        PRD: "An approved release sets `status` to `RELEASED` and
        `release_verified_by_inspector_id` from `X-User-ID`, then retires the seal:
        the station's `seals_in_circulation_count` is decremented by 1 and its
        `seals_retired_count` incremented by 1 — the seal is physically cut, so it
        never returns to stock — and the vessel's `quarantine_hold_until` is
        cleared."

        Design: Difficulty/cross_entity_state_dependency/approved_release_depends_on_a_verified_decon_order_of_the_same_record
        """
        ctx = _release_requested_with_a_treated_decon_order()
        verified = verify_dry(
            ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "VERIFIED"
        )
        assert verified["status"] == "VERIFIED"

        order = validate_success(
            _approve_release(ctx["quarantine_order"]["id"], ctx["inspector_c"]["id"]),
            200,
        )

        assert order["status"] == "RELEASED"
        assert order["release_verified_by_inspector_id"] == ctx["inspector_c"]["id"]
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 1
        assert station["seals_in_circulation_count"] == 0
        assert station["seals_retired_count"] == 1
        assert_seal_inventory_conserved(station)
        assert fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"] is None
