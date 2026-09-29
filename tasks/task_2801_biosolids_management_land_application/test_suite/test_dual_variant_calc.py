"""Both volatile-solids-reduction variants, and both odor risk variants, are
persisted from the same inputs while only one of each pair is allowed to gate.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_batch_state,
    assert_percent,
)
from test_helpers.test_users import LIAISON_HEADERS
from test_helpers import factories as F
from prd_bench_local_runner.testing import validate_success


class TestVolatileSolidsReductionVariants:
    def test_digestion_persists_both_variants_and_only_van_kleeck_gates(
        self, build, facility
    ):
        """PRD §3.2: "Only `vsr_pct_van_kleeck` is compliance-binding: it alone decides vector attraction reduction under `VAR_OPTION_1_VSR` and it alone can reject a batch."

        Digesting 200.000 dry tons at 70.00% volatile solids down to 160.000 at
        55.00% yields van Kleeck 47.62 and mass balance 37.14 from one request.

        Mass balance lands below the 38.00 vector attraction minimum while van
        Kleeck clears it, and the batch is not rejected because only the van
        Kleeck figure is compared against that minimum.

        Design: Difficulty/dual_variant_calc/vsr_van_kleeck_gates_while_mass_balance_only_reports
        """
        batch = build.batch(facility["id"])
        digested = build.digest(batch["id"])

        assert_percent(digested["vsr_pct_van_kleeck"], 47.62)
        assert_percent(digested["vsr_pct_mass_balance"], 37.14)
        assert digested["vsr_pct_van_kleeck"] != digested["vsr_pct_mass_balance"]
        assert digested["vsr_pct_mass_balance"] < C.VSR_MINIMUM_PCT
        assert digested["vsr_pct_van_kleeck"] >= C.VSR_MINIMUM_PCT

        assert_batch_state(
            digested,
            process_status=C.PROCESS_DIGESTED,
            quality_status=C.QUALITY_UNTESTED,
        )
        assert digested["rejection_reason"] is None
        assert digested["pathogen_class"] == C.PATHOGEN_CLASS_B
        assert digested["version"] == 2

    def test_mass_balance_below_the_minimum_does_not_block_certification(
        self, build, facility, cadmium_limit
    ):
        """PRD §3.2: "`vsr_pct_mass_balance` is the operations figure published in the annual report and is never a gate."

        A batch whose mass balance reduction is 37.14 - below the 38.00 vector
        attraction minimum - still reaches QUALIFIED, because the reported mass
        balance figure never participates in the vector attraction decision.

        Design: Difficulty/dual_variant_calc/vsr_van_kleeck_gates_while_mass_balance_only_reports
        """
        batch = build.batch(facility["id"])
        build.digest(batch["id"])
        dewatered = build.dewater(batch["id"])
        assert_batch_state(dewatered, quality_status=C.QUALITY_PENDING_RESULTS)

        build.lab_result(batch["id"])
        certified = build.certify(batch["id"])

        assert_percent(certified["vsr_pct_mass_balance"], 37.14)
        assert certified["vsr_pct_mass_balance"] < C.VSR_MINIMUM_PCT
        assert_batch_state(certified, quality_status=C.QUALITY_QUALIFIED)
        assert certified["vector_demonstrated_at_batch"] is True
        assert certified["rejection_reason"] is None


class TestOdorRiskVariants:
    def _two_complaints(self, build, api, facility_id, site_id):
        """One substantiated SEVERE complaint and one still-open MODERATE complaint."""
        severe = build.complaint(
            facility_id,
            site_id=site_id,
            received_at="2026-07-01T14:00:00Z",
            severity="SEVERE",
            description="Strong odor during afternoon spreading",
            complainant_contact="neighbor-a@example.com",
        )
        build.investigate(severe["id"])
        build.resolve(
            severe["id"],
            outcome=C.COMPLAINT_SUBSTANTIATED,
            investigation_note="Field crew confirmed surface application upwind",
            resolution_action="OPERATIONAL_CHANGE",
        )
        moderate_response = api.create_complaint(
            F.complaint_payload(
                facility_id,
                site_id=site_id,
                received_at="2026-07-15T09:00:00Z",
                severity="MODERATE",
                description="Odor noticeable at the property line",
            ),
            LIAISON_HEADERS,
        )
        moderate = validate_success(moderate_response, 201)
        return severe, moderate

    def test_precautionary_variant_gates_a_site_close_to_residences(
        self, build, api, facility
    ):
        """PRD §3.11: "`gating_risk_score` is `odor_risk_score_precautionary` when the site's `nearest_residence_ft` is strictly below 1500 feet, and `odor_risk_score_historical` otherwise."

        A substantiated SEVERE complaint scores 28.00 historically; adding a
        still-open MODERATE complaint lifts the precautionary score to 40.00.

        The site sits 1200 ft from the nearest residence, below the 1500 ft
        threshold, so the precautionary figure is the one exposed as the
        scheduling gate. Neither figure restricts the site, and an unresolved
        complaint leaves the facility's substantiated 30-day count untouched.

        Design: Difficulty/dual_variant_calc/odor_risk_precautionary_variant_gates_site_near_residences
        """
        site = build.permitted_site(facility["id"], nearest_residence_ft=1200)
        _, moderate = self._two_complaints(build, api, facility["id"], site["id"])

        refreshed = build.read_site(site["id"])
        assert_percent(refreshed["odor_risk_score_historical"], 28.00)
        assert_percent(refreshed["odor_risk_score_precautionary"], 40.00)
        assert_percent(refreshed["gating_risk_score"], 40.00)
        assert refreshed["status"] == C.SITE_PERMITTED
        assert refreshed["restriction_reason"] is None
        assert refreshed["pfas_advisory_flag"] is False

        assert moderate["status"] == C.COMPLAINT_RECEIVED
        current_facility = build.read_facility(facility["id"])
        assert current_facility["substantiated_complaint_count_30d"] == 0
        assert current_facility["posture"] == C.POSTURE_OPEN

    def test_historical_variant_gates_a_site_far_from_residences(
        self, build, api, facility
    ):
        """PRD §3.11: "`gating_risk_score` is `odor_risk_score_precautionary` when the site's `nearest_residence_ft` is strictly below 1500 feet, and `odor_risk_score_historical` otherwise."

        With the identical pair of complaints, a site 3000 ft from the nearest
        residence exposes the historical figure - 28.00, which excludes the open
        MODERATE complaint - as its gating score, while the precautionary figure
        is still reported at 40.00.

        Design: Difficulty/dual_variant_calc/odor_risk_precautionary_variant_gates_site_near_residences
        """
        site = build.permitted_site(facility["id"], nearest_residence_ft=3000)
        self._two_complaints(build, api, facility["id"], site["id"])

        refreshed = build.read_site(site["id"])
        assert_percent(refreshed["odor_risk_score_historical"], 28.00)
        assert_percent(refreshed["odor_risk_score_precautionary"], 40.00)
        assert_percent(refreshed["gating_risk_score"], 28.00)
        assert refreshed["status"] == C.SITE_PERMITTED
