"""Guidance windows, guidance OCC, and the audit engagement pipeline —
PRD §2.7, §3.4, §3.9.
"""

from test_helpers import (
    ApiErrorId,
    complete_audit,
    complete_audit_payload,
    create_active_participant,
    create_audit,
    create_audit_payload,
    create_guidance_document_payload,
    create_passed_proposal,
    create_rule_proposal,
    create_web_transaction_code,
    get_transaction_code,
    make_auditor_headers,
    publish_guidance,
    set_clock,
    start_audit,
    transition_proposal,
    validate_error,
    validate_success,
)


def test_guidance_half_open_window_adjacency_allowed_overlap_rejected(api, admin_headers):
    """PRD §3.4: "Two guidance documents for the same transaction code may not
    cover the same time: a new document whose half-open window intersects the
    window of an existing `PUBLISHED` document for that code is rejected with
    `ERR_GUIDANCE_WINDOW_OVERLAP` — though a pair that merely shares a boundary
    date (one ends exactly where the other begins) does not overlap, because
    the end is exclusive."

    Design: Difficulty/resource_temporal_overlap/guidance_half_open_window_adjacency_allowed_overlap_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter1 = create_active_participant(participant_type="BOTH", routing_number="111000025")
    voter2 = create_active_participant(participant_type="ODFI", routing_number="222000039")
    voter3 = create_active_participant(participant_type="RDFI", routing_number="333000041")
    code = create_web_transaction_code()
    code_version = code["version"]
    proposal = create_passed_proposal(
        code,
        votes=[(voter1, "YEA"), (voter2, "YEA"), (voter3, "YEA")],
        effective_date="2026-10-20",
    )
    set_clock("2026-10-20T09:00:00Z")
    proposal = transition_proposal(proposal["id"], "EFFECTIVE")

    g1 = publish_guidance(
        proposal, code,
        expected_transaction_code_version=code_version,
        effective_from="2027-01-01", effective_until="2027-07-01",
        supersede_prior=False,
    )
    assert g1["status"] == "PUBLISHED"

    g2 = publish_guidance(
        proposal, code,
        expected_transaction_code_version=code_version,
        effective_from="2027-07-01", effective_until=None,
        supersede_prior=False,
    )
    assert g2["status"] == "PUBLISHED"

    overlapping = api.create_guidance_document(
        create_guidance_document_payload(
            proposal["id"], code["id"], code_version,
            effective_from="2027-06-15", effective_until="2027-12-01",
            supersede_prior=False,
        ),
        admin_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_GUIDANCE_WINDOW_OVERLAP)


def test_audit_closed_interval_shared_boundary_is_overlap(api, admin_headers):
    """PRD §3.9: "Two engagements of the same participant may not overlap: a
    new audit whose closed interval from `start_date` through `end_date`
    intersects another audit of that participant in `SCHEDULED` or
    `IN_PROGRESS` status is rejected with `ERR_AUDIT_WINDOW_OVERLAP`, and here
    a shared boundary date does count as an overlap, because both ends are
    inclusive."

    Design: Difficulty/resource_temporal_overlap/audit_closed_interval_shared_boundary_is_overlap
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH", routing_number="111000025")
    audit1 = create_audit(
        participant, "2026-10-05", "2026-10-09",
        auditor_headers=make_auditor_headers("aud-1"),
    )

    touching = api.create_audit(
        create_audit_payload(
            participant["id"], start_date="2026-10-09", end_date="2026-10-13"
        ),
        make_auditor_headers("aud-2"),
    )
    validate_error(touching, ApiErrorId.ERR_AUDIT_WINDOW_OVERLAP)

    audit3 = create_audit(
        participant, "2026-10-10", "2026-10-14",
        auditor_headers=make_auditor_headers("aud-2"),
    )
    assert audit3["status"] == "SCHEDULED"

    audit1_after = validate_success(api.get_audit(audit1["id"], admin_headers))
    assert audit1_after["status"] == "SCHEDULED"


