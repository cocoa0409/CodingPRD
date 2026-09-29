"""
Validation corners: the pagination window, the inclusive claim cap and coverage
window, the compound telemetry guard, the logical-clock cancellation bound, the
destination-unit gate, and the two faces of the credit ceiling.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CANCEL_DATE_INVALID,
    ERR_CLAIM_AMOUNT_EXCEEDS_CAP,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_RUNTIME_WINDOW,
    ERR_OUTSIDE_COVERAGE_WINDOW,
    ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED,
    ERR_TRANSFER_TARGET_INVALID,
)
from test_helpers.test_users import OPERATOR


class TestPaginationWindow:
    """Both edges of the declared limit range, plus a negative offset."""

    def test_the_pagination_window_is_policed_on_both_edges(self, api):
        """
        A limit of 101 and a limit of 0 are both refused, so is a negative offset,
        while a limit of exactly 100 is inside the window and answers with an
        empty page.

        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400); the same error covers a filter query parameter whose value is not a recognised member of the enumeration it filters on."

        Design: Corner/validations/list_limit_outside_one_to_one_hundred_returns_invalid_pagination
        """
        validate_error(
            api.list_subscriptions(OPERATOR, {"limit": 101}), ERR_INVALID_PAGINATION, 400
        )
        validate_error(
            api.list_subscriptions(OPERATOR, {"limit": 0}), ERR_INVALID_PAGINATION, 400
        )
        validate_error(
            api.list_subscriptions(OPERATOR, {"offset": -1}), ERR_INVALID_PAGINATION, 400
        )

        rows, meta = validate_paginated(
            api.list_subscriptions(OPERATOR, {"limit": 100, "offset": 0})
        )
        assert rows == []
        a.assert_page_meta(meta, limit=100, offset=0, total_count=0, has_more=False)


class TestClaimFilingBounds:
    """The inclusive hard cap and the inclusive sixty-day coverage window."""

    def test_the_claim_hard_cap_is_inclusive(self, api):
        """
        One cent above the hundred-thousand-cent ceiling is refused and mints
        nothing, while the ceiling itself is accepted — so exactly one claim exists
        afterwards, still awaiting triage.

        PRD §3.7: "Finally the ask is capped: a `requested_amount_cents` above one hundred thousand cents is rejected with `ERR_CLAIM_AMOUNT_EXCEEDS_CAP`."

        Design: Corner/validations/claim_requested_amount_above_the_hard_cap_rejected
        """
        env = fx.build_base_env(api)

        validate_error(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    requested_amount_cents=100001,
                    description="Cabinet panel cracked",
                ),
                env.pm_headers,
            ),
            ERR_CLAIM_AMOUNT_EXCEEDS_CAP,
            422,
        )

        claim = validate_success(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    requested_amount_cents=100000,
                    description="Cabinet panel cracked",
                ),
                env.pm_headers,
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["provisional_amount_cents"] is None
        assert claim["approved_amount_cents"] is None

        _rows, meta = validate_paginated(
            api.list_claims(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert meta["total_count"] == 1

    def test_the_sixtieth_day_after_the_incident_still_files(self, api):
        """
        The same incident date flips purely on the clock: sixty days after the
        incident is inside the window, sixty-one days is outside it, and the
        refused filing leaves the claim count where the accepted one put it.

        PRD §3.7: "The incident must fall inside the coverage window, which has three edges at once: the `incident_date` must be on or after the calendar date of the subscription's `activated_at`, must not be later than the logical-clock date, and must not be more than sixty days before the logical-clock date; any of the three failing is `ERR_OUTSIDE_COVERAGE_WINDOW`."

        Design: Corner/validations/claim_filed_exactly_sixty_days_after_the_incident_is_accepted
        """
        env = fx.build_base_env(api)
        fx.set_clock(api, "2026-10-04T00:00:00Z")

        claim = validate_success(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    incident_date="2026-08-05",
                    description="Return grille torn on day one",
                ),
                env.pm_headers,
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED"

        fx.set_clock(api, "2026-10-05T00:00:00Z")
        validate_error(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    incident_date="2026-08-05",
                    description="Return grille torn on day one",
                ),
                env.pm_headers,
            ),
            ERR_OUTSIDE_COVERAGE_WINDOW,
            422,
        )

        _rows, meta = validate_paginated(
            api.list_claims(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert meta["total_count"] == 1


class TestTelemetryAndCancellationBounds:
    """The compound window guard, and the clock-anchored cancellation date."""

    def test_the_telemetry_guard_rejects_a_flat_window_and_a_zero_pressure(self, api):
        """
        Two different violations surface the same rejection — a window whose end
        does not pass its start, and a pressure drop of zero — while a single
        pascal is accepted, so the pressure rule is strictly-positive rather than a
        magnitude threshold.

        PRD §3.2: "A window whose `window_end` is not strictly after its `window_start`, or whose `static_pressure_delta_pa` is not greater than zero, is rejected with `ERR_INVALID_RUNTIME_WINDOW`."

        Design: Corner/validations/degenerate_runtime_window_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        prop = fx.create_property(api)
        unit = fx.create_unit(api, prop["id"])

        validate_error(
            api.create_runtime_reading(
                unit["id"],
                f.runtime_reading_payload(
                    "2026-08-07T00:00:00Z", "2026-08-07T00:00:00Z", 168, 100, "PRESSURE_SENSOR"
                ),
                OPERATOR,
            ),
            ERR_INVALID_RUNTIME_WINDOW,
            422,
        )
        validate_error(
            api.create_runtime_reading(
                unit["id"],
                f.runtime_reading_payload(
                    "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 168, 0, "PRESSURE_SENSOR"
                ),
                OPERATOR,
            ),
            ERR_INVALID_RUNTIME_WINDOW,
            422,
        )

        reading = validate_success(
            api.create_runtime_reading(
                unit["id"],
                f.runtime_reading_payload(
                    "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 168, 1, "PRESSURE_SENSOR"
                ),
                OPERATOR,
            ),
            201,
        )
        assert reading["static_pressure_delta_pa"] == 1

        rows, meta = validate_paginated(api.list_runtime_readings(unit["id"], OPERATOR))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [reading["id"]]

    def test_a_cancellation_dated_before_the_logical_clock_is_refused(self, api):
        """
        One day before the logical clock is refused and moves nothing — no status
        change, no version bump, no ledger row — while the clock date itself
        settles the subscription, so the bound is inclusive.

        PRD §3.9: "First the date is checked: the `effective_date` must be on or after the logical-clock date and must not be later than the subscription's `lease_end_date`, and a violation is `ERR_CANCEL_DATE_INVALID`."

        Design: Corner/validations/cancel_effective_date_in_the_past_rejected
        """
        env = fx.build_base_env(api)
        fx.set_clock(api, "2026-09-11T00:00:00Z")

        validate_error(
            api.cancel_subscription(
                env.subscription_id,
                f.cancel_payload("2026-09-10", "Backdated move-out"),
                OPERATOR,
            ),
            ERR_CANCEL_DATE_INVALID,
            422,
        )

        after = fx.read_subscription(api, env.subscription_id)
        assert after["status"] == "ACTIVE"
        assert after["cancel_effective_date"] is None
        assert after["version"] == 2
        _rows, meta = validate_paginated(
            api.list_ledger_entries(env.subscription_id, OPERATOR)
        )
        assert meta["total_count"] == 2
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        cancelled = validate_success(
            api.cancel_subscription(
                env.subscription_id,
                f.cancel_payload("2026-09-11", "Move-out today"),
                OPERATOR,
            )
        )
        assert cancelled["status"] == "CANCELLED"


