"""Optimistic concurrency, the institution cascade, filtered listing, and
immediate consistency (PRD §2.7, §2.10, §3.3, §3.4).
"""
from test_helpers import (
    ADMIN,
    APPEALS,
    ApiErrorId,
    PANEL,
    accord,
    add_petitioned_patent,
    api_client,
    assert_proceeding,
    assert_same_instant,
    create_litigation_matter,
    create_petition_payload,
    decide_institution,
    file_petition,
    get_litigation_matter,
    get_patent,
    get_petition,
    new_world,
    patch_litigation_matter,
    per_ground_scores,
    setup_instituted_proceeding,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_second_petition_with_stale_patent_version_rejected_412():
    """PRD §2.7: "Filing a petition (`POST /ptab/petitions`) requires the
    request to carry `expected_patent_version`, the client's last observed
    `version` of the target patent. If the patent's current `version` differs
    — because a prior filing or a decision cascade has advanced it since the
    client last read the patent — the request is rejected with
    `ERR_STALE_PATENT_VERSION` (HTTP 412). A successful petition filing
    itself increments the patent's `version` by one".

    Design: Corner/cross_cutting_layers/second_petition_with_stale_patent_version_rejected_412
    """
    world = new_world(petitioner_name="PAZ Corp", owner_name="OAZ Corp",
                      total_claims=3)
    stale_version = world["patent"]["version"]
    file_petition(world["petitioner"]["id"], world["patent"]["id"],
                  challenged_claims=[1])
    # The first filing bumped the patent 1 -> 2; the stale read is rejected.
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=[2],
        grounds=[{"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
        prior_art=[{"reference_type": "PRINTED_PUBLICATION",
                    "citation": "SAE 2019"}],
        expected_patent_version=stale_version,
    )
    resp = api_client.create_petition(payload, world["petitioner_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_PATENT_VERSION, 412)
    fresh_version = get_patent(world["patent"]["id"])["version"]
    assert fresh_version == stale_version + 1
    # The identical filing succeeds once it carries the refreshed version.
    payload["expected_patent_version"] = fresh_version
    data = validate_success(
        api_client.create_petition(payload, world["petitioner_headers"]), 201
    )
    assert data["status"] == "FILED"


def test_matter_patch_with_stale_version_rejected_412():
    """PRD §2.7: "Updating a litigation matter
    (`PATCH /ptab/litigation-matters/{matterId}`) requires the request to
    carry `expected_litigation_matter_version`, the client's last observed
    `version` of the matter. A mismatch with the matter's current `version` —
    advanced by another docket update or by an institution or
    full-cancellation cascade — is rejected with `ERR_STALE_MATTER_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_layers/matter_patch_with_stale_version_rejected_412
    """
    world = new_world(petitioner_name="PBA Corp", owner_name="OBA Corp")
    matter = create_litigation_matter(
        world["patent"]["id"], world["petitioner"]["id"],
        "2026-04-01T00:00:00Z", court_name="N.D. Cal.",
        docket_number="3:25-cv-01600",
    )
    first = patch_litigation_matter(
        matter["id"],
        {"trial_date": "2027-04-01T00:00:00Z",
         "expected_litigation_matter_version": matter["version"]},
    )
    assert first["version"] == matter["version"] + 1
    resp = api_client.patch_litigation_matter(
        matter["id"],
        {"status": "STAYED",
         "expected_litigation_matter_version": matter["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MATTER_VERSION, 412)
    assert get_litigation_matter(matter["id"])["status"] == "ACTIVE"


def test_institution_cascade_creates_proceeding_reviews_patent_and_stays_matters():
    """PRD §3.4: "An institution moves the petition to `INSTITUTED` and fires
    the full institution cascade atomically within the same request." and "In
    the same stroke the patent moves `ISSUED → IN_REVIEW` with its `version`
    incremented by one, and every `ACTIVE` litigation matter for the patent
    is stayed with `stay_reason` set to `INSTITUTION_STAY`."

    Design: Corner/cross_cutting_layers/institution_cascade_creates_proceeding_reviews_patent_and_stays_matters
    """
    # Matter served 2025-12-01 (274 days -> investment +20), trial
    # 2028-06-01 (beyond the base projection -> proximity 0): Fintiv 40.
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1, 2),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 82},
                {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 71}],
        lead_judge="judge-zane", petitioner_name="PBB Corp",
        owner_name="OBB Corp",
        matters=[{"complaint_served_date": "2025-12-01T00:00:00Z",
                  "trial_date": "2028-06-01T00:00:00Z",
                  "court_name": "W.D. Tex.", "docket_number": "6:25-cv-01700"}],
    )
    assert world["decision"]["outcome"] == "INSTITUTED"
    proceeding = world["proceeding"]
    assert_proceeding(proceeding)
    assert proceeding["phase"] == "INSTITUTED"
    assert proceeding["instituted_claims"] == [1, 2]
    assert proceeding["briefing_cycle"] == 0
    assert proceeding["amendment_slots_available"] == 1
    assert_same_instant(proceeding["fwd_due_date"], "2027-09-01T00:00:00Z",
                        "fwd_due_date")
    patent = get_patent(world["patent"]["id"])
    assert patent["status"] == "IN_REVIEW"
    matter = get_litigation_matter(world["matters"][0]["id"])
    assert matter["status"] == "STAYED"
    assert matter["stay_reason"] == "INSTITUTION_STAY"
    # The cascade incremented the matter's version (1 -> 2).
    assert matter["version"] == world["matters"][0]["version"] + 1


def test_petitions_filter_by_status_returns_only_matching_rows():
    """PRD §3.3: "Pending petitions can be browsed with optional
    `patent_id`, `petitioner_id`, and `status` filters." — the filter narrows
    the result set and its `total_count` (PRD §2.3).

    Design: Corner/cross_cutting_layers/petitions_filter_by_status_returns_only_matching_rows
    """
    world = new_world(petitioner_name="PBC Corp", owner_name="OBC Corp")
    add_petitioned_patent(world, patent_number="US10001063A",
                          challenged_claims=(1,))  # stays FILED
    denied = add_petitioned_patent(world, patent_number="US10001063B",
                                   challenged_claims=(1,), do_accord=True)
    decide_institution(denied["petition"]["id"], per_ground_scores((1, 10)),
                       "judge-abby")
    denied_rows, denied_meta = validate_paginated(
        api_client.list_petitions(APPEALS, params={"status": "DENIED"})
    )
    assert len(denied_rows) == 1
    assert denied_rows[0]["id"] == denied["petition"]["id"]
    assert denied_meta["total_count"] == 1
    assert denied_meta["has_more"] is False
    filed_rows, filed_meta = validate_paginated(
        api_client.list_petitions(APPEALS, params={"status": "FILED"})
    )
    assert len(filed_rows) == 1
    assert filed_meta["total_count"] == 1


def test_institution_decision_response_and_petition_read_agree_immediately():
    """PRD §2.10: "Every mutation, including each cascade hop, is applied
    atomically within the triggering request, and all recomputed fields are
    visible in that request's response." PRD §3.4: "the petition's own
    `merits_max_score` and `advisory_aggregate_score` are recorded on the
    petition as well."

    Design: Corner/consistency_model/institution_decision_response_and_petition_read_agree_immediately
    """
    world = new_world(petitioner_name="PBD Corp", owner_name="OBD Corp")
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1, 2])
    accord(petition["id"])
    data = validate_success(
        api_client.decide_institution(
            petition["id"],
            {"per_ground_scores": per_ground_scores(
                (1, 90), (2, 40, "OBVIOUSNESS_103")),
             "lead_judge_user_id": "judge-boris"},
            PANEL,
        ),
        201,
    )
    # round_half_up(0.7*90 + 0.3*65) = round_half_up(82.5) = 83.
    assert data["outcome"] == "INSTITUTED"
    assert data["merits_max_score"] == 90
    assert data["advisory_aggregate_score"] == 83
    petition_after = get_petition(petition["id"])
    assert petition_after["status"] == "INSTITUTED"
    assert petition_after["merits_max_score"] == 90
    assert petition_after["advisory_aggregate_score"] == 83
