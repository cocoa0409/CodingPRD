"""Formula and production-run referential gates."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, setup_accepted_lots, create_active_formula,
    create_blend_run, create_committed_blend_run, create_agreement,
    create_line, get_line_version, formula_payload, formula_line_payload,
    blend_run_payload, production_run_payload,
)


class TestDuplicateProductCode:
    def test_duplicate_product_code_rejected(self, api):
        """PRD §3.3: "Product codes are unique among formulas in `DRAFT` or
        `ACTIVE`: creating a formula whose `product_code` is already held by a
        `DRAFT` or `ACTIVE` formula is rejected with
        `ERR_DUPLICATE_PRODUCT_CODE` (HTTP 409) unless the new formula chains
        that same code through `supersedes_formula_id`."

        The unchained copy is rejected; the chained revision is accepted with
        revision 2.

        Design: Corner/validations/duplicate_product_code_rejected
        """
        resp = api_client.create_formula(
            formula_payload("DUP-1", name="First", target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        f1 = validate_success(resp, 201)
        resp = api_client.create_formula(
            formula_payload("DUP-1", name="Copycat", target_flavor_units=81.0),
            TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRODUCT_CODE)
        resp = api_client.create_formula(
            formula_payload("DUP-1", name="Revision", target_flavor_units=81.0,
                            supersedes_formula_id=f1["id"]),
            TEST_USERS["flavor_scientist_headers"])
        f2 = validate_success(resp, 201)
        assert f2["revision"] == 2


class TestBlendRunRequiresActiveFormula:
    def test_blend_run_create_requires_active_formula(self, api):
        """PRD §3.4: "a `FlavorScientist` creates a blend run from a
        `formula_id` (which must reference an `ACTIVE` formula, else
        `ERR_FORMULA_NOT_ACTIVE`)". PRD §3.4: "A new blend run is `DRAFT`".

        Design: Corner/validations/blend_run_create_requires_active_formula
        """
        resp = api_client.create_formula(
            formula_payload("NA-7", target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        formula = validate_success(resp, 201)
        validate_success(api_client.add_formula_line(
            formula["id"],
            formula_line_payload(spice_code="CUMIN",
                                 target_proportion_pct=100.0,
                                 min_lot_flavor_units=0.0),
            TEST_USERS["flavor_scientist_headers"]), 201)
        resp = api_client.create_blend_run(
            blend_run_payload(formula["id"], "COST_MIN", 5),
            TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_ACTIVE)
        validate_success(api_client.activate_formula(
            formula["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        resp = api_client.create_blend_run(
            blend_run_payload(formula["id"], "COST_MIN", 5),
            TEST_USERS["flavor_scientist_headers"])
        created = validate_success(resp, 201)
        assert created["status"] == "DRAFT"


class TestRunFormulaAndQuantityMismatch:
    def test_run_formula_and_quantity_mismatch(self, api):
        """PRD §3.5: "a `formula_id` differing from the blend run's formula is
        rejected with `ERR_FORMULA_MISMATCH`, HTTP 422". PRD §3.5: "the
        planned `quantity_kg` (which must equal the referenced blend run's
        `target_batch_kg` exactly, else `ERR_QUANTITY_MISMATCH`, HTTP 422)".

        Design: Corner/validations/run_formula_and_quantity_mismatch
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        fa = create_active_formula("FM-A")
        fb = create_active_formula("FM-B")
        br = create_committed_blend_run(fa["id"], "COST_MIN", 10)
        line = create_line(name="Line-FM")
        version = get_line_version(line["id"])
        window = ("2026-09-21T08:00:00Z", "2026-09-21T10:00:00Z")
        resp = api_client.create_production_run(
            production_run_payload(line["id"], fb["id"], br["id"], 10,
                                   window[0], window[1], version),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_FORMULA_MISMATCH)
        resp = api_client.create_production_run(
            production_run_payload(line["id"], fa["id"], br["id"], 99,
                                   window[0], window[1], version),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_QUANTITY_MISMATCH)
        runs = get_success_data(api_client.list_production_runs(
            TEST_USERS["production_scheduler_headers"],
            params={"line_id": line["id"]}))
        assert len(runs) == 0


class TestPrivateLabelAgreementGates:
    def test_private_label_agreement_gates(self, api):
        """PRD §3.5: "when the formula's `brand_type` is `PRIVATE_LABEL`,
        omitting `private_label_agreement_id` is rejected with
        `ERR_AGREEMENT_REQUIRED` (HTTP 422); and when an agreement is
        supplied, the formula's `product_code` must appear in that agreement's
        `product_codes`, else `ERR_PRODUCT_NOT_IN_AGREEMENT` (HTTP 422)."

        Design: Corner/validations/private_label_agreement_gates
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        formula = create_active_formula("PLP-1", brand_type="PRIVATE_LABEL")
        br = create_committed_blend_run(formula["id"], "COST_MIN", 10)
        line = create_line(name="Line-PL")
        agr_no = create_agreement("Other Retail", ["OTHER-1"], 500)
        agr_ok = create_agreement("Riverbend Foods", ["PLP-1"], 500)
        version = get_line_version(line["id"])
        window = ("2026-09-22T08:00:00Z", "2026-09-22T10:00:00Z")
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   window[0], window[1], version),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_REQUIRED)
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   window[0], window[1], version,
                                   private_label_agreement_id=agr_no["id"]),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_IN_AGREEMENT)
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   window[0], window[1], version,
                                   private_label_agreement_id=agr_ok["id"]),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)


class TestWeeklyPoolCapacityGate:
    def test_run_exceeding_weekly_pool_returns_capacity_exceeded(self, api):
        """PRD §3.5: "If scheduling would push the week's balance below zero —
        pool minus scheduled minus reserved going negative — the request is
        rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)." PRD §2.7: "A
        successful scheduling increments the line's `version` by 1" (a
        rejected schedule is not a successful one).

        A 60 kg run against a 10 kg/shift line (week pool 50 kg) is rejected
        and the line's OCC version does not advance.

        Design: Corner/validations/run_exceeding_weekly_pool_returns_capacity_exceeded
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        formula = create_active_formula("CAPX")
        br = create_committed_blend_run(formula["id"], "COST_MIN", 60)
        line = create_line(name="Line-TINY", capacity_kg_per_shift=10)
        version = get_line_version(line["id"])
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 60,
                                   "2026-09-23T08:00:00Z",
                                   "2026-09-23T16:00:00Z", version),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        assert get_line_version(line["id"]) == version
