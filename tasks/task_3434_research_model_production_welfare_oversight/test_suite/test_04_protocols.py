"""IACUC protocols: the monotonic quota gates at exact fit, the review
resubmission loop, terminal lockdown, clock-sweep expiry blocking cohort
creation, and segregation of duties on approval.
"""
from test_helpers import (
    TEST_USERS,
    ANIMALS_PER_BREEDING_PAIR,
    ApiErrorId,
    advance_clock,
    api_client,
    create_colony_in_room,
    create_colony_payload,
    create_cohort_in_colony,
    create_cohort_payload,
    create_draft_protocol,
    create_registered_facility,
    find_protocol_in_facility,
    make_facility_manager_headers,
    make_iacuc_reviewer_headers,
    read_colony,
    setup_production_site,
    transition_colony,
    transition_protocol,
    validate_error,
    validate_success,
)

_FM = TEST_USERS["facility_manager_headers"]


def test_protocol_quota_exact_fit_boundary_cohort_side():
    """PRD Section 3.4: "recording a cohort requires `animals_used` plus the
    incoming total headcount (`count_male` plus `count_female`) to be less
    than or equal to `approved_animal_quota`; exceeding the quota at either
    gate is `ERR_PROTOCOL_QUOTA_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/protocol_quota_exact_fit_boundary
    """
    site = setup_production_site(protocol_quota=100)
    colony = create_colony_in_room(site, breeding_pair_count=20)
    transition_colony(colony["id"], "EXPANDING")

    # 20 pairs * 2 = 40 used; cohort of 60 brings the accumulator to exactly
    # 100 == quota, and equality passes.
    cohort = create_cohort_in_colony(colony["id"], count_male=30, count_female=30)
    assert cohort["initial_count_total"] == 60
    protocol = find_protocol_in_facility(site["protocol"]["id"], site["facility"]["id"])
    assert protocol["animals_used"] == 20 * ANIMALS_PER_BREEDING_PAIR + 60
    assert protocol["animals_used"] == 100

    # One more animal tips the accumulator to 101 > 100: rejected.
    resp = api_client.create_cohort(
        create_cohort_payload(colony["id"], count_male=1, count_female=0), _FM
    )
    validate_error(resp, ApiErrorId.ERR_PROTOCOL_QUOTA_EXCEEDED)


def test_protocol_quota_exact_fit_boundary_colony_side():
    """PRD Section 3.4: "founding a colony requires `animals_used` plus twice
    the incoming `breeding_pair_count` to be less than or equal to
    `approved_animal_quota`" and "The accumulator is strictly monotonic:
    culls, allocation releases, shipment departures, and colony retirements
    never refund it".

    Design: Difficulty/boundary_precision_check/protocol_quota_exact_fit_boundary
    """
    site = setup_production_site(protocol_quota=100)
    colony = create_colony_in_room(site, breeding_pair_count=20)
    transition_colony(colony["id"], "EXPANDING")
    create_cohort_in_colony(colony["id"], count_male=30, count_female=30)

    protocol = find_protocol_in_facility(site["protocol"]["id"], site["facility"]["id"])
    assert protocol["animals_used"] == 100

    # At exactly 100, any further colony founding (100 + 2*1 > 100) is
    # rejected and the accumulator does not move.
    payload = create_colony_payload(
        site["room"]["id"], site["strain"]["id"], site["protocol"]["id"],
        breeding_pair_count=1,
    )
    resp = api_client.create_colony(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_PROTOCOL_QUOTA_EXCEEDED)

    protocol = find_protocol_in_facility(site["protocol"]["id"], site["facility"]["id"])
    assert protocol["animals_used"] == 100


