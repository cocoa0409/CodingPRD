"""Rejection-ladder priority conflicts and inclusive/strict numeric boundaries.

Every test in this module drives one write that is defective in more than one
way at once, or sits exactly on a declared threshold, and pins the single
observable outcome PRD.md commits to.
"""
import pytest

from test_helpers import (
    ADMIN, APPROVER, AUDITOR, CUSTOMS, LAB, SPECIALIST,
    ApiErrorId,
    create_style, draft_permanent_label, expected_durability_floor,
    fiber_line, file_shipment, make_headers, open_audit, raise_finding,
    read_audit, read_brand, read_finding, read_label, read_style,
    register_brand, register_market, reserve_fiber_test,
    setup_label_ready_style, submit_label,
    validate_error, validate_success,
)

# --- shared literals ------------------------------------------------------

# A label identifier deliberately absent from an empty store.
_MISSING_LABEL_ID = "00000000-0000-0000-0000-0000000009ff"

# US demands 20 legible wash cycles, CA demands 25, so a label printed for both
# takes 25 as its base floor.
_US_CA_MARKETS = [
    {"market_code": "US", "required_languages": ["en"],
     "min_durability_cycles": 20},
    {"market_code": "CA", "required_languages": ["en", "fr"],
     "min_durability_cycles": 25, "absolute_claim_tolerance_pp": 0.3},
]
_US_CA_MIN_CYCLES = {"US": 20, "CA": 25}

# The specialist that authors every label in this module.
_AUTHOR_USER_ID = "op-specialist-1"

_THREE_LINE_FIBERS = [
    fiber_line("COTTON", 60.0),
    fiber_line("POLYESTER", 37.0),
    fiber_line("ELASTANE", 3.0),
]
_ABSOLUTE_CLAIM_FIBERS = [fiber_line("COTTON", 100.0)]


def _knit_top_with_short_stock_rating(rating=30):
    """A KNIT_TOP style targeting [US, CA] with fiber, origin and care evidence
    all in place, plus a DRAFT permanent label whose stock rating is below the
    scaled durability floor. Returns (bundle, label)."""
    bundle = setup_label_ready_style(
        markets=_US_CA_MARKETS,
        style_overrides={"product_class": "KNIT_TOP", "net_weight_grams": 320.0},
    )
    label = draft_permanent_label(bundle, headers=SPECIALIST,
                                 durability_cycles_rating=rating)
    return bundle, label


def _fiber_style(brand_id, declared_fibers):
    return create_style(brand_id, target_market_codes=["US"],
                        product_class="WOVEN_OUTERWEAR",
                        net_weight_grams=320.0,
                        declared_fibers=[dict(line) for line in declared_fibers])


def _post_fiber_results(api, style_id, measured_fibers,
                        specimen_received_at="2026-08-03T09:00:00Z",
                        results_due_at="2026-08-05T09:00:00Z"):
    """Reserve one fiber-content bench for the style on its own window and post
    the given measurements. Returns the updated laboratory row."""
    test = reserve_fiber_test(style_id, lab_code="LAB-ATL-1", method="AATCC_20A",
                              specimen_received_at=specimen_received_at,
                              results_due_at=results_due_at)
    resp = api.post_lab_test_results(test["id"], {"measured_fibers": measured_fibers}, LAB)
    return validate_success(resp, 200)


