"""Boundary precision: ceiling equality admitted; MFC floor equality admitted."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_cleared_order,
    create_delivered_order,
    create_submitted_price_list,
    setup_active_chain,
    validate_error,
    validate_success,
)

CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestVehicleCeilingBoundary:
    def test_exact_ceiling_equality_admitted(self, api):
        """PRD §3.2: "Equality is admissible — when the existing consumption
        plus the new total equals the ceiling exactly, the delivery is
        admitted; one cent above the ceiling is rejected with
        ERR_VEHICLE_CEILING_EXCEEDED (HTTP 422)."

        Design: Difficulty/boundary_precision_check/vehicle_ceiling_exact_equality_admitted
        """
        _, _, vehicle, price_list = setup_active_chain(
            vehicle_overrides={"ceiling_cents": 25000},
            lines=[{"sku": "SW-1", "basis_price_cents": 20000,
                    "offered_price_cents": 5000, "origin_country": "US"}],
        )
        o1 = create_cleared_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 2}],
        )
        validate_success(api.deliver_order(o1["id"], OPS))
        assert o1["order_total_cents"] == 10000
        o2 = create_cleared_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 3}],
        )
        assert o2["order_total_cents"] == 15000
        # 10000 + 15000 == 25000 == ceiling: admitted.
        resp = api.deliver_order(o2["id"], OPS)
        o2 = validate_success(resp)
        assert o2["billing_status"] == "DELIVERED"

    def test_one_cent_over_ceiling_rejected(self, api):
        """PRD §3.2: "adding the new order's order_total_cents to that sum
        must not exceed ceiling_cents. Equality is admissible — when the
        existing consumption plus the new total equals the ceiling exactly,
        the delivery is admitted; one cent above the ceiling is rejected with
        ERR_VEHICLE_CEILING_EXCEEDED (HTTP 422)."

        Design: Difficulty/boundary_precision_check/vehicle_ceiling_exact_equality_admitted
        """
        _, _, vehicle, price_list = setup_active_chain(
            vehicle_overrides={"ceiling_cents": 25000},
            lines=[{"sku": "SW-1", "basis_price_cents": 20000,
                    "offered_price_cents": 5000, "origin_country": "US"}],
        )
        # Consume the ceiling exactly: 10000 + 15000 = 25000.
        o1 = create_delivered_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 2}],
        )
        o2 = create_delivered_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 3}],
        )
        assert o1["order_total_cents"] == 10000
        assert o2["order_total_cents"] == 15000
        # Any further positive-total delivery on this tier exceeds the ceiling.
        o3 = create_cleared_order(
            vehicle["id"], price_list["id"], lines=[{"sku": "SW-1", "qty": 1}],
        )
        resp = api.deliver_order(o3["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_CEILING_EXCEEDED)
        o3 = validate_success(api.get_order(o3["id"], OPS))
        assert o3["billing_status"] == "UNBILLED"


class TestMfcFloorBoundary:
    def _setup(self, api):
        # Agreement mfc_discount_pct = 0.20; basis 10000 -> floor = 8000.
        return setup_active_chain(
            agreement_overrides={"mfc_discount_pct": 0.20},
        )

    def test_offered_equal_floor_admitted(self, api):
        """PRD §3.3: "Equality with the floor is allowed; one cent above the
        floor is rejected with ERR_MFC_FLOOR_VIOLATION."

        Design: Difficulty/boundary_precision_check/mfc_floor_exact_equality_admitted
        """
        _, _, vehicle, _ = self._setup(api)
        p1 = create_submitted_price_list(
            vehicle["id"],
            lines=[{"sku": "SW-1", "basis_price_cents": 10000,
                    "offered_price_cents": 8000, "origin_country": "US"}],
        )
        # floor(10000 * (1 - 0.20)) = 8000; offered == floor -> admitted.
        resp = api.activate_price_list(p1["id"], CO)
        pl = validate_success(resp)
        assert pl["status"] == "ACTIVE"

    def test_offered_one_cent_over_floor_rejected(self, api):
        """PRD §3.3: "The MFC floor is the most-favored-customer price floor
        applied per line: the line's offered_price_cents must not exceed the
        integer floor of basis_price_cents multiplied by one minus the
        agreement's mfc_discount_pct. Equality with the floor is allowed; one
        cent above the floor is rejected with ERR_MFC_FLOOR_VIOLATION."

        Design: Difficulty/boundary_precision_check/mfc_floor_exact_equality_admitted
        """
        _, _, vehicle, _ = self._setup(api)
        p2 = create_submitted_price_list(
            vehicle["id"],
            lines=[{"sku": "SW-1", "basis_price_cents": 10000,
                    "offered_price_cents": 8001, "origin_country": "US"}],
        )
        resp = api.activate_price_list(p2["id"], CO)
        validate_error(resp, ApiErrorId.ERR_MFC_FLOOR_VIOLATION)
        pl = validate_success(api.get_price_list(p2["id"], TEST_USERS["contracts_manager_headers"]))
        assert pl["status"] == "SUBMITTED"
