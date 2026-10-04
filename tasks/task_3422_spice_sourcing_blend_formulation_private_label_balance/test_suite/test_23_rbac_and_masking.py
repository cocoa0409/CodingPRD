"""Role denial and the SupplierRep masked view / ownership scope."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_supplier, create_received_lot, post_test,
    create_active_formula, formula_payload, make_supplier_rep_headers,
    get_lot,
)


class TestRoleDenial:
    def test_wrong_role_disposition_returns_unauthorized(self, api):
        """PRD §2.1: "If the role is valid but is not listed among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: only `QualityManager` is
        authorized for `POST /spice/lots/{id}/disposition`.

        QualityAnalyst — a different person than any test poster — is still
        role-denied; the lot's state does not change.

        Design: Corner/rbac/wrong_role_disposition_returns_unauthorized
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="OREGANO",
                                  origin_region="Lesvos", quantity_kg=40,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150)
        post_test(lot["id"], "MICRO", 40000, analyst_id="qa-1")
        resp = api_client.disposition_lot(
            lot["id"], {"action": "QUARANTINE"},
            TEST_USERS["quality_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        assert get_lot(lot["id"])["status"] == "IN_TEST"

    def test_supplier_rep_cannot_create_formula(self, api):
        """PRD §2.1: "If the role is valid but is not listed among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: only `FlavorScientist` is
        authorized for `POST /spice/formulas`.

        Design: Corner/rbac/supplier_rep_cannot_create_formula
        """
        supplier = create_supplier(name="S1 Farms")
        resp = api_client.create_formula(
            formula_payload("HAX-1", name="Sneaky", target_flavor_units=80.0),
            make_supplier_rep_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403


class TestSupplierRepMaskedView:
    def test_supplier_rep_masked_view_and_ownership_scope(self, api):
        """PRD §2.10: "When a `SupplierRep` lists the lines of a formula, the
        response is the masked view: `spice_code` and `target_proportion_pct`
        are replaced by null, while `masked_component_code`,
        `allergen_profile`, `organic_required`, and `min_lot_flavor_units`
        remain visible". PRD §2.1: "a `SupplierRep` may only read lots whose
        `supplier_id` equals `X-User-ID`, and anything touching another
        supplier's lot behaves as though that lot does not exist — a direct
        read of another supplier's lot fails with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/rbac/supplier_rep_masked_view_and_ownership_scope
        """
        s1 = create_supplier(name="S1 Farms", origin_country="IN")
        s2 = create_supplier(name="S2 Farms", origin_country="VN")
        l1 = create_received_lot(s1["id"], quantity_kg=40,
                                 flavor_intensity_units=60.0,
                                 moisture_pct=9.0, cost_per_kg_cents=150)
        l2 = create_received_lot(s2["id"], origin_region="Dak Lak",
                                 quantity_kg=40, flavor_intensity_units=60.0,
                                 moisture_pct=9.0, cost_per_kg_cents=150)
        formula = create_active_formula(
            "MSK-9", target_flavor_units=80.0,
            lines=[dict(spice_code="BLACK_PEPPER", target_proportion_pct=100.0,
                        min_lot_flavor_units=40.0)])
        rep = make_supplier_rep_headers(s1["id"])
        resp = api_client.list_formula_lines(formula["id"], rep)
        lines = get_success_data(resp)
        assert len(lines) == 1
        masked = lines[0]
        assert masked["masked_component_code"] == "CMP-A"
        assert masked["spice_code"] is None
        assert masked["target_proportion_pct"] is None
        assert masked["allergen_profile"] == "NONE"
        assert masked["min_lot_flavor_units"] == pytest.approx(40.0)
        own = validate_success(api_client.get_lot(l1["id"], rep), 200)
        assert own["id"] == l1["id"]
        resp = api_client.get_lot(l2["id"], rep)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