class TestApproveStateThenSegregationThenDurability:
    """One approve call defective at ladder steps 9, 10 and 36 simultaneously."""

    def test_draft_label_reports_state_invalid_not_the_durability_defect(self, api):
        """PRD 2.7: "State legality: the target row must sit in a state from which the requested transition is declared — `ERR_LABEL_STATE_INVALID`, `ERR_LAB_TEST_STATE_INVALID`, `ERR_ORIGIN_STATE_INVALID`, `ERR_SHIPMENT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID` or `ERR_FINDING_STATE_INVALID` (all HTTP 409), on every action endpoint that drives a state transition."

        The label is still in DRAFT, would be approved by its own author, and
        claims a stock rating below the floor, yet the earliest applicable check
        is the state check.

        Design: Difficulty/priority_pair_validation_conflict/approve_answers_state_then_segregation_then_durability_in_priority_order
        """
        bundle, label = _knit_top_with_short_stock_rating()
        assert label["state"] == "DRAFT", "the label must start in DRAFT"

        # The acting approver is the author, so segregation of duties is violated too.
        resp = api.approve_label_spec(
            label["id"], make_headers(_AUTHOR_USER_ID, "LabelingApprover"))
        validate_error(resp, ApiErrorId.ERR_LABEL_STATE_INVALID, 409)

        assert read_label(label["id"])["state"] == "DRAFT", (
            "a rejected approval must not move the artifact"
        )

    def test_segregation_pre_empts_durability_once_the_label_is_pending(self, api):
        """PRD 2.1: "the `X-User-ID` of the approving `LabelingApprover` must differ from the `authored_by_user_id` recorded on the artifact. If they are the same operator, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/approve_answers_state_then_segregation_then_durability_in_priority_order
        """
        bundle, label = _knit_top_with_short_stock_rating()
        submitted = submit_label(label["id"], SPECIALIST)
        assert submitted["state"] == "PENDING_APPROVAL"
        assert submitted["authored_by_user_id"] == _AUTHOR_USER_ID

        # Self-approval: ladder step 10 answers, not step 36.
        resp = api.approve_label_spec(
            label["id"], make_headers(_AUTHOR_USER_ID, "LabelingApprover"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        # A different approver clears step 10 and now reaches the durability gate.
        resp = api.approve_label_spec(label["id"], APPROVER)
        validate_error(resp, ApiErrorId.ERR_DURABILITY_INSUFFICIENT, 422)

    def test_three_rejections_in_ladder_order_leave_the_artifact_unapproved(self, api):
        """PRD 3.6: "The substantiated figure is the smaller of two numbers: the `legibility_cycles` reported by the pinned care-performance run, and the `durability_cycles_rating` the specialist claimed for the label stock."

        Design: Difficulty/priority_pair_validation_conflict/approve_answers_state_then_segregation_then_durability_in_priority_order
        """
        bundle, label = _knit_top_with_short_stock_rating(rating=30)
        style_id = bundle["style"]["id"]
        author_as_approver = make_headers(_AUTHOR_USER_ID, "LabelingApprover")

        errors = []
        resp = api.approve_label_spec(label["id"], author_as_approver)
        errors.append(validate_error(resp, ApiErrorId.ERR_LABEL_STATE_INVALID, 409)["error_id"])
        submit_label(label["id"], SPECIALIST)
        resp = api.approve_label_spec(label["id"], author_as_approver)
        errors.append(validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)["error_id"])
        resp = api.approve_label_spec(label["id"], APPROVER)
        errors.append(validate_error(resp, ApiErrorId.ERR_DURABILITY_INSUFFICIENT, 422)["error_id"])

        assert errors == ["ERR_LABEL_STATE_INVALID", "ERR_SEGREGATION_OF_DUTIES",
                          "ERR_DURABILITY_INSUFFICIENT"], (
            f"Expected the ladder to answer state, then duty segregation, then "
            f"durability, got {errors}"
        )

        final = read_label(label["id"])
        assert final["state"] == "PENDING_APPROVAL", (
            "three rejected approvals must leave the artifact in PENDING_APPROVAL"
        )
        assert final["approved_by_user_id"] is None, (
            "approved_by_user_id must stay null while every approval is rejected"
        )

        floor = expected_durability_floor(_US_CA_MIN_CYCLES, ["US", "CA"], "KNIT_TOP")
        assert floor == 32, "25 base cycles scaled by the knit-top factor 1.25 rounds up to 32"
        summary = validate_success(api.get_compliance_summary(style_id, ADMIN), 200)
        assert summary["required_durability_cycles"] == 32, (
            f"Expected the style-wide durability floor 32, got "
            f"{summary['required_durability_cycles']}"
        )


class TestRoleGateAnswersBeforePathExistence:
    """Ladder step 2 outranks ladder step 3 on the very same request."""

    @pytest.mark.parametrize("role", [
        "LabelingSpecialist", "BrandAdmin", "ComplianceAdmin",
        "AccreditedLab", "CustomsOfficer", "Auditor",
    ])
    def test_unlisted_role_gets_role_not_permitted_for_an_unknown_label(self, api, role):
        """PRD 2.1: "Once the caller is authenticated, the service compares the acting role against the list of roles authorized for the invoked endpoint in §4; a role that is not listed there is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Approval is the `LabelingApprover`'s exclusive act, so no other role may
        learn whether the label id resolves.

        Design: Difficulty/priority_pair_validation_conflict/role_gate_answers_before_path_existence
        """
        resp = api.approve_label_spec(_MISSING_LABEL_ID, make_headers("op-x-1", role))
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    def test_permitted_role_reaches_the_path_existence_check(self, api):
        """PRD 2.6: "Identifiers embedded in a URL path are resolved strictly left to right, and the first one that does not resolve to a live row decides the 404."

        Design: Difficulty/priority_pair_validation_conflict/role_gate_answers_before_path_existence
        """
        resp = api.approve_label_spec(_MISSING_LABEL_ID,
                                      make_headers("op-appr-1", "LabelingApprover"))
        validate_error(resp, ApiErrorId.ERR_LABEL_SPEC_NOT_FOUND, 404)

    def test_switching_to_the_approver_role_flips_403_into_404(self, api):
        """PRD 2.7: "The service therefore evaluates checks in one fixed order and returns the error of the **earliest** applicable check — never the most obvious defect, and never the last one discovered."

        Design: Difficulty/priority_pair_validation_conflict/role_gate_answers_before_path_existence
        """
        first = api.approve_label_spec(
            _MISSING_LABEL_ID, make_headers("op-spec-9", "LabelingSpecialist"))
        second = api.approve_label_spec(
            _MISSING_LABEL_ID, make_headers("op-appr-9", "LabelingApprover"))

        assert first.status_code == 403 and second.status_code == 404, (
            f"Expected 403 then 404 on the same unknown label id, got "
            f"{first.status_code} then {second.status_code}"
        )
        validate_error(first, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_error(second, ApiErrorId.ERR_LABEL_SPEC_NOT_FOUND, 404)


class TestRequestShapeAnswersBeforeTheLicensorRule:
    """Ladder step 6 outranks ladder step 7 on `POST /labeling/brands`."""

    def test_undeclared_party_type_answers_before_the_missing_licensor(self, api):
        """PRD 2.7: "Request shape — `ERR_INVALID_REQUEST`, on every endpoint. This covers a missing required field, an enum value that is not a declared member, a number outside its declared range, an array that is required to be non-empty but is empty, a `limit` outside 1 through 100 or a negative `offset`, a `method` that does not match the `test_type` it is reserved for, a `wash_temp_c` present on a fiber-content reservation or absent on a care-performance one, and a `results_due_at` that is not strictly after `specimen_received_at`."

        The body is malformed and legally incoherent at once: `SUBLICENSEE` is not
        a declared `party_type`, and `LICENSOR_OF_RECORD` carries no licensor.

        Design: Difficulty/priority_pair_validation_conflict/request_shape_answers_before_the_licensor_rule
        """
        register_brand(legal_name="Harborline Group", rn_number="RN99001")
        resp = api.create_brand({
            "legal_name": "Southgate Licensee LLC",
            "party_type": "SUBLICENSEE",
            "responsibility_mode": "LICENSOR_OF_RECORD",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_licensor_rule_surfaces_only_once_the_enum_is_corrected(self, api):
        """PRD 3.1: "Registration is rejected with `ERR_LICENSOR_REQUIRED` when a licensee omits its licensor, when `LICENSOR_OF_RECORD` is chosen without a licensor, or when a licensor is supplied by a party that is not a licensee."

        Design: Difficulty/priority_pair_validation_conflict/request_shape_answers_before_the_licensor_rule
        """
        licensor = register_brand(legal_name="Harborline Group", rn_number="RN99001")

        resp = api.create_brand({
            "legal_name": "Southgate Licensee LLC",
            "party_type": "LICENSEE",
            "responsibility_mode": "LICENSOR_OF_RECORD",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_LICENSOR_REQUIRED, 422)

        resp = api.create_brand({
            "legal_name": "Southgate Licensee LLC",
            "party_type": "LICENSEE",
            "licensor_brand_id": licensor["id"],
            "responsibility_mode": "LICENSOR_OF_RECORD",
        }, ADMIN)
        licensee = validate_success(resp, 201)
        assert licensee["responsible_brand_id"] == licensor["id"], (
            "LICENSOR_OF_RECORD must resolve responsibility to the licensor row, "
            f"got {licensee['responsible_brand_id']}"
        )
        assert licensee["posture"] == "OPEN", "a freshly registered party starts OPEN"
        assert licensee["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
            "a freshly registered party owns no shipments, so its ledger starts at 0.00"
        )

    @pytest.mark.parametrize("mutate", ["licensee_without_licensor",
                                        "non_licensee_with_licensor"])
    def test_the_other_two_licensor_incoherences_are_also_422(self, api, mutate):
        """PRD 2.7: "Licensor coherence on brand registration — `ERR_LICENSOR_REQUIRED`, on `POST /labeling/brands`."

        Design: Difficulty/priority_pair_validation_conflict/request_shape_answers_before_the_licensor_rule
        """
        licensor = register_brand(legal_name="Harborline Group", rn_number="RN99001")
        if mutate == "licensee_without_licensor":
            payload = {"legal_name": "Southgate Licensee LLC", "party_type": "LICENSEE",
                       "licensor_brand_id": None,
                       "responsibility_mode": "SELF_OF_RECORD"}
        else:
            payload = {"legal_name": "Westbay Owner Ltd", "party_type": "BRAND_OWNER",
                       "licensor_brand_id": licensor["id"],
                       "responsibility_mode": "SELF_OF_RECORD"}
        validate_error(api.create_brand(payload, ADMIN),
                       ApiErrorId.ERR_LICENSOR_REQUIRED, 422)


class TestFiberToleranceIsInclusiveAtTheExactMarketTolerance:
    """One tenth of a percentage point decides the fiber-content verdict."""

    def test_deviation_exactly_equal_to_the_tolerance_passes(self, api):
        """PRD 3.4: "Third, the comparison is inclusive: the verdict is a pass when `result_delta_pp_max` is less than or equal to the governing tolerance, so a deviation exactly equal to the tolerance passes."

        Design: Difficulty/boundary_precision_check/fiber_tolerance_comparison_is_inclusive_at_the_exact_market_tolerance
        """
        register_market("US", fiber_tolerance_pp=3.0, absolute_claim_tolerance_pp=0.0)
        brand = register_brand(legal_name="Northline Apparel Co")
        style = _fiber_style(brand["id"], _THREE_LINE_FIBERS)

        row = _post_fiber_results(api, style["id"], [
            {"fiber_generic_name": "COTTON", "measured_pct": 57.0},
            {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
            {"fiber_generic_name": "ELASTANE", "measured_pct": 3.0},
        ])

        assert row["result_delta_pp_max"] == pytest.approx(3.0, abs=0.01), (
            f"Expected the largest deviation 3.0 pp, got {row['result_delta_pp_max']}"
        )
        assert row["state"] == "PASSED", (
            f"3.0 pp against a 3.0 pp tolerance is inclusive, so the run must PASS, "
            f"got {row['state']}"
        )
        assert row["valid_until"] == "2027-08-03T09:00:00Z", (
            f"a fiber-content horizon is specimen_received_at plus 365 days, never "
            f"the posting instant, got {row['valid_until']}"
        )
        assert read_style(style["id"])["substantiation_state"] == "FIBER_SUBSTANTIATED"

    def test_one_tenth_beyond_the_tolerance_fails(self, api):
        """PRD 3.4: "The second hop, caused by the first, sets the style's `substantiation_state` to `FIBER_MISSTATED` and its `label_readiness` to `BLOCKED`."

        Design: Difficulty/boundary_precision_check/fiber_tolerance_comparison_is_inclusive_at_the_exact_market_tolerance
        """
        register_market("US", fiber_tolerance_pp=3.0, absolute_claim_tolerance_pp=0.0)
        brand = register_brand(legal_name="Northline Apparel Co")
        style = _fiber_style(brand["id"], _THREE_LINE_FIBERS)

        row = _post_fiber_results(api, style["id"], [
            {"fiber_generic_name": "COTTON", "measured_pct": 56.9},
            {"fiber_generic_name": "POLYESTER", "measured_pct": 40.1},
            {"fiber_generic_name": "ELASTANE", "measured_pct": 3.0},
        ])

        assert row["result_delta_pp_max"] == pytest.approx(3.1, abs=0.01), (
            f"Expected the largest deviation 3.1 pp, got {row['result_delta_pp_max']}"
        )
        assert row["state"] == "FAILED", (
            f"3.1 pp exceeds the 3.0 pp tolerance, got {row['state']}"
        )
        refreshed = read_style(style["id"])
        assert refreshed["substantiation_state"] == "FIBER_MISSTATED"
        assert refreshed["label_readiness"] == "BLOCKED"

    def test_absolute_claim_collapses_the_tolerance_to_zero_point_zero(self, api):
        """PRD 3.4: "For an absolute claim the governing tolerance is the smallest `absolute_claim_tolerance_pp` across those markets, and because that figure is 0.0 in the United States market, any measured foreign fiber at all fails."

        A single non-exempt line at 100.0 is the absolute claim, so a deviation of
        exactly 0.0 still passes while the 0.3 pp foreign line fails.

        Design: Difficulty/boundary_precision_check/fiber_tolerance_comparison_is_inclusive_at_the_exact_market_tolerance
        """
        register_market("US", fiber_tolerance_pp=3.0, absolute_claim_tolerance_pp=0.0)
        brand = register_brand(legal_name="Northline Apparel Co")
        clean = _fiber_style(brand["id"], _ABSOLUTE_CLAIM_FIBERS)
        adulterated = _fiber_style(brand["id"], _ABSOLUTE_CLAIM_FIBERS)

        clean_row = _post_fiber_results(
            api, clean["id"],
            [{"fiber_generic_name": "COTTON", "measured_pct": 100.0}],
            specimen_received_at="2026-08-03T09:00:00Z",
            results_due_at="2026-08-05T09:00:00Z")
        assert clean_row["result_delta_pp_max"] == pytest.approx(0.0, abs=0.01)
        assert clean_row["state"] == "PASSED", (
            f"0.0 pp against a 0.0 pp absolute-claim tolerance is inclusive, got "
            f"{clean_row['state']}"
        )
        assert read_style(clean["id"])["substantiation_state"] == "FIBER_SUBSTANTIATED"

        # POLYESTER is absent from the declaration, so it enters the union at a
        # declared 0.0 and contributes a 0.3 pp deviation.
        dirty_row = _post_fiber_results(
            api, adulterated["id"],
            [{"fiber_generic_name": "COTTON", "measured_pct": 99.7},
             {"fiber_generic_name": "POLYESTER", "measured_pct": 0.3}],
            specimen_received_at="2026-08-11T09:00:00Z",
            results_due_at="2026-08-13T09:00:00Z")
        assert dirty_row["result_delta_pp_max"] == pytest.approx(0.3, abs=0.01), (
            f"Expected the undeclared POLYESTER line to contribute 0.3 pp, got "
            f"{dirty_row['result_delta_pp_max']}"
        )
        assert dirty_row["state"] == "FAILED", (
            f"0.3 pp exceeds a 0.0 pp absolute-claim tolerance, got {dirty_row['state']}"
        )
        assert read_style(adulterated["id"])["substantiation_state"] == "FIBER_MISSTATED"


def _penalty_ledger_fixture():
    """Market US at a 0.100 marking-duty rate, one brand, one style, and two
    filed entries: ENT-4001 assesses exactly 25,000.00 and ENT-4002 exactly one
    cent. Returns (brand, first_entry, second_entry)."""
    register_market("US", marking_duty_rate=0.100)
    brand = register_brand(legal_name="Northline Apparel Co")
    style = create_style(brand["id"], target_market_codes=["US"],
                        net_weight_grams=320.0)
    first = file_shipment(brand["id"], style["id"], entry_number="ENT-4001",
                          quantity_units=12000, declared_value_usd=250000.00,
                          entry_market_code="US")
    second = file_shipment(brand["id"], style["id"], entry_number="ENT-4002",
                           quantity_units=1, declared_value_usd=0.10,
                           entry_market_code="US")
    return brand, first, second


_DEFICIENT = {"outcome": "DEFICIENT", "deficiency_code": "MISSING_ORIGIN"}


class TestSuspensionLedgerThresholdIsStrictlyGreater:
    """USD 25,000.00 exactly is not enough; 25,000.01 is."""

    def test_a_ledger_of_exactly_the_threshold_leaves_the_brand_open(self, api):
        """PRD 3.1: "It is derived in a fixed order: if the ledger is **strictly greater** than USD 25,000.00 the posture is `SUSPENDED`, so a ledger of exactly 25,000.00 is not suspended; otherwise, if there exists at least one compliance audit of this brand of record whose state is `IN_REVIEW` and whose critical-finding count is **at least** 3 — three critical findings is enough — the posture is `RESTRICTED`; otherwise it is `OPEN`."

        Design: Difficulty/boundary_precision_check/suspension_ledger_threshold_is_strictly_greater_and_crossed_by_one_cent
        """
        brand, first, _second = _penalty_ledger_fixture()

        reviewed = validate_success(
            api.marking_review(first["id"], dict(_DEFICIENT), CUSTOMS), 200)
        assert reviewed["penalty_assessed_usd"] == pytest.approx(25000.00, abs=0.01), (
            f"250000.00 at a 0.100 duty rate escalated by 1.00 assesses 25000.00, got "
            f"{reviewed['penalty_assessed_usd']}"
        )
        assert reviewed["assessment_basis"] == "AD_VALOREM"
        assert reviewed["marking_state"] == "REDELIVERY_ORDERED"

        row = read_brand(brand["id"])
        assert row["outstanding_penalty_usd"] == pytest.approx(25000.00, abs=0.01), (
            f"Expected a ledger of exactly 25000.00, got {row['outstanding_penalty_usd']}"
        )
        assert row["posture"] == "OPEN", (
            "a ledger of exactly 25,000.00 is not strictly greater than the "
            f"threshold, so the posture must stay OPEN, got {row['posture']}"
        )

    def test_one_cent_beyond_the_threshold_suspends_the_brand(self, api):
        """PRD 3.8: "Only after all of that does the entry enter the ledger, and the brand-of-record's `outstanding_penalty_usd` and `posture` are recomputed with this entry now included — which is how a single large assessment can drive a party to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/suspension_ledger_threshold_is_strictly_greater_and_crossed_by_one_cent
        """
        brand, first, second = _penalty_ledger_fixture()
        validate_success(api.marking_review(first["id"], dict(_DEFICIENT), CUSTOMS), 200)
        assert read_brand(brand["id"])["posture"] == "OPEN"

        reviewed = validate_success(
            api.marking_review(second["id"], dict(_DEFICIENT), CUSTOMS), 200)
        assert reviewed["posture_at_review"] == "OPEN", (
            "the posture is frozen excluding this entry, so it must still read OPEN, "
            f"got {reviewed['posture_at_review']}"
        )
        assert reviewed["penalty_assessed_usd"] == pytest.approx(0.01, abs=0.01), (
            f"0.10 at a 0.100 duty rate assesses 0.01, got "
            f"{reviewed['penalty_assessed_usd']}"
        )
        assert reviewed["assessment_basis"] == "AD_VALOREM", (
            "an OPEN frozen posture selects the ad valorem variant, got "
            f"{reviewed['assessment_basis']}"
        )

        row = read_brand(brand["id"])
        assert row["outstanding_penalty_usd"] == pytest.approx(25000.01, abs=0.01), (
            f"Expected the ledger to reach 25000.01, got {row['outstanding_penalty_usd']}"
        )
        assert row["posture"] == "SUSPENDED", (
            f"25000.01 is strictly greater than 25000.00, got {row['posture']}"
        )

    def test_both_candidate_figures_stand_beside_the_selected_basis(self, api):
        """PRD 3.8: "Fourth, the statutory alternative is computed. `penalty_statutory_usd` is the smaller of two figures: `quantity_units` multiplied by a per-unit penalty of USD 1.25, rounded half-up to 2 decimal places; and `declared_value_usd` multiplied by a statutory cap rate of 0.80, also rounded half-up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/suspension_ledger_threshold_is_strictly_greater_and_crossed_by_one_cent
        """
        brand, first, second = _penalty_ledger_fixture()

        big = validate_success(
            api.marking_review(first["id"], dict(_DEFICIENT), CUSTOMS), 200)
        assert big["penalty_ad_valorem_usd"] == pytest.approx(25000.00, abs=0.01)
        assert big["penalty_statutory_usd"] == pytest.approx(15000.00, abs=0.01), (
            "12000 units at 1.25 is 15000.00, below the 0.80 cap of 200000.00, got "
            f"{big['penalty_statutory_usd']}"
        )
        assert big["penalty_mitigated_usd"] == pytest.approx(0.00, abs=0.01)

        tiny = validate_success(
            api.marking_review(second["id"], dict(_DEFICIENT), CUSTOMS), 200)
        assert tiny["penalty_ad_valorem_usd"] == pytest.approx(0.01, abs=0.01)
        assert tiny["penalty_statutory_usd"] == pytest.approx(0.08, abs=0.01), (
            "the 0.80 cap on a declared value of 0.10 yields 0.08 and beats the 1.25 "
            f"per-unit figure, got {tiny['penalty_statutory_usd']}"
        )
        assert tiny["penalty_assessed_usd"] == pytest.approx(0.01, abs=0.01), (
            "AD_VALOREM is the basis for a non-suspended frozen posture, so the "
            f"assessed figure is the ad valorem one, got {tiny['penalty_assessed_usd']}"
        )


def _audit_severity_fixture():
    """One brand, two styles (the uniqueness rule forbids two live findings
    sharing audit, style and finding_code) and one open audit over the brand."""
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co")
    first_style = create_style(brand["id"], style_code="NL-C-01",
                              target_market_codes=["US"], net_weight_grams=320.0)
    second_style = create_style(brand["id"], style_code="NL-C-02",
                               target_market_codes=["US"], net_weight_grams=320.0)
    audit = open_audit(brand["id"])
    return brand, first_style, second_style, audit


class TestSeverityEscalationAndRestrictThresholdAreBothInclusive:
    """Two inclusive integer breakpoints meeting on the same audit."""

    def test_five_thousand_units_escalates_but_four_thousand_nine_hundred_ninety_nine_does_not(self, api):
        """PRD 3.9: "The breakpoint is inclusive: 4,999 affected units does not escalate, 5,000 does."

        Design: Difficulty/boundary_precision_check/severity_escalation_and_restrict_threshold_are_both_inclusive
        """
        _brand, first_style, second_style, audit = _audit_severity_fixture()

        below = validate_success(api.create_audit_finding(audit["id"], {
            "style_id": first_style["id"], "finding_code": "CARE_UNSUBSTANTIATED",
            "units_affected": 4999}, AUDITOR), 201)
        at = validate_success(api.create_audit_finding(audit["id"], {
            "style_id": second_style["id"], "finding_code": "CARE_UNSUBSTANTIATED",
            "units_affected": 5000}, AUDITOR), 201)

        assert below["severity"] == "MAJOR", (
            "CARE_UNSUBSTANTIATED bases at MAJOR and 4999 units does not escalate, "
            f"got {below['severity']}"
        )
        assert at["severity"] == "CRITICAL", (
            "5000 units escalates MAJOR by exactly one level to CRITICAL, got "
            f"{at['severity']}"
        )

    def test_brand_turns_restricted_at_exactly_three_critical_findings(self, api):
        """PRD 3.1: "otherwise, if there exists at least one compliance audit of this brand of record whose state is `IN_REVIEW` and whose critical-finding count is **at least** 3 — three critical findings is enough — the posture is `RESTRICTED`; otherwise it is `OPEN`."

        Design: Difficulty/boundary_precision_check/severity_escalation_and_restrict_threshold_are_both_inclusive
        """
        brand, first_style, second_style, audit = _audit_severity_fixture()
        raise_finding(audit["id"], first_style["id"],
                      finding_code="CARE_UNSUBSTANTIATED", units_affected=4999)

        observed = []
        for style_id, code in [(second_style["id"], "CARE_UNSUBSTANTIATED"),
                               (first_style["id"], "IDENTITY_MISSING"),
                               (first_style["id"], "PLACEMENT_NON_PERMANENT")]:
            created = validate_success(api.create_audit_finding(audit["id"], {
                "style_id": style_id, "finding_code": code,
                "units_affected": 5000}, AUDITOR), 201)
            assert created["severity"] == "CRITICAL", (
                f"{code} at 5000 units escalates to CRITICAL, got {created['severity']}"
            )
            row = read_brand(brand["id"])
            observed.append((row["critical_audit_finding_count"], row["posture"]))

        assert observed == [(1, "OPEN"), (2, "OPEN"), (3, "RESTRICTED")], (
            "the restriction predicate is inclusive at 3 critical findings, so the "
            f"first two criticals must leave the brand OPEN, got {observed}"
        )

    def test_rollup_counts_stay_invariant_across_the_four_findings(self, api):
        """PRD 3.9: "`units_in_scope` sums `units_affected` over **every** finding of the audit with no state filter at all, which is what makes it invariant under disposition, verification and reopening."

        Design: Difficulty/boundary_precision_check/severity_escalation_and_restrict_threshold_are_both_inclusive
        """
        brand, first_style, second_style, audit = _audit_severity_fixture()
        below = raise_finding(audit["id"], first_style["id"],
                             finding_code="CARE_UNSUBSTANTIATED", units_affected=4999)
        for style_id, code in [(second_style["id"], "CARE_UNSUBSTANTIATED"),
                               (first_style["id"], "IDENTITY_MISSING"),
                               (first_style["id"], "PLACEMENT_NON_PERMANENT")]:
            raise_finding(audit["id"], style_id, finding_code=code,
                          units_affected=5000)

        rolled = read_audit(audit["id"])
        assert rolled["state"] == "IN_REVIEW", (
            f"the first finding drives the audit to IN_REVIEW, got {rolled['state']}"
        )
        assert rolled["open_finding_count"] == 4, (
            f"all four findings are still OPEN, got {rolled['open_finding_count']}"
        )
        assert rolled["critical_finding_count"] == 3, (
            f"exactly the three escalated findings are CRITICAL, got "
            f"{rolled['critical_finding_count']}"
        )
        assert rolled["units_in_scope"] == 19999, (
            f"4999 + 5000 + 5000 + 5000 is 19999, got {rolled['units_in_scope']}"
        )
        assert read_finding(below["id"])["units_unresolved"] == 4999, (
            "an undispositioned finding keeps its whole affected total unresolved"
        )
        assert read_brand(brand["id"])["critical_audit_finding_count"] == 3, (
            "the brand sums the critical-finding counts of its audits"
        )
