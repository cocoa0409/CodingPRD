"""Corner coverage: action and bulk endpoints."""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_allocation_hold, create_and_commit_allocation_hold,
    create_allocation_forecast, get_supply_node, get_partner, get_product,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]


class TestSupplyNodeStageCycle:
    """Draining then binding settles penalties; returning to OPEN resets the score."""

    def _pool_in_friction_hold(self):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        # A COOL pool refuses a WARM hold at the band check, so a HOT-declared pool is
        # used: it accepts the WARM hold, then re-derives its ceiling to COOL once the
        # epoch advance re-splits the committed-rate temperature.
        node = create_supply_node(product["id"], node_code="POOL-HOT-1",
                                  requested_hotness_tier="HOT", node_region="EMEA")
        hold = create_allocation_hold(product["id"], node["id"], 500, partner["id"],
                                      hold_friction_tier="WARM")
        get_success_data(api.advance_epoch(ADMIN))
        get_success_data(api.cancel_allocation_hold(hold["id"],
                                                    make_partner_ops_headers(partner["id"])))
        # Return the pool to OPEN from FRICTION_HOLD so the drain step's OPEN
        # precondition and zero-held-units precondition are both satisfied.
        reopened = validate_success(api.set_supply_node_stage(
            node["id"], {"target_stage": "OPEN"}, PLANNER))
        assert reopened["stage"] == "OPEN"
        return partner, product, node

    def test_drain_then_bind_then_open_settles_and_resets(self):
        """PRD §3.3: "From `DRAINING` the pool may be bound, moving to `BINDING` provided
        its friction score does not exceed 4.0; entering `BINDING` settles every active
        penalty on the pool."
        PRD §2.6: "it decays at every epoch advance and is reset to 0.0 when the pool
        returns to `OPEN` from `BINDING`."

        Design: Corner/endpoints/supply_node_binding_crystallises_penalties_and_reopen_resets_the_score
        """
        partner, product, node = self._pool_in_friction_hold()

        drained = validate_success(api.set_supply_node_stage(
            node["id"], {"target_stage": "DRAINING"}, PLANNER))
        assert drained["stage"] == "DRAINING"
        bound = validate_success(api.set_supply_node_stage(
            node["id"], {"target_stage": "BINDING"}, PLANNER))
        assert bound["stage"] == "BINDING"

        penalties, _ = validate_paginated(api.list_friction_penalties(
            PLANNER, params={"supply_node_id": node["id"]}))
        assert penalties[0]["penalty_state"] == "SETTLED", (
            "entering BINDING settles every active penalty on the pool"
        )

    def test_returning_the_pool_to_open_resets_the_friction_score(self):
        """PRD §2.6: "it decays at every epoch advance and is reset to 0.0 when the pool
        returns to `OPEN` from `BINDING`."

        Design: Corner/endpoints/supply_node_binding_crystallises_penalties_and_reopen_resets_the_score
        """
        partner, product, node = self._pool_in_friction_hold()
        validate_success(api.set_supply_node_stage(node["id"], {"target_stage": "DRAINING"},
                                                   PLANNER))
        validate_success(api.set_supply_node_stage(node["id"], {"target_stage": "BINDING"},
                                                   PLANNER))

        reopened = validate_success(api.set_supply_node_stage(
            node["id"], {"target_stage": "OPEN"}, PLANNER))
        assert reopened["stage"] == "OPEN"
        assert reopened["friction_penalty_score"] == 0.0, (
            f"returning to OPEN resets the friction score, got "
            f"{reopened['friction_penalty_score']}"
        )


class TestBulkAllocationHolds:
    """The bulk form creates one reservation per member and advances the version once."""

    def test_bulk_request_creates_one_hold_per_member(self):
        """PRD §3.4: "the bulk form of this request reserves for several SKUs at once,
        creating one hold per `members` entry all in `REQUESTED` state, advancing the
        partner by a single version for the whole batch, and recomputing the pool's
        commitment fee and temperature once."

        Design: Corner/endpoints/allocation_holds_bulk_creates_one_reservation_per_licence_member
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])

        response = api.create_allocation_holds_bulk({
            "partner_id": partner["id"],
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "hold_friction_tier": "COOL",
            "members": [{"license_code": "SL-A"}, {"license_code": "SL-B"},
                        {"license_code": "SL-C"}],
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        holds = validate_success(response)
        assert len(holds) == 3, f"one hold per member entry, got {len(holds)}"

        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]), params={"partner_id": partner["id"]}))
        assert meta["total_count"] == 3
        assert all(row["state"] == "REQUESTED" for row in data), (
            "every bulk member opens in REQUESTED"
        )

    def test_bulk_request_advances_the_partner_version_exactly_once(self):
        """PRD §3.4: "advancing the partner by a single version for the whole batch".
        PRD §2.8: "a cancellation from either `REQUESTED` or `COMMITTED` subtracts the
        quantity" — REQUESTED holds are not yet committed, so the ledger is untouched.

        Design: Corner/endpoints/allocation_holds_bulk_creates_one_reservation_per_licence_member
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        before = get_partner(partner["id"])
        product_state = get_product(product["id"])

        validate_success(api.create_allocation_holds_bulk({
            "partner_id": partner["id"],
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "hold_friction_tier": "COOL",
            "members": [{"license_code": "SL-A"}, {"license_code": "SL-B"},
                        {"license_code": "SL-C"}],
            "expected_partner_version": before["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"])), 200)

        after = get_partner(partner["id"])
        assert after["version"] == before["version"] + 1, (
            f"the whole batch advances the partner by one version, got "
            f"{after['version']} from {before['version']}"
        )
        assert after["capacity_ledger_net"] == 0, (
            "REQUESTED holds are not yet committed, so the ledger is untouched"
        )


class TestEmptyCandidateRanking:
    """The ranking read returns an empty array rather than an error."""

    def test_empty_candidate_set_returns_an_empty_array(self):
        """PRD §3.3: "An empty candidate set returns an empty array at that surface
        rather than an error; the error case belongs to the allocation path."

        Design: Corner/endpoints/empty_candidate_ranking_returns_an_empty_array_not_an_error
        """
        startup_clock()
        partner = create_validated_partner()
        product = create_product()
        node = create_supply_node(product["id"])

        response = api.rank_supply_node(node["id"], PLANNER)
        data = validate_success(response)
        assert data == [], f"the ranking array is empty, got {data}"
        assert response.json()["response_type"] == "array"