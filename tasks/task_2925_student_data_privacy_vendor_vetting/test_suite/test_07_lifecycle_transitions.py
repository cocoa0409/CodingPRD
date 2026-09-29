"""Lifecycle behaviour of every stateful row: legal edges, refused edges,
terminal lockdown, the negotiation cycle and the suspension compensation pair.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    factories as fac,
    fixtures as fx,
    make_analyst_headers,
    make_teacher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_CATALOG_ENTRY_NOT_ACTIVE,
    ERR_COMMITMENT_ALREADY_DECIDED,
    ERR_DETECTION_ALREADY_TRIAGED,
    ERR_DISPOSITION_NOT_APPLICABLE,
    ERR_INCIDENT_STATE_INVALID,
    ERR_REMEDIATION_ROUND_LIMIT,
    ERR_REQUEST_STATE_INVALID,
    ERR_REVIEW_ALREADY_DECIDED,
    ERR_REVIEW_STATE_INVALID,
    ERR_VENDOR_STATE_INVALID,
)
from test_helpers.constants import (
    ANONYMIZE,
    APPLICATION_APPROVED,
    APPLICATION_CANDIDATE,
    APPLICATION_IN_REVIEW,
    BAND_LOW,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLASSIFICATION_UNAUTHORIZED,
    CLOCK_DEFAULT_RENDERED,
    COMMITMENT_PROPOSED,
    COMMITMENT_REJECTED,
    COMMITMENT_SUPERSEDED,
    CREDENTIAL_SENIOR,
    DECISION_BLOCK,
    DECISION_CLEAR,
    DETECTION_BLOCKED,
    DISPOSITION_ACCEPT,
    DISPOSITION_REJECT,
    DISPOSITION_REMOVE,
    ELEMENT_STUDENT_NAME,
    ENTRY_EXPIRED,
    ENTRY_EXPIRING_SOON,
    ENTRY_PUBLISHED,
    ENTRY_REVOKED,
    ENTRY_SUSPENDED_HOLD,
    HARD_DELETE,
    INCIDENT_CONTAINED,
    INCIDENT_REMEDIATED,
    INCIDENT_REPORTED,
    INCIDENT_UNAUTHORIZED_DISCLOSURE,
    NOTIFICATION_PENDING,
    POSTURE_CLEAR,
    POSTURE_FROZEN,
    REQUEST_DRAFT,
    RESOLVE_REMEDIATE,
    REVIEW_CLEARED,
    REVIEW_REMEDIATION_SUBMITTED,
    REVIEW_SCREENING,
    SOURCE_NETWORK_DNS,
    SSO_LTI13,
    SUBPROCESSOR_DISCLOSED,
    TRIAGE_ACCEPT_FOR_REVIEW,
    TRIAGE_BLOCK,
    TRIAGE_ESCALATE,
    VENDOR_APPROVED,
    VENDOR_REGISTERED,
    VENDOR_SUSPENDED,
    VENDOR_UNDER_REVIEW,
    VISIBILITY_HIDDEN,
    VISIBILITY_VISIBLE,
)

CLOCK_INSIDE_REAUTHORIZATION_WINDOW = "2027-07-15T00:00:00Z"
CLOCK_PAST_A_ONE_MONTH_WINDOW = "2026-10-01T00:00:00Z"


def _primary_school_chain(api, **overrides):
    """The canonical grade 3-5 reading product on a US vendor with clean terms."""
    kwargs = dict(
        vendor={"legal_name": "Brightpath Reading Co"},
        application={
            "name": "Brightpath Readers",
            "category": CATEGORY_INSTRUCTIONAL_CONTENT,
            "grade_band_low": 3,
            "grade_band_high": 5,
            "sso_protocol": SSO_LTI13,
        },
        teacher={"school_code": "ES-11", "grade_bands_taught": [3, 4, 5]},
        request={
            "grade_band_low": 3,
            "grade_band_high": 5,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_capacity=2400,
    )
    kwargs.update(overrides)
    return kwargs


def _cleared_chain_with_one_accepted_element(api):
    """Walk to a CLEARED review, which leaves the vendor APPROVED at risk 0.72."""
    return fx.decided_review_chain(
        api,
        DECISION_CLEAR,
        commitments=((ELEMENT_STUDENT_NAME, 365, ANONYMIZE),),
        findings_count=0,
        **_primary_school_chain(api),
    )


# ---------------------------------------------------------------------------
# The suspension / reinstatement compensation pair
# ---------------------------------------------------------------------------


def test_suspending_a_vendor_holds_only_its_non_terminal_entries(api):
    """The revoked sibling is terminal, so the cascade must not rewrite it.

    PRD: "Because the posture became `FROZEN`, every catalog entry belonging to
    any application of that vendor whose `status` is `PUBLISHED` or
    `EXPIRING_SOON` moves to `SUSPENDED_HOLD`, recording in `hold_restored_from`
    the status it just left."

    Design: Corner/state_machines/vendor_suspend_cascade_holds_only_non_terminal_catalog_entries
    """
    chain = _cleared_chain_with_one_accepted_element(api)
    held = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        "2026-08-01T00:00:00Z",
        "2027-08-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    terminal = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        "2027-08-01T00:00:00Z",
        "2028-08-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.revoke_entry(api, terminal["id"], "Duplicate future window withdrawn.")
    terminal_version_before = fx.read_entry(api, terminal["id"])["version"]

    response = api.suspend_vendor(
        chain.vendor_id,
        fac.suspension_payload("State audit finding pending."),
        ADMIN_HEADERS,
    )

    vendor = validate_success(response, 200)
    assert vendor["status"] == VENDOR_SUSPENDED, (
        f"Expected SUSPENDED, got {vendor['status']}"
    )
    assert_instant_equals(vendor["suspended_at"], CLOCK_DEFAULT_RENDERED, "suspended_at")
    assert vendor["privacy_posture"] == POSTURE_FROZEN, (
        f"Suspension freezes unconditionally, got {vendor['privacy_posture']}"
    )
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score")

    held_after = fx.read_entry(api, held["id"])
    assert held_after["status"] == ENTRY_SUSPENDED_HOLD, (
        f"Expected SUSPENDED_HOLD, got {held_after['status']}"
    )
    assert held_after["hold_restored_from"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {held_after['hold_restored_from']!r}"
    )
    terminal_after = fx.read_entry(api, terminal["id"])
    assert terminal_after["status"] == ENTRY_REVOKED, (
        f"The terminal sibling stays REVOKED, got {terminal_after['status']}"
    )
    assert terminal_after["hold_restored_from"] is None, (
        "A revoked entry was never held, so hold_restored_from stays null"
    )
    assert_integer_equals(
        terminal_after["version"], terminal_version_before, "revoked entry version"
    )
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"Expected HIDDEN, got {app['catalog_visibility']}"
    )


def test_reinstatement_restores_the_entry_from_the_clock_not_from_the_held_status(api):
    """Held while PUBLISHED, the entry comes back aged as EXPIRING_SOON.

    PRD: "Because the posture left `FROZEN`, every catalog entry of that
    vendor's applications still in `SUSPENDED_HOLD` is restored, and the landing
    state is chosen **purely from the clock position, never from
    `hold_restored_from`**: the entry returns to `PUBLISHED` when the clock is
    before its `reauthorization_due_at`, to `EXPIRING_SOON` when the clock is at
    or after `reauthorization_due_at` but still before `expires_at`, and to
    `EXPIRED` when the clock is at or after `expires_at`."

    Design: Corner/state_machines/vendor_reinstate_restores_entry_from_the_clock_not_from_hold_restored_from
    """
    chain = _cleared_chain_with_one_accepted_element(api)
    entry = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        "2026-08-01T00:00:00Z",
        "2027-08-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.suspend_vendor(api, chain.vendor_id, reason="State audit finding pending.")
    fx.set_clock(api, CLOCK_INSIDE_REAUTHORIZATION_WINDOW)

    vendor = fx.reinstate_vendor(api, chain.vendor_id, note="Audit finding closed.")

    assert vendor["status"] == VENDOR_APPROVED, (
        f"Expected APPROVED, got {vendor['status']}"
    )
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"No other freeze condition holds, got {vendor['privacy_posture']}"
    )
    restored = fx.read_entry(api, entry["id"])
    assert_instant_equals(
        restored["reauthorization_due_at"],
        "2027-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    assert restored["status"] == ENTRY_EXPIRING_SOON, (
        f"The clock is past the lead time, got {restored['status']}"
    )
    assert restored["hold_restored_from"] is None, (
        "hold_restored_from is cleared once the entry is restored"
    )
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_VISIBLE, (
        f"An EXPIRING_SOON entry is still visible, got {app['catalog_visibility']}"
    )


# ---------------------------------------------------------------------------
# Initial states and refused entry edges
# ---------------------------------------------------------------------------


def test_a_vendor_stays_registered_until_a_review_opens(api):
    """Registering an application is not enough to move the vendor.

    PRD: "Opening a review also moves the vendor from `REGISTERED` to
    `UNDER_REVIEW` when it was still `REGISTERED`, recomputing that vendor's
    `privacy_posture` and advancing its `version`."

    Design: Corner/state_machines/vendor_initial_state_is_registered_with_no_review
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")

    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
    )

    after = fx.read_vendor(api, vendor["id"])
    assert after["status"] == VENDOR_REGISTERED, (
        f"An application alone does not open a review, got {after['status']}"
    )
    assert after["suspended_at"] is None, (
        f"Expected suspended_at null, got {after['suspended_at']!r}"
    )
    assert app["status"] == APPLICATION_CANDIDATE, (
        f"Expected CANDIDATE, got {app['status']}"
    )


