"""Commercial variant tests: tipping fee acceptance vs projection, and
contracted vs merchant energy billing."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_received_delivery,
    make_accepted_delivery,
    make_active_ppa,
    make_active_merchant_ppa,
    create_waste_supply_agreement_payload,
    create_energy_delivery_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
ET = TEST_USERS["energy_trader_headers"]
REG = TEST_USERS["regulator_headers"]


def _setup_amendment_scenario():
    """Agreement ACTIVE at rate 8000, one delivery ACCEPTED, one still SCHEDULED,
    then an amendment at rate 9000 applied. Returns (agreement, accepted_delivery,
    scheduled_delivery_id)."""
    m1 = make_municipality()
    make_boiler()
    agreement = make_active_agreement(municipality_id=m1["id"], tipping_fee_per_tonne_cents=8000)
    accepted, agreement = make_accepted_delivery(
        agreement, manifest_ref="MAN-D1", tonnes=10, delivered_at="2026-09-02T08:00:00Z"
    )
    scheduled = make_delivery(
        agreement["id"], manifest_ref="MAN-D2", tonnes=10, delivered_at="2026-09-03T08:00:00Z"
    )
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
    return agreement, accepted, scheduled["id"]


class TestTippingFeeProjectionDivergesAfterAmendment:
    def test_accepted_fee_persists_at_original_rate_and_projection_uses_amended_rate(self):
        """PRD §3.3: "On acceptance the delivery's `tipping_fee_cents` is set — authoritatively, this once — to the delivery's `tonnes` multiplied by the agreement's `tipping_fee_per_tonne_cents` at the moment of acceptance, rounded half-up to whole cents; until acceptance the field is null."
        PRD §3.3: "the projection of the fee the load would incur at the agreement's current `tipping_fee_per_tonne_cents`, computed as the delivery's `tonnes` multiplied by that current rate and rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/tipping_fee_projection_diverges_after_amendment
        """
        agreement, accepted, scheduled_id = _setup_amendment_scenario()

        assert accepted["tipping_fee_cents"] == 80000

        d2 = validate_success(api_client.get_waste_delivery(scheduled_id, REG))
        assert d2["projected_fee_cents"] == 90000
        assert d2["tipping_fee_cents"] is None

        base = validate_success(api_client.get_waste_supply_agreement(agreement["id"], CM))
        assert base["tipping_fee_per_tonne_cents"] == 9000

    def test_projection_recomputed_per_read_while_accepted_fee_is_immutable(self):
        """PRD §3.3: "The projection is advisory only — it is never persisted as the actual fee, and because an amendment may supersede the base rate at any moment, the projection may differ from the fee eventually charged at acceptance."
        PRD §3.2: "the base agreement's `guaranteed_annual_tonnage` and `tipping_fee_per_tonne_cents` are overwritten with the amendment's values, the base's `version` increments by one, and the base remains `ACTIVE` and continues to accumulate deliveries."

        Design: Difficulty/dual_variant_calc/tipping_fee_projection_diverges_after_amendment
        """
        agreement, accepted, scheduled_id = _setup_amendment_scenario()

        # The SCHEDULED delivery shows the amended rate on every read.
        for _ in range(2):
            d2 = validate_success(api_client.get_waste_delivery(scheduled_id, REG))
            assert d2["projected_fee_cents"] == 90000
            assert d2["tipping_fee_cents"] is None

        # The previously ACCEPTED delivery's persisted fee never moves.
        d1 = validate_success(api_client.get_waste_delivery(accepted["id"], REG))
        assert d1["tipping_fee_cents"] == 80000
        assert d1["status"] == "ACCEPTED"


class TestEnergyBillingContractedVsMerchant:
    def _setup_ppas(self):
        ppa = make_active_ppa()
        merchant = make_active_merchant_ppa()
        return ppa, merchant

    def test_identical_mwh_bills_differently_under_contracted_and_merchant_variants(self):
        """PRD §3.7: "Under the contracted variant (`PPA`), the `billed_amount_cents` is the `delivered_mwh` multiplied by the agreement's `energy_rate_cents_per_mwh`. Under the merchant variant, it is the `delivered_mwh` multiplied by the delivery's own `merchant_price_cents_per_mwh`."

        Design: Difficulty/dual_variant_calc/energy_billing_contracted_vs_merchant
        """
        ppa, merchant = self._setup_ppas()

        ed1 = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(ppa_id=ppa["id"], delivered_mwh=500), ET
            ),
            expected_status=201,
        )
        assert ed1["billed_amount_cents"] == 3750000

        ed2 = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(
                    ppa_id=merchant["id"], delivered_mwh=500, merchant_price_cents_per_mwh=6900
                ),
                ET,
            ),
            expected_status=201,
        )
        assert ed2["billed_amount_cents"] == 3450000
        assert ed1["billed_amount_cents"] != ed2["billed_amount_cents"]

    def test_merchant_delivery_has_zero_capacity_payment(self):
        """PRD §3.7: "For a `MERCHANT` agreement this is unconditionally zero."
        PRD §3.7: "Because the two variants draw on different rates, the same delivered quantity under the two kinds generally yields different billed amounts."

        Design: Difficulty/dual_variant_calc/energy_billing_contracted_vs_merchant
        """
        ppa, merchant = self._setup_ppas()
        make_boiler()  # PPA capacity payment draws on available boiler MW.

        ed1 = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(ppa_id=ppa["id"], delivered_mwh=500), ET
            ),
            expected_status=201,
        )
        assert ed1["capacity_payment_cents"] > 0

        ed2 = validate_success(
            api_client.create_energy_delivery(
                create_energy_delivery_payload(
                    ppa_id=merchant["id"], delivered_mwh=500, merchant_price_cents_per_mwh=6900
                ),
                ET,
            ),
            expected_status=201,
        )
        assert ed2["capacity_payment_cents"] == 0
