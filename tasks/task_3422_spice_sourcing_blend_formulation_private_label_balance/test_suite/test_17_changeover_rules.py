"""Changeover matrix: allergen carryover, high-segregation, organic transition."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_agreement, create_active_formula,
    create_committed_blend_run, create_line, schedule_run, get_line_version,
    production_run_payload,
)


class TestAllergenCarryoverMatrix:
    def test_changeover_allergen_carryover_matrix(self, api):
        """PRD §3.5: "if the predecessor's allergen set is not a subset of the
        new run's allergen set, allergen carryover is possible and the class
        is `WET_WASH`. ... If the allergen sets are exactly equal, both runs
        share a `brand_type`, and — for `PRIVATE_LABEL` runs — both reference
        the same `private_label_agreement_id`, the class is `NONE`. In every
        remaining case the class is `DRY_CLEAN`."

        NONE (first run) -> DRY_CLEAN (SESAME introduced after allergen-free:
        {} is a subset of {SESAME} but the sets differ) -> WET_WASH (SESAME
        predecessor then allergen-free: {SESAME} is not a subset of {}) ->
        NONE (identical sets, same brand).

        Design: Corner/calculations/changeover_allergen_carryover_matrix
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        fn = create_active_formula("NA-1")
        fs = create_active_formula(
            "SA-1", lines=[dict(spice_code="BLACK_PEPPER",
                                target_proportion_pct=100.0,
                                allergen_profile="SESAME",
                                min_lot_flavor_units=50.0)])
        bn = create_committed_blend_run(fn["id"], "COST_MIN", 10)
        bs = create_committed_blend_run(fs["id"], "COST_MIN", 10)
        line = create_line(name="Line-M")
        r1 = schedule_run(line["id"], fn["id"], bn["id"], 10,
                          "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z")
        r2 = schedule_run(line["id"], fs["id"], bs["id"], 10,
                          "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z")
        r3 = schedule_run(line["id"], fn["id"], bn["id"], 10,
                          "2026-09-07T12:00:00Z", "2026-09-07T14:00:00Z")
        r4 = schedule_run(line["id"], fn["id"], bn["id"], 10,
                          "2026-09-07T14:00:00Z", "2026-09-07T16:00:00Z")
        assert r1["predecessor_run_id"] is None
        assert r1["changeover_class_required"] == "NONE"
        assert r2["predecessor_run_id"] == r1["id"]
        assert r2["changeover_class_required"] == "DRY_CLEAN"
        assert r3["predecessor_run_id"] == r2["id"]
        assert r3["changeover_class_required"] == "WET_WASH"
        assert r4["predecessor_run_id"] == r3["id"]
        assert r4["changeover_class_required"] == "NONE"


class TestHighSegregationChangeover:
    def _setup(self):
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        agr = create_agreement("Confidential Foods", ["PL-HS-8"], 1000,
                               confidentiality_level="HIGH_SEGREGATION",
                               development_nda_signed=True)
        fg = create_active_formula("GN-8")
        fp = create_active_formula("PL-HS-8", brand_type="PRIVATE_LABEL")
        bg = create_committed_blend_run(fg["id"], "COST_MIN", 10)
        bp = create_committed_blend_run(fp["id"], "COST_MIN", 10)
        lf = create_line(name="Line-F")
        lb = create_line(name="Line-Bsc",
                         supported_changeover_classes=["NONE", "DRY_CLEAN",
                                                       "WET_WASH"])
        # A branded predecessor on each line 08:00-10:00.
        schedule_run(lf["id"], fg["id"], bg["id"], 10,
                     "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z")
        schedule_run(lb["id"], fg["id"], bg["id"], 10,
                     "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z")
        return {"agr": agr, "fp": fp, "bp": bp, "lf": lf, "lb": lb}

    def test_high_segregation_forces_full_sanitation_and_capability_gate(self, api):
        """PRD §3.5: "When either the predecessor or the new run is a
        high-segregation private-label run — meaning its formula's
        `brand_type` is `PRIVATE_LABEL` and its agreement's
        `confidentiality_level` is `HIGH_SEGREGATION` — the class is
        `FULL_SANITATION`." PRD §3.5: "The computed class must then be a
        member of the line's `supported_changeover_classes`; a line that
        cannot execute the required sanitation rejects the schedule with
        `ERR_ALLERGEN_CHANGEOVER_INSUFFICIENT` (HTTP 409)."

        Design: Corner/calculations/changeover_high_segregation_forces_full_sanitation_and_capability_gate
        """
        s = self._setup()
        ok = schedule_run(s["lf"]["id"], s["fp"]["id"], s["bp"]["id"], 10,
                          "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z",
                          private_label_agreement_id=s["agr"]["id"])
        assert ok["changeover_class_required"] == "FULL_SANITATION"
        payload = production_run_payload(
            s["lb"]["id"], s["fp"]["id"], s["bp"]["id"], 10,
            "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z",
            get_line_version(s["lb"]["id"]),
            private_label_agreement_id=s["agr"]["id"])
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_INSUFFICIENT)


class TestOrganicTransitionChangeover:
    def test_changeover_organic_transition_wet_wash(self, api):
        """PRD §3.5: "If the sets are compatible but the new run's formula is
        fully organic — every line of its formula has `organic_required`
        true, with an empty formula counting as not organic — while the
        predecessor's formula is not fully organic, the non-organic-to-organic
        transition also demands `WET_WASH`."

        Identical allergen sets and brand, but ORG-9 (all lines
        organic_required) follows STD-9 (not organic): WET_WASH.

        Design: Corner/calculations/changeover_organic_transition_wet_wash
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100),
                                             organic=True)
        fs = create_active_formula(
            "STD-9", lines=[dict(spice_code="BLACK_PEPPER",
                                 target_proportion_pct=100.0,
                                 organic_required=False,
                                 min_lot_flavor_units=50.0)])
        fo = create_active_formula(
            "ORG-9", lines=[dict(spice_code="BLACK_PEPPER",
                                 target_proportion_pct=100.0,
                                 organic_required=True,
                                 min_lot_flavor_units=50.0)])
        bs = create_committed_blend_run(fs["id"], "COST_MIN", 10)
        bo = create_committed_blend_run(fo["id"], "COST_MIN", 10)
        line = create_line(name="Line-O")
        r1 = schedule_run(line["id"], fs["id"], bs["id"], 10,
                          "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z")
        assert r1["changeover_class_required"] == "NONE"
        r2 = schedule_run(line["id"], fo["id"], bo["id"], 10,
                          "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z")
        assert r2["predecessor_run_id"] == r1["id"]
        assert r2["changeover_class_required"] == "WET_WASH"
