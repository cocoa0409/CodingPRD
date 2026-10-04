"""Entity creation defaults, computed/system fields, and request-shape rules."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_supplier, create_received_lot, post_test,
    supplier_payload, lot_payload, formula_payload, formula_line_payload,
    assert_lot, assert_safety_test, assert_lot_mass_invariant,
)


class TestLotCreationDefaults:
    def test_lot_creation_defaults_and_computed_fields(self, api):
        """PRD §3.1: "A freshly received lot starts in `RECEIVED` status, with
        `quantity_remaining_kg` initialized to the full `quantity_kg` and both
        `quantity_consumed_kg` and `quantity_wasted_kg` initialized to 0".
        PRD §2.4: "Every persisted resource carries a server-minted `id` — a
        UUID with no type prefix — assigned at creation and returned in every
        representation."

        Design: Corner/entities/lot_creation_defaults_and_computed_fields
        """
        supplier = create_supplier()
        lot = create_received_lot(
            supplier["id"], spice_code="CUMIN", origin_region="Aleppo",
            quantity_kg=60, flavor_intensity_units=55.5, moisture_pct=9.5,
            cost_per_kg_cents=210, allergen_profile="CELERY",
            organic_certified=True)
        assert_lot(lot)
        assert lot["status"] == "RECEIVED"
        assert lot["quantity_remaining_kg"] == pytest.approx(60.0)
        assert lot["quantity_consumed_kg"] == pytest.approx(0.0)
        assert lot["quantity_wasted_kg"] == pytest.approx(0.0)
        assert lot["version"] == 1
        assert_lot_mass_invariant(lot)

    def test_lot_invalid_enum_value_rejected(self, api):
        """PRD §2.8: "Request shape: required fields are present, types are
        valid, enum values fall within their declared sets, and unknown fields
        are rejected, else `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.1: the
        `spice_code` is "exactly one of `BLACK_PEPPER`, `PAPRIKA`, `CUMIN`,
        `OREGANO`, `GARLIC_POWDER`, or `CINNAMON`".

        TURMERIC is outside the declared set; the rejected write persists
        nothing.

        Design: Corner/entities/lot_invalid_enum_value_rejected
        """
        supplier = create_supplier()
        resp = api_client.create_lot(
            lot_payload(supplier["id"], spice_code="TURMERIC"),
            TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        lots = get_success_data(api_client.list_lots(
            TEST_USERS["supply_planner_headers"]))
        assert len(lots) == 0

    def test_lot_crop_year_out_of_range_rejected(self, api):
        """PRD §2.8: "Value ranges and cross-field semantics: ... `crop_year`
        between 2000 and 2100 inclusive ... else `ERR_VALIDATION` (HTTP 422)."

        crop_year 1999 violates range semantics — 422, distinct from the
        request-shape 400.

        Design: Corner/entities/lot_crop_year_out_of_range_rejected
        """
        supplier = create_supplier()
        resp = api_client.create_lot(
            lot_payload(supplier["id"], spice_code="CUMIN",
                        origin_region="Aleppo", crop_year=1999),
            TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestSupplierDefaults:
    def test_supplier_optional_defaults_applied(self, api):
        """PRD §3.1: "The `certifications` array defaults to empty when
        omitted". PRD §3.1: "The `knowledge_tier` is `MASKED_ONLY` or `FULL`
        and defaults to `MASKED_ONLY` when omitted".

        Design: Corner/entities/supplier_optional_defaults_applied
        """
        resp = api_client.create_supplier(
            supplier_payload(name="Default Farms", origin_country="ES"),
            TEST_USERS["supply_planner_headers"])
        supplier = validate_success(resp, 201)
        assert supplier["knowledge_tier"] == "MASKED_ONLY"
        assert supplier["certifications"] == []


class TestSafetyTestShape:
    def test_safety_test_immutable_no_version_fields(self, api):
        """PRD §2.4: "The sole exception to this common shape is the safety
        test record: a safety test is an append-only, immutable event carrying
        only `id` and `created_at`, with both `updated_at` and `version`
        absent from it, and once posted it is never modified." PRD §3.2: "the
        server copies the posting analyst's `X-User-ID` into
        `analyst_user_id`, computes the `result`, and links the record to the
        lot via `lot_id` taken from the URL path."

        Design: Corner/entities/safety_test_immutable_no_version_fields
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="OREGANO",
                                  origin_region="Lesvos", quantity_kg=40,
                                  flavor_intensity_units=60.0,
                                  moisture_pct=9.0, cost_per_kg_cents=150)
        t = post_test(lot["id"], "MICRO", 1000, lab_code="LAB-Z",
                      analyst_id="qa-7")
        assert_safety_test(t)
        assert t["result"] == "PASS"
        assert t["analyst_user_id"] == "qa-7"
        assert t["lot_id"] == lot["id"]


class TestFormulaLinesAndRevisions:
    def test_formula_line_masked_codes_sequential(self, api):
        """PRD §2.10: "Every formula line carries a system-assigned
        `masked_component_code`, a pseudonym built from the prefix `CMP-`
        followed by a letter assigned in creation order within the formula —
        the first line created is `CMP-A`, the second `CMP-B`, and so on."

        Design: Corner/entities/formula_line_masked_codes_sequential
        """
        resp = api_client.create_formula(
            formula_payload("MASK-1", target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        formula = validate_success(resp, 201)
        codes = []
        for line in (dict(spice_code="BLACK_PEPPER", target_proportion_pct=50.0,
                          min_lot_flavor_units=40.0),
                     dict(spice_code="PAPRIKA", target_proportion_pct=30.0,
                          min_lot_flavor_units=40.0),
                     dict(spice_code="CUMIN", target_proportion_pct=20.0,
                          allergen_profile="SESAME", min_lot_flavor_units=40.0)):
            resp = api_client.add_formula_line(
                formula["id"], formula_line_payload(**line),
                TEST_USERS["flavor_scientist_headers"])
            codes.append(validate_success(resp, 201)["masked_component_code"])
        assert codes == ["CMP-A", "CMP-B", "CMP-C"]

    def test_formula_revision_supersedes_and_retires(self, api):
        """PRD §3.3: "the new formula's `revision` becomes the superseded
        formula's `revision` plus 1, whereas a fresh `product_code` starts at
        `revision` 1." PRD §3.3: "Successful activation flips the formula to
        `ACTIVE` and simultaneously retires every other `ACTIVE` formula
        carrying the same `product_code`". PRD §3.3: "Formula listings accept
        optional `status`, `brand_type`, `product_code`, and
        `supersedes_formula_id` filters."

        Design: Corner/entities/formula_revision_supersedes_and_retires
        """
        resp = api_client.create_formula(
            formula_payload("CURRY-5", name="Curry v1",
                            target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        f1 = validate_success(resp, 201)
        assert f1["revision"] == 1
        validate_success(api_client.add_formula_line(
            f1["id"], formula_line_payload(min_lot_flavor_units=40.0),
            TEST_USERS["flavor_scientist_headers"]), 201)
        validate_success(api_client.activate_formula(
            f1["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        resp = api_client.create_formula(
            formula_payload("CURRY-5", name="Curry v2", target_flavor_units=82.0,
                            supersedes_formula_id=f1["id"]),
            TEST_USERS["flavor_scientist_headers"])
        f2 = validate_success(resp, 201)
        assert f2["revision"] == 2
        assert f2["status"] == "DRAFT"
        validate_success(api_client.add_formula_line(
            f2["id"], formula_line_payload(min_lot_flavor_units=40.0),
            TEST_USERS["flavor_scientist_headers"]), 201)
        validate_success(api_client.activate_formula(
            f2["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        f1_after = validate_success(api_client.get_formula(
            f1["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        assert f1_after["status"] == "RETIRED"
        children = get_success_data(api_client.list_formulas(
            TEST_USERS["flavor_scientist_headers"],
            params={"supersedes_formula_id": f1["id"]}))
        assert len(children) == 1
        assert children[0]["id"] == f2["id"]
