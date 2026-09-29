"""Dry verification: the retreat cycle, the inclusive dry_until gate and rule priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    dry_verification_payload,
    fetch_decon_order,
    fetch_record,
    fetch_station,
    fetch_watercraft,
    make_release_verifier_headers,
    set_clock,
    setup_treated_order,
    treat_order,
    validate_error,
    validate_success,
    verify_dry,
)


def _half_effective_treated_order():
    """A HIGH-band order treated at 130 degrees, so effectiveness is 50.00.

    treated_at is 2026-08-05T09:02:00Z, required_dry_hours 45 and dry_until
    2026-08-07T06:02:00Z.
    """
    return setup_treated_order(
        water_temp_f=130,
        arrived_at="2026-08-05T08:00:00Z",
        screen_at="2026-08-05T08:00:00Z",
        decon_bay_count=1,
    )


def _fully_effective_treated_order():
    """A HIGH-band order treated at the thresholds: required_dry_hours 18.

    treated_at is 2026-08-05T09:02:00Z and dry_until is 2026-08-06T03:02:00Z.
    """
    return setup_treated_order(
        arrived_at="2026-08-05T08:00:00Z",
        screen_at="2026-08-05T08:00:00Z",
        decon_bay_count=1,
    )


def _verify(order_id, inspector_id, outcome):
    return api_client.verify_decon_dry_time(
        order_id, dry_verification_payload(outcome),
        make_release_verifier_headers(inspector_id),
    )


class TestRetreatCycleRevisitsTreated:
    """An order re-enters TREATED and recomputes its whole derived block."""

    def test_a_retreat_verdict_returns_the_order_to_retreat_required(self):
        """At dry_until a RETREAT leaves the record in DECON_REQUIRED.

        PRD: "`TREATED → RETREAT_REQUIRED` sets `status` to `RETREAT_REQUIRED`
        and `verified_by_inspector_id` from `X-User-ID`, vacates the bay, and
        deliberately leaves the parent record sitting in `DECON_REQUIRED`; only
        the order's `version` advances."

        Design: Difficulty/non_linear_state_machine/decon_order_retreat_cycle_revisits_treated
        """
        ctx = _half_effective_treated_order()
        first = ctx["decon_order"]
        assert float(first["treatment_effectiveness_pct"]) == 50.00
        assert first["required_dry_hours"] == 45
        assert_instant_equals(first["dry_until"], "2026-08-07T06:02:00Z", "dry_until")
        set_clock("2026-08-07T06:02:00Z")

        order = verify_dry(first["id"], ctx["inspector_c"]["id"], "RETREAT")

        assert order["status"] == "RETREAT_REQUIRED"
        assert order["verified_by_inspector_id"] == ctx["inspector_c"]["id"]
        assert order["attempt_count"] == 1
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_REQUIRED"

    def test_the_second_treatment_recomputes_the_whole_derived_block(self):
        """The retreatment overwrites effectiveness and dry time rather than accumulating.

        PRD: "The **documented dry time** follows immediately, in a five-step
        order that is pinned and must not be rearranged. Step one takes
        `base_dry_hours` from `band_at_order`, using the same band-to-hours
        mapping given above. Step two reads `treatment_effectiveness_pct` from
        the treatment just scored. Step three computes the credit: the base dry
        hours multiplied by the effectiveness expressed as a fraction of 100,
        multiplied by 0.75, then floored to a whole number of hours — so even a
        perfect treatment can never earn back more than three quarters of the
        base obligation."

        Design: Difficulty/non_linear_state_machine/decon_order_retreat_cycle_revisits_treated
        """
        ctx = _half_effective_treated_order()
        set_clock("2026-08-07T06:02:00Z")
        verify_dry(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "RETREAT")
        set_clock("2026-08-07T07:00:00Z")

        order = treat_order(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"],
            140, 3000, 240,
        )

        assert order["status"] == "TREATED"
        assert order["attempt_count"] == 2
        assert float(order["treatment_effectiveness_pct"]) == 100.00
        assert order["base_dry_hours"] == 72
        assert order["required_dry_hours"] == 18
        assert_instant_equals(order["treated_at"], "2026-08-07T07:04:00Z", "treated_at")
        assert_instant_equals(order["dry_until"], "2026-08-08T01:04:00Z", "dry_until")
        assert_instant_equals(
            order["bay_released_at"], "2026-08-07T07:34:00Z", "bay_released_at"
        )

    def test_the_decontamination_charge_is_overwritten_not_accumulated(self):
        """Two treatments of 2 and 4 dwell minutes bill 1800 cents, never 2700.

        PRD: "The fee calculation of §3.5 is re-run on the parent record with the
        `dwell_seconds` just recorded, overwriting `decon_fee_cents`,
        `surcharge_cents` and `total_fee_cents`, and the station's
        `collected_fees_cents` is adjusted by the resulting delta."

        Design: Difficulty/non_linear_state_machine/decon_order_retreat_cycle_revisits_treated
        """
        ctx = _half_effective_treated_order()
        first_pass = fetch_record(ctx["record"]["id"])
        assert first_pass["decon_fee_cents"] == 900
        assert first_pass["total_fee_cents"] == 3400
        set_clock("2026-08-07T06:02:00Z")
        verify_dry(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "RETREAT")
        set_clock("2026-08-07T07:00:00Z")

        treat_order(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 240)

        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_status"] == "DECON_REQUIRED"
        assert record["decon_fee_cents"] == 1800
        assert record["total_fee_cents"] == 4300
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 4300


class TestDryVerificationAtTheExactDryUntilInstant:
    """The dry-time gate is inclusive at `dry_until`, which is not a round instant."""

    def test_verification_at_exactly_dry_until_is_accepted_and_cascades(self):
        """2026-08-06T03:02:00Z equals dry_until, so the vessel is released.

        PRD: "For the two outcomes that are *judgements about the dry period*,
        `VERIFIED` and `RETREAT`, the current logical time must have reached or
        passed `dry_until`, and a time exactly equal to `dry_until` satisfies the
        requirement; earlier is `ERR_DRY_TIME_NOT_ELAPSED`."  PRD: "`TREATED →
        VERIFIED` sets the order's `status` to `VERIFIED` and
        `verified_by_inspector_id` from `X-User-ID`, and then cascades twice. The
        parent record moves `DECON_REQUIRED → DECON_COMPLETED`, and that record
        transition in turn stamps the vessel's `last_decon_verified_at` at the
        current logical time and clears the vessel's `mandatory_decon_flag`."

        Design: Difficulty/boundary_precision_check/dry_verification_at_the_exact_dry_until_instant
        """
        ctx = _fully_effective_treated_order()
        assert ctx["decon_order"]["required_dry_hours"] == 18
        assert_instant_equals(
            ctx["decon_order"]["dry_until"], "2026-08-06T03:02:00Z", "dry_until"
        )
        set_clock("2026-08-06T03:02:00Z")

        order = validate_success(
            _verify(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "VERIFIED"), 200
        )

        assert order["status"] == "VERIFIED"
        assert order["verified_by_inspector_id"] == ctx["inspector_c"]["id"]
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_COMPLETED"
        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert_instant_equals(
            watercraft["last_decon_verified_at"], "2026-08-06T03:02:00Z",
            "last_decon_verified_at",
        )
        assert watercraft["mandatory_decon_flag"] is False

    @pytest.mark.parametrize("outcome", ["VERIFIED", "RETREAT"])
    def test_one_second_before_dry_until_both_judgements_are_refused(self, outcome):
        """At 2026-08-06T03:01:59Z the dry period has not elapsed.

        PRD: "20. The documented dry period has elapsed — otherwise
        `ERR_DRY_TIME_NOT_ELAPSED` (409). Applies to dry verification."

        Design: Difficulty/boundary_precision_check/dry_verification_at_the_exact_dry_until_instant
        """
        ctx = _fully_effective_treated_order()
        set_clock("2026-08-06T03:01:59Z")

        response = _verify(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], outcome)

        validate_error(response, ApiErrorId.ERR_DRY_TIME_NOT_ELAPSED)
        assert fetch_decon_order(ctx["decon_order"]["id"])["status"] == "TREATED"
        assert fetch_watercraft(ctx["watercraft"]["id"])["last_decon_verified_at"] is None

    def test_abandonment_is_exempt_from_the_dry_time_gate(self):
        """ABANDON is accepted at the same instant the judgements are refused.

        PRD: "`ABANDON` is deliberately exempt from that gate: a vessel may be
        abandoned at any point after treatment."

        Design: Difficulty/boundary_precision_check/dry_verification_at_the_exact_dry_until_instant
        """
        ctx = _fully_effective_treated_order()
        set_clock("2026-08-06T03:01:59Z")

        order = validate_success(
            _verify(ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "ABANDON"), 200
        )

        assert order["status"] == "ABANDONED"
        assert (
            fetch_record(ctx["record"]["id"])["inspection_status"]
            == "DECON_FAILED_ABANDONED"
        )


class TestDryTimeCheckBeatsSegregationOfDuties:
    """Two violations coexist; the 409 dry-time check is announced, not the 403."""

    def test_the_dry_time_check_is_announced_before_the_self_signing_check(self):
        """The technician self-signing early gets 409 ERR_DRY_TIME_NOT_ELAPSED.

        PRD: "The verifier's `X-User-ID` may not equal the order's
        `treated_by_inspector_id` — a technician may not sign off their own work
        — and a collision is `ERR_SEGREGATION_OF_DUTIES`."  PRD: "For the two
        outcomes that are *judgements about the dry period*, `VERIFIED` and
        `RETREAT`, the current logical time must have reached or passed
        `dry_until`, and a time exactly equal to `dry_until` satisfies the
        requirement; earlier is `ERR_DRY_TIME_NOT_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/dry_time_check_beats_segregation_of_duties_on_dry_verification
        """
        ctx = _fully_effective_treated_order()
        assert ctx["decon_order"]["treated_by_inspector_id"] == ctx["inspector_b"]["id"]
        set_clock("2026-08-05T09:02:00Z")

        response = _verify(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"], "VERIFIED"
        )

        validate_error(response, ApiErrorId.ERR_DRY_TIME_NOT_ELAPSED)
        order = fetch_decon_order(ctx["decon_order"]["id"])
        assert order["status"] == "TREATED"
        assert order["verified_by_inspector_id"] is None
        assert order["required_dry_hours"] == 18
        assert_instant_equals(order["dry_until"], "2026-08-06T03:02:00Z", "dry_until")
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_REQUIRED"
        assert fetch_watercraft(ctx["watercraft"]["id"])["last_decon_verified_at"] is None

    def test_once_the_dry_period_elapses_the_same_call_reveals_the_403(self):
        """At dry_until the identical self-signing call is ERR_SEGREGATION_OF_DUTIES.

        PRD: "The verifier's `X-User-ID` may not equal the order's
        `treated_by_inspector_id` — a technician may not sign off their own work
        — and a collision is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/dry_time_check_beats_segregation_of_duties_on_dry_verification
        """
        ctx = _fully_effective_treated_order()
        set_clock("2026-08-06T03:02:00Z")

        response = _verify(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"], "VERIFIED"
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert fetch_decon_order(ctx["decon_order"]["id"])["status"] == "TREATED"
