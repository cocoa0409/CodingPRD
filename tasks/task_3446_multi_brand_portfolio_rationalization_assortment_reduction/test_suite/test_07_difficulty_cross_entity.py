"""Difficulty queue: cross-entity state dependencies — Divestiture.separate
gated on the linked TSA, and ProductTransfer creation gated on the target
plant's state.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    announce_closure,
    create_plant,
    create_product_transfer_payload,
    set_clock,
    setup_closed_plant,
    setup_divestiture_closed,
    setup_listed_item,
    terminate_tsa,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


class TestSeparateRequiresTsaTerminated:
    def test_separate_blocked_while_tsa_active(self):
        """PRD §3.5: "Final separation requires the divestiture to be `CLOSED`
        and its TSA to be `TERMINATED`; if services are still running (or the
        TSA has not even activated) the separation is rejected with
        `ERR_TSA_STILL_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/separate_requires_tsa_terminated
        """
        _, divestiture, tsa = setup_divestiture_closed()
        assert tsa["tsa_status"] == "ACTIVE", "Setup failed: TSA must be ACTIVE"
        resp = api_client.separate_divestiture(divestiture["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TSA_STILL_ACTIVE)
        after = validate_ok(api_client.get_divestiture(divestiture["id"], PM))
        assert after["divestiture_status"] == "CLOSED"

    def test_separate_after_natural_termination_succeeds(self):
        """PRD §3.5: "if that figure is zero or negative the termination is
        natural and the penalty is 0."
        PRD §3.5: "Separation moves the divestiture from `CLOSED` to
        `SEPARATED` and the brand from `DIVESTED` to `EXITED`, incrementing
        both versions. `EXITED` is the brand's terminal state."

        Design: Difficulty/cross_entity_state_dependency/separate_requires_tsa_terminated
        """
        brand, divestiture, tsa = setup_divestiture_closed(
            tsa_start_date="2026-09-01T00:00:00Z",
            tsa_end_date="2027-09-01T00:00:00Z",
        )
        # Terminate exactly at end_date: days remaining = 0 -> natural.
        set_clock("2027-09-01T00:00:00Z")
        terminated = terminate_tsa(tsa["id"])
        assert terminated["tsa_status"] == "TERMINATED"
        assert terminated["early_termination_penalty_cents"] == 0, (
            f"termination at clock == end_date is natural: penalty must be 0, "
            f"got {terminated['early_termination_penalty_cents']}"
        )
        separated = validate_ok(api_client.separate_divestiture(divestiture["id"], PM))
        assert separated["divestiture_status"] == "SEPARATED"
        brands, _ = validate_paginated(api_client.list_brands(PM))
        brand_after = {b["id"]: b for b in brands}[brand["id"]]
        assert brand_after["brand_status"] == "EXITED"


class TestTransferRequiresTargetPlantOperating:
    def test_closing_target_plant_rejected(self):
        """PRD §3.4: "The target plant must be `OPERATING`; a `CLOSING` or
        `CLOSED` target is rejected with `ERR_TARGET_PLANT_NOT_OPERATING`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_target_plant_operating
        """
        _, _, item = setup_listed_item()
        source_id = item["primary_plant_id"]
        closing = create_plant(quarterly_capacity_units=1000000)
        announce_closure(closing["id"])
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(item["id"], source_id, closing["id"]),
            SCP,
        )
        validate_error(resp, ApiErrorId.ERR_TARGET_PLANT_NOT_OPERATING)
        transfers, _ = validate_paginated(
            api_client.list_product_transfers(SCP, params={"item_id": item["id"]})
        )
        assert transfers == [], "No transfer may be persisted on a rejected create"

    def test_closed_target_plant_rejected(self):
        """PRD §3.4: "The target plant must be `OPERATING`; a `CLOSING` or
        `CLOSED` target is rejected with `ERR_TARGET_PLANT_NOT_OPERATING`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/transfer_requires_target_plant_operating
        """
        _, _, item = setup_listed_item()
        closed = setup_closed_plant()
        assert closed["plant_status"] == "CLOSED", "Setup failed: plant must be CLOSED"
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(
                item["id"], item["primary_plant_id"], closed["id"]
            ),
            SCP,
        )
        validate_error(resp, ApiErrorId.ERR_TARGET_PLANT_NOT_OPERATING)
