"""Boundary precision: the inspection deadline, the per-load fee month window
and the derived offer pay ceiling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_fleet_unit,
    enroll_agent,
    enroll_capacity_owner,
    get_success_data,
    setup_pending_bco_with_unit,
    set_logical_clock,
    validate_error,
    validate_success,
)


class TestInspectionDeadline:
    """The exclusive deadline instant."""

    def test_inspection_deadline_exclusive_boundary(self, api):
        """PRD §2.9: "Recording a passing inspection requires the supplied
        `inspected_at` to be strictly before the unit's `inspection_due_at`; the
        deadline instant itself is already too late, and an inspection recorded
        exactly at `inspection_due_at` is refused with
        `ERR_EQUIPMENT_INSPECTION_OVERDUE`."

        Design: Difficulty/boundary_precision_check/inspection_deadline_exclusive_boundary
        """
        state = setup_pending_bco_with_unit(inspection_due_at="2026-09-10T00:00:00Z")
        unit = state["equipment"]

        accepted = validate_success(
            api.record_inspection(
                unit["id"],
                {"inspected_at": "2026-09-09T23:59:59Z", "result": "PASS",
                 "inspector_certificate": "CERT-TX-911"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        assert accepted["status"] == "IN_SERVICE"
        assert accepted["inspection_status"] == "CURRENT"

        refused = api.record_inspection(
            unit["id"],
            {"inspected_at": "2026-09-10T00:00:00Z", "result": "PASS",
             "inspector_certificate": "CERT-TX-912"},
            TEST_USERS["safety_reviewer_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_EQUIPMENT_INSPECTION_OVERDUE, expected_status=409)

        after = get_success_data(api.get_equipment(unit["id"], TEST_USERS["network_admin_headers"]))
        assert after["inspection_passed_at"] == "2026-09-09T23:59:59Z", (
            "the late record did not overwrite the passing timestamp"
        )

    def test_inspection_status_flips_to_overdue_at_the_deadline_instant(self, api):
        """PRD §2.9: "Otherwise, if the clock is before `inspection_due_at`, the
        status is `DUE`. Otherwise the status is `OVERDUE`."
        PRD §3.2: "A new unit lands in `PENDING_INSPECTION` with a null
        `inspection_passed_at`".

        Design: Difficulty/boundary_precision_check/inspection_deadline_exclusive_boundary
        """
        set_logical_clock("2026-09-01T00:00:00Z")
        pending = setup_pending_bco_with_unit(inspection_due_at="2026-09-10T00:00:00Z")
        fresh_unit = pending["equipment"]

        inspected = validate_success(
            api.record_inspection(
                fresh_unit["id"],
                {"inspected_at": "2026-09-09T23:59:59Z", "result": "PASS",
                 "inspector_certificate": "CERT-TX-913"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )

        never_inspected = add_fleet_unit(
            pending["bco"], inspect=False, inspection_due_at="2026-09-10T00:00:00Z"
        )

        set_logical_clock("2026-09-10T00:00:00Z")

        overdue = get_success_data(
            api.get_equipment(never_inspected["id"], TEST_USERS["network_admin_headers"])
        )
        assert overdue["inspection_status"] == "OVERDUE"

        still_current = get_success_data(
            api.get_equipment(inspected["id"], TEST_USERS["network_admin_headers"])
        )
        assert still_current["inspection_status"] == "CURRENT", (
            "a pass recorded strictly before the deadline keeps CURRENT"
        )


class TestComputedFieldsRecomputeOnRead:
    """Derived fields follow the clock with no write in between."""

    def test_equipment_and_document_status_recomputed_on_read(self, api):
        """PRD §2.9: "every clock-derived field — a credential's `status`, a
        customer account's `exclusivity_status`, a unit's `inspection_status`,
        an offer's expiry, an agent's `settlement_hold` — is re-evaluated on the
        next read."
        PRD §2.9: "is `EXPIRING_SOON` when the remaining time before `expires_at`
        is greater than zero and at most 30 days".

        Design: Corner/entities/equipment_inspection_and_document_status_recomputed_on_read
        """
        set_logical_clock("2026-09-01T00:00:00Z")
        bco = enroll_capacity_owner()
        unit = add_fleet_unit(bco, inspect=False, inspection_due_at="2026-10-01T00:00:00Z")
        doc = get_success_data(
            api.create_compliance_document(
                {
                    "capacity_owner_id": bco["id"],
                    "document_type": "CDL",
                    "document_number": "TX-CDL-79002",
                    "issued_at": "2025-09-15T00:00:00Z",
                    "expires_at": "2026-09-15T00:00:00Z",
                },
                TEST_USERS["safety_reviewer_headers"],
            )
        )

        unit_open = get_success_data(api.get_equipment(unit["id"], TEST_USERS["network_admin_headers"]))
        assert unit_open["inspection_status"] == "DUE"
        assert unit_open["inspection_passed_at"] is None
        assert unit_open["version"] == 1

        # PRD §2.9: a credential is `EXPIRING_SOON` when the remaining time
        # before `expires_at` is greater than zero and at most 30 days. The
        # 2026-09-15 deadline is 14 days out, well inside that band.
        doc_open = get_success_data(
            api.get_compliance_document(doc["id"], TEST_USERS["network_admin_headers"])
        )
        assert doc_open["status"] == "EXPIRING_SOON"

        set_logical_clock("2026-09-10T00:00:00Z")
        doc_soon = get_success_data(
            api.get_compliance_document(doc["id"], TEST_USERS["network_admin_headers"])
        )
        assert doc_soon["status"] == "EXPIRING_SOON"

        # PRD §2.9: the credential is `EXPIRED` once the clock reaches
        # `expires_at`, and the flip follows the clock with no write in between.
        set_logical_clock("2026-09-15T00:00:00Z")
        doc_expired = get_success_data(
            api.get_compliance_document(doc["id"], TEST_USERS["network_admin_headers"])
        )
        assert doc_expired["status"] == "EXPIRED"

        set_logical_clock("2026-10-01T00:00:00Z")
        unit_late = get_success_data(api.get_equipment(unit["id"], TEST_USERS["network_admin_headers"]))
        assert unit_late["inspection_status"] == "OVERDUE"
        assert unit_late["version"] == 1, "nothing was written across both reads"


class TestLoadRetrieval:
    """Revenue fields round-trip and the board flag is derived from the agent."""

    def test_load_get_returns_stored_revenue_mix_unchanged(self, api):
        """PRD §3.4: "A `FreightAgent` promotes a load with a payload carrying
        the owning `agent_id`, the `customer_ref` the load books under — which
        must match a customer account's `customer_ref` for the same agent — an
        `origin_state` and a `destination_state`, a `linehaul_revenue_cents`
        greater than zero, an optional `fuel_surcharge_cents` defaulting to zero,
        an optional `accessorial_revenue_cents` defaulting to zero, and a
        `dispatched_miles` greater than zero."
        PRD §2.4: "Each load carries a read-only `board_required` flag, true when
        the promoting agent's `status` is `ACTIVE` and that agent's
        `settlement_hold` is false, and false otherwise."

        Design: Corner/entities/load_get_returns_stored_revenue_mix_unchanged
        """
        from test_helpers import promote_load, register_customer

        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)

        created = validate_success(
            api.create_load(
                {
                    "agent_id": agent["id"],
                    "customer_ref": customer["customer_ref"],
                    "origin_state": "TX",
                    "destination_state": "OK",
                    "linehaul_revenue_cents": 180000,
                    "fuel_surcharge_cents": 32400,
                    "accessorial_revenue_cents": 12000,
                    "dispatched_miles": 1240,
                },
                _agent_headers(agent),
            ), 201
        )
        assert created["status"] == "POSTED"
        assert created["linehaul_revenue_cents"] == 180000
        assert created["fuel_surcharge_cents"] == 32400
        assert created["accessorial_revenue_cents"] == 12000
        assert created["dispatched_miles"] == 1240
        assert created["origin_state"] == "TX"
        assert created["destination_state"] == "OK"
        assert created["board_required"] is True

        fetched = validate_success(
            api.get_load(created["id"], TEST_USERS["network_admin_headers"]), 200
        )
        assert fetched["linehaul_revenue_cents"] == created["linehaul_revenue_cents"]
        assert fetched["fuel_surcharge_cents"] == created["fuel_surcharge_cents"]
        assert fetched["accessorial_revenue_cents"] == created["accessorial_revenue_cents"]
        assert fetched["dispatched_miles"] == created["dispatched_miles"]


class TestMonthWindow:
    """The per-load fee schedule's half-open calendar month."""

    def test_empty_month_still_bills_the_base_fee(self, api):
        """PRD §3.9: "a month with no eligible loads at all still bills the base
        rate of 5000 cents, because the schedule is never zero."
        PRD §3.9: "The window anchors at the first instant of the calendar month
        containing the logical clock, at 00:00:00Z, and ends one calendar month
        later".

        Design: Difficulty/combinatorial_formula/per_load_fee_interval_boundary_and_empty_month
        """
        set_logical_clock("2026-09-01T00:00:00Z")
        agent = enroll_agent()

        tier = validate_success(
            api.evaluate_per_load_tier(
                agent["id"], {"settlement_method": "marginal"},
                TEST_USERS["settlement_operator_headers"],
            ), 200
        )
        assert tier["tier_load_count"] == 0
        assert tier["marginal_fee_cents"] == 0
        assert tier["cumulative_fee_cents"] == 0
        assert tier["effective_per_load_fee_cents"] == 5000

        period = validate_success(
            api.run_period_close(
                {"agent_id": agent["id"], "period_month": "2026-09"},
                TEST_USERS["network_admin_headers"],
            ), 200
        )
        assert period["eligible_load_count"] == 0
        assert period["per_load_fee_cents"] == 5000
        assert period["period_fee_cents"] == 0
        assert period["effective_per_load_fee_cents"] == 5000

    def test_fifty_eligible_loads_still_read_tier_one(self, api):
        """PRD §3.9: "The per-load rate is banded by the eligible count — up to
        and including 50 eligible loads bills 4500 cents each, up to and
        including 150 bills 4000 cents each, and more than 150 bills 3500 cents
        each".
        PRD §3.9: "An eligible load for the count is any load of that agent whose
        status is `AWARDED`, `COVERED`, `IN_TRANSIT`, `DELIVERED`, or `SETTLED`".

        Design: Difficulty/combinatorial_formula/per_load_fee_interval_boundary_and_empty_month
        """
        from test_helpers import register_customer, setup_eligible_loads

        set_logical_clock("2026-09-01T00:00:00Z")
        agent = enroll_agent()
        customer = register_customer(agent)
        setup_eligible_loads(agent, customer["customer_ref"], 50)

        period = validate_success(
            api.run_period_close(
                {"agent_id": agent["id"], "period_month": "2026-09"},
                TEST_USERS["network_admin_headers"],
            ), 200
        )
        assert period["eligible_load_count"] == 50
        assert period["per_load_fee_cents"] == 4500
        assert period["period_fee_cents"] == 50 * 4500
        assert period["paid_load_count"] == 0, "an AWARDED load is not yet a paid load"

    def test_the_band_maximum_is_inclusive_at_fifty(self, api):
        """PRD §3.9: "up to and including 50 eligible loads bills 4500 cents
        each".
        PRD §3.9: "The period fee is the eligible count multiplied by that one
        band rate".

        Design: Difficulty/combinatorial_formula/per_load_fee_interval_boundary_and_empty_month
        """
        from test_helpers import register_customer, setup_eligible_loads

        set_logical_clock("2026-09-01T00:00:00Z")
        agent = enroll_agent()
        customer = register_customer(agent)
        setup_eligible_loads(agent, customer["customer_ref"], 49)

        at_49 = validate_success(
            api.run_period_close(
                {"agent_id": agent["id"], "period_month": "2026-09"},
                TEST_USERS["network_admin_headers"],
            ), 200
        )
        assert at_49["eligible_load_count"] == 49
        assert at_49["per_load_fee_cents"] == 4500

        _fifty_first, = setup_eligible_loads(agent, customer["customer_ref"], 1)
        at_50 = validate_success(
            api.run_period_close(
                {"agent_id": agent["id"], "period_month": "2026-09"},
                TEST_USERS["network_admin_headers"],
            ), 200
        )
        assert at_50["eligible_load_count"] == 50
        assert at_50["per_load_fee_cents"] == 4500, "the boundary is inclusive at the band maximum"


class TestPaidLoadCount:
    """A separate reconciliation figure counts the delivered and settled loads."""

    def test_paid_count_tracks_delivered_and_settled_loads(self, api):
        """PRD §3.9: "A separate reconciliation figure counts the agent's
        `DELIVERED` and `SETTLED` loads as its paid count."

        Design: Difficulty/combinatorial_formula/per_load_fee_interval_boundary_and_empty_month
        """
        from test_helpers import setup_haul_to_delivered

        set_logical_clock("2026-09-01T00:00:00Z")
        state = setup_haul_to_delivered()
        agent = state["agent"]

        period = validate_success(
            api.run_period_close(
                {"agent_id": agent["id"], "period_month": "2026-09"},
                TEST_USERS["network_admin_headers"],
            ), 200
        )
        assert period["paid_load_count"] == 1
        assert period["eligible_load_count"] == 1
        assert period["per_load_fee_cents"] == 4500
        assert period["period_fee_cents"] == 4500


def _agent_headers(agent):
    from test_helpers import make_freight_agent_headers
    return make_freight_agent_headers(agent["id"])