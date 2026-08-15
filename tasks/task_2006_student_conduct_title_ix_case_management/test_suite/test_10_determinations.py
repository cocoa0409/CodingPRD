"""Determinations: severity variants, the sanction matrix, restitution, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    case_version,
    create_case,
    create_determination_draft,
    determination_payload,
    drive_case_to_deliberation,
    drive_case_to_issued,
    get_case,
    issue_determination,
    issue_payload,
    make_cast,
    make_coordinator_headers,
    make_decision_maker_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _deliberation_case(cast, categories):
    case = create_case(cast, categories=list(categories))
    drive_case_to_deliberation(case["id"], cast)
    return case


class TestSeverityVariants:
    def test_provisional_and_final_scores_diverge_on_mitigating(self, api):
        """PRD 2.9: "Under the PROVISIONAL variant — computed at
        determination-draft creation and stored as `provisional_severity_score` —
        the mitigating contribution is zero, because mitigations are unverified
        until issue. A consequence implementers must honor: for otherwise
        identical inputs, `provisional_severity_score` can be strictly greater
        than `final_severity_score`."

        Design: Difficulty/dual_variant_calc/sanction_severity_provisional_excludes_mitigating
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = _deliberation_case(cast, ("SEXUAL_ASSAULT",))
        # base 40 + 15*1 prior + 10*2 aggravating = 75 provisional.
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            aggravating_factor_count=2, mitigating_factor_count=2,
            prior_responsible_findings=1,
        )
        assert det["provisional_severity_score"] == 75, (
            "PROVISIONAL excludes mitigating: 40 + 15 + 20"
        )
        assert det["status"] == "DRAFT"

        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{"sanction_type": "SUSPENSION", "duration_days": 120}],
        )
        # FINAL includes mitigating: 75 - 5*2 = 65.
        assert issued["final_severity_score"] == 65
        assert issued["final_tier"] == "TIER_3", "65 lands in [50,74] although the provisional 75 would have been TIER_4"
        assert issued["status"] == "ISSUED"

    def test_final_tier_governed_by_final_score_not_provisional(self, api):
        """PRD 2.9: "**Tier bands** have inclusive lower bounds: a score from 0
        through 24 is `TIER_1`; 25 through 49 is `TIER_2`; 50 through 74 is
        `TIER_3`; 75 and above is `TIER_4`."
        PRD 2.9: "- `TIER_3` allows `PROBATION` from 91 to 365 days, `SUSPENSION`
        from 91 to 365 days, `RESTITUTION`, and `NO_CONTACT_CONTINUATION` from 1
        to 365 days."

        Design: Difficulty/dual_variant_calc/sanction_severity_provisional_excludes_mitigating
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = _deliberation_case(cast, ("SEXUAL_ASSAULT",))
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            aggravating_factor_count=2, mitigating_factor_count=2,
            prior_responsible_findings=1,
        )
        assert det["provisional_severity_score"] == 75
        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{"sanction_type": "SUSPENSION", "duration_days": 120}],
        )
        # The provisional 75 (would-be TIER_4) does not govern; the final 65
        # does, so TIER_3's SUSPENSION 120d is legal.
        assert issued["final_severity_score"] == 65
        assert issued["final_tier"] == "TIER_3"
        assert issued["provisional_severity_score"] == 75
        sanctions, _ = validate_paginated(
            api.list_determination_sanctions(
                det["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert len(sanctions) == 1
        assert sanctions[0]["sanction_type"] == "SUSPENSION"
        assert sanctions[0]["duration_days"] == 120
        assert sanctions[0]["status"] == "ACTIVE"


class TestSanctionMatrixBoundary:
    def _tier3_boundary_draft(self, cast):
        """STALKING case in DELIBERATION; draft prior=1, agg=1, mit=1.

        Provisional: 30 + 15 + 10 = 55. Final: 55 - 5 = 50 (TIER_3 lower bound).
        """
        case = _deliberation_case(cast, ("STALKING",))
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            aggravating_factor_count=1, mitigating_factor_count=1,
            prior_responsible_findings=1, rationale="Stalking established",
        )
        return case, det

    def test_matrix_rejects_below_tier_floor_then_accepts_at_floor(self, api):
        """PRD 2.9: "A selection whose type is not offered by the final tier, or
        whose `duration_days` falls outside the tier's inclusive bounds for that
        type, is rejected with `ERR_SANCTION_OUTSIDE_MATRIX` (422)."
        PRD 2.9: "- `TIER_3` allows `PROBATION` from 91 to 365 days, `SUSPENSION`
        from 91 to 365 days, `RESTITUTION`, and `NO_CONTACT_CONTINUATION` from 1
        to 365 days."

        Design: Difficulty/combinatorial_formula/sanction_matrix_tier_boundary_mode_a
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, det = self._tier3_boundary_draft(cast)
        dm_h = make_decision_maker_headers(cast["dm"]["id"])

        # PROBATION 30d is legal in TIER_2 but below the TIER_3 floor of 91.
        rejected = api.issue_determination(
            det["id"], issue_payload([{"sanction_type": "PROBATION", "duration_days": 30}]), dm_h
        )
        validate_error(rejected, ApiErrorId.ERR_SANCTION_OUTSIDE_MATRIX)
        still_draft = validate_success(
            api.get_determination(det["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert still_draft["status"] == "DRAFT", "no partial issue on rejection"

        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{"sanction_type": "SUSPENSION", "duration_days": 91}],
        )
        assert issued["status"] == "ISSUED"
        assert issued["final_severity_score"] == 50
        assert issued["final_tier"] == "TIER_3"

    def test_matrix_boundary_provisional_and_final_arithmetic(self, api):
        """PRD 2.9: "**Tier bands** have inclusive lower bounds: a score from 0
        through 24 is `TIER_1`; 25 through 49 is `TIER_2`; 50 through 74 is
        `TIER_3`; 75 and above is `TIER_4`."
        PRD 2.9: "Under the PROVISIONAL variant — computed at determination-draft
        creation and stored as `provisional_severity_score` — the mitigating
        contribution is zero, because mitigations are unverified until issue."

        Design: Difficulty/combinatorial_formula/sanction_matrix_tier_boundary_mode_a
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, det = self._tier3_boundary_draft(cast)
        # 30 base + 15 prior + 10 aggravating, mitigating excluded at draft.
        assert det["provisional_severity_score"] == 55

        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{"sanction_type": "SUSPENSION", "duration_days": 91}],
        )
        # 55 - 5 mitigating = 50, the inclusive TIER_3 lower bound.
        assert issued["final_severity_score"] == 50
        assert issued["final_tier"] == "TIER_3", "50 is the inclusive lower bound of [50,74]"


class TestRestitutionPinnedOrder:
    def _restitution_draft(self, cast):
        """SEXUAL_ASSAULT case in DELIBERATION; draft prior=1 -> matrix 55."""
        case = _deliberation_case(cast, ("SEXUAL_ASSAULT",))
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            aggravating_factor_count=0, mitigating_factor_count=0,
            prior_responsible_findings=1, rationale="Assault established",
        )
        return case, det

    def test_restitution_capped_at_cap_tier_before_points_move_tier(self, api):
        """PRD 2.9: "Step 3: determine the **cap tier** from the matrix score
        alone, without restitution points, and look up the restitution cap:
        `TIER_1` 0 cents, `TIER_2` 0 cents, `TIER_3` 50,000 cents (500 dollars),
        `TIER_4` 250,000 cents (2,500 dollars). Step 4: the sanction's
        `applied_restitution_cents` is the smaller of the summed cents and the
        cap".
        PRD 2.9: "Two consequences are deliberate: the restitution cap remains
        the cap-tier cap from step 3 even when `final_tier` lands above the cap
        tier, and `applied_restitution_cents` is zero for every non-`RESTITUTION`
        sanction."

        Design: Difficulty/combinatorial_formula/restitution_pinned_evaluation_order_mode_c
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, det = self._restitution_draft(cast)
        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{
                "sanction_type": "RESTITUTION",
                "restitution_items": [
                    {"description": "Laptop repair", "amount_dollars": 300.00},
                    {"description": "Medical copay", "amount_dollars": 250.00},
                ],
            }],
        )
        assert issued["final_severity_score"] == 55, "matrix score excludes restitution points"
        # Items 30000 + 25000 = 55000 cents, clamped to the TIER_3 cap 50000 —
        # not the TIER_4 cap 250000, because the cap is fixed before points land.
        # 500 restitution points push the total to 555, so final_tier is TIER_4.
        assert issued["final_tier"] == "TIER_4"

        sanctions, _ = validate_paginated(
            api.list_determination_sanctions(
                det["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert len(sanctions) == 1
        assert sanctions[0]["sanction_type"] == "RESTITUTION"
        assert sanctions[0]["applied_restitution_cents"] == 50000

    def test_restitution_points_move_final_tier_above_cap_tier(self, api):
        """PRD 2.9: "Step 5: restitution points are the applied cents divided by
        100 (one point per full dollar) rounded down to a whole number. Step 6:
        total points are the matrix score plus the restitution points. Step 7:
        `final_tier` is the tier band of that total, and it governs the duration
        bounds for *all* sanction selections on the determination."

        Design: Difficulty/combinatorial_formula/restitution_pinned_evaluation_order_mode_c
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, det = self._restitution_draft(cast)
        issued = issue_determination(
            det["id"], cast["dm"]["id"],
            [{
                "sanction_type": "RESTITUTION",
                "restitution_items": [
                    {"description": "Laptop repair", "amount_dollars": 300.00},
                    {"description": "Medical copay", "amount_dollars": 250.00},
                ],
            }],
        )
        # matrix 55 + floor(50000/100) = 500 points -> total 555 -> TIER_4.
        assert issued["final_severity_score"] == 55
        assert issued["final_tier"] == "TIER_4"
        sanctions, _ = validate_paginated(
            api.list_determination_sanctions(
                det["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert sanctions[0]["applied_restitution_cents"] == 50000
        assert sanctions[0]["status"] == "ACTIVE"


class TestStandardOfEvidencePin:
    def test_issue_standard_of_evidence_mismatch_rejected(self, api):
        """PRD 3.5: "the payload's `standard_of_evidence` equals the case's
        intake-pinned `standard_of_evidence` — a mismatch is
        `ERR_STANDARD_OF_EVIDENCE_MISMATCH` (422), because the same standard must
        apply to both parties".
        PRD 3.1: "That standard is **pinned at intake and immutable** for the
        life of the case, and the same standard applies to both parties."

        Design: Corner/calculations/issue_standard_of_evidence_mismatch_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = create_case(
            cast, categories=["OTHER_SEX_BASED"], received_via="EMAIL",
            standard_of_evidence="CLEAR_AND_CONVINCING",
        )
        drive_case_to_deliberation(case["id"], cast)
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            standard_of_evidence="PREPONDERANCE", rationale="Wrong standard",
        )

        resp = api.issue_determination(
            det["id"], issue_payload([{"sanction_type": "WARNING"}]),
            make_decision_maker_headers(cast["dm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STANDARD_OF_EVIDENCE_MISMATCH)

        coord_h = make_coordinator_headers(cast["coord"]["id"])
        still = validate_success(api.get_determination(det["id"], coord_h))
        assert still["status"] == "DRAFT"
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "DELIBERATION"
        sanctions, meta = validate_paginated(api.list_determination_sanctions(det["id"], coord_h))
        assert sanctions == [] and meta["total_count"] == 0


class TestDraftAuthorship:
    def test_determination_draft_by_non_decision_maker_rejected(self, api):
        """PRD 3.5: "Only the decision-maker of the case's completed hearing may
        draft or issue; anyone else is `ERR_NOT_HEARING_DECISION_MAKER`."
        PRD 3.4: "The decision-maker — and only that person; anyone else is
        rejected with `ERR_NOT_HEARING_DECISION_MAKER` (422)".

        Design: Corner/validations/determination_draft_by_non_decision_maker_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "dm2", "advc", "advr")
        case = _deliberation_case(cast, ("OTHER_SEX_BASED",))
        version = case_version(case["id"], cast["coord"]["id"])
        # dm2 carries the DecisionMaker role but is not this hearing's
        # decision-maker: identity binding fails, not the role check.
        resp = api.create_determination(
            case["id"],
            determination_payload(version, rationale="Interloper draft"),
            make_decision_maker_headers(cast["dm2"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_HEARING_DECISION_MAKER)

        dets, meta = validate_paginated(
            api.list_case_determinations(case["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert dets == [] and meta["total_count"] == 0


class TestRestitutionItemsGate:
    def test_restitution_without_items_rejected(self, api):
        """PRD 3.5: "Restitution selections additionally require a non-empty
        `restitution_items` array whose every item carries a `description` and an
        `amount_dollars` strictly greater than zero, failing as
        `ERR_RESTITUTION_ITEMS_REQUIRED` (422)".

        Design: Corner/validations/restitution_without_items_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = _deliberation_case(cast, ("SEXUAL_ASSAULT",))
        det = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            prior_responsible_findings=1,
        )
        # The tier (TIER_3 at matrix 55) would allow restitution, but the fiscal
        # gate is separate: no items, no issue.
        resp = api.issue_determination(
            det["id"], issue_payload([{"sanction_type": "RESTITUTION"}]),
            make_decision_maker_headers(cast["dm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESTITUTION_ITEMS_REQUIRED)
        still = validate_success(
            api.get_determination(det["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert still["status"] == "DRAFT"


class TestIssuedReadback:
    def test_determination_and_sanction_readback_after_issue(self, api):
        """PRD 3.5: "The determination itself moves `DRAFT → ISSUED`, stamps
        `issued_at` from the logical clock, computes `appeal_deadline` as
        `issued_at` plus the 5-day appeal window (filings at exactly that instant
        are timely), and records `issued_by_id` as the decision-maker taken from
        the completed hearing."
        PRD 3.5: "Each selection becomes a `Sanction` row in `ACTIVE` status,
        bound to the issuing determination through `determination_id`, with
        `effective_from` equal to the determination's `issued_at` and
        `applied_restitution_cents` zero for non-restitution types."
        PRD 2.9: "**Tier bands** have inclusive lower bounds: a score from 0
        through 24 is `TIER_1`".

        Design: Corner/endpoints/determination_and_sanction_readback_after_issue
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = create_case(cast, categories=["OTHER_SEX_BASED"], received_via="EMAIL")
        stage = drive_case_to_issued(case["id"], cast)
        det = stage["determination"]
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        reread = validate_success(api.get_determination(det["id"], coord_h))
        assert reread["status"] == "ISSUED"
        # OTHER_SEX_BASED base 15, all factor counts zero: final score 15.
        assert reread["final_severity_score"] == 15
        assert reread["final_tier"] == "TIER_1"
        # Issued at the hearing instant 2026-09-01T10:00:00Z; deadline is +5d.
        assert_instant_equals(reread["issued_at"], "2026-09-01T10:00:00Z", "issued_at")
        assert_instant_equals(
            reread["appeal_deadline"], "2026-09-06T10:00:00Z", "appeal_deadline"
        )
        assert reread["issued_by_id"] == cast["dm"]["id"]

        sanctions, meta = validate_paginated(api.list_determination_sanctions(det["id"], coord_h))
        assert meta["total_count"] == 1
        sanction = sanctions[0]
        assert sanction["sanction_type"] == "WARNING"
        assert sanction["status"] == "ACTIVE"
        assert sanction.get("duration_days") is None, "WARNING is a duration-less type"
        assert sanction["applied_restitution_cents"] == 0
        assert_instant_equals(sanction["effective_from"], "2026-09-01T10:00:00Z", "effective_from")


class TestDeterminationCreateOcc:
    def test_occ_determination_create_stale_version_and_draft_supersede(self, api):
        """PRD 2.10: "- **Creating a determination draft** legitimately supersedes
        an existing `DRAFT`, and on a remanded case continues a lineage whose
        prior determinations were superseded by the remand (§3.5); a writer
        working from a pre-remand view of the case must restart from the current
        version."
        PRD 2.10: "the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP
        412), forcing the client to re-read the case before writing."
        PRD 3.5: "A case holds at most one draft at a time by supersession:
        creating a new `DRAFT` moves any existing `DRAFT` on the case to
        `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/occ_determination_create_stale_version_and_draft_supersede
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case = _deliberation_case(cast, ("OTHER_SEX_BASED",))
        observed = case_version(case["id"], cast["coord"]["id"])
        dm_h = make_decision_maker_headers(cast["dm"]["id"])
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        first = validate_success(
            api.create_determination(
                case["id"], determination_payload(observed, rationale="Draft one"), dm_h
            ),
            201,
        )
        # Same observed version: the first create already advanced the case.
        stale = api.create_determination(
            case["id"], determination_payload(observed, rationale="Draft two stale"), dm_h
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CASE_VERSION)

        fresh = case_version(case["id"], cast["coord"]["id"])
        second = validate_success(
            api.create_determination(
                case["id"],
                determination_payload(
                    fresh, responsibility_finding="NOT_RESPONSIBLE",
                    rationale="Draft two fresh",
                ),
                dm_h,
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        superseded = validate_success(api.get_determination(first["id"], coord_h))
        assert superseded["status"] == "SUPERSEDED", (
            "create-with-supersede applied to the winner's retry"
        )