class TestDestinationUnitGate:
    """The transfer's legality lives on a third entity: the destination unit."""

    def test_a_transfer_is_refused_unless_the_destination_unit_is_available(self, api):
        """
        The identical payload flips from refusal to acceptance on the destination
        unit's status alone: an occupied unit and the subscription's own unit are
        both refused with the same code, an available unit is accepted, and the two
        refusals consume no version.

        PRD §3.8: "The destination must be a genuinely different unit and must be `AVAILABLE`: a `to_unit_id` equal to the subscription's current `unit_id`, or a destination unit in any status other than `AVAILABLE`, is rejected with `ERR_TRANSFER_TARGET_INVALID`."

        Design: Corner/validations/transfer_to_a_non_available_unit_rejected
        """
        env = fx.build_base_env(api)
        occupied_unit = fx.create_unit(api, env.property_id, unit_label="A-201")
        resident_b = fx.create_resident(
            api, full_name="Ben Ortiz", email="ben.ortiz@example.com", household_size=3
        )
        # Ladder rung 22 (ERR_UNIT_OCCUPANCY_CONFLICT) sits above rung 26
        # (ERR_TRANSFER_TARGET_INVALID), so the occupant's lease must clear the
        # incoming lease (2026-08-01 .. 2027-07-31) by more than the three-day
        # turnover buffer; otherwise rung 22 answers first and rung 26 is never
        # reached. This isolates the destination-status gate under test.
        subscription_b = fx.create_subscription(
            api,
            resident_b["id"],
            occupied_unit["id"],
            lease_start_date="2027-08-05",
            lease_end_date="2028-07-31",
        )
        fx.activate_subscription(api, subscription_b["id"])
        available_unit = fx.create_unit(api, env.property_id, unit_label="A-301")

        assert validate_success(api.get_unit(occupied_unit["id"], OPERATOR))["status"] == (
            "OCCUPIED"
        )
        assert validate_success(api.get_unit(available_unit["id"], OPERATOR))["status"] == (
            "AVAILABLE"
        )

        validate_error(
            api.create_subscription_transfer(
                f.transfer_payload(
                    env.subscription_id, occupied_unit["id"], "2026-08-05", 2
                ),
                OPERATOR,
            ),
            ERR_TRANSFER_TARGET_INVALID,
            422,
        )
        validate_error(
            api.create_subscription_transfer(
                f.transfer_payload(env.subscription_id, env.unit_id, "2026-08-05", 2),
                OPERATOR,
            ),
            ERR_TRANSFER_TARGET_INVALID,
            422,
        )

        still_active = fx.read_subscription(api, env.subscription_id)
        assert still_active["status"] == "ACTIVE"
        assert still_active["version"] == 2

        transfer = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(
                    env.subscription_id, available_unit["id"], "2026-08-05", 2
                ),
                OPERATOR,
            ),
            201,
        )
        assert transfer["status"] == "REQUESTED"
        assert fx.read_subscription(api, env.subscription_id)["status"] == "TRANSFER_PENDING"


