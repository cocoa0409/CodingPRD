"""Origin methods and marking-penalty variants computed over one row.

Every test in this module translates exactly one instance of the difficulty
design index: the two legal origin theories frozen onto a single
determination, the two penalty variants stored side by side on a single
customs entry, the four-operator durability composition, the pinned
two-step rounding order of the ad valorem charge, and the posture/penalty
fixed point resolved by excluding the entry under review from the ledger.
"""
import pytest

from test_helpers import *  # noqa: F401,F403


# --- shared fixture literals ---------------------------------------------

def _s1_fibers():
    """COTTON 60.0 / POLYESTER 37.0 / ELASTANE 3.0, all non-exempt."""
    return [fiber_line("COTTON", 60.0),
            fiber_line("POLYESTER", 37.0),
            fiber_line("ELASTANE", 3.0)]


def _s1_measured():
    """A laboratory measurement that reproduces the declaration exactly."""
    return [{"fiber_generic_name": "COTTON", "measured_pct": 60.0},
            {"fiber_generic_name": "POLYESTER", "measured_pct": 37.0},
            {"fiber_generic_name": "ELASTANE", "measured_pct": 3.0}]


def _s1_graph():
    """The five-node supply graph whose two origin theories disagree.

    FIBER IN 500.0g / 2.00 root; YARN IN 480.0g / 3.00; YARN PK 520.0g / 2.50;
    FABRIC CN 950.0g / 6.00; CUT_AND_SEW VN 900.0g / 9.00.
    Value added over YARN/FABRIC/CUT_AND_SEW peaks at VN (9.00); yarn weight
    peaks at PK (520.0 against 480.0).
    """
    return [
        {"stage": "FIBER", "country_code": "IN",
         "value_added_usd": 2.00, "weight_grams": 500.0},
        {"stage": "YARN", "country_code": "IN",
         "value_added_usd": 3.00, "weight_grams": 480.0, "_parent": 0},
        {"stage": "YARN", "country_code": "PK",
         "value_added_usd": 2.50, "weight_grams": 520.0, "_parent": 0},
        {"stage": "FABRIC", "country_code": "CN",
         "value_added_usd": 6.00, "weight_grams": 950.0, "_parent": 1},
        {"stage": "CUT_AND_SEW", "country_code": "VN",
         "value_added_usd": 9.00, "weight_grams": 900.0, "_parent": 3},
    ]


MARKETS_US_CA = [
    {"market_code": "US", "required_languages": ["en"],
     "fiber_tolerance_pp": 3.0, "absolute_claim_tolerance_pp": 0.0,
     "min_durability_cycles": 20, "marking_duty_rate": 0.100},
    {"market_code": "CA", "required_languages": ["en", "fr"],
     "fiber_tolerance_pp": 3.0, "absolute_claim_tolerance_pp": 0.3,
     "min_durability_cycles": 25, "marking_duty_rate": 0.100},
]


def _s1_style_overrides(**extra):
    overrides = {"style_code": "NL-4410", "product_class": "KNIT_TOP",
                 "net_weight_grams": 320.0, "declared_fibers": _s1_fibers()}
    overrides.update(extra)
    return overrides


def _s1_with_graph():
    """Markets US and CA, brand Northline Apparel Co, style S1 and its
    five-node supply graph. Returns (brand, style)."""
    for spec in MARKETS_US_CA:
        spec = dict(spec)
        register_market(spec.pop("market_code"), **spec)
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(brand["id"], target_market_codes=["US", "CA"],
                         **_s1_style_overrides())
    build_supply_graph(style["id"], _s1_graph())
    return brand, style


def _brand_with_style(market_code="US", **market_overrides):
    """One registered market, brand Northline Apparel Co and a style targeting
    that market. Returns (brand, style)."""
    register_market(market_code, **market_overrides)
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(brand["id"], target_market_codes=[market_code],
                         **_s1_style_overrides())
    return brand, style


def _money(value):
    """Cent-exact comparison: the tolerance is deliberately tighter than one
    cent so a figure that is off by a single cent fails."""
    return pytest.approx(value, abs=0.001)