def test_guidance_create_on_non_effective_proposal_rejected(api, admin_headers):
    """PRD §3.4: "Publishing is refused with `ERR_PROPOSAL_NOT_EFFECTIVE` when
    the referenced proposal is not actually in `EFFECTIVE` status or the
    transaction code does not match."

    Design: Corner/validations/guidance_create_on_non_effective_proposal_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    code = create_web_transaction_code()
    proposal = create_rule_proposal(code, effective_date="2027-01-01")
    assert proposal["status"] == "DRAFT"

    resp = api.create_guidance_document(
        create_guidance_document_payload(
            proposal["id"], code["id"], code["version"],
            effective_from="2027-01-01", effective_until=None,
            supersede_prior=False,
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_EFFECTIVE)


def test_occ_guidance_supersede_stale_version_rejected(api, admin_headers):
    """PRD §3.4: "Setting `supersede_prior` to true lifts the overlap
    prohibition instead of rejecting: the overlapping `PUBLISHED` documents of
    that transaction code transition to `SUPERSEDED`, and the transaction
    code's `version` increments by one."
    PRD §2.7: "Publishing a guidance document requires a non-optional
    `expected_transaction_code_version` field carrying the client's last
    observed `version` of the `TransactionCode`. A prior supersession has
    already advanced that version, so a request whose
    `expected_transaction_code_version` no longer matches is rejected with
    `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to supersede
    guidance the caller never observed."

    Design: Corner/complexity_layers/occ_guidance_supersede_stale_version_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    code_version = code["version"]
    proposal = create_passed_proposal(
        code, votes=[(voter, "YEA")], effective_date="2026-10-20"
    )
    set_clock("2026-10-20T09:00:00Z")
    proposal = transition_proposal(proposal["id"], "EFFECTIVE")

    g1 = publish_guidance(
        proposal, code,
        expected_transaction_code_version=code_version,
        effective_from="2027-01-01", effective_until="2027-07-01",
        supersede_prior=False,
    )
    g2 = publish_guidance(
        proposal, code,
        expected_transaction_code_version=code_version,
        effective_from="2027-03-01", effective_until=None,
        supersede_prior=True,
    )
    assert g2["status"] == "PUBLISHED"

    code_after = get_transaction_code(code["id"])
    assert code_after["version"] == code_version + 1
    g1_after = validate_success(api.get_guidance_document(g1["id"], admin_headers))
    assert g1_after["status"] == "SUPERSEDED"

    stale = api.create_guidance_document(
        create_guidance_document_payload(
            proposal["id"], code["id"], code_version,
            effective_from="2027-04-01", effective_until=None,
            supersede_prior=True,
        ),
        admin_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    g2_after = validate_success(api.get_guidance_document(g2["id"], admin_headers))
    assert g2_after["status"] == "PUBLISHED"


def test_audit_complete_by_creator_rejected(api, admin_headers):
    """PRD §3.9: "Completion moves the audit from `IN_PROGRESS` to `COMPLETED`
    with the auditor supplying a `findings_count` of zero or more; the same
    start-date guard applies to completion as to starting work, and segregation
    of duties forbids the creating auditor from completing their own engagement
    — an `X-User-ID` equal to `created_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES` — while the completing auditor's identifier is
    stamped as `completed_by_user_id`."

    Design: Corner/rbac/audit_complete_by_creator_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH", routing_number="111000025")
    audit = create_audit(
        participant, "2026-06-01", "2026-06-30",
        auditor_headers=make_auditor_headers("aud-1"),
    )
    audit = start_audit(audit, auditor_headers=make_auditor_headers("aud-1"))

    own_completion = api.transition_audit(
        audit["id"], complete_audit_payload(3), make_auditor_headers("aud-1")
    )
    validate_error(own_completion, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    completed = complete_audit(audit, 3, auditor_headers=make_auditor_headers("aud-2"))
    assert completed["status"] == "COMPLETED"
    assert completed["completed_by_user_id"] == "aud-2"
    assert completed["findings_count"] == 3


def test_audit_start_before_start_date_rejected(api, admin_headers):
    """PRD §3.9: "Work begins by moving the audit from `SCHEDULED` to
    `IN_PROGRESS`, allowed only once the logical date has reached `start_date`,
    otherwise `ERR_AUDIT_NOT_STARTED`"

    Design: Corner/validations/audit_start_before_start_date_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH", routing_number="111000025")
    audit = create_audit(
        participant, "2026-10-05", "2026-10-09",
        auditor_headers=make_auditor_headers("aud-1"),
    )

    resp = api.transition_audit(
        audit["id"], {"to_state": "IN_PROGRESS"}, make_auditor_headers("aud-1")
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_STARTED)

    after = validate_success(api.get_audit(audit["id"], admin_headers))
    assert after["status"] == "SCHEDULED"