class TestCreditCeiling:
    """The ceiling is conditioned on the payer and evaluated against the balance."""

    def _two_pending_activations(self, api, credit_limit_cents, second_billing_party):
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.create_sku(api)
        prop = fx.create_property(api, credit_limit_cents=credit_limit_cents)
        unit_a = fx.create_unit(api, prop["id"], unit_label="A-101")
        fx.activate_property(api, prop["id"])
        unit_b = fx.create_unit(api, prop["id"], unit_label="A-102")
        resident_a = fx.create_resident(api)
        resident_b = fx.create_resident(
            api, full_name="Ben Ortiz", email="ben.ortiz@example.com", household_size=3
        )
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        sub_a = fx.create_subscription(api, resident_a["id"], unit_a["id"])
        sub_b = fx.create_subscription(
            api, resident_b["id"], unit_b["id"], billing_party=second_billing_party
        )
        return prop, unit_b, sub_a, sub_b

    def test_the_ceiling_is_checked_only_for_manager_billed_subscriptions(self, api):
        """
        Against a three-thousand-cent ceiling the manager-billed activation is
        refused and stays PENDING_SETUP with no ledger row, while the
        resident-billed activation on a sibling unit succeeds — and the property's
        balance is still 0, because resident-billed charges never enter it.

        PRD §2.11: "The check applies to property-manager-billed subscriptions at a property whose `billing_mode` is `PM_BILLED`: the property's current `outstanding_balance_cents` plus the charge the request would post must be less than or equal to `credit_limit_cents`, and a request that would push it past the ceiling is rejected with `ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED` (HTTP 402) with no partial commitment."

        Design: Corner/validations/credit_limit_gate_applies_only_to_property_manager_billed_activation
        """
        prop, _unit_b, sub_pm, sub_resident = self._two_pending_activations(
            api, 3000, "RESIDENT"
        )

        validate_error(
            api.activate_subscription(sub_pm["id"], OPERATOR),
            ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED,
            402,
        )
        refused = fx.read_subscription(api, sub_pm["id"])
        assert refused["status"] == "PENDING_SETUP"
        _rows, refused_meta = validate_paginated(
            api.list_ledger_entries(sub_pm["id"], OPERATOR)
        )
        assert refused_meta["total_count"] == 0

        accepted = validate_success(api.activate_subscription(sub_resident["id"], OPERATOR))
        assert accepted["status"] == "ACTIVE"

        assert a.property_balance(api, prop["id"], OPERATOR) == 0

    def test_two_affordable_activations_are_refused_in_aggregate(self, api):
        """
        Each activation commits 5588 against an eight-thousand-cent ceiling, so
        either one alone fits; the second is refused because the check reads the
        balance the first one already posted, and nothing about the refused
        subscription or its unit moves.

        PRD §2.11: "The check applies to property-manager-billed subscriptions at a property whose `billing_mode` is `PM_BILLED`: the property's current `outstanding_balance_cents` plus the charge the request would post must be less than or equal to `credit_limit_cents`, and a request that would push it past the ceiling is rejected with `ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED` (HTTP 402) with no partial commitment."

        Design: Corner/validations/two_individually_affordable_activations_breach_the_credit_limit_together
        """
        prop, unit_b, sub_a, sub_b = self._two_pending_activations(
            api, 8000, "PROPERTY_MANAGER"
        )

        first = validate_success(api.activate_subscription(sub_a["id"], OPERATOR))
        assert first["status"] == "ACTIVE"
        assert a.property_balance(api, prop["id"], OPERATOR) == 5588

        validate_error(
            api.activate_subscription(sub_b["id"], OPERATOR),
            ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED,
            402,
        )

        assert fx.read_subscription(api, sub_b["id"])["status"] == "PENDING_SETUP"
        assert validate_success(api.get_unit(unit_b["id"], OPERATOR))["status"] == "AVAILABLE"
        assert a.property_balance(api, prop["id"], OPERATOR) == 5588
        _rows, meta = validate_paginated(api.list_ledger_entries(sub_b["id"], OPERATOR))
        assert meta["total_count"] == 0
