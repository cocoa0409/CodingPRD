"""Early termination: exposure breakdown and terminal status (PRD §3.2)."""
from test_helpers import (
    validate_success, set_clock, create_plant, create_customer,
    create_active_agreement, create_qualified_format, get_agreement,
    manager, api_client,
)


class TestTerminateExposure:
    def test_terminate_returns_exposure_breakdown_and_terminal_status(self, api):
        """PRD §3.2: "Termination computes the customer's early-exit exposure
        and returns the breakdown in the response — `agreement_id`, the
        resulting `status`, `shortfall_fee_cents`, `unamortized_tooling_cents`,
        and `total_exposure_cents`. The shortfall fee charges for undelivered
        commitment: the shortfall in units is the greater of zero and
        `committed_annual_units` minus `ytd_settled_units`, and the fee is that
        shortfall divided by one thousand and multiplied by 400 cents, rounded
        half-up to whole cents. The tooling component sums, over every can
        format belonging to the agreement's customer at the agreement's plant
        that still stands `TOOLED` or `QUALIFIED`, each format's unamortized
        exposure as defined in §3.3".

        Design: Corner/endpoints/terminate_returns_exposure_breakdown_and_terminal_status
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"],
                                            committed_annual_units=12_000_000)
        create_qualified_format(plant["id"], customer["id"],
                                size_code="8OZ-SLEEK", shape="SLEEK",
                                is_specialty=True, metal_lbs_per_1000_units=22.0,
                                tooling_investment_cents=500000,
                                min_volume_commitment_units=1000000)
        data = validate_success(
            api.terminate_agreement(agreement["id"], manager()))
        assert data["status"] == "TERMINATED"
        assert data["agreement_id"] == agreement["id"]
        # max(0, 12000000 - 0) / 1000 x 400
        assert data["shortfall_fee_cents"] == 4800000
        # 500000 x (1 - 0/1000000), per-format rounded then summed
        assert data["unamortized_tooling_cents"] == 500000
        assert data["total_exposure_cents"] == 5300000
        assert get_agreement(agreement["id"])["status"] == "TERMINATED"
