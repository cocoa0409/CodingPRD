"""Breadth probes over calculation constants, input-set validation, and
computed reads on empty sets."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_campaign_testing,
    campaign_transition_payload,
    compute_conformity_final_bp,
    create_campaign,
    create_election_definition,
    create_test_laboratory,
    create_voting_system,
    file_deficiencies,
    get_campaign,
    make_election_official_headers,
    resubmit_campaign,
    set_clock,
    setup_election_definition,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

VENDOR = TEST_USERS["vendor_rep_headers"]
AUTHORITY = TEST_USERS["certification_authority_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_conformity_aging_blocks_late_certification(api):
    """PRD §3.2: "The final-audit variant, stored as `conformity_final_bp`,
    starts from 10000 and subtracts 1500 per open critical deficiency, 250
    per open major, 50 per open minor, 400 per completed resubmission, and an
    aging term of 10 basis points per full week elapsed since
    `last_submitted_at`".
    PRD §3.2: "the freshly evaluated final-audit conformity must be at least
    8000 basis points, otherwise `ERR_CONFORMITY_BELOW_THRESHOLD`."
    PRD §3.2: "At certify time the final-audit score is evaluated fresh
    against the current logical clock rather than read from storage."

    Design: Corner/calculations/conformity_aging_blocks_late_certification
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 0, 0, 1)
    resubmit_campaign(campaign["id"], 0, 0, 1)
    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 0, 0, 1)
    resubmit_campaign(campaign["id"], 0, 0, 1)
    set_clock("2028-12-30T00:00:00Z")
    begin_campaign_testing(campaign["id"], lab["id"])

    expected_final = compute_conformity_final_bp(
        0, 0, 0, 2, "2026-09-01T00:00:00Z", "2028-12-30T00:00:00Z"
    )
    assert expected_final == 7990, "10000 - 400*2 - 10*121 = 7990 < 8000"

    resp = api.transition_certification_campaign(
        campaign["id"], campaign_transition_payload("CERTIFIED"), AUTHORITY
    )
    validate_error(resp, ApiErrorId.ERR_CONFORMITY_BELOW_THRESHOLD)
    assert get_campaign(campaign["id"])["status"] == "IN_TEST"
    certs, meta = validate_paginated(
        api.list_certificates(AUDITOR, params={"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 0, "no certificate is minted on a refused certify"


def test_la_tallies_shape_validation(api):
    """PRD §3.6: "The tallies are validated before any arithmetic: the key
    set of `scanned_tallies` must equal the key set of `expected_tallies`,
    every value must be a non-negative integer, and `total_expected` — the
    sum of the expected values — must be at least 1; any violation is
    `ERR_INVALID_TALLIES`."

    Design: Corner/calculations/la_tallies_shape_validation
    """
    base = setup_election_definition("PROGRAMMED")
    off1 = base["officials"][0]["id"]
    ed_id = base["definition"]["id"]

    resp = api.create_la_test(
        ed_id,
        {"expected_tallies": {"PRES": 100, "SEN": 50},
         "scanned_tallies": {"PRES": 100}},
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TALLIES)

    resp = api.create_la_test(
        ed_id,
        {"expected_tallies": {"PRES": 0, "SEN": 0},
         "scanned_tallies": {"PRES": 0, "SEN": 0}},
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TALLIES)


def test_readiness_empty_fleet_returns_zero_counts(api):
    """PRD §3.5: "The **fleet readiness** read considers the set of equipment
    units whose `jurisdiction_id` equals the definition's jurisdiction and
    whose `voting_system_id` equals the definition's procurement's voting
    system, and reports `jurisdiction_id`, `voting_system_id`, `unit_count`
    (the size of that set), and two readiness tallies."
    PRD §3.5: "The response fields are `unit_count`,
    `optimistic_ready_count`, and `conservative_ready_count`."

    Design: Corner/calculations/readiness_empty_fleet_returns_zero_counts
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"], base["procurement"]["id"],
        acting_official_id=off1,
    )
    resp = api.get_readiness(definition["id"], AUDITOR)
    readiness = validate_success(resp)
    assert readiness["unit_count"] == 0
    assert readiness["optimistic_ready_count"] == 0
    assert readiness["conservative_ready_count"] == 0
