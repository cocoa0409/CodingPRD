"""Center assignment selector: gated scoring, tie-breaks, empty pool, OCC."""
import pytest

from test_helpers import (
    ADMIN,
    COUNSELOR,
    ApiErrorId,
    api_client,
    assign_applicant,
    center_assignment_payload,
    create_center,
    create_trade_program,
    get_applicant,
    make_eligible_applicant,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_four_centers():
    """A: R-NORTH 4 beds WELDING cap 3 (score 4.70); B: R-NORTH 20 beds
    WELDING cap 8 (score 9.00); C: R-SOUTH 50 beds WELDING cap 10 (score 8.00);
    D: R-NORTH 100 beds with its only WELDING program CLOSED (gated out)."""
    center_a = create_center(name="Center A", region_code="R-NORTH", total_beds=4)
    create_trade_program(center_a["id"], trade_code="WELDING", capacity=3)
    center_b = create_center(name="Center B", region_code="R-NORTH", total_beds=20)
    create_trade_program(center_b["id"], trade_code="WELDING", capacity=8)
    center_c = create_center(name="Center C", region_code="R-SOUTH", total_beds=50)
    create_trade_program(center_c["id"], trade_code="WELDING", capacity=10)
    center_d = create_center(name="Center D", region_code="R-NORTH", total_beds=100)
    program_d = create_trade_program(center_d["id"], trade_code="WELDING",
                                     capacity=40)
    close_resp = api_client.patch_trade_program(
        program_d["id"], {"status": "CLOSED"}, ADMIN
    )
    validate_success(close_resp, 200)
    return center_a, center_b, center_c, center_d


class TestGatedWeightedRanking:
    def test_same_region_center_beats_larger_raw_pools(self):
        """PRD section 3.2: "The score is the trade component weighted by 0.5,
        plus the capacity component weighted by 0.3, plus the geographic
        component weighted by 0.2 — that is, one-half of the trade component,
        three-tenths of the capacity component, and one-fifth of the geographic
        component summed together — rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/center_ranking_multi_input_gated_scoring
        """
        _a, center_b, _c, _d = _setup_four_centers()
        applicant, _case = make_eligible_applicant(full_name="Rank Stu")
        result = assign_applicant(applicant, residential_track=False)
        assert result["assignment_status"] == "ASSIGNED"
        assert result["assigned_center_id"] == center_b["id"], (
            "B (9.00) must beat C (8.00) and A (4.70)"
        )
        assert result["assigned_center_score"] == pytest.approx(9.0)

    def test_closed_program_center_is_gated_out_of_candidate_list(self):
        """PRD section 3.2: "A center qualifies only when it operates at least
        one trade program whose trade_code equals the applicant's
        desired_trade_code, whose status is OPEN, and whose open_seats is at
        least 1".

        Design: Difficulty/combinatorial_formula/center_ranking_multi_input_gated_scoring
        """
        _setup_four_centers()
        applicant, _case = make_eligible_applicant(full_name="Rank Stu")
        result = assign_applicant(applicant, residential_track=False)
        ranked = result["ranked_candidates"]
        assert isinstance(ranked, list)
        assert len(ranked) == 3, (
            "exactly the three qualifying centers are ranked; the center whose "
            "only matching program is CLOSED is absent"
        )


class TestEmptyPool:
    def test_no_eligible_center_returns_422(self):
        """PRD section 3.2: "An empty pool is rejected with
        ERR_NO_ELIGIBLE_CENTER."

        Design: Corner/errors/no_eligible_center_pool_returns_422
        """
        center = create_center(name="Pool Center", total_beds=4)
        create_trade_program(center["id"], trade_code="WELDING", capacity=3)
        applicant, _case = make_eligible_applicant(
            full_name="Pool Stu", desired_trade_code="CARPENTRY"
        )
        fresh = get_applicant(applicant["id"])
        resp = api_client.assign_center(
            applicant["id"],
            center_assignment_payload(fresh["version"], residential_track=False),
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CENTER)
        assert get_applicant(applicant["id"])["assignment_status"] == "NONE"


class TestAssignmentOcc:
    def test_stale_reassignment_rejected_412(self):
        """PRD section 2.6: "If the applicant's current version has advanced
        beyond that observed value — because, for instance, another counselor
        filed a case or ran an assignment in the meantime — the write is
        rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_center_assignment_returns_412
        """
        center = create_center(name="Occ Center", total_beds=4)
        create_trade_program(center["id"], trade_code="WELDING", capacity=3)
        applicant, _case = make_eligible_applicant(full_name="Occ Asg")
        fresh = get_applicant(applicant["id"])
        first = api_client.assign_center(
            applicant["id"],
            center_assignment_payload(fresh["version"], residential_track=False),
            COUNSELOR,
        )
        assert validate_success(first)["assignment_status"] == "ASSIGNED"
        resp = api_client.assign_center(
            applicant["id"],
            center_assignment_payload(fresh["version"], residential_track=False),
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_fresh_reassignment_is_legitimate_supersede(self):
        """PRD section 3.2: "Running assignment again while the applicant is
        ASSIGNED is a legitimate supersede — the new winner overwrites the old
        and the version advances again".

        Design: Corner/cross_cutting_layers/occ_stale_center_assignment_returns_412
        """
        center = create_center(name="Occ Center", total_beds=4)
        create_trade_program(center["id"], trade_code="WELDING", capacity=3)
        applicant, _case = make_eligible_applicant(full_name="Occ Asg")
        first = assign_applicant(applicant, residential_track=False)
        assert first["assignment_status"] == "ASSIGNED"
        version_after_first = get_applicant(applicant["id"])["version"]
        second = api_client.assign_center(
            applicant["id"],
            center_assignment_payload(version_after_first,
                                      residential_track=False),
            COUNSELOR,
        )
        assert validate_success(second)["assignment_status"] == "ASSIGNED"
        assert (
            get_applicant(applicant["id"])["version"] == version_after_first + 1
        ), "a successful supersede advances the applicant version by exactly 1"


class TestCreatedAtTieBreak:
    def test_identical_scores_fall_to_earlier_created_center(self):
        """PRD section 3.2: "Candidates are ranked by score descending; ties
        fall to beds_available descending; remaining ties fall to the center's
        created_at ascending — never to the center's id."

        Design: Corner/cross_cutting_layers/center_ranking_tie_break_created_at
        """
        set_clock("2026-09-01T00:00:00Z")
        tie_one = create_center(name="Tie One", region_code="R-NORTH",
                                total_beds=4)
        create_trade_program(tie_one["id"], trade_code="WELDING", capacity=3)
        # Advance the logical clock one second so the two centers cannot share
        # a created_at reading under any conforming clock implementation.
        set_clock("2026-09-01T00:00:01Z")
        tie_two = create_center(name="Tie Two", region_code="R-NORTH",
                                total_beds=4)
        create_trade_program(tie_two["id"], trade_code="WELDING", capacity=3)
        applicant, _case = make_eligible_applicant(full_name="Tie Stu")
        result = assign_applicant(applicant, residential_track=False)
        assert result["assigned_center_id"] == tie_one["id"], (
            "score and beds_available tied at 4.70/4; created_at ascending "
            "must pick the earlier-created center"
        )
        assert result["assigned_center_score"] == pytest.approx(4.7)


class TestApplicantListFilter:
    def test_filter_by_assigned_center_id(self):
        """PRD section 3.1: "Applicants can be listed with optional
        assigned_center_id and assignment_status filters".

        Design: Corner/state_machines/applicant_list_filters_by_assignment
        """
        center_a = create_center(name="Flt A", region_code="R-NORTH",
                                 total_beds=9)
        create_trade_program(center_a["id"], trade_code="WELDING", capacity=3)
        center_b = create_center(name="Flt B", region_code="R-SOUTH",
                                 total_beds=9)
        create_trade_program(center_b["id"], trade_code="CARPENTRY", capacity=3)
        applicant_one, _ = make_eligible_applicant(full_name="Flt One")
        result_one = assign_applicant(applicant_one, residential_track=False)
        assert result_one["assigned_center_id"] == center_a["id"]
        applicant_two, _ = make_eligible_applicant(
            full_name="Flt Two", home_region_code="R-SOUTH",
            desired_trade_code="CARPENTRY",
        )
        result_two = assign_applicant(applicant_two, residential_track=False)
        assert result_two["assigned_center_id"] == center_b["id"]
        rows = validate_success(
            api_client.list_applicants(
                ADMIN, params={"assigned_center_id": center_a["id"]}
            )
        )
        assert [row["id"] for row in rows] == [applicant_one["id"]]