def test_suspending_a_registered_vendor_is_a_state_conflict(api):
    """Neither half of the suspension pair is reachable from REGISTERED.

    PRD: "**Suspension** is the district's blunt instrument, available to a
    `PrivacyOfficeAdmin` on a vendor whose `status` is `APPROVED` or
    `CONDITIONAL`; any other status is refused with `ERR_VENDOR_STATE_INVALID`."

    Design: Corner/state_machines/suspend_a_registered_vendor_is_state_invalid
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")

    suspend = api.suspend_vendor(
        vendor["id"],
        fac.suspension_payload("Premature suspension attempt."),
        ADMIN_HEADERS,
    )
    reinstate = api.reinstate_vendor(
        vendor["id"], {"note": "Premature reinstatement attempt."}, ADMIN_HEADERS
    )

    validate_error(suspend, ERR_VENDOR_STATE_INVALID, 409)
    validate_error(reinstate, ERR_VENDOR_STATE_INVALID, 409)
    after = fx.read_vendor(api, vendor["id"])
    assert after["status"] == VENDOR_REGISTERED, (
        f"Expected REGISTERED, got {after['status']}"
    )
    assert after["suspended_at"] is None, (
        f"A refused suspension must not stamp suspended_at, got {after['suspended_at']!r}"
    )
    assert after["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {after['privacy_posture']}"
    )


def test_removing_a_never_verified_subprocessor_is_not_applicable(api):
    """DISCLOSED is reviewable, so the refusal is the applicability rung.

    PRD: "Among the remaining rows, the applicability of the submitted
    disposition is checked *after* the notification-terms rule: `VERIFY` requires
    the row to be in `DISCLOSED` and `REMOVE` requires it to be in `VERIFIED` or
    `FLAGGED` — a `DISCLOSED` row must be verified or flagged before it can be
    removed — and a violation of either yields `ERR_DISPOSITION_NOT_APPLICABLE`."

    Design: Corner/state_machines/subprocessor_remove_straight_from_disclosed_is_not_applicable
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, full_name="Ana Lopez", review_capacity_minutes=2400
    )
    subprocessor = fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Northwind Hosting",
        country_code="US",
        sub_breach_notification_hours=24,
    )

    response = api.review_subprocessor(
        subprocessor["id"],
        fac.subprocessor_review_payload(
            DISPOSITION_REMOVE,
            reviewed_note="Attempting removal before any verification.",
        ),
        make_analyst_headers(analyst["id"]),
    )

    validate_error(response, ERR_DISPOSITION_NOT_APPLICABLE, 422)
    after = validate_success(api.get_subprocessor(subprocessor["id"], ADMIN_HEADERS), 200)
    assert after["status"] == SUBPROCESSOR_DISCLOSED, (
        f"The refused disposition leaves the row DISCLOSED, got {after['status']}"
    )
    owner = fx.read_vendor(api, vendor["id"])
    assert_integer_equals(
        owner["flagged_subprocessor_count"], 0, "flagged_subprocessor_count"
    )
    assert owner["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {owner['privacy_posture']}"
    )


