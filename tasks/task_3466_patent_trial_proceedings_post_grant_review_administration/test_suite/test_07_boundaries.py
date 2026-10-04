"""Boundary precision: the 365-day petition time bar and the merits
threshold (PRD §3.3, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    add_petitioned_patent,
    api_client,
    create_litigation_matter,
    create_party,
    create_petition_payload,
    decide_institution,
    file_petition,
    get_patent,
    get_petition,
    make_petitioner_headers,
    new_world,
    per_ground_scores,
    validate_error,
)


class TestPetitionTimeBarBoundary:
    def _world_with_two_defendants(self):
        world = new_world(petitioner_name="PA Corp", owner_name="O12 Corp",
                          total_claims=4, patent_number="US10000012",
                          title="Cam", issue_date="2020-02-01T00:00:00Z")
        pa_id = world["petitioner"]["id"]
        pb = create_party("PB Corp", "PETITIONER")
        # Exactly 365 days before the 2026-09-01 filing for PA; 366 for PB.
        create_litigation_matter(
            world["patent"]["id"], pa_id, "2025-09-01T00:00:00Z",
            court_name="E.D. Tex.", docket_number="2:25-cv-00401",
        )
        create_litigation_matter(
            world["patent"]["id"], pb["id"], "2025-08-31T00:00:00Z",
            court_name="E.D. Tex.", docket_number="2:25-cv-00402",
        )
        return world, pa_id, pb["id"]

    def test_filing_exactly_365_days_after_service_is_not_barred(self):
        """PRD §3.3: "if any litigation matter exists for the same patent
        naming the petitioner as defendant whose `complaint_served_date` lies
        strictly more than 365 days before the filing date, the petition is
        rejected with `ERR_PETITION_TIME_BARRED`. Exactly 365 days elapsed is
        not barred, while 366 days is".

        Design: Difficulty/boundary_precision_check/petition_time_bar_exactly_365_days_allowed_366_barred
        """
        world, pa_id, _ = self._world_with_two_defendants()
        petition = file_petition(pa_id, world["patent"]["id"],
                                 challenged_claims=[1])
        assert petition["status"] == "FILED"

    def test_filing_366_days_after_service_is_barred(self):
        """PRD §3.3: "Exactly 365 days elapsed is not barred, while 366 days
        is; and the matter's later disposition does not lift the bar".

        Design: Difficulty/boundary_precision_check/petition_time_bar_exactly_365_days_allowed_366_barred
        """
        world, pa_id, pb_id = self._world_with_two_defendants()
        # A valid first filing advances the patent's version by one (PRD
        # §3.3), so the barred filing carries the refreshed version to reach
        # the time-bar check.
        file_petition(pa_id, world["patent"]["id"], challenged_claims=[1])
        fresh_version = get_patent(world["patent"]["id"])["version"]
        payload = create_petition_payload(
            patent_id=world["patent"]["id"], petitioner_id=pb_id,
            challenged_claims=[1], expected_patent_version=fresh_version,
        )
        resp = api_client.create_petition(payload, make_petitioner_headers(pb_id))
        validate_error(resp, ApiErrorId.ERR_PETITION_TIME_BARRED, 422)


class TestMeritsThresholdBoundary:
    def _two_accorded_petitions(self):
        world = new_world(petitioner_name="P13 Corp", owner_name="O13 Corp")
        a = add_petitioned_patent(
            world, patent_number="US10000013A",
            challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
        )
        b = add_petitioned_patent(
            world, patent_number="US10000013B",
            challenged_claims=(1, 2),
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
            do_accord=True,
        )
        return world, a, b

    def test_score_exactly_40_institutes_an_ipr(self):
        """PRD §3.4: "The merits are met when the maximum score is at least
        the threshold — a top score of exactly 40 institutes an `IPR`, while
        39 does not."

        Design: Difficulty/boundary_precision_check/merits_threshold_score_40_institutes_39_denies
        """
        _, a, _ = self._two_accorded_petitions()
        data = decide_institution(
            a["petition"]["id"],
            per_ground_scores((1, 40), (2, 35, "OBVIOUSNESS_103")),
            "judge-kate",
        )
        assert data["outcome"] == "INSTITUTED"
        assert get_petition(a["petition"]["id"])["status"] == "INSTITUTED"

    def test_score_39_denies_an_ipr_on_the_merits(self):
        """PRD §3.4: "when the merits are not met, the outcome is
        `DENIED_MERITS`." PRD §3.4: "A denial leaves the petition `DENIED`
        and terminal."

        Design: Difficulty/boundary_precision_check/merits_threshold_score_40_institutes_39_denies
        """
        _, _, b = self._two_accorded_petitions()
        data = decide_institution(
            b["petition"]["id"],
            per_ground_scores((1, 39), (2, 39, "OBVIOUSNESS_103")),
            "judge-kurt",
        )
        assert data["outcome"] == "DENIED_MERITS"
        assert data["merits_max_score"] == 39
        assert get_petition(b["petition"]["id"])["status"] == "DENIED"