class TestOriginMethodVariants:
    """The two legal origin theories computed over one supply graph."""

    def test_draft_freezes_both_candidate_countries_from_one_graph(self, api):
        """PRD 3.3: "The **substantial-transformation** variant takes the non-ornamentation nodes whose stage is `YARN`, `FABRIC` or `CUT_AND_SEW`, groups them by `country_code`, and for each country sums the `value_added_usd` of its nodes at 2 decimal places." PRD 3.3: "The **yarn-forward** variant takes only the non-ornamentation nodes whose stage is `YARN`; if the style has no yarn node at all, and only then, it falls back to the nodes whose stage is `FIBER`." PRD 3.3: "The row also stores `divergent`, which is true exactly when `st_country` and `yf_country` are not the same country."

        Design: Difficulty/dual_variant_calc/origin_substantial_transformation_versus_yarn_forward_on_one_graph
        """
        brand, style = _s1_with_graph()

        draft = draft_determination(style["id"])
        assert_origin_determination(draft)

        assert draft["state"] == "DRAFT", (
            f"a new determination is created in DRAFT, got {draft['state']}")
        assert draft["st_country"] == "VN", (
            "substantial transformation ranks by summed value_added_usd over "
            "YARN/FABRIC/CUT_AND_SEW, where VN contributes 9.00 against CN 6.00, "
            f"IN 3.00 and PK 2.50, so st_country must be VN, got {draft['st_country']}")
        assert draft["yf_country"] == "PK", (
            "yarn-forward ranks by summed weight_grams over the YARN nodes only, "
            "where PK carries 520.0 grams against IN 480.0, so yf_country must be "
            f"PK, got {draft['yf_country']}")
        assert draft["divergent"] is True, (
            "divergent is true exactly when st_country and yf_country differ, and "
            f"VN != PK, got {draft['divergent']}")
        assert draft["graph_node_count"] == 5, (
            "graph_node_count is the count of the non-ornamentation population, "
            f"which is all five filed nodes, got {draft['graph_node_count']}")
        assert draft["method_pinned"] is None, (
            "method_pinned stays null while the row is a DRAFT")
        assert draft["determined_country"] is None, (
            "determined_country stays null while the row is a DRAFT")

        style_row = read_style(style["id"])
        assert style_row["origin_state"] == "ORIGIN_DRAFTED", (
            "drafting from ORIGIN_UNDETERMINED advances the style to "
            f"ORIGIN_DRAFTED, got {style_row['origin_state']}")

    def test_pinned_method_selects_which_frozen_country_is_determined(self, api):
        """PRD 3.3: "On success the row records `method_pinned`, derives `determined_country` from the frozen pair — `st_country` under substantial transformation, `yf_country` under yarn-forward — stamps `issued_at` from the logical clock, and moves from `DRAFT` to `ISSUED`." PRD 3.3: "Any other determination of the same style that was standing in `ISSUED` transitions to `SUPERSEDED`."

        Design: Difficulty/dual_variant_calc/origin_substantial_transformation_versus_yarn_forward_on_one_graph
        """
        brand, style = _s1_with_graph()

        first = issue_determination(draft_determination(style["id"])["id"],
                                   "SUBSTANTIAL_TRANSFORMATION")
        assert first["method_pinned"] == "SUBSTANTIAL_TRANSFORMATION"
        assert first["determined_country"] == "VN", (
            "under SUBSTANTIAL_TRANSFORMATION determined_country is st_country, "
            f"which is VN, got {first['determined_country']}")
        assert first["state"] == "ISSUED"
        assert_second_precision_instant(first["issued_at"], "issued_at")

        second = issue_determination(draft_determination(style["id"])["id"],
                                    "YARN_FORWARD")
        assert second["method_pinned"] == "YARN_FORWARD"
        assert second["determined_country"] == "PK", (
            "under YARN_FORWARD determined_country is yf_country, which is PK, "
            f"got {second['determined_country']}")
        assert second["state"] == "ISSUED"

        assert (second["st_country"], second["yf_country"]) == ("VN", "PK"), (
            "the same five rows freeze the same candidate pair on every "
            f"determination, got {second['st_country']}/{second['yf_country']}")
        assert first["determined_country"] != second["determined_country"], (
            "the identical graph yields a different determined_country under "
            "each pinned legal method")

        first_now = get_success_data(api.get_origin_determination(first["id"], ADMIN))
        assert first_now["state"] == "SUPERSEDED", (
            "the determination that was standing in ISSUED transitions to "
            f"SUPERSEDED when a new one is issued, got {first_now['state']}")
        assert first_now["determined_country"] == "VN", (
            "a superseded row keeps the country it derived")

        style_row = read_style(style["id"])
        assert style_row["origin_state"] == "ORIGIN_ISSUED", (
            "issuing advances the origin dimension to ORIGIN_ISSUED, got "
            f"{style_row['origin_state']}")

    def test_redraft_over_the_issued_row_keeps_it_standing_and_blocks_readiness(self, api):
        """PRD 3.3: "From `ORIGIN_ISSUED` the style returns to `ORIGIN_DRAFTED` while the issued row **keeps standing** until the new row is itself issued; `label_readiness` returns to `BLOCKED`, which is what blocks any permanent-label approval while the re-draft is pending."

        Design: Difficulty/dual_variant_calc/origin_substantial_transformation_versus_yarn_forward_on_one_graph
        """
        brand, style = _s1_with_graph()
        issued = issue_determination(draft_determination(style["id"])["id"],
                                    "SUBSTANTIAL_TRANSFORMATION")
        pass_fiber_test(style["id"], _s1_measured())

        ready = read_style(style["id"])
        assert ready["label_readiness"] == "READY", (
            "a substantiated style with an issued determination reads READY, got "
            f"{ready['label_readiness']}")

        redraft = draft_determination(style["id"])
        assert redraft["state"] == "DRAFT"

        issued_now = get_success_data(api.get_origin_determination(issued["id"], ADMIN))
        assert issued_now["state"] == "ISSUED", (
            "the issued row keeps standing until the new row is itself issued, "
            f"got {issued_now['state']}")

        style_row = read_style(style["id"])
        assert style_row["origin_state"] == "ORIGIN_DRAFTED", (
            "re-drafting returns the origin dimension from ORIGIN_ISSUED to "
            f"ORIGIN_DRAFTED, got {style_row['origin_state']}")
        assert style_row["label_readiness"] == "BLOCKED", (
            "label_readiness returns to BLOCKED while the re-draft is pending, "
            f"got {style_row['label_readiness']}")
        assert style_row["substantiation_state"] == "FIBER_SUBSTANTIATED", (
            "the fiber dimension is untouched by an origin re-draft, got "
            f"{style_row['substantiation_state']}")


