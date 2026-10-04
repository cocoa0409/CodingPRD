"""Credential lifecycle: not-found reads, the strictly-greater lapse and
expiry boundaries, the renewal window, the late-renewal fee, and the state
error outranking the window error on a REVOKED credential.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    REGISTRAR,
    RENEWAL_BASE_FEE_CENTS,
    RENEWAL_FEE_WHEN_LAPSED_CENTS,
    ApiErrorId,
    add_days,
    create_pd_event,
    date_of,
    make_adult_learner_headers,
    make_reviewer_headers,
    read_credential,
    record_attendance,
    renew_credential,
    renew_credential_payload,
    renewal_window_open_date,
    reset_clock,
    revoke_credential,
    set_clock,
    set_clock_past_expiry,
    set_clock_past_grace,
    setup_credentialed_teacher,
    validate_error,
)


def test_credential_get_unknown_id_returns_not_found(api):
    """PRD section 2.7: "Tier 3 is existence: path identifiers are validated
    left to right, then body-supplied foreign keys that are present and
    well-formed — `school_id`, `learner_id`, `classroom_id`, `credential_id`,
    `self_study_id`, `supervisor_credential_id`, `host_school_id`,
    `to_classroom_id`, `visit_id` — each failing with its entity-specific 404".

    Design: Corner/entities/credential_get_unknown_id_returns_not_found
    """
    reset_clock()
    resp = api.get_credential(NON_EXISTENT_UUID, headers=REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_FOUND)


def test_credential_lapses_only_after_expiry_date_boundary(api):
    """PRD section 2.5: "A `Credential` in `ACTIVE` flips to `LAPSED` when the
    current logical date becomes strictly greater than the date of its
    `expires_at`".

    Design: Corner/state_machines/credential_lapses_only_after_expiry_date_boundary
    """
    reset_clock()
    teacher = setup_credentialed_teacher(learner_name="Boundary Learner")
    credential = teacher.credential
    assert date_of(credential["expires_at"]) == "2029-09-01"

    set_clock("2029-09-01T00:00:00Z")
    on_date = read_credential(credential["id"])
    assert on_date["status"] == "ACTIVE", "strictly-greater comparison: still ACTIVE on the date"

    set_clock("2029-09-02T00:00:00Z")
    day_after = read_credential(credential["id"])
    assert day_after["status"] == "LAPSED"


def test_renewal_before_window_open_rejected(api):
    """PRD section 3.5: "the renewal window: the current logical date must fall
    inside the inclusive interval that opens `renewal_window_months` before the
    date of `expires_at` and closes `renewal_grace_months` after it — both
    boundary dates themselves qualify — otherwise `ERR_RENEWAL_WINDOW_CLOSED`
    (HTTP 422)".

    Design: Corner/validations/renewal_before_window_open_rejected
    """
    reset_clock()
    teacher = setup_credentialed_teacher(learner_name="Window Learner")
    credential = teacher.credential
    window_opens = renewal_window_open_date(credential)
    assert window_opens == "2029-06-01"

    set_clock(add_days(window_opens, -1) + "T00:00:00Z")
    rejected = api.renew_credential(
        credential["id"],
        renew_credential_payload(RENEWAL_BASE_FEE_CENTS),
        headers=make_adult_learner_headers(teacher.learner["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
    credential = read_credential(credential["id"])
    assert credential["status"] == "ACTIVE"
    assert credential["renewed_count"] == 0


def _teacher_with_30_ce_hours():
    """Credentialed teacher plus exactly 30 CE hours (18 + 12) earned in
    February 2027 — qualifies under the CYCLE variant at the first window."""
    teacher = setup_credentialed_teacher()
    event18 = create_pd_event()
    event12 = create_pd_event(
        start_at="2027-02-27T09:00:00Z", end_at="2027-03-01T17:00:00Z", ce_hours=12
    )
    set_clock("2027-03-02T00:00:00Z")
    record_attendance(event18["id"], teacher.credential["id"])
    record_attendance(event12["id"], teacher.credential["id"])
    return teacher


def test_credential_lapses_then_late_renewal_inside_grace(api):
    """PRD section 3.5: "A successful renewal from `ACTIVE` — or a late renewal
    from `LAPSED` inside the grace window — returns the credential to `ACTIVE`,
    sets `cycle_start` to the current logical date, recomputes `expires_at` as
    today plus the `ACTIVE` catalog's `credential_validity_months`, increments
    `renewed_count`, refreshes `issued_at` to now". PRD section 3.5: "the
    expected amount is 8500 cents, plus a 5000-cent late fee when the
    credential is `LAPSED`".

    Design: Difficulty/non_linear_state_machine/credential_lapse_renew_cycle
    """
    reset_clock()
    teacher = _teacher_with_30_ce_hours()
    credential = read_credential(teacher.credential["id"])

    set_clock_past_expiry(credential)
    assert read_credential(credential["id"])["status"] == "LAPSED"

    renewed = renew_credential(
        credential["id"], learner_id=teacher.learner["id"], fee_cents=RENEWAL_FEE_WHEN_LAPSED_CENTS
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 1
    assert renewed["cycle_start"] == "2029-09-02"
    assert date_of(renewed["expires_at"]) == "2032-09-02"


def test_credential_expires_past_grace_and_renew_rejected(api):
    """PRD section 2.5: "a `LAPSED` credential flips to `EXPIRED` when the
    current logical date becomes strictly greater than the date of `expires_at`
    extended by the `ACTIVE` catalog's `renewal_grace_months`". PRD section
    3.5: "a `REVOKED` or `EXPIRED` one fails with
    `ERR_CREDENTIAL_NOT_RENEWABLE` (HTTP 409), which outranks any window
    error".

    Design: Difficulty/non_linear_state_machine/credential_lapse_renew_cycle
    """
    reset_clock()
    teacher = setup_credentialed_teacher()
    credential = read_credential(teacher.credential["id"])

    set_clock_past_expiry(credential)
    lapsed = read_credential(credential["id"])
    assert lapsed["status"] == "LAPSED"
    set_clock_past_grace(lapsed)
    expired = read_credential(credential["id"])
    assert expired["status"] == "EXPIRED"

    rejected = api.renew_credential(
        credential["id"],
        renew_credential_payload(RENEWAL_FEE_WHEN_LAPSED_CENTS),
        headers=make_adult_learner_headers(teacher.learner["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_CREDENTIAL_NOT_RENEWABLE)


def _revoked_credential_at_closed_window():
    """Credential issued at the clock baseline, immediately revoked (no
    classroom ever leads with it), clock then advanced past the grace end so
    the renewal window is closed too."""
    teacher = setup_credentialed_teacher(learner_name="Prio Learner")
    revoke_credential(
        teacher.credential["id"],
        reviewer_headers=make_reviewer_headers("rev-mira"),
        reason="Fabricated CE records",
    )
    set_clock("2030-06-01T00:00:00Z")
    return teacher


def test_renew_on_revoked_credential_rejected_with_state_error(api):
    """PRD section 3.5: "First, state: only an `ACTIVE` or `LAPSED` credential
    can renew; a `REVOKED` or `EXPIRED` one fails with
    `ERR_CREDENTIAL_NOT_RENEWABLE` (HTTP 409), which outranks any window
    error." At 2030-06-01 the grace window (ending 2030-03-01) is also closed,
    yet the state error — not `ERR_RENEWAL_WINDOW_CLOSED` — is returned.

    Design: Difficulty/priority_pair_validation_conflict/renew_on_revoked_credential_rejected_with_state_error_over_window_error
    """
    reset_clock()
    teacher = _revoked_credential_at_closed_window()
    rejected = api.renew_credential(
        teacher.credential["id"],
        renew_credential_payload(RENEWAL_BASE_FEE_CENTS),
        headers=make_adult_learner_headers(teacher.learner["id"]),
    )
    error = validate_error(rejected, ApiErrorId.ERR_CREDENTIAL_NOT_RENEWABLE)
    assert error["error_id"] != ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value


def test_rejected_renew_leaves_revoked_credential_unchanged(api):
    """PRD section 3.5: "a `REVOKED` or `EXPIRED` one fails with
    `ERR_CREDENTIAL_NOT_RENEWABLE` (HTTP 409)". PRD section 3.5: "Revocation is
    the disciplinary exit, taken by an `AccreditationReviewer` with an optional
    `reason`, from either `ACTIVE` or `LAPSED`; any other state fails with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/renew_on_revoked_credential_rejected_with_state_error_over_window_error
    """
    reset_clock()
    teacher = _revoked_credential_at_closed_window()
    api.renew_credential(
        teacher.credential["id"],
        renew_credential_payload(RENEWAL_BASE_FEE_CENTS),
        headers=make_adult_learner_headers(teacher.learner["id"]),
    )
    credential = read_credential(teacher.credential["id"])
    assert credential["status"] == "REVOKED"
    assert credential["renewed_count"] == 0
