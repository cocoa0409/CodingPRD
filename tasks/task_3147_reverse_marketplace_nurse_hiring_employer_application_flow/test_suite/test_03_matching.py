"""Candidate matching: score arithmetic, suppressed rows, regeneration, ranking."""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


def _gen_and_list(requisition, employer, headers=None, params=None):
    fx_resp = api_client.generate_matches(requisition["id"], headers or make_employer_headers(employer["id"]))
    validate_success(fx_resp)
    rows, _ = validate_paginated(
        api_client.list_requisition_matches(
            requisition["id"], headers or make_employer_headers(employer["id"]), params=params
        )
    )
    return rows


class TestMatchScoreCombinatorics:
    def test_match_score_multi_input_nonlinear(self, api):
        """PRD §3.3: "Geography contributes 40 points when the nurse's `home_state` equals the requisition's `facility_state`, otherwise nothing. Experience contributes 25 points scaled by the nurse's `years_experience` capped at ten years — that is, 25 multiplied by the lesser of the nurse's years and ten, divided by ten; a nurse at ten or more years earns the full 25. Shift alignment contributes 20 points when `desired_shift` equals the requisition's `shift`; failing that, 10 points when either side is `ROTATING`; otherwise nothing. Commute feasibility contributes 15 points when the nurse's `max_commute_miles` is at least the requisition's `distance_from_facility_miles`."
        PRD §3.3: "The returned ranking orders by `match_score` descending, breaking ties by the nurse's `created_at` ascending; ties beyond that are impossible because creation timestamps are unique."

        Design: Difficulty/combinatorial_formula/match_score_multi_input_nonlinear
        """
        fx.set_clock()
        nurse_a = fx.setup_active_nurse(
            email="a@x.com", years_experience=8, desired_shift="DAY",
        )["nurse"]
        nurse_b = fx.setup_active_nurse(
            email="b@x.com", years_experience=14, desired_shift="ROTATING",
        )["nurse"]
        nurse_c = fx.setup_active_nurse(
            email="c@x.com", years_experience=14, desired_shift="NIGHT",
        )["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer, shift="DAY", distance_from_facility_miles=20)

        rows = _gen_and_list(req, employer)
        by_nurse = {row["nurse_id"]: row for row in rows}
        assert len(rows) == 3
        # A: 40 geo + 25*min(8,10)/10=20 exp + 20 shift-exact + 15 commute = 95
        assert by_nurse[nurse_a["id"]]["match_score"] == 95
        # B: 40 + 25*min(14,10)/10=25 (cap saturation) + 10 ROTATING partial + 15 = 90
        assert by_nurse[nurse_b["id"]]["match_score"] == 90
        # C: 40 + 25 + 0 (NIGHT vs DAY earns no partial) + 15 = 80
        assert by_nurse[nurse_c["id"]]["match_score"] == 80

        assert [row["nurse_id"] for row in rows] == [
            nurse_a["id"], nurse_b["id"], nurse_c["id"]
        ], "ranked order must be match_score DESC"

    def test_experience_cap_saturates_at_ten_years(self, api):
        """PRD §3.3: "Experience contributes 25 points scaled by the nurse's `years_experience` capped at ten years — that is, 25 multiplied by the lesser of the nurse's years and ten, divided by ten; a nurse at ten or more years earns the full 25."

        Design: Difficulty/combinatorial_formula/match_score_multi_input_nonlinear
        """
        fx.set_clock()
        nurse_10 = fx.setup_active_nurse(
            email="ten@x.com", years_experience=10, desired_shift="DAY",
        )["nurse"]
        nurse_14 = fx.setup_active_nurse(
            email="fourteen@x.com", years_experience=14, desired_shift="DAY",
        )["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer, shift="DAY")

        rows = _gen_and_list(req, employer)
        by_nurse = {row["nurse_id"]: row["match_score"] for row in rows}
        # Both earn the capped 25-point experience term: 40 + 25 + 20 + 15 = 100.
        assert by_nurse[nurse_10["id"]] == 100
        assert by_nurse[nurse_14["id"]] == 100


class TestMatchScoreBaseVariant:
    def test_certless_nurse_in_pool_with_empty_required_certs(self, api):
        """PRD §3.3: "Finally, when `required_certs` is non-empty and the nurse lacks any required cert unexpired, a hard penalty of 20 points is subtracted — the nurse is penalized, not excluded."
        PRD §3.3: "The candidate pool is every nurse who is `ACTIVE`, license-verified, and whose `primary_specialty` equals the requisition's `specialty`."

        Design: Difficulty/dual_variant_calc/match_score_base_vs_strict_cert_pool
        """
        fx.set_clock()
        nurse = fx.setup_active_nurse(
            email="nora@x.com", years_experience=8, desired_shift="DAY",
        )["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(
            employer, required_certs=[], shift="DAY", distance_from_facility_miles=20
        )

        rows = _gen_and_list(req, employer)
        assert len(rows) == 1
        assert rows[0]["nurse_id"] == nurse["id"]
        # No required certs means no penalty: 40 + 20 + 20 + 15 = 95.
        assert rows[0]["match_score"] == 95
        assert rows[0]["suppressed"] is False

    def test_cert_penalty_subtracted_not_excluded(self, api):
        """PRD §3.3: "Finally, when `required_certs` is non-empty and the nurse lacks any required cert unexpired, a hard penalty of 20 points is subtracted — the nurse is penalized, not excluded."

        Design: Difficulty/dual_variant_calc/match_score_base_vs_strict_cert_pool
        """
        fx.set_clock()
        nurse = fx.setup_active_nurse(
            email="nora@x.com", years_experience=8, desired_shift="DAY",
        )["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(
            employer, required_certs=["CCRN"], shift="DAY", distance_from_facility_miles=20
        )

        rows = _gen_and_list(req, employer)
        # The nurse holds no CCRN: penalized by 20, not excluded.
        assert len(rows) == 1
        assert rows[0]["nurse_id"] == nurse["id"]
        assert rows[0]["match_score"] == 95 - 20


class TestSuppressedMatches:
    def test_suppressed_match_hidden_from_employer_visible_to_admin(self, api):
        """PRD §2.8: "At match generation, a requisition whose `employer_id` appears in the nurse's `confidentiality_exclusions` still produces a `Match` row, but that row is persisted with `suppressed` set to true and is never returned to the `Employer` role."
        PRD §3.3: "Nurses whose `confidentiality_exclusions` contain the requisition's `employer_id` are still scored, but their `Match` rows are persisted with `suppressed` true and are excluded from every employer-visible read; `Candidate` and `PlatformAdmin` readers of a nurse's matches see the suppressed rows, while the employer-facing requisition match list never returns them."

        Design: Corner/entities/suppressed_match_hidden_from_employer_visible_to_admin
        """
        fx.set_clock()
        fx.create_employer(legal_name="Bayview Medical")
        shady = fx.create_employer(
            legal_name="Shady Pines", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        nurse = fx.setup_active_nurse(
            email="shy2@x.com", current_employer_name="Shady Pines",
        )["nurse"]
        req = fx.create_requisition(shady, unit_name="ICU-South", openings_total=1)
        validate_success(
            api_client.generate_matches(req["id"], make_employer_headers(shady["id"]))
        )

        employer_rows, employer_meta = validate_paginated(
            api_client.list_requisition_matches(req["id"], make_employer_headers(shady["id"]))
        )
        assert len(employer_rows) == 0, "the employer must never see its suppressed match"

        admin_rows, admin_meta = validate_paginated(
            api_client.list_requisition_matches(req["id"], ADMIN, params={"include_suppressed": True})
        )
        assert len(admin_rows) == 1
        assert admin_rows[0]["suppressed"] is True
        assert admin_rows[0]["nurse_id"] == nurse["id"]

        nurse_rows, _ = validate_paginated(
            api_client.list_nurse_matches(nurse["id"], ADMIN)
        )
        assert any(row["suppressed"] is True for row in nurse_rows), (
            "the nurse-side match list includes suppressed rows"
        )


class TestMatchRegeneration:
    def test_generate_matches_replaces_prior_generation(self, api):
        """PRD §3.3: "Generation is idempotent per requisition: prior non-suppressed `Match` rows for the requisition are replaced by the new run."

        Design: Corner/endpoints/generate_matches_replaces_prior_generation
        """
        fx.set_clock()
        nurse = fx.setup_active_nurse(email="nora@x.com")["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer)

        rows = _gen_and_list(req, employer)
        assert len(rows) == 1
        assert rows[0]["nurse_id"] == nurse["id"]

        fx.setup_active_nurse(email="late@x.com", years_experience=7)

        rows = _gen_and_list(req, employer)
        assert len(rows) == 2, "regeneration reflects the latest pool only"
        assert len({row["nurse_id"] for row in rows}) == 2, (
            "no stale duplicate of the first nurse may survive regeneration"
        )
        for row in rows:
            assert isinstance(row["match_score"], int)
            assert isinstance(row["suppressed"], bool)


class TestSelectorPolicy:
    def test_selector_policy_ranking_and_tie_break(self, api):
        """PRD §3.3: "The returned ranking orders by `match_score` descending, breaking ties by the nurse's `created_at` ascending; ties beyond that are impossible because creation timestamps are unique."

        Design: Corner/cross_cutting_layers/selector_policy_ranking_and_tie_break
        """
        fx.set_clock()
        nurse_a = fx.setup_active_nurse(
            email="twina@x.com", years_experience=8, desired_shift="DAY",
        )["nurse"]
        nurse_b = fx.setup_active_nurse(
            email="twinb@x.com", years_experience=8, desired_shift="DAY",
        )["nurse"]
        nurse_c = fx.setup_active_nurse(
            email="lowc@x.com", years_experience=2, desired_shift="DAY",
        )["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer, shift="DAY", distance_from_facility_miles=20)

        rows = _gen_and_list(req, employer)
        assert len(rows) == 3
        # A and B score identically (95); C scores 40 + 5 + 20 + 15 = 80.
        assert rows[0]["match_score"] == 95
        assert rows[1]["match_score"] == 95
        assert rows[2]["match_score"] == 80
        assert rows[2]["nurse_id"] == nurse_c["id"]
        # The 95-tie breaks on created_at ASC: A registered before B.
        assert [rows[0]["nurse_id"], rows[1]["nurse_id"]] == [nurse_a["id"], nurse_b["id"]]