def test_deciding_a_screening_review_is_refused_before_any_findings_round(api):
    """A lead who is not the assignee still cannot skip the findings round.

    PRD: "A decision is only reachable from `FINDINGS_ISSUED`: a review still in
    `SCREENING` or sitting in `REMEDIATION_SUBMITTED` is refused with
    `ERR_REVIEW_STATE_INVALID`, which makes at least one findings round
    mandatory, and a review already in `CLEARED`, `CONDITIONAL` or `BLOCKED` is
    refused one rung later with `ERR_REVIEW_ALREADY_DECIDED`."

    Design: Corner/state_machines/review_decide_straight_out_of_screening_is_state_invalid
    """
    chain = fx.screening_review_chain(api, **_primary_school_chain(api))

    response = api.decide_review(
        chain.review_id,
        fac.decision_payload(
            DECISION_CLEAR, decision_note="Skipping the findings round."
        ),
        chain.decider_headers,
    )

    validate_error(response, ERR_REVIEW_STATE_INVALID, 409)
    review = fx.read_review(api, chain.review_id)
    assert review["status"] == REVIEW_SCREENING, (
        f"Expected SCREENING, got {review['status']}"
    )
    app = fx.read_application(api, chain.application_id)
    assert app["status"] == APPLICATION_IN_REVIEW, (
        f"Expected IN_REVIEW, got {app['status']}"
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert vendor["status"] == VENDOR_UNDER_REVIEW, (
        f"Expected UNDER_REVIEW, got {vendor['status']}"
    )


def test_resolving_an_uncontained_incident_is_a_state_conflict(api):
    """The response dimension is strictly REPORTED then CONTAINED then closed.

    PRD: "**Resolution** is a `PrivacyOfficeAdmin` operation, requires
    `response_status` to be exactly `CONTAINED` — otherwise
    `ERR_INCIDENT_STATE_INVALID` — and takes a `disposition` of `REMEDIATE` or
    `ESCALATE` plus an optional `remediation_note` that is recorded on the row."

    Design: Corner/state_machines/incident_resolve_before_containment_is_state_invalid
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-07-31T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=100,
        max_data_tier=2,
    )

    premature = api.resolve_incident(
        incident["id"],
        fac.resolution_payload(
            RESOLVE_REMEDIATE, remediation_note="Resolving before containment."
        ),
        ADMIN_HEADERS,
    )

    validate_error(premature, ERR_INCIDENT_STATE_INVALID, 409)
    still_reported = fx.read_incident(api, incident["id"])
    assert still_reported["response_status"] == INCIDENT_REPORTED, (
        f"Expected REPORTED, got {still_reported['response_status']}"
    )
    contained = fx.contain_incident(api, incident["id"], "2026-08-01T00:00:00Z")
    assert contained["response_status"] == INCIDENT_CONTAINED, (
        f"Expected CONTAINED, got {contained['response_status']}"
    )
    assert_instant_equals(
        contained["contained_at"], CLOCK_DEFAULT_RENDERED, "contained_at"
    )
    resolved = fx.resolve_incident(
        api,
        incident["id"],
        RESOLVE_REMEDIATE,
        remediation_note="Deletion certificate received.",
    )
    assert resolved["response_status"] == INCIDENT_REMEDIATED, (
        f"Expected REMEDIATED, got {resolved['response_status']}"
    )
    assert resolved["notification_status"] == NOTIFICATION_PENDING, (
        "The response dimension never touches the notification dimension, got "
        f"{resolved['notification_status']}"
    )
    owner = fx.read_vendor(api, vendor["id"])
    assert_integer_equals(owner["open_incident_count"], 0, "open_incident_count")


def test_a_rejected_commitment_can_be_neither_re_rejected_nor_resurrected(api):
    """REJECTED is terminal in both directions, and the rung is rung 13.

    PRD: "The commitment itself must still be dispositionable — `PROPOSED` or
    `ACCEPTED` — because `REJECTED` and `SUPERSEDED` are terminal and yield
    `ERR_COMMITMENT_ALREADY_DECIDED`."

    Design: Corner/state_machines/rejected_commitment_is_terminal_for_decide
    """
    chain = fx.screening_review_chain(api, **_primary_school_chain(api))
    commitment = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    fx.decide_commitment(
        api, commitment["id"], DISPOSITION_REJECT, chain.decider_headers
    )

    second_reject = api.decide_commitment(
        commitment["id"], {"disposition": DISPOSITION_REJECT}, chain.decider_headers
    )
    resurrection = api.decide_commitment(
        commitment["id"], {"disposition": DISPOSITION_ACCEPT}, chain.decider_headers
    )

    validate_error(second_reject, ERR_COMMITMENT_ALREADY_DECIDED, 409)
    validate_error(resurrection, ERR_COMMITMENT_ALREADY_DECIDED, 409)
    after = fx.read_commitment(api, commitment["id"])
    assert after["status"] == COMMITMENT_REJECTED, (
        f"Expected REJECTED, got {after['status']}"
    )
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert_decimal_equals(vendor["risk_score"], "0.00", "risk_score")


# ---------------------------------------------------------------------------
# The negotiation cycle and the idempotent triage
# ---------------------------------------------------------------------------


def test_the_findings_loop_stops_at_the_third_round(api):
    """round_number is monotone and capped, so a fourth round is refused.

    PRD: "A round issued out of `REMEDIATION_SUBMITTED` increases `round_number`
    by 1, and that increase may never carry the counter past 3: a fourth round is
    refused with `ERR_REMEDIATION_ROUND_LIMIT`."

    Design: Corner/state_machines/findings_remediation_loop_terminates_at_the_third_round
    """
    chain = fx.screening_review_chain(api, **_primary_school_chain(api))
    fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    for round_number, findings_count in ((1, 3), (2, 2), (3, 1)):
        fx.issue_findings(
            api,
            chain.review_id,
            findings_count,
            chain.assignee_headers,
            decision_note=f"Round {round_number}.",
        )
        fx.submit_remediation(
            api,
            chain.review_id,
            1,
            chain.liaison_headers,
            remediation_note=f"Round {round_number} remediation.",
        )

    response = api.issue_findings(
        chain.review_id,
        fac.findings_payload(1, decision_note="Round 4 attempt."),
        chain.assignee_headers,
    )

    validate_error(response, ERR_REMEDIATION_ROUND_LIMIT, 409)
    review = fx.read_review(api, chain.review_id)
    assert_integer_equals(review["round_number"], 3, "round_number")
    assert review["status"] == REVIEW_REMEDIATION_SUBMITTED, (
        f"The refused round leaves the loop where it was, got {review['status']}"
    )
    assert_integer_equals(review["open_findings_count"], 0, "open_findings_count")
    assert_integer_equals(
        review["unresolved_findings_count"], 0, "unresolved_findings_count"
    )
    assert_instant_equals(
        review["remediation_due_at"], "2026-08-15T00:00:00.000Z", "remediation_due_at"
    )


def test_a_second_detection_triage_is_refused_as_already_triaged(api):
    """All four triage outcomes are terminal, whatever the second disposition is.

    PRD: "**Triage** is performed by a `PrivacyOfficeAdmin` or a
    `PrivacyAnalyst`, who supply a `disposition` and an optional `note`, and it
    may happen only once: a detection whose `status` is no longer `NEW` is
    refused with `ERR_DETECTION_ALREADY_TRIAGED`."

    Design: Corner/state_machines/detection_second_triage_is_refused_as_already_triaged
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
    )
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, full_name="Ana Lopez", review_capacity_minutes=2400
    )
    detection = fx.observe_detection(
        api,
        "readers.brightpath.example",
        "2026-07-31T12:00:00Z",
        application_id=app["id"],
        school_code="ES-11",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )

    blocked = fx.triage_detection(api, detection["id"], TRIAGE_BLOCK, note="No authorization on file.")
    second = api.triage_detection(
        detection["id"],
        fac.detection_triage_payload(TRIAGE_ESCALATE, note="Second thoughts."),
        make_analyst_headers(analyst["id"]),
    )

    assert blocked["status"] == DETECTION_BLOCKED, (
        f"Expected BLOCKED, got {blocked['status']}"
    )
    assert blocked["classification"] == CLASSIFICATION_UNAUTHORIZED, (
        f"A matched application with no authorization is UNAUTHORIZED, got "
        f"{blocked['classification']}"
    )
    assert blocked["matched_catalog_entry_id"] is None, (
        f"No entry exists to match, got {blocked['matched_catalog_entry_id']!r}"
    )
    assert_decimal_equals(blocked["exposure_score"], "63.00", "exposure_score")
    validate_error(second, ERR_DETECTION_ALREADY_TRIAGED, 409)
    after = fx.read_detection(api, detection["id"])
    assert after["status"] == DETECTION_BLOCKED, (
        f"Expected BLOCKED, got {after['status']}"
    )
    assert after["linked_incident_id"] is None, (
        "The refused ESCALATE minted no incident, got "
        f"{after['linked_incident_id']!r}"
    )
    _rows, meta = validate_paginated(api.list_incidents(ADMIN_HEADERS, vendor_id=vendor["id"]))
    assert meta["total_count"] == 0, (
        f"Expected no incidents, got {meta['total_count']}"
    )


