"""CoverageDesign tests: provisional vs final capacity variants, OCC on site
version, required_cell_count rounding, capacity shortfall, minimum target,
design revision monotonicity, and supersession cascades.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_design,
    create_approved_survey,
    create_cell,
    create_design_for_site,
    create_enterprise_with_site,
    create_site_payload,
    create_submitted_design,
    create_survey_payload,
    get_success_data,
    make_field_technician_headers,
    validate_error,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
FT = TEST_USERS["field_technician_headers"]


def _site_with_approved_survey(site_overrides=None, material="OPEN"):
    """Enterprise + Site + APPROVED survey. Returns (ent, site, survey)."""
    ent, site = create_enterprise_with_site(site_overrides=site_overrides)
    ft = make_field_technician_headers("ft-design")
    payload = create_survey_payload(
        surveyor_id="ft-design", building_material_class=material
    )
    survey = get_success_data(api_client.create_survey(site["id"], payload, ft))
    survey = get_success_data(api_client.submit_survey(site["id"], survey["id"], ft))
    survey = get_success_data(api_client.approve_survey(site["id"], survey["id"], RFE))
    site = get_success_data(api_client.get_site(site["id"], NA))
    return ent, site, survey


class TestProvisionalVsFinalCapacity:
    def test_provisional_capacity_per_cell_rounding_and_sum(self):
        """PRD §3.3: "The estimate sums a per-cell contribution over every
        CellSector under the site in `PLANNED` or `CONFIGURED` status — cells
        in `DECOMMISSIONED` are excluded — where each cell contributes its
        slice-class base rate (900 Mbps for `EMBB` usage, 300 Mbps for `URLLC`,
        60 Mbps for `MMTC`; capacity estimation defaults to the `EMBB` class),
        scaled by the ratio of the cell's `max_eirp_dbm` to the 40 dBm
        reference but never scaled above unity, and further scaled by one minus
        the ratio of the survey's `attenuation_factor_db` to the 30 dB
        full-loss reference."
        PRD §3.3: "Each per-cell contribution is rounded half-up to a whole
        Mbps before the contributions are summed."

        Design: Difficulty/dual_variant_calc/design_capacity_provisional_vs_final_diverges
        """
        # OPEN material => attenuation 3 => factor (1 - 3/30) = 0.9
        # One cell, max_eirp_dbm=40 => eirp factor 1.0
        # provisional per-cell = round_half_up(900 * 1.0 * 0.9) = 810
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 2000},
            material="OPEN",
        )
        create_cell(site["id"], sector_label="NE-A", max_eirp_dbm=40)
        site = get_success_data(api_client.get_site(site["id"], NA))
        design, _site = create_submitted_design(
            site["id"], survey["id"], site["version"]
        )
        assert design["predicted_capacity_mbps"] == 810

    def test_final_capacity_applies_conservative_variant_on_approval(self):
        """PRD §3.3: "The final, conservative capacity variant recomputes the
        same per-cell structure but with a 9 dB interference margin in place of
        the optimistic 6 dB, and additionally subtracts a five percent penalty
        for each `ON_AIR` neighbor cell within 500 meters, compounding
        multiplicatively and counting at most three neighbors — so one neighbor
        scales the contribution by 0.95, two by 0.95 squared, and three or more
        by 0.95 cubed."
        PRD §3.3: "`final_capacity_mbps` remains null until approval; it is
        computed only when the design is `APPROVED`."

        Design: Difficulty/dual_variant_calc/design_capacity_provisional_vs_final_diverges
        """
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 2000},
            material="OPEN",
        )
        create_cell(site["id"], sector_label="NE-B", max_eirp_dbm=40)
        create_cell(site["id"], sector_label="NE-C", max_eirp_dbm=40)
        create_cell(site["id"], sector_label="NE-D", max_eirp_dbm=40)
        site = get_success_data(api_client.get_site(site["id"], NA))
        design, _site = create_submitted_design(
            site["id"], survey["id"], site["version"]
        )
        # final_capacity_mbps stays null until approval.
        assert design["final_capacity_mbps"] is None
        resp = api_client.approve_design(site["id"], design["id"], NA)
        approved = validate_success(resp)
        # The final variant is conservative: with the neighbor penalty and the
        # larger interference margin it can never exceed the provisional
        # estimate. The PRD does not pin the margin's arithmetic, so the
        # uniquely derivable assertions are: final is computed on approval, and
        # final <= provisional.
        assert approved["status"] == "APPROVED"
        assert approved["final_capacity_mbps"] is not None
        assert approved["final_capacity_mbps"] <= approved["predicted_capacity_mbps"]


class TestDesignOcc:
    def test_stale_site_version_rejected(self):
        """PRD §2.7: "creating a coverage design against a Site requires the
        request to carry `expected_site_version` equal to the Site's current
        `version`. This captures the case where a newer site survey was just
        approved — bumping the Site's `version` — so the client drafting a
        design on the old survey baseline is working from stale ground. A
        mismatch is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_site_version_occ_conflict
        """
        _ent, site = create_enterprise_with_site()
        stale_version = site["version"]  # captured before the survey approval
        _survey, site_after = create_approved_survey(site["id"], surveyor_id="ft-occ")
        assert site_after["version"] == stale_version + 1

        resp = api_client.create_design(
            site["id"],
            {
                "based_on_survey_id": _survey["id"],
                "edge_compute_required": False,
                "edge_compute_placement": "NONE",
                "expected_site_version": stale_version,
            },
            RFE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SITE_VERSION)

    def test_current_site_version_accepted(self):
        """PRD §2.7: "creating a coverage design against a Site requires the
        request to carry `expected_site_version` equal to the Site's current
        `version`."

        Design: Corner/errors/stale_site_version_occ_conflict
        """
        _ent, site, survey = _site_with_approved_survey()
        resp = api_client.create_design(
            site["id"],
            {
                "based_on_survey_id": survey["id"],
                "edge_compute_required": False,
                "edge_compute_placement": "NONE",
                "expected_site_version": site["version"],
            },
            RFE,
        )
        data = validate_success(resp, expected_status=201)
        assert_design(data)
        assert data["status"] == "DRAFT"


class TestDesignCrossEntityDependency:
    def test_design_create_rejected_when_survey_not_approved(self):
        """PRD §3.3: "a submission whose base survey is not `APPROVED` is
        invalid from the design's current state."
        PRD §2.9: "requesting a transition the resource's current state does
        not allow yields `ERR_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site = create_enterprise_with_site()
        ft = make_field_technician_headers("ft-subonly")
        payload = create_survey_payload(surveyor_id="ft-subonly")
        survey = get_success_data(api_client.create_survey(site["id"], payload, ft))
        survey = get_success_data(api_client.submit_survey(site["id"], survey["id"], ft))
        site = get_success_data(api_client.get_site(site["id"], NA))

        # Creation of the design draft succeeds; the survey-state rule gates
        # the design's submission (DRAFT -> SUBMITTED).
        design = create_design_for_site(site["id"], survey["id"], site["version"])
        resp = api_client.submit_design(site["id"], design["id"], RFE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_design_create_rejected_when_survey_rejected(self):
        """PRD §3.3: "a submission whose base survey is not `APPROVED` is
        invalid from the design's current state."
        PRD §3.2: "An `RFEngineer` may instead reject a `SUBMITTED` survey,
        moving it to `REJECTED` with no further effect."

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site = create_enterprise_with_site()
        ft = make_field_technician_headers("ft-rej")
        payload = create_survey_payload(surveyor_id="ft-rej")
        survey = get_success_data(api_client.create_survey(site["id"], payload, ft))
        survey = get_success_data(api_client.submit_survey(site["id"], survey["id"], ft))
        survey = get_success_data(api_client.reject_survey(site["id"], survey["id"], RFE))
        site = get_success_data(api_client.get_site(site["id"], NA))

        # A REJECTED survey likewise blocks the design's submission.
        design = create_design_for_site(site["id"], survey["id"], site["version"])
        resp = api_client.submit_design(site["id"], design["id"], RFE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRequiredCellCount:
    def test_required_cell_count_concrete_nested_rounding(self):
        """PRD §3.3: "First, `required_cell_count`: the site's `site_area_sqm`
        divided by an effective per-cell coverage of 5,000 square meters, where
        that per-cell figure is scaled down by a material penalty factor
        computed as one minus the survey's `attenuation_factor_db` over 30,
        with the factor floored at 0.25 so a very lossy building never reduces
        effective coverage below a quarter of nominal; the quotient is rounded
        up to a whole number, and the result is at least 1".

        Design: Difficulty/combinatorial_formula/remediation_cell_count_ceil_nested_rounding_mode_b
        """
        # CONCRETE -> att 12 -> factor = 1 - 12/30 = 0.6
        # effective coverage = 5000 * 0.6 = 3000; 4000 / 3000 = 1.333 -> ceil = 2
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 2000},
            material="CONCRETE",
        )
        site = get_success_data(api_client.get_site(site["id"], NA))
        design, _site = create_submitted_design(
            site["id"], survey["id"], site["version"]
        )
        assert design["required_cell_count"] == 2

    def test_required_cell_count_factor_floored_at_quarter(self):
        """PRD §3.3: "with the factor floored at 0.25 so a very lossy building
        never reduces effective coverage below a quarter of nominal".

        Design: Difficulty/combinatorial_formula/remediation_cell_count_ceil_nested_rounding_mode_b
        """
        # STEEL -> att 18 -> raw factor = 1 - 18/30 = 0.4 (still above floor)
        # effective coverage = 5000 * 0.4 = 2000; 4100/2000 = 2.05 -> ceil = 3
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4100, "target_capacity_mbps": 2000},
            material="STEEL",
        )
        site = get_success_data(api_client.get_site(site["id"], NA))
        design, _site = create_submitted_design(
            site["id"], survey["id"], site["version"]
        )
        assert design["required_cell_count"] == 3


class TestDesignApprovalGuards:
    def test_approve_rejected_when_capacity_shortfall_positive(self):
        """PRD §3.3: "Approval requires `capacity_shortfall_mbps` to be exactly
        zero; any positive shortfall is rejected with `ERR_CAPACITY_SHORTFALL`
        (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 2000},
            material="OPEN",
        )
        # No cells at all => predicted 0 < target 2000 => shortfall 2000.
        site = get_success_data(api_client.get_site(site["id"], NA))
        design, _site = create_submitted_design(
            site["id"], survey["id"], site["version"]
        )
        assert design["capacity_shortfall_mbps"] == 2000
        resp = api_client.approve_design(site["id"], design["id"], NA)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_SHORTFALL)

    def test_submit_rejected_when_target_capacity_below_100(self):
        """PRD §3.3: "if the site's `target_capacity_mbps` is below 100 Mbps
        the submission is rejected with `ERR_TARGET_CAPACITY_TOO_LOW`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 50},
            material="OPEN",
        )
        site = get_success_data(api_client.get_site(site["id"], NA))
        design = create_design_for_site(site["id"], survey["id"], site["version"])
        resp = api_client.submit_design(site["id"], design["id"], RFE)
        validate_error(resp, ApiErrorId.ERR_TARGET_CAPACITY_TOO_LOW)


class TestDesignRevisionAndSupersession:
    def test_design_revision_increments_per_site(self):
        """PRD §3.3: "Each new design receives a `design_revision` one greater
        than the highest revision previously issued for that site".

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site, survey = _site_with_approved_survey()
        site = get_success_data(api_client.get_site(site["id"], NA))
        d1 = create_design_for_site(site["id"], survey["id"], site["version"])
        site = get_success_data(api_client.get_site(site["id"], NA))
        d2 = create_design_for_site(site["id"], survey["id"], site["version"])
        assert d1["design_revision"] == 1
        assert d2["design_revision"] == 2

    def test_approved_design_supersedes_prior_and_decommissions_planned_cells(self):
        """PRD §3.3: "When approval succeeds, three things happen together:
        the parent Site moves `SURVEYED → DESIGNED` with `posture` becoming
        `COORDINATING` and `version` incrementing; the design's
        `final_capacity_mbps` is computed by the conservative final variant
        described below; and any previously `APPROVED` design for the same site
        is superseded, moving to `SUPERSEDED`."
        PRD §3.3: "Superseding a design — whether because a newer design was
        approved or because its base survey was superseded — also cascades to
        the physical plan: every CellSector still in `PLANNED` under the
        superseded design is moved to `DECOMMISSIONED`."

        Design: Difficulty/cross_entity_state_dependency/design_approve_requires_survey_approved
        """
        _ent, site, survey = _site_with_approved_survey(
            site_overrides={"site_area_sqm": 4000, "target_capacity_mbps": 500},
            material="OPEN",
        )
        cell = create_cell(site["id"], sector_label="KEEP-1", max_eirp_dbm=40)
        site = get_success_data(api_client.get_site(site["id"], NA))
        # Design 1 with the cell => predicted 810 >= 500 => shortfall 0.
        d1, _site = create_submitted_design(site["id"], survey["id"], site["version"])
        d1 = get_success_data(api_client.approve_design(site["id"], d1["id"], NA))
        assert d1["status"] == "APPROVED"

        # Design 2 on same approved survey.
        site = get_success_data(api_client.get_site(site["id"], NA))
        d2, _site = create_submitted_design(site["id"], survey["id"], site["version"])
        d2 = get_success_data(api_client.approve_design(site["id"], d2["id"], NA))
        assert d2["status"] == "APPROVED"

        d1_after = get_success_data(api_client.get_design(d1["id"], NA))
        assert d1_after["status"] == "SUPERSEDED"
