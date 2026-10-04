"""Agreement creation: freight-zone derivation, ledger defaults, GET roundtrip,
and body foreign-key order (PRD §2.6, §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, set_clock, create_plant, create_customer,
    create_agreement, get_agreement, create_agreement_payload, manager,
)


def _agreement_terms(plant_id, customer_id):
    return create_agreement_payload(
        plant_id, customer_id, committed_annual_units=12_000_000,
        pass_through_pct=0.92, conversion_cost_cents_per_1000=1500,
        start_date="2026-01-01", end_date="2026-12-31")


class TestFreightZone:
    def test_agreement_create_computes_freight_zone_near_mid_far(self, api):
        """PRD §3.2: "At creation the system computes the agreement's
        `freight_zone` once and freezes it: `NEAR` when the plant's `region`
        equals the customer's `home_region`, `MID` when the two region codes
        differ but share their first two characters, and `FAR` otherwise."

        Design: Corner/entities/agreement_create_computes_freight_zone_near_mid_far
        """
        set_clock()
        plant = create_plant(region="US-SW")
        cust_near = create_customer(name="Near Co", home_region="US-SW",
                                    filling_lines_count=2)
        cust_mid = create_customer(name="Mid Co", home_region="US-NE",
                                   filling_lines_count=2)
        cust_far = create_customer(name="Far Co", home_region="FR-LY",
                                   filling_lines_count=2)
        a_near = create_agreement(plant["id"], cust_near["id"])
        a_mid = create_agreement(plant["id"], cust_mid["id"])
        a_far = create_agreement(plant["id"], cust_far["id"])
        assert a_near["freight_zone"] == "NEAR"
        assert a_mid["freight_zone"] == "MID"
        assert a_far["freight_zone"] == "FAR"
        for agreement in (a_near, a_mid, a_far):
            assert agreement["status"] == "DRAFT"


class TestAgreementDefaults:
    def test_agreement_create_applies_ledger_and_accuracy_defaults(self, api):
        """PRD §3.2: "A new agreement is `DRAFT`, with `ytd_settled_units` at 0,
        `delivered_revenue_cents` at 0, `volume_tier` of `STANDARD`, and both
        accuracy fields — `rolling_accuracy_pct` and `lifetime_accuracy_pct` —
        at 100 until forecasts close."

        Design: Corner/entities/agreement_create_applies_ledger_and_accuracy_defaults
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        resp = api.create_agreement(_agreement_terms(plant["id"], customer["id"]),
                                    manager())
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["ytd_settled_units"] == 0
        assert data["delivered_revenue_cents"] == 0
        assert data["volume_tier"] == "STANDARD"
        assert data["rolling_accuracy_pct"] == 100
        assert data["lifetime_accuracy_pct"] == 100
        assert data["version"] == 1

    def test_agreement_get_roundtrips_stored_terms_unchanged(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §3.2: "At creation the system computes the agreement's
        `freight_zone` once and freezes it".

        Design: Corner/entities/agreement_get_roundtrips_stored_terms_unchanged
        """
        set_clock()
        plant = create_plant(region="US-SW")
        customer = create_customer(home_region="US-SW", filling_lines_count=4)
        agreement = create_agreement(plant["id"], customer["id"],
                                     pass_through_pct=0.92)
        data = get_agreement(agreement["id"])
        assert data["committed_annual_units"] == 12_000_000
        assert data["pass_through_pct"] == pytest.approx(0.92)
        assert data["conversion_cost_cents_per_1000"] == 1500
        assert data["start_date"] == "2026-01-01"
        assert data["end_date"] == "2026-12-31"
        assert data["freight_zone"] == "NEAR"
        assert data["status"] == "DRAFT"


class TestAgreementFkOrder:
    def test_agreement_create_body_fk_order_plant_then_customer(self, api):
        """PRD §2.6: "foreign keys carried in the request body are checked in
        the endpoint's declared input order, and each missing reference maps to
        its own error: a `plant_id` that matches no plant is rejected with
        `ERR_PLANT_NOT_FOUND`, a `customer_id` with `ERR_CUSTOMER_NOT_FOUND`".

        Design: Corner/errors/agreement_create_body_fk_order_plant_then_customer
        """
        set_clock()
        plant = create_plant()
        bogus_plant = "00000000-0000-4000-8000-000000000001"
        bogus_customer = "00000000-0000-4000-8000-000000000002"
        resp_both = api.create_agreement(
            _agreement_terms(bogus_plant, bogus_customer), manager())
        err_both = validate_error(resp_both, ApiErrorId.ERR_PLANT_NOT_FOUND)
        assert err_both["error_id"] != ApiErrorId.ERR_CUSTOMER_NOT_FOUND
        resp_cust = api.create_agreement(
            _agreement_terms(plant["id"], bogus_customer), manager())
        validate_error(resp_cust, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
        data, _meta = validate_paginated(api.list_agreements(manager()))
        assert len(data) == 0, "no agreement persisted after rejected creates"