def test_re_authoring_an_element_supersedes_the_earlier_proposal(api):
    """One element never holds two PROPOSED rows at once.

    PRD: "When a new commitment is created for a review and element code that
    already has a `PROPOSED` commitment, the system moves that earlier row to the
    terminal `SUPERSEDED` state, records the new row's identifier in the earlier
    row's `superseded_by_commitment_id`, and advances the earlier row's
    `version`."

    Design: Corner/state_machines/duplicate_element_code_supersedes_the_earlier_proposed_commitment
    """
    chain = fx.screening_review_chain(api, **_primary_school_chain(api))
    earlier = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )

    later = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )

    assert later["status"] == COMMITMENT_PROPOSED, (
        f"Expected PROPOSED, got {later['status']}"
    )
    assert_integer_equals(later["sensitivity_tier"], 1, "sensitivity_tier")
    superseded = fx.read_commitment(api, earlier["id"])
    assert superseded["status"] == COMMITMENT_SUPERSEDED, (
        f"Expected SUPERSEDED, got {superseded['status']}"
    )
    assert superseded["superseded_by_commitment_id"] == later["id"], (
        "The earlier row must point at the new row, got "
        f"{superseded['superseded_by_commitment_id']!r}"
    )
    assert later["superseded_by_commitment_id"] is None, (
        f"The survivor points at nobody, got {later['superseded_by_commitment_id']!r}"
    )
    _rows, meta = validate_paginated(
        api.list_commitments(ADMIN_HEADERS, review_id=chain.review_id, status=COMMITMENT_PROPOSED)
    )
    assert meta["total_count"] == 1, (
        f"Exactly one PROPOSED row survives, got {meta['total_count']}"
    )
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )


