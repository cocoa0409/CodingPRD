"""The operations checkpoint: ops_run_index and the two expiry sweeps
(PRD §2.4). All clock movement is forward from the startup default."""
from test_helpers import (
    validate_success, set_clock, create_plant, create_customer,
    create_active_agreement, create_scrap_return, get_agreement,
    manager, api_client,
)


class TestRunOps:
    def test_run_ops_expires_past_end_agreements_and_stale_pickups(self, api):
        """PRD §2.4: "Running the checkpoint increments that plant's
        `ops_run_index` by 1 and bumps the plant's `version`, then performs two
        expiry sweeps against the logical clock: - Every supply agreement still
        in `ACTIVE` or `RENEGOTIATING` status whose `end_date` is strictly
        before the logical clock's current date transitions to `EXPIRED` ...
        - Every scrap return still `SCHEDULED` whose `pickup_window_end` is
        strictly before the logical clock transitions to `EXPIRED`".

        Design: Corner/cross_cutting_layers/run_ops_expires_past_end_agreements_and_stale_pickups
        """
        # Clock at the startup default 2026-09-01; agreement ends 2026-09-30,
        # pickup window ends 2026-09-10 — both reachable without moving the
        # clock backwards.
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"],
                                            start_date="2026-09-01",
                                            end_date="2026-09-30")
        pickup = create_scrap_return(
            customer["id"], plant["id"],
            pickup_window_start="2026-09-10T09:00:00Z",
            pickup_window_end="2026-09-10T10:00:00Z")
        set_clock("2026-10-02T00:00:00Z")
        plant_after = validate_success(api.run_ops(plant["id"], manager()))
        assert plant_after["ops_run_index"] == 1
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"
        sr = validate_success(api.get_scrap_return(pickup["id"], manager()))
        assert sr["status"] == "EXPIRED"
        # A second checkpoint sweeps nothing already terminal; the index still
        # advances by exactly 1.
        plant_second = validate_success(api.run_ops(plant["id"], manager()))
        assert plant_second["ops_run_index"] == 2
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"
        sr2 = validate_success(api.get_scrap_return(pickup["id"], manager()))
        assert sr2["status"] == "EXPIRED"