def test_protocol_review_resubmission_loop():
    """PRD Section 3.9: "Revision requests loop — a protocol in
    `REVISION_REQUESTED` returns to `SUBMITTED` on resubmission, which
    refreshes `submitted_by_user_id` to the resubmitting caller."

    Design: Corner/state_machines/protocol_review_resubmission_loop
    """
    facility = create_registered_facility()
    protocol = create_draft_protocol(facility["id"], submitter_id="fm-1")

    transition_protocol(protocol["id"], "SUBMITTED", make_facility_manager_headers("fm-1"))
    transition_protocol(protocol["id"], "UNDER_REVIEW", make_iacuc_reviewer_headers("rev-1"))
    transition_protocol(
        protocol["id"], "REVISION_REQUESTED", make_iacuc_reviewer_headers("rev-1")
    )
    transition_protocol(protocol["id"], "SUBMITTED", make_facility_manager_headers("fm-2"))
    transition_protocol(protocol["id"], "UNDER_REVIEW", make_iacuc_reviewer_headers("rev-1"))
    final = transition_protocol(
        protocol["id"], "APPROVED", make_iacuc_reviewer_headers("rev-1")
    )
    assert final["status"] == "APPROVED"

    protocol = find_protocol_in_facility(protocol["id"], facility["id"])
    assert protocol["status"] == "APPROVED"
    assert protocol["submitted_by_user_id"] == "fm-2"


def test_protocol_rejected_terminal_lockdown():
    """PRD Section 3.9: "The drafting manager may withdraw a protocol from
    `DRAFT` or `SUBMITTED` into the terminal `WITHDRAWN` state, and `REJECTED`
    is likewise terminal."
    PRD Section 2.7: "And any transition or action requested against a
    resource whose current state does not declare that transition — including
    any further transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/protocol_rejected_terminal_lockdown
    """
    facility = create_registered_facility()
    protocol = create_draft_protocol(facility["id"], submitter_id="fm-1")
    transition_protocol(protocol["id"], "SUBMITTED", make_facility_manager_headers("fm-1"))
    transition_protocol(protocol["id"], "UNDER_REVIEW", make_iacuc_reviewer_headers("rev-1"))
    rejected = transition_protocol(
        protocol["id"], "REJECTED", make_iacuc_reviewer_headers("rev-1")
    )
    assert rejected["status"] == "REJECTED"

    resp = api_client.transition_protocol(
        protocol["id"], {"target_state": "APPROVED"}, make_iacuc_reviewer_headers("rev-2")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    protocol = find_protocol_in_facility(protocol["id"], facility["id"])
    assert protocol["status"] == "REJECTED"


def test_protocol_expiry_blocks_cohort_creation():
    """PRD Section 3.9: "when the clock sweep finds the logical clock strictly
    past an `APPROVED` protocol's `expiration_date`, the protocol transitions
    to the terminal `EXPIRED` state, and colonies referencing it can no longer
    create cohorts or accept allocations — any such attempt meets
    `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409)".

    Design: Corner/validations/protocol_expiry_blocks_cohort_creation
    """
    site = setup_production_site(
        protocol_overrides={"expiration_date": "2026-10-01T00:00:00Z"}
    )
    colony = create_colony_in_room(site, breeding_pair_count=10)
    transition_colony(colony["id"], "EXPANDING")

    advance_clock("2026-10-02T00:00:00Z")

    protocol = find_protocol_in_facility(site["protocol"]["id"], site["facility"]["id"])
    assert protocol["status"] == "EXPIRED"
    # The 12-week SNP interval lapses only on 2026-11-24, so the genetic gate
    # is not the one failing here.
    assert read_colony(colony["id"])["genetic_status"] == "CLEAR"

    resp = api_client.create_cohort(
        create_cohort_payload(
            colony["id"], birth_date="2026-09-15T00:00:00Z",
            count_male=5, count_female=5,
        ),
        _FM,
    )
    validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)


def test_protocol_segregation_of_duties():
    """PRD Section 2.1: "the operator who submitted a protocol may not approve
    or reject it, and the inspector who filed a report may not verify its
    corrective closure; either attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD Section 3.9: "Approval and rejection carry the segregation-of-duties
    guard: the deciding caller's `X-User-ID` must differ from
    `submitted_by_user_id`".

    Design: Corner/rbac/protocol_segregation_of_duties
    """
    facility = create_registered_facility()
    protocol = create_draft_protocol(facility["id"], submitter_id="shared-1")
    transition_protocol(
        protocol["id"], "SUBMITTED", make_facility_manager_headers("shared-1")
    )
    transition_protocol(
        protocol["id"], "UNDER_REVIEW", make_iacuc_reviewer_headers("rev-1")
    )

    resp = api_client.transition_protocol(
        protocol["id"], {"target_state": "APPROVED"},
        make_iacuc_reviewer_headers("shared-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    final = transition_protocol(
        protocol["id"], "APPROVED", make_iacuc_reviewer_headers("rev-2")
    )
    assert final["status"] == "APPROVED"