def test_revoking_an_entry_the_sweep_expired_is_refused(api):
    """A window already behind the clock lands on EXPIRED in one pass.

    PRD: "Revocation is the district's early exit, available to a
    `PrivacyOfficeAdmin` on an entry in `PUBLISHED`, `EXPIRING_SOON` or
    `SUSPENDED_HOLD`; any other status is refused with
    `ERR_CATALOG_ENTRY_NOT_ACTIVE`."

    Design: Corner/state_machines/revoke_an_expired_catalog_entry_is_not_active
    """
    chain = _cleared_chain_with_one_accepted_element(api)
    entry = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.set_clock(api, CLOCK_PAST_A_ONE_MONTH_WINDOW)

    sweep = fx.run_sweep(api)
    late_revocation = api.revoke_catalog_entry(
        entry["id"], fac.revoke_payload("Late withdrawal attempt."), ADMIN_HEADERS
    )

    assert_integer_equals(sweep["evaluated_entry_count"], 1, "evaluated_entry_count")
    assert_integer_equals(sweep["expiring_soon_count"], 0, "expiring_soon_count")
    assert_integer_equals(sweep["expired_count"], 1, "expired_count")
    assert_integer_equals(
        sweep["overdue_notification_count"], 0, "overdue_notification_count"
    )
    expired = fx.read_entry(api, entry["id"])
    assert expired["status"] == ENTRY_EXPIRED, (
        f"The clock is past expires_at, got {expired['status']}"
    )
    assert_instant_equals(
        expired["reauthorization_due_at"],
        "2026-08-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"Expected HIDDEN, got {app['catalog_visibility']}"
    )
    validate_error(late_revocation, ERR_CATALOG_ENTRY_NOT_ACTIVE, 409)
    after = fx.read_entry(api, entry["id"])
    assert after["status"] == ENTRY_EXPIRED, (
        f"The refused revocation changes nothing, got {after['status']}"
    )
    assert after["revoked_reason"] is None, (
        f"Expected revoked_reason null, got {after['revoked_reason']!r}"
    )


