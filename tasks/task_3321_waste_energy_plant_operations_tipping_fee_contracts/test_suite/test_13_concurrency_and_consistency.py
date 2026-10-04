"""Concurrency and consistency tests: OCC stale-version handling, amendment
cascades invalidating pending OCC, immediate visibility, and pagination."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_received_delivery,
    make_accepted_delivery,
    make_landfill,
    make_pending_shipment,
    make_active_ppa,
    make_active_merchant_ppa,
    create_waste_supply_agreement_payload,
    create_energy_delivery_payload,
    create_boiler_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
ET = TEST_USERS["energy_trader_headers"]
EO = TEST_USERS["environmental_officer_headers"]
REG = TEST_USERS["regulator_headers"]


class TestMerchantPriceRequired:
    def test_merchant_delivery_without_price_snapshot_rejected(self):
        """PRD §3.7: "For a `MERCHANT` agreement, each delivery must additionally carry its `merchant_price_cents_per_mwh` snapshot; omitting it is rejected with `ERR_MERCHANT_PRICE_REQUIRED`."

        Design: Corner/validations/merchant_delivery_requires_price_snapshot
        """
        merchant = make_active_merchant_ppa()
        resp = api_client.create_energy_delivery(
            create_energy_delivery_payload(ppa_id=merchant["id"], delivered_mwh=500), ET
        )
        validate_error(resp, ApiErrorId.ERR_MERCHANT_PRICE_REQUIRED)


class TestEnergyDeliveryPeriodOutsideTerm:
    def test_straddling_period_rejected_but_exclusive_end_boundary_allowed(self):
        """PRD §3.7: "The period must fall entirely within the agreement's term — a delivery whose period lies outside the interval from `term_start` to `term_end` is rejected with `ERR_PERIOD_OUTSIDE_TERM`."
        PRD §3.7: "the term from `term_start` to `term_end` (exclusive, after the start)."

        Design: Corner/validations/energy_delivery_period_outside_term_rejected
        """
        ppa = make_active_ppa(
            term_start="2026-01-01T00:00:00Z", term_end="2026-12-01T00:00:00Z"
        )
        resp = api_client.create_energy_delivery(
            create_energy_delivery_payload(
                ppa_id=ppa["id"],
                period_start="2026-11-20T00:00:00Z",
                period_end="2026-12-05T00:00:00Z",
                delivered_mwh=100,
            ),
            ET,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OUTSIDE_TERM)

        # period_end exactly at term_end is inside the half-open term interval.
        ed = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(
                    ppa_id=ppa["id"],
                    period_start="2026-11-20T00:00:00Z",
                    period_end="2026-12-01T00:00:00Z",
                    delivered_mwh=100,
                ),
                ET,
            ),
            expected_status=201,
        )
        assert ed["billed_amount_cents"] == 750000


class TestFkReverseReachability:
    def test_deliveries_filtered_by_agreement_id(self):
        """PRD §3.3: "The delivery list is filterable by `agreement_id`, by `status`, and by `diversion_outage_id`."

        Design: Corner/endpoints/fk_reverse_reachability_lists_children
        """
        m1 = make_municipality()
        a1 = make_active_agreement(municipality_id=m1["id"])
        a2 = make_active_agreement(
            municipality_id=m1["id"], guaranteed_annual_tonnage=500, tipping_fee_per_tonne_cents=7000
        )
        delivery = make_delivery(a1["id"], manifest_ref="MAN-1")

        empty, meta_empty = validate_paginated(
            api_client.list_waste_deliveries(CM, params={"agreement_id": a2["id"]})
        )
        assert empty == []
        assert meta_empty["total_count"] == 0

        items, meta = validate_paginated(
            api_client.list_waste_deliveries(CM, params={"agreement_id": a1["id"]})
        )
        assert meta["total_count"] == 1
        assert [d["id"] for d in items] == [delivery["id"]]


class TestPutEditRecomputesProjection:
    def test_edit_of_scheduled_delivery_updates_projected_fee(self):
        """PRD §3.3: "While a delivery remains `SCHEDULED`, reads of it surface an advisory `projected_fee_cents`: the projection of the fee the load would incur at the agreement's current `tipping_fee_per_tonne_cents`, computed as the delivery's `tonnes` multiplied by that current rate and rounded half-up to whole cents."
        PRD §3.3: "While a delivery is `SCHEDULED`, a `PlantOperator` may edit its `tonnes`, `heating_value_mj_per_kg`, or `delivered_at`; each edit increments the delivery's `version`."

        Design: Corner/endpoints/put_edit_of_scheduled_delivery_recomputes_projection
        """
        m1 = make_municipality()
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery = make_delivery(agreement["id"], manifest_ref="MAN-1", tonnes=10)

        get_success_data(api_client.update_waste_delivery(delivery["id"], {"tonnes": 25}, PO))

        fresh = validate_success(api_client.get_waste_delivery(delivery["id"], CM))
        assert fresh["projected_fee_cents"] == 200000
        assert fresh["version"] == 2


class TestDerateRangeValidation:
    def test_derated_capacity_must_be_strictly_between_zero_and_max(self):
        """PRD §3.4: "When a boiler cannot run at full capacity but need not be taken out of service, the operator derates it, supplying a `derated_capacity_mw` strictly greater than zero and strictly less than the boiler's `max_thermal_capacity_mw`; the boiler moves from `ONLINE` to `DERATED` and the supplied value is recorded on the boiler."
        PRD §2.6: "7. Field shape and range — numeric positivity and range constraints, interval ordering, and enum membership, else `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/derate_range_validation
        """
        boiler = make_boiler()  # 50 MW

        resp = api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 0}, PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 50}, PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        derated = get_success_data(
            api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 30}, PO)
        )
        assert derated["status"] == "DERATED"
        assert derated["derated_capacity_mw"] == pytest.approx(30)


class TestDecommissionBlockedByScheduledOutage:
    def test_scheduled_outage_blocks_decommission_until_cancelled(self):
        """PRD §3.4: "Decommissioning is permanent: a boiler in `ONLINE` may be moved to the terminal `OFFLINE` status only when no outage window for that boiler is `SCHEDULED` or `ACTIVE`; attempting it otherwise is rejected with `ERR_OUTAGE_IN_PROGRESS`."
        PRD §3.4: "A `SCHEDULED` outage may instead be cancelled, moving it to the terminal `CANCELLED` status; `COMPLETED` is the other terminal state."

        Design: Corner/endpoints/decommission_blocked_by_scheduled_outage
        """
        from test_helpers import create_outage_window_payload

        boiler = make_boiler()
        outage = get_success_data(
            api_client.create_outage_window(create_outage_window_payload(boiler_id=boiler["id"]), PO)
        )

        resp = api_client.decommission_boiler(boiler["id"], PO)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_IN_PROGRESS)

        get_success_data(api_client.cancel_outage_window(outage["id"], PO))

        offline = get_success_data(api_client.decommission_boiler(boiler["id"], PO))
        assert offline["status"] == "OFFLINE"


class TestOccStaleVersionOnDeliveryAccept:
    def test_stale_agreement_version_rejected_then_fresh_version_accepted(self):
        """PRD §3.3: "Acceptance is an OCC-guarded write: the request must carry `expected_agreement_version` equal to the delivery's agreement's current `version`, else `ERR_STALE_VERSION`."
        PRD §2.9: "Accepting a received waste delivery requires `expected_agreement_version` matching the delivery's waste supply agreement's current `version`. A stale value means the agreement's rate or cumulative tonnage changed since the client read it, so the fee computed from the client's view would be wrong and the accept is refused."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_current_accepted
        """
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(municipality_id=m1["id"])
        d1 = make_received_delivery(
            agreement["id"], manifest_ref="MAN-1", tonnes=10, delivered_at="2026-09-02T08:00:00Z"
        )
        d2 = make_received_delivery(
            agreement["id"], manifest_ref="MAN-2", tonnes=20, delivered_at="2026-09-03T08:00:00Z"
        )

        # Accept of D1 bumps the agreement's version, invalidating the client's copy.
        get_success_data(
            api_client.accept_waste_delivery(
                d1["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )

        resp = api_client.accept_waste_delivery(
            d2["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        accepted = get_success_data(
            api_client.accept_waste_delivery(
                d2["id"], {"expected_agreement_version": agreement["version"] + 1}, PO
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["tipping_fee_cents"] == 160000


class TestOccStaleLandfillVersionOnComplete:
    def test_stale_landfill_version_rejected_then_fresh_version_completes(self):
        """PRD §3.9: "Completion is an OCC-guarded write requiring `expected_landfill_version` equal to the receiving landfill's current `version`, else `ERR_STALE_VERSION`."
        PRD §2.9: "Completing an ash shipment requires `expected_landfill_version` matching the receiving landfill's current `version`. A stale value means remaining capacity or status changed since the client read it, invalidating the disposal-capacity check, and the completion is refused."

        Design: Corner/cross_cutting_layers/occ_stale_landfill_version_on_complete
        """
        landfill = make_landfill(remaining_capacity_tonnes=1000, daily_receipt_limit_tonnes=500)
        s1, landfill = make_pending_shipment(
            landfill["id"], passed=True, tonnes=10, shipped_on="2026-09-06"
        )
        s2, _ = make_pending_shipment(
            landfill["id"], passed=True, tonnes=20, shipped_on="2026-09-06"
        )

        # Completing S1 bumps the landfill version, invalidating the client's copy.
        get_success_data(
            api_client.complete_ash_shipment(
                s1["id"], {"expected_landfill_version": landfill["version"]}, EO
            )
        )

        resp = api_client.complete_ash_shipment(
            s2["id"], {"expected_landfill_version": landfill["version"]}, EO
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        completed = get_success_data(
            api_client.complete_ash_shipment(
                s2["id"], {"expected_landfill_version": landfill["version"] + 1}, EO
            )
        )
        assert completed["status"] == "DISPOSED"

        fresh = validate_success(api_client.get_landfill(landfill["id"], EO))
        assert fresh["remaining_capacity_tonnes"] == pytest.approx(970, abs=1e-9)


class TestAmendmentBumpsBaseVersionInvalidatingPendingOcc:
    def test_pre_amendment_version_rejected_and_retry_bills_at_amended_rate(self):
        """PRD §3.2: "the base agreement's `guaranteed_annual_tonnage` and `tipping_fee_per_tonne_cents` are overwritten with the amendment's values, the base's `version` increments by one, and the base remains `ACTIVE` and continues to accumulate deliveries."
        PRD §3.3: "Acceptance is an OCC-guarded write: the request must carry `expected_agreement_version` equal to the delivery's agreement's current `version`, else `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/cascade_amendment_bumps_base_version_invalidating_pending_occ
        """
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery = make_received_delivery(agreement["id"], manifest_ref="MAN-1", tonnes=10)

        get_success_data(
            api_client.create_waste_supply_agreement(
                create_waste_supply_agreement_payload(
                    municipality_id=m1["id"],
                    tipping_fee_per_tonne_cents=9000,
                    amendment_of_agreement_id=agreement["id"],
                    expected_base_agreement_version=agreement["version"],
                ),
                CM,
            )
        )

        # The pre-amendment version is now stale.
        resp = api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        accepted = get_success_data(
            api_client.accept_waste_delivery(
                delivery["id"], {"expected_agreement_version": agreement["version"] + 1}, PO
            )
        )
        assert accepted["status"] == "ACCEPTED"
        # Acceptance bills at the amended rate.
        assert accepted["tipping_fee_cents"] == 90000


class TestImmediateConsistency:
    def test_accept_response_and_agreement_reflect_mutation_immediately(self):
        """PRD §3.3: "On acceptance the delivery's `tipping_fee_cents` is set — authoritatively, this once — to the delivery's `tonnes` multiplied by the agreement's `tipping_fee_per_tonne_cents` at the moment of acceptance, rounded half-up to whole cents; until acceptance the field is null. The agreement's `cumulative_delivered_tonnes` grows by the delivery's `tonnes`, so the put-or-pay base grows immediately, and both the delivery's and the agreement's `version` increment by one."

        Design: Corner/consistency_model/immediate_consistency_accept_visible_in_same_response
        """
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery = make_received_delivery(agreement["id"], manifest_ref="MAN-1", tonnes=10)

        accepted = validate_success(
            api_client.accept_waste_delivery(
                delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["tipping_fee_cents"] == 80000

        fresh = validate_success(api_client.get_waste_supply_agreement(agreement["id"], CM))
        assert fresh["cumulative_delivered_tonnes"] == pytest.approx(10, abs=1e-9)
        assert fresh["version"] == agreement["version"] + 1


class TestPaginationLimitOffsetInteraction:
    def test_default_page_and_offset_page_of_twelve_boilers(self):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and at most 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

        Design: Corner/consistency_model/pagination_limit_offset_has_more_interaction
        """
        for i in range(1, 13):
            make_boiler(name=f"Boiler-{i:02d}")

        page1, meta1 = validate_paginated(api_client.list_boilers(REG))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_boilers(REG, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12