# --- customs entries used by the penalty instances ------------------------

def _file_entry(brand, style, entry_number, quantity_units, declared_value_usd,
                market_code="US"):
    return file_shipment(brand["id"], style["id"], entry_number=entry_number,
                         quantity_units=quantity_units,
                         declared_value_usd=declared_value_usd,
                         entry_market_code=market_code)


class TestMarkingPenaltyVariantSelection:
    """One deficient entry stores both candidate penalty figures; the frozen
    posture decides which of the two is the assessed one."""

    def test_open_posture_entry_stores_both_figures_and_applies_ad_valorem(self, api):
        """PRD 3.8: "Fifth, the variant actually applied is selected and stored in `assessment_basis`: it is `STATUTORY_PER_UNIT` when the frozen `posture_at_review` is `SUSPENDED`, and `AD_VALOREM` otherwise." PRD 3.8: "Fourth, the statutory alternative is computed. `penalty_statutory_usd` is the smaller of two figures: `quantity_units` multiplied by a per-unit penalty of USD 1.25, rounded half-up to 2 decimal places; and `declared_value_usd` multiplied by a statutory cap rate of 0.80, also rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/marking_penalty_ad_valorem_versus_statutory_per_unit_on_one_entry
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)
        entry = _file_entry(brand, style, "ENT-1001", 12000, 300000.00)
        assert entry["marking_state"] == "ENTRY_FILED"

        reviewed = review_shipment(entry["id"], "DEFICIENT", "MISSING_ORIGIN")
        assert_import_shipment(reviewed)

        assert reviewed["posture_at_review"] == "OPEN", (
            "the brand carried no prior exposure, so the frozen posture is OPEN, "
            f"got {reviewed['posture_at_review']}")
        assert reviewed["penalty_ad_valorem_usd"] == _money(30000.00), (
            "300000.00 at a marking_duty_rate of 0.100 is a duty base of "
            "30000.00, and an OPEN posture multiplies by 1.00, got "
            f"{reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_statutory_usd"] == _money(15000.00), (
            "the statutory alternative is the smaller of 12000 * 1.25 = 15000.00 "
            "and 300000.00 * 0.80 = 240000.00, got "
            f"{reviewed['penalty_statutory_usd']}")
        assert reviewed["assessment_basis"] == "AD_VALOREM", (
            "the frozen posture is not SUSPENDED, so the basis is AD_VALOREM, got "
            f"{reviewed['assessment_basis']}")
        assert reviewed["penalty_assessed_usd"] == _money(30000.00), (
            "penalty_assessed_usd is whichever figure the basis names, here the "
            f"ad valorem 30000.00, got {reviewed['penalty_assessed_usd']}")
        assert reviewed["penalty_mitigated_usd"] == _money(0.00)
        assert reviewed["marking_state"] == "REDELIVERY_ORDERED"

    def test_suspended_posture_switches_the_same_entry_to_statutory_per_unit(self, api):
        """PRD 3.8: "Fifth, the variant actually applied is selected and stored in `assessment_basis`: it is `STATUTORY_PER_UNIT` when the frozen `posture_at_review` is `SUSPENDED`, and `AD_VALOREM` otherwise." PRD 3.8: "Sixth, `penalty_assessed_usd` is set to whichever of the two figures the basis names, and `penalty_mitigated_usd` is set to 0.00."

        Design: Difficulty/dual_variant_calc/marking_penalty_ad_valorem_versus_statutory_per_unit_on_one_entry
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)
        first = _file_entry(brand, style, "ENT-1001", 12000, 300000.00)
        review_shipment(first["id"], "DEFICIENT", "MISSING_ORIGIN")
        assert read_brand(brand["id"])["posture"] == "SUSPENDED", (
            "a ledger of 30000.00 is strictly above 25000.00, so the brand of "
            "record is SUSPENDED before the second entry is reviewed")

        second = _file_entry(brand, style, "ENT-1002", 4000, 10000.00)
        reviewed = review_shipment(second["id"], "DEFICIENT", "MISSING_ORIGIN")

        assert reviewed["posture_at_review"] == "SUSPENDED", (
            "the ledger excluding this entry already stands at 30000.00, so the "
            f"frozen posture is SUSPENDED, got {reviewed['posture_at_review']}")
        assert reviewed["penalty_ad_valorem_usd"] == _money(2000.00), (
            "10000.00 at 0.100 is a duty base of 1000.00, and a SUSPENDED "
            f"posture multiplies by 2.00, got {reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_statutory_usd"] == _money(5000.00), (
            "the statutory alternative is the smaller of 4000 * 1.25 = 5000.00 "
            f"and 10000.00 * 0.80 = 8000.00, got {reviewed['penalty_statutory_usd']}")
        assert reviewed["assessment_basis"] == "STATUTORY_PER_UNIT", (
            "a frozen posture of SUSPENDED selects STATUTORY_PER_UNIT, got "
            f"{reviewed['assessment_basis']}")
        assert reviewed["penalty_assessed_usd"] == _money(5000.00), (
            "the statutory figure 5000.00 is the assessed one even though the ad "
            "valorem variant computed 2000.00 from the identical inputs, got "
            f"{reviewed['penalty_assessed_usd']}")
        assert reviewed["penalty_mitigated_usd"] == _money(0.00)
        assert reviewed["marking_state"] == "REDELIVERY_ORDERED"

    def test_ledger_of_record_sums_entries_assessed_under_either_basis(self, api):
        """PRD 3.1: "It is the sum, over every customs entry whose importing party resolves through the brand-of-record rule to this party and whose marking state is either `REDELIVERY_ORDERED` or `MARKING_CORRECTED`, of that entry's assessed penalty minus its mitigated amount, with the total rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/marking_penalty_ad_valorem_versus_statutory_per_unit_on_one_entry
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)
        first = review_shipment(
            _file_entry(brand, style, "ENT-1001", 12000, 300000.00)["id"],
            "DEFICIENT", "MISSING_ORIGIN")
        second = review_shipment(
            _file_entry(brand, style, "ENT-1002", 4000, 10000.00)["id"],
            "DEFICIENT", "MISSING_ORIGIN")

        assert first["assessment_basis"] == "AD_VALOREM"
        assert second["assessment_basis"] == "STATUTORY_PER_UNIT"

        ledger = read_brand(brand["id"])
        assert ledger["outstanding_penalty_usd"] == _money(35000.00), (
            "the ledger sums 30000.00 assessed under AD_VALOREM and 5000.00 "
            "assessed under STATUTORY_PER_UNIT, each with nothing mitigated, got "
            f"{ledger['outstanding_penalty_usd']}")
        assert ledger["posture"] == "SUSPENDED", (
            "a ledger of 35000.00 is strictly greater than 25000.00, got "
            f"{ledger['posture']}")
        assert ledger["responsible_brand_id"] == brand["id"], (
            "a SELF_OF_RECORD party is its own brand of record")


# --- the durability floor composition ------------------------------------

MIN_CYCLES_BY_MARKET = {"US": 20, "CA": 25}


def _durability_bundle(legibility_cycles=40):
    """Markets US (20 cycles) and CA (25 cycles), a KNIT_TOP style S1 with an
    issued determination, a passed fiber run and a passed care run reporting
    the given legibility_cycles."""
    return setup_label_ready_style(
        markets=[dict(spec) for spec in MARKETS_US_CA],
        style_overrides=_s1_style_overrides(),
        measured_fibers=_s1_measured(),
        care_results={"legibility_cycles": legibility_cycles},
    )


class TestDurabilityFloorComposition:
    """max over the label's markets, then the product-class factor, then the
    ceiling, then the min over the two evidence sources."""

    def test_substantiated_figure_equal_to_the_composed_floor_passes(self, api):
        """PRD 3.6: "The scaled product is rounded **up** to the next whole cycle, so a base of 25 cycles on a knit top yields 25 multiplied by 1.25, which is 31.25, and therefore a floor of 32." PRD 3.6: "The check passes when the substantiated figure is greater than or equal to the floor, so a substantiated figure exactly equal to the floor passes."

        Design: Difficulty/combinatorial_formula/durability_floor_composes_market_max_class_factor_ceiling_and_evidence_min
        """
        bundle = _durability_bundle(legibility_cycles=40)
        floor = expected_durability_floor(MIN_CYCLES_BY_MARKET, ["US", "CA"], "KNIT_TOP")
        assert floor == 32, (
            "max(20, 25) scaled by the knit-top factor 1.25 is 31.25 and rounds "
            f"up to 32, got {floor}")

        bundle, label = setup_pending_permanent_label(
            bundle=bundle, label_overrides={"durability_cycles_rating": 32})
        assert label["durability_cycles_rating"] == 32

        approved = validate_success(api.approve_label_spec(label["id"], APPROVER), 200)
        assert approved["state"] == "APPROVED", (
            "min(legibility_cycles 40, durability_cycles_rating 32) is 32, which "
            f"equals the floor of 32 and therefore passes, got {approved['state']}")
        assert approved["approved_by_user_id"] == "op-approver-1", (
            "approved_by_user_id records the acting approver, got "
            f"{approved['approved_by_user_id']}")

        summary = get_success_data(
            api.get_compliance_summary(bundle["style"]["id"], ADMIN))
        assert summary["required_durability_cycles"] == 32, (
            "the summary floor is computed the same way over the style's whole "
            f"target market list [US, CA], got {summary['required_durability_cycles']}")
        assert summary["substantiated_durability_cycles"] == 40, (
            "substantiated_durability_cycles is the legibility_cycles of the "
            "newest passed care-performance run, which is 40, got "
            f"{summary['substantiated_durability_cycles']}")

        style_row = read_style(bundle["style"]["id"])
        assert style_row["label_readiness"] == "READY"

    def test_rating_one_cycle_below_the_ceiling_is_rejected(self, api):
        """PRD 3.6: "**The durability adequacy check** works out a floor and compares the substantiated figure against it." PRD 3.6: "The floor starts as the greatest `min_durability_cycles` among the regimes of exactly the artifact's `market_codes` — the label's own market set, not the style's full target list."

        Design: Difficulty/combinatorial_formula/durability_floor_composes_market_max_class_factor_ceiling_and_evidence_min
        """
        bundle = _durability_bundle(legibility_cycles=40)
        bundle, label = setup_pending_permanent_label(
            bundle=bundle, label_overrides={"durability_cycles_rating": 30})

        validate_error(api.approve_label_spec(label["id"], APPROVER),
                       ApiErrorId.ERR_DURABILITY_INSUFFICIENT)

        after = read_label(label["id"])
        assert after["state"] == "PENDING_APPROVAL", (
            "a rating of 30 is below the composed floor of 32, so the artifact "
            f"stays in PENDING_APPROVAL, got {after['state']}")
        assert after["approved_by_user_id"] is None, (
            "a rejected approval records no approver, got "
            f"{after['approved_by_user_id']}")

    def test_substantiated_figure_is_the_min_of_the_two_evidence_sources(self, api):
        """PRD 3.6: "The substantiated figure is the smaller of two numbers: the `legibility_cycles` reported by the pinned care-performance run, and the `durability_cycles_rating` the specialist claimed for the label stock." PRD 3.9: "It returns `substantiated_durability_cycles`, which is the `legibility_cycles` of the newest passed care-performance run of the style and reads 0 when the style has none." PRD 3.9: "and `ERR_DURABILITY_INSUFFICIENT` while the substantiated cycles figure is strictly less than the required one."

        Design: Difficulty/combinatorial_formula/durability_floor_composes_market_max_class_factor_ceiling_and_evidence_min
        """
        bundle = _durability_bundle(legibility_cycles=31)
        assert bundle["care_test"]["legibility_cycles"] == 31

        bundle, label = setup_pending_permanent_label(
            bundle=bundle, label_overrides={"durability_cycles_rating": 100})

        validate_error(api.approve_label_spec(label["id"], APPROVER),
                       ApiErrorId.ERR_DURABILITY_INSUFFICIENT)

        summary = get_success_data(
            api.get_compliance_summary(bundle["style"]["id"], ADMIN))
        assert summary["required_durability_cycles"] == 32
        assert summary["substantiated_durability_cycles"] == 31, (
            "the substantiated figure is read from the care run's "
            f"legibility_cycles, got {summary['substantiated_durability_cycles']}")
        assert ApiErrorId.ERR_DURABILITY_INSUFFICIENT.value in summary["blocking_reasons"], (
            "the durability gate is unsatisfied while 31 is strictly less than "
            f"the required 32, got {summary['blocking_reasons']}")


# --- the pinned two-step rounding order -----------------------------------

def _mx_brand_with_style():
    """Market MX at a marking_duty_rate of 0.075, plus brand and style S1."""
    return _brand_with_style(
        "MX", required_languages=["es"], fiber_tolerance_pp=4.0,
        absolute_claim_tolerance_pp=0.5, min_durability_cycles=15,
        marking_duty_rate=0.075)


def _three_critical_findings(brand, style):
    """An audit carrying three findings that derive to CRITICAL: two by code and
    one by the 5,000-unit escalation. Returns (audit, findings)."""
    audit = open_audit(brand["id"], scope="IMPORT_MARKING")
    findings = [
        raise_finding(audit["id"], style["id"],
                      finding_code="FIBER_CONTENT_MISSTATED", units_affected=100),
        raise_finding(audit["id"], style["id"],
                      finding_code="ORIGIN_MISSTATED", units_affected=100),
        raise_finding(audit["id"], style["id"],
                      finding_code="CARE_UNSUBSTANTIATED", units_affected=5000),
    ]
    return read_audit(audit["id"]), findings


class TestAdValoremRoundingOrder:
    """The ad valorem charge is a two-stage rounding chain that cannot be
    collapsed into a single rounding."""

    def test_duty_is_rounded_to_cents_before_the_escalation_multiplier(self, api):
        """PRD 3.8: "The two roundings are ordered and the order matters: round the duty to cents first, then round the escalated product." PRD 3.8: "Multiplying the unrounded duty by the multiplier and rounding once yields a different number and is not the pinned semantics."

        Design: Difficulty/combinatorial_formula/marking_penalty_two_step_rounding_order_is_pinned
        """
        brand, style = _mx_brand_with_style()
        _three_critical_findings(brand, style)
        assert read_brand(brand["id"])["posture"] == "RESTRICTED", (
            "three critical findings on an IN_REVIEW audit restrict the brand of "
            "record before the entry is reviewed")

        entry = _file_entry(brand, style, "ENT-2001", 800, 1000.10, "MX")
        reviewed = review_shipment(entry["id"], "DEFICIENT", "WRONG_ORIGIN")

        assert reviewed["posture_at_review"] == "RESTRICTED"
        assert reviewed["penalty_ad_valorem_usd"] == _money(112.52), (
            "1000.10 * 0.075 = 75.0075 rounds half-up to a duty base of 75.01, "
            "and 75.01 * 1.50 = 112.515 rounds half-up to 112.52, got "
            f"{reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_ad_valorem_usd"] != _money(112.51), (
            "112.51 is what a single rounding of 1000.10 * 0.075 * 1.50 yields, "
            "which is not the pinned semantics, got "
            f"{reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_statutory_usd"] == _money(800.08), (
            "the statutory alternative is the smaller of 800 * 1.25 = 1000.00 and "
            f"1000.10 * 0.80 = 800.08, got {reviewed['penalty_statutory_usd']}")
        assert reviewed["assessment_basis"] == "AD_VALOREM", (
            "a frozen posture of RESTRICTED is not SUSPENDED, so the basis stays "
            f"AD_VALOREM, got {reviewed['assessment_basis']}")
        assert reviewed["penalty_assessed_usd"] == _money(112.52)

        ledger = read_brand(brand["id"])
        assert ledger["outstanding_penalty_usd"] == _money(112.52), (
            "the ledger carries the assessed penalty minus nothing mitigated, got "
            f"{ledger['outstanding_penalty_usd']}")
        assert ledger["posture"] == "RESTRICTED", (
            "112.52 is far below 25000.00, so the restriction from the audit still "
            f"decides the posture, got {ledger['posture']}")

    def test_open_posture_multiplier_of_one_still_rounds_the_duty_base_first(self, api):
        """PRD 3.8: "Second, the marking-duty rate is read from the regime of the entry's port — the `marking_duty_rate` of the `entry_market_code` regime — and a duty base is computed as `declared_value_usd` multiplied by that rate, rounded half-up to 2 decimal places." PRD 3.8: "The multiplier is 1.00 for an `OPEN` posture, 1.50 for `RESTRICTED` and 2.00 for `SUSPENDED`."

        Design: Difficulty/combinatorial_formula/marking_penalty_two_step_rounding_order_is_pinned
        """
        brand, style = _mx_brand_with_style()
        assert read_brand(brand["id"])["posture"] == "OPEN"

        entry = _file_entry(brand, style, "ENT-2001", 800, 1000.10, "MX")
        reviewed = review_shipment(entry["id"], "DEFICIENT", "WRONG_ORIGIN")

        assert reviewed["posture_at_review"] == "OPEN"
        assert reviewed["penalty_ad_valorem_usd"] == _money(75.01), (
            "1000.10 * 0.075 = 75.0075 rounds half-up to 75.01, and an OPEN "
            "posture multiplies that rounded base by 1.00, got "
            f"{reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_ad_valorem_usd"] != _money(75.00), (
            "the duty base is rounded half-up rather than truncated, got "
            f"{reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_statutory_usd"] == _money(800.08)
        assert reviewed["assessment_basis"] == "AD_VALOREM"
        assert reviewed["penalty_assessed_usd"] == _money(75.01)

        ledger = read_brand(brand["id"])
        assert ledger["outstanding_penalty_usd"] == _money(75.01)
        assert ledger["posture"] == "OPEN", (
            "a ledger of 75.01 with no restricting audit leaves the posture OPEN, "
            f"got {ledger['posture']}")

    def test_escalation_multiplier_is_read_from_the_derived_audit_posture(self, api):
        """PRD 3.9: "That base then escalates by exactly one level when `units_affected` reaches 5,000 units, where escalation maps `MINOR` to `MAJOR`, `MAJOR` to `CRITICAL`, and `CRITICAL` to `CRITICAL`." PRD 3.1: "It is derived in a fixed order: if the ledger is **strictly greater** than USD 25,000.00 the posture is `SUSPENDED`, so a ledger of exactly 25,000.00 is not suspended; otherwise, if there exists at least one compliance audit of this brand of record whose state is `IN_REVIEW` and whose critical-finding count is **at least** 3 — three critical findings is enough — the posture is `RESTRICTED`; otherwise it is `OPEN`."

        Design: Difficulty/combinatorial_formula/marking_penalty_two_step_rounding_order_is_pinned
        """
        brand, style = _mx_brand_with_style()
        audit, findings = _three_critical_findings(brand, style)

        assert findings[2]["severity"] == "CRITICAL", (
            "CARE_UNSUBSTANTIATED is base MAJOR and escalates one level at "
            f"exactly 5,000 affected units, got {findings[2]['severity']}")
        assert audit["state"] == "IN_REVIEW", (
            f"the first finding drives the audit out of OPEN, got {audit['state']}")
        assert audit["critical_finding_count"] == 3, (
            "two findings are critical by code and the third by escalation, got "
            f"{audit['critical_finding_count']}")
        assert audit["units_in_scope"] == 5200, (
            "units_in_scope sums units_affected over every finding: "
            f"100 + 100 + 5000, got {audit['units_in_scope']}")
        assert read_brand(brand["id"])["posture"] == "RESTRICTED"

        entry = _file_entry(brand, style, "ENT-2001", 800, 1000.10, "MX")
        reviewed = review_shipment(entry["id"], "DEFICIENT", "WRONG_ORIGIN")

        assert reviewed["posture_at_review"] == "RESTRICTED", (
            "the posture frozen onto the row is the one derived from the audit, "
            f"got {reviewed['posture_at_review']}")
        assert reviewed["penalty_ad_valorem_usd"] == _money(112.52), (
            "a RESTRICTED posture escalates the rounded duty base 75.01 by 1.50, "
            f"got {reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_assessed_usd"] == _money(112.52)


class TestPenaltyPostureFixedPoint:
    """The penalty depends on the posture and the posture depends on the
    ledger, so the entry under review is excluded from its own ledger."""

    def test_entry_cannot_escalate_itself_through_its_own_penalty(self, api):
        """PRD 3.8: "First, the posture of the brand of record is evaluated **excluding this entry from the ledger**, and the result is frozen onto the row as `posture_at_review`." PRD 3.8: "This is what makes it impossible for an assessment to escalate itself."

        Design: Difficulty/combinatorial_formula/penalty_and_posture_circularity_resolved_by_excluding_the_shipment_itself
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)
        entry = _file_entry(brand, style, "ENT-3001", 12000, 300000.00)
        reviewed = review_shipment(entry["id"], "DEFICIENT", "MISSING_IDENTITY")

        assert reviewed["posture_at_review"] == "OPEN", (
            "the ledger excluding this entry is 0.00, so the frozen posture is "
            f"OPEN even though this entry alone will suspend the brand, got "
            f"{reviewed['posture_at_review']}")
        assert reviewed["penalty_ad_valorem_usd"] == _money(30000.00), (
            "the duty base of 30000.00 is escalated by the OPEN multiplier 1.00; "
            "an entry that saw its own penalty would have escalated to 60000.00, "
            f"got {reviewed['penalty_ad_valorem_usd']}")
        assert reviewed["penalty_statutory_usd"] == _money(15000.00), (
            "the statutory alternative is the smaller of 12000 * 1.25 = 15000.00 "
            f"and 300000.00 * 0.80 = 240000.00, got "
            f"{reviewed['penalty_statutory_usd']}")
        assert reviewed["assessment_basis"] == "AD_VALOREM", (
            "the frozen posture is OPEN, so the basis stays AD_VALOREM rather "
            f"than switching to the statutory 15000.00, got "
            f"{reviewed['assessment_basis']}")
        assert reviewed["penalty_assessed_usd"] == _money(30000.00)
        assert reviewed["marking_state"] == "REDELIVERY_ORDERED"

    def test_the_assessment_enters_the_ledger_only_after_it_is_computed(self, api):
        """PRD 3.1: "`outstanding_penalty_usd` is the party's marking-penalty ledger of record, carried at 2 decimal places and never negative, and it starts at 0.00 because a freshly registered party owns no shipments." PRD 3.8: "Only after all of that does the entry enter the ledger, and the brand-of-record's `outstanding_penalty_usd` and `posture` are recomputed with this entry now included — which is how a single large assessment can drive a party to `SUSPENDED`."

        Design: Difficulty/combinatorial_formula/penalty_and_posture_circularity_resolved_by_excluding_the_shipment_itself
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)
        before = read_brand(brand["id"])
        assert before["outstanding_penalty_usd"] == _money(0.00), (
            "a freshly registered party owns no shipments, got "
            f"{before['outstanding_penalty_usd']}")
        assert before["posture"] == "OPEN"

        entry = _file_entry(brand, style, "ENT-3001", 12000, 300000.00)
        filed = read_brand(brand["id"])
        assert filed["outstanding_penalty_usd"] == _money(0.00), (
            "an entry still in ENTRY_FILED contributes nothing, got "
            f"{filed['outstanding_penalty_usd']}")

        reviewed = review_shipment(entry["id"], "DEFICIENT", "MISSING_IDENTITY")
        assert reviewed["posture_at_review"] == "OPEN"

        after = read_brand(brand["id"])
        assert after["outstanding_penalty_usd"] == _money(30000.00), (
            "the assessed 30000.00 enters the ledger only after the assessment is "
            f"complete, got {after['outstanding_penalty_usd']}")
        assert after["posture"] == "SUSPENDED", (
            "30000.00 is strictly greater than 25000.00, so the party is now "
            f"SUSPENDED, got {after['posture']}")

    def test_compliant_and_still_filed_entries_never_enter_the_ledger(self, api):
        """PRD 3.1: "Entries still in `ENTRY_FILED` and entries found `MARKING_COMPLIANT` contribute nothing." PRD 3.8: "A compliant outcome moves the entry to the terminal state `MARKING_COMPLIANT` and leaves every penalty figure at 0.00."

        Design: Difficulty/combinatorial_formula/penalty_and_posture_circularity_resolved_by_excluding_the_shipment_itself
        """
        brand, style = _brand_with_style("US", marking_duty_rate=0.100)

        compliant = review_shipment(
            _file_entry(brand, style, "ENT-3001", 12000, 300000.00)["id"],
            "COMPLIANT", None)
        assert compliant["marking_state"] == "MARKING_COMPLIANT"
        assert compliant["penalty_ad_valorem_usd"] == _money(0.00)
        assert compliant["penalty_statutory_usd"] == _money(0.00)
        assert compliant["penalty_assessed_usd"] == _money(0.00), (
            "a compliant outcome leaves every penalty figure at 0.00, got "
            f"{compliant['penalty_assessed_usd']}")

        _file_entry(brand, style, "ENT-3002", 12000, 300000.00)
        assert read_brand(brand["id"])["posture"] == "OPEN", (
            "neither the compliant entry nor the one still in ENTRY_FILED enters "
            "the ledger")

        deficient = review_shipment(
            _file_entry(brand, style, "ENT-3003", 12000, 300000.00)["id"],
            "DEFICIENT", "MISSING_IDENTITY")
        assert deficient["posture_at_review"] == "OPEN", (
            "the ledger excluding this entry still reads 0.00, so the frozen "
            f"posture is OPEN, got {deficient['posture_at_review']}")
        assert deficient["penalty_assessed_usd"] == _money(30000.00)

        ledger = read_brand(brand["id"])
        assert ledger["outstanding_penalty_usd"] == _money(30000.00), (
            "only the one entry in REDELIVERY_ORDERED contributes, got "
            f"{ledger['outstanding_penalty_usd']}")
        assert ledger["posture"] == "SUSPENDED"