# ---------------------------------------------------------------------------
# Terminal lockdown at the two ends of the review workflow
# ---------------------------------------------------------------------------


def test_triaging_a_draft_request_is_a_state_conflict(api):
    """Scoring happens at submit, so a draft has nothing to triage.

    PRD: "Only a `SUBMITTED` request may be triaged; anything else is
    `ERR_REQUEST_STATE_INVALID`."

    Design: Corner/state_machines/triage_a_draft_request_is_state_invalid
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
    )
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7108",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, full_name="Ana Lopez", review_capacity_minutes=2400
    )
    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        make_teacher_headers(teacher["id"]),
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )

    response = api.triage_request(
        request["id"],
        fac.triage_payload(TRIAGE_ACCEPT_FOR_REVIEW, triage_note="Triaging a draft."),
        make_analyst_headers(analyst["id"]),
    )

    validate_error(response, ERR_REQUEST_STATE_INVALID, 409)
    after = fx.read_request(api, request["id"])
    assert after["status"] == REQUEST_DRAFT, (
        f"Expected DRAFT, got {after['status']}"
    )
    assert_decimal_equals(after["priority_score"], "0.00", "priority_score")
    assert after["priority_band"] == BAND_LOW, (
        f"A drafted request carries the LOW band, got {after['priority_band']}"
    )
    assert after["triage_note"] is None, (
        f"A refused triage records no note, got {after['triage_note']!r}"
    )
    application = fx.read_application(api, app["id"])
    assert application["status"] == APPLICATION_CANDIDATE, (
        f"Expected CANDIDATE, got {application['status']}"
    )


def test_a_second_decision_on_a_cleared_review_is_refused(api):
    """CLEARED is terminal, so the rung is the already-decided one.

    PRD: "a review already in `CLEARED`, `CONDITIONAL` or `BLOCKED` is refused
    one rung later with `ERR_REVIEW_ALREADY_DECIDED`."

    Design: Corner/state_machines/review_second_decide_is_refused_as_already_decided
    """
    chain = _cleared_chain_with_one_accepted_element(api)
    decided = fx.read_review(api, chain.review_id)
    version_after_first_decision = decided["version"]

    response = api.decide_review(
        chain.review_id,
        fac.decision_payload(
            DECISION_BLOCK, decision_note="Reversing the decision."
        ),
        chain.decider_headers,
    )

    validate_error(response, ERR_REVIEW_ALREADY_DECIDED, 409)
    after = fx.read_review(api, chain.review_id)
    assert after["status"] == REVIEW_CLEARED, (
        f"Expected CLEARED, got {after['status']}"
    )
    assert_decimal_equals(
        after["final_compliance_score"], "100.00", "final_compliance_score"
    )
    assert_integer_equals(
        after["version"], version_after_first_decision, "review version"
    )
    app = fx.read_application(api, chain.application_id)
    assert app["status"] == APPLICATION_APPROVED, (
        f"The refused call cascaded nothing, got {app['status']}"
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert vendor["status"] == VENDOR_APPROVED, (
        f"Expected APPROVED, got {vendor['status']}"
    )
