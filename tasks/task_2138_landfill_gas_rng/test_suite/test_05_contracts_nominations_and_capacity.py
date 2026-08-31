"""The commercial desk: offtake contracts, gas-day nominations, pooled
receipt-point capacity and the optimistic-concurrency guard on contract writes."""

from test_helpers import (
    ApiErrorId,
    approx_2dp,
    approx_4dp,
    assert_pipeline_nomination,
    create_nomination_payload,
    create_offtake_contract_payload,
    fixtures,
    make_offtaker_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BASE_CLOCK_UTC


def _site_plant_and_active_contract(contract_overrides=None):
    set_clock(BASE_CLOCK_UTC)
    site = fixtures.create_site()
    plant = fixtures.create_plant(site["id"])
    contract = fixtures.create_active_contract(site["id"], **(contract_overrides or {}))
    return site, plant, contract


class TestReceiptPointCapacity:
    def test_two_nominations_landing_exactly_on_the_receipt_point_cap_are_accepted(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "The nomination's own `hourly_rate_dth` is its `nominated_dth`
        divided by the length of its window in hours, rounded half up to four decimal
        places."
        PRD §3.6: "The new nomination is accepted when the committed hourly rate plus the
        new nomination's hourly rate, rounded half up to four decimal places, is less
        than or equal to the cap rounded half up to four decimal places — landing exactly
        on the cap is accepted. Exceeding it is refused with
        `ERR_RECEIPT_POINT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/nomination_half_open_windows_pool_receipt_point_capacity
        """
        site, plant, contract = _site_plant_and_active_contract()
        # The cap is 4800.0 / 24 = 200.0 dth per hour.
        window = {
            "gas_day_start": "2026-08-11T00:00:00Z",
            "gas_day_end": "2026-08-12T00:00:00Z",
        }

        first = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    fixtures.contract_version(contract["id"]),
                    nominated_dth=2400.0,
                    **window,
                ),
                scheduler_headers,
            ),
            201,
        )
        assert_pipeline_nomination(first)
        assert first["hourly_rate_dth"] == approx_4dp(100.0)
        assert first["status"] == "DRAFT"
        assert first["committed_dth"] == approx_2dp(0.0)
        assert first["delivered_dth"] == approx_2dp(0.0)
        assert first["curtail_reason"] is None

        second = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    fixtures.contract_version(contract["id"]),
                    nominated_dth=2400.0,
                    **window,
                ),
                scheduler_headers,
            ),
            201,
        )
        assert second["hourly_rate_dth"] == approx_4dp(100.0), (
            "100.0 + 100.0 lands exactly on the 200.0 dth/hour cap"
        )

        validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    fixtures.contract_version(contract["id"]),
                    nominated_dth=24.0,
                    **window,
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_RECEIPT_POINT_CAPACITY_EXCEEDED.value,
        )

    def test_adjacent_gas_day_nomination_does_not_share_receipt_point_capacity(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "The nominations competing for the same capacity are those of the
        same plant whose `status` is `DRAFT`, `CONFIRMED` or `SCHEDULED` and whose
        half-open window intersects the requested half-open window; nominations that are
        `DELIVERED`, `CURTAILED` or `CANCELLED` have released their capacity and are
        excluded entirely."
        PRD §3.6: "Because the windows are half-open, a nomination that ends at the exact
        instant another begins does not intersect it and does not consume shared capacity,
        which is precisely the geometry the pipeline's own gas-day accounting uses."

        Design: Difficulty/resource_temporal_overlap/nomination_half_open_windows_pool_receipt_point_capacity
        """
        site, plant, contract = _site_plant_and_active_contract()
        for _ in range(2):
            validate_success(
                api.create_nomination(
                    create_nomination_payload(
                        contract["id"],
                        plant["id"],
                        fixtures.contract_version(contract["id"]),
                        nominated_dth=2400.0,
                        gas_day_start="2026-08-11T00:00:00Z",
                        gas_day_end="2026-08-12T00:00:00Z",
                    ),
                    scheduler_headers,
                ),
                201,
            )

        adjacent = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    fixtures.contract_version(contract["id"]),
                    nominated_dth=2400.0,
                    gas_day_start="2026-08-12T00:00:00Z",
                    gas_day_end="2026-08-13T00:00:00Z",
                ),
                scheduler_headers,
            ),
            201,
        )
        assert adjacent["hourly_rate_dth"] == approx_4dp(100.0)
        assert adjacent["status"] == "DRAFT", (
            "the 2026-08-12 window starts exactly where the full 2026-08-11 window ends, "
            "so the two half-open windows never intersect"
        )

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"plant_id": plant["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 3


class TestNominationRejections:
    def test_nomination_against_a_contract_still_pending_is_refused(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "The contract must be in `ACTIVE`; a nomination against a contract
        still `PENDING`, or one that has been `SUSPENDED` or `TERMINATED`, is refused with
        `ERR_CONTRACT_NOT_ACTIVE`."
        PRD §3.6: "A new contract opens in `status` `PENDING` with `delivered_dth_mtd` at
        0, and a `ProjectAdmin` or `CommercialScheduler` then moves it to `ACTIVE`,
        `SUSPENDED` or `TERMINATED` as the commercial relationship dictates."

        Design: Corner/state_machines/nomination_against_pending_contract_returns_contract_not_active
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])
        contract = validate_success(
            api.create_offtake_contract(
                create_offtake_contract_payload(site["id"]), scheduler_headers
            ),
            201,
        )
        assert contract["status"] == "PENDING"

        validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    contract["version"],
                    gas_day_start="2026-08-11T00:00:00Z",
                    gas_day_end="2026-08-12T00:00:00Z",
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
        )

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"contract_id": contract["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

    def test_gas_day_window_that_does_not_run_forward_is_refused(
        self, api, scheduler_headers
    ):
        """PRD §2.5: "**Interval direction (priority 57).** An interval's end instant
        must be strictly after its start instant, or `ERR_INTERVAL_INVALID` with HTTP
        422. This covers a work order's `window_end` against `window_start`, a
        nomination's `gas_day_end` against `gas_day_start`, a contract's `term_end`
        against `term_start`, and the `end_at` supplied when a downtime record is closed
        against that record's `start_at`."

        Design: Corner/validations/nomination_with_zero_length_window_is_rejected
        """
        site, plant, contract = _site_plant_and_active_contract()

        validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    contract["version"],
                    gas_day_start="2026-08-11T00:00:00Z",
                    gas_day_end="2026-08-11T00:00:00Z",
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_INTERVAL_INVALID.value,
        )

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"contract_id": contract["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

    def test_nomination_escaping_the_contract_term_is_refused(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "The nominated window must lie entirely inside the contract term,
        from `term_start` inclusive to `term_end` exclusive, or the write is refused with
        `ERR_CONTRACT_TERM_WINDOW`."

        Design: Corner/validations/nomination_outside_contract_term_is_rejected
        """
        site, plant, contract = _site_plant_and_active_contract(
            {"term_start": "2026-08-01T00:00:00Z", "term_end": "2026-09-01T00:00:00Z"}
        )

        validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    contract["version"],
                    gas_day_start="2026-09-05T00:00:00Z",
                    gas_day_end="2026-09-06T00:00:00Z",
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_CONTRACT_TERM_WINDOW.value,
        )

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"contract_id": contract["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

    def test_nomination_above_the_contract_daily_quantity_is_refused_before_capacity(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "The nominated quantity must not exceed the contract's
        `contract_mdq_dth_per_day`, or `ERR_CONTRACT_MDQ_EXCEEDED`. And only after that
        daily-quantity check does the receipt point itself get tested."

        Design: Corner/errors/nomination_above_contract_mdq_is_rejected
        """
        site, plant, contract = _site_plant_and_active_contract()

        # 3500 dth over 24 hours is 145.8333 dth/hour, comfortably under the 200.0 cap,
        # so only the contract's 3000.0 dth/day quota can be what refuses this.
        error = validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    contract["version"],
                    nominated_dth=3500.0,
                    gas_day_start="2026-08-11T00:00:00Z",
                    gas_day_end="2026-08-12T00:00:00Z",
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_CONTRACT_MDQ_EXCEEDED.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_RECEIPT_POINT_CAPACITY_EXCEEDED.value

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"plant_id": plant["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

    def test_confirming_an_already_confirmed_nomination_is_refused(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "Confirming it takes `DRAFT → CONFIRMED` and requires the parent
        contract to be in `ACTIVE`, failing which the confirmation is refused with
        `ERR_CONTRACT_NOT_ACTIVE`; a `ProjectAdmin`, a `CommercialScheduler`, or the
        `Offtaker` that owns the contract may confirm, and an offtaker acting on a
        nomination whose `contract_id` is not its own identifier is refused with
        `ERR_NOT_RESOURCE_OWNER`."
        PRD §3.6: "Curtailment and cancellation are `CommercialScheduler` prerogatives on
        the operator path. Every other status pair is refused with
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/second_confirm_on_nomination_returns_invalid_transition
        """
        site, plant, contract = _site_plant_and_active_contract()
        nomination = fixtures.create_confirmed_nomination(
            contract["id"],
            plant["id"],
            gas_day_start="2026-08-11T00:00:00Z",
            gas_day_end="2026-08-12T00:00:00Z",
        )
        assert nomination["status"] == "CONFIRMED"

        validate_error(
            api.set_nomination_status(
                nomination["id"], {"to_status": "CONFIRMED"}, scheduler_headers
            ),
            ApiErrorId.ERR_INVALID_TRANSITION.value,
        )
        assert fixtures.read_nomination(nomination["id"])["status"] == "CONFIRMED"


class TestContractConcurrency:
    def test_stale_expected_contract_version_is_refused_until_the_client_re_reads(
        self, api, scheduler_headers
    ):
        """PRD §2.7: "A `POST /pipeline-nominations` request must carry
        `expected_contract_version`, a non-optional field holding the `version` of the
        target `OfftakeContract` that the client last observed. If that value does not
        equal the contract's current `version`, the create is rejected with
        `ERR_STALE_CONTRACT_VERSION` and HTTP 412."
        PRD §2.7: "A successful create increments the contract's `version` by one, so the
        next writer must re-read before it can write."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_contract_version_on_nomination_create_returns_precondition_failed
        """
        site, plant, contract = _site_plant_and_active_contract()
        observed = fixtures.contract_version(contract["id"])

        first = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    observed,
                    gas_day_start="2026-08-11T00:00:00Z",
                    gas_day_end="2026-08-12T00:00:00Z",
                ),
                scheduler_headers,
            ),
            201,
        )
        assert first["status"] == "DRAFT"

        validate_error(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    observed,
                    gas_day_start="2026-08-13T00:00:00Z",
                    gas_day_end="2026-08-14T00:00:00Z",
                ),
                scheduler_headers,
            ),
            ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
        )

        fresh = fixtures.contract_version(contract["id"])
        assert fresh == observed + 1, "the successful create advanced the contract"

        retried = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    fresh,
                    gas_day_start="2026-08-13T00:00:00Z",
                    gas_day_end="2026-08-14T00:00:00Z",
                ),
                scheduler_headers,
            ),
            201,
        )
        assert retried["hourly_rate_dth"] == approx_4dp(100.0)

        _, meta = validate_paginated(
            api.list_nominations(
                scheduler_headers,
                params={"contract_id": contract["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2

    def test_contract_version_advances_by_exactly_one_on_every_mutation(
        self, api, scheduler_headers
    ):
        """PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the
        current logical instant on every mutation, and `version`, an integer that starts
        at 1 on creation and increments by exactly one on every mutation of the row."
        PRD §3.6: "Every such status change increments the contract's `version` by one,
        which matters a great deal for the concurrency rule below."
        PRD §3.6: "A successful write also increments the parent contract's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_by_one_on_every_mutation
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])

        contract = validate_success(
            api.create_offtake_contract(
                create_offtake_contract_payload(site["id"]), scheduler_headers
            ),
            201,
        )
        assert contract["version"] == 1

        activated = validate_success(
            api.set_contract_status(
                contract["id"], {"to_status": "ACTIVE"}, scheduler_headers
            )
        )
        assert activated["version"] == 2

        nomination = validate_success(
            api.create_nomination(
                create_nomination_payload(
                    contract["id"],
                    plant["id"],
                    activated["version"],
                    gas_day_start="2026-08-11T00:00:00Z",
                    gas_day_end="2026-08-12T00:00:00Z",
                ),
                scheduler_headers,
            ),
            201,
        )
        assert nomination["version"] == 1, "a freshly created nomination starts at 1"

        after_nomination = fixtures.read_contract(contract["id"])
        assert after_nomination["version"] == 3, (
            "the nomination write advanced its parent contract as a side effect"
        )
        assert after_nomination["status"] == "ACTIVE"


class TestOfftakerOwnership:
    def test_offtaker_cannot_confirm_a_nomination_written_against_another_contract(
        self, api, scheduler_headers
    ):
        """PRD §2.1: "When `X-User-Role` is `Offtaker`, `X-User-ID` is the `id` of the
        acting `OfftakeContract`; ownership checks compare a nomination's `contract_id` —
        or, when the contract itself is being read, the contract's own `id` — to
        `X-User-ID`. An entity-backed role that reaches for a resource it does not own is
        rejected with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

        Design: Corner/rbac/offtaker_cannot_confirm_a_nomination_written_against_another_contract
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])
        contract_a = fixtures.create_active_contract(site["id"])
        contract_b = fixtures.create_active_contract(
            site["id"], counterparty_name="Northstar Gas", price_usd_per_dth=5.10
        )
        nomination = fixtures.create_nomination(
            contract_a["id"],
            plant["id"],
            gas_day_start="2026-08-11T00:00:00Z",
            gas_day_end="2026-08-12T00:00:00Z",
        )

        validate_error(
            api.set_nomination_status(
                nomination["id"],
                {"to_status": "CONFIRMED"},
                make_offtaker_headers(contract_b["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        )

        unchanged = fixtures.read_nomination(nomination["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["contract_id"] == contract_a["id"]

    def test_offtaker_may_confirm_a_nomination_on_its_own_contract(
        self, api, scheduler_headers
    ):
        """PRD §3.6: "Confirming it takes `DRAFT → CONFIRMED` and requires the parent
        contract to be in `ACTIVE`, failing which the confirmation is refused with
        `ERR_CONTRACT_NOT_ACTIVE`; a `ProjectAdmin`, a `CommercialScheduler`, or the
        `Offtaker` that owns the contract may confirm, and an offtaker acting on a
        nomination whose `contract_id` is not its own identifier is refused with
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/offtaker_can_confirm_a_nomination_on_its_own_contract
        """
        site, plant, contract = _site_plant_and_active_contract()
        nomination = fixtures.create_nomination(
            contract["id"],
            plant["id"],
            gas_day_start="2026-08-11T00:00:00Z",
            gas_day_end="2026-08-12T00:00:00Z",
        )
        offtaker = make_offtaker_headers(contract["id"])

        confirmed = validate_success(
            api.set_nomination_status(
                nomination["id"], {"to_status": "CONFIRMED"}, offtaker
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["hourly_rate_dth"] == approx_4dp(100.0)

        own_contract = validate_success(
            api.get_offtake_contract(contract["id"], offtaker)
        )
        assert own_contract["status"] == "ACTIVE"
