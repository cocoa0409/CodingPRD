"""Archival deposit evidence and the two gates in front of a cancellation."""

from test_helpers import (
    archival_check_payload,
    assert_archival_check,
    assert_commitment,
    assert_subscription,
    attest_archival_check,
    open_archival_check,
    read_commitment,
    read_member,
    read_subscription,
    report_incident,
    set_clock,
    setup_active_subscription,
    setup_cancel_ready,
    setup_configured_access,
    subscription_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _only_check(api, headers, subscription_id):
    """The single archival deposit check of a subscription, read from its listing."""
    rows, meta = validate_paginated(api.list_archival_checks(subscription_id, headers))
    assert meta["total_count"] == 1
    return rows[0]


def test_archival_check_create_with_the_observed_version_succeeds_and_bumps_it(api, admin):
    """A freshly observed version is accepted, and the write moves the version on.

    PRD: "The check is created in `PENDING` with `attested_title_count` and
    `coverage_pct` both null, and the creation increments the subscription's
    `version` by 1."

    PRD: "`POST /erm/subscriptions/{id}/archival-checks` likewise requires
    `expected_subscription_version` as a non-optional body field carrying the
    client's last observed subscription `version`, and likewise rejects a mismatch
    with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/archival_check_create_with_the_observed_version_succeeds_and_bumps_it
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    observed_version = subscription_version(subscription_id)

    response = api.create_archival_check(
        subscription_id,
        archival_check_payload(observed_version, "PORTICO", 380),
        admin,
    )
    data = validate_success(response, expected_status=201)

    assert_archival_check(data)
    assert data["status"] == "PENDING"
    assert data["agency_code"] == "PORTICO"
    assert data["deposited_title_count"] == 380
    assert data["attested_title_count"] is None, "the publisher has not spoken yet"
    assert data["coverage_pct"] is None
    assert data["subscription_id"] == subscription_id

    assert subscription_version(subscription_id) != observed_version, (
        "the client's captured version is now stale for any follow-up write"
    )
    _, meta = validate_paginated(api.list_archival_checks(subscription_id, admin))
    assert meta["total_count"] == 1


def test_archival_check_create_with_a_stale_subscription_version_is_rejected(api, admin):
    """An incident filed in between moves the subscription and invalidates the view.

    PRD: "If the value does not equal the subscription's current `version`, the
    request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."

    PRD: "Here the risk is evidentiary: a new check supersedes the value of an
    earlier `FAILED` check for the cancellation gate, and coverage is measured
    against the subscription's current entitled title count, so a stale view would
    let the collections office record coverage against a title count that a
    restructuring has already changed."

    Design: Corner/cross_cutting_complexity_layers/archival_check_create_with_a_stale_subscription_version_is_rejected
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    observed_version = subscription_version(subscription_id)

    report_incident(subscription_id, scenario["member"]["id"], "OFF_CAMPUS_DENIED", True)
    assert read_subscription(subscription_id)["access_health_score"] == 92, (
        "one off-campus denial decays the score by eight points"
    )
    assert subscription_version(subscription_id) != observed_version, (
        "recomputing the score was a mutation of the subscription row"
    )

    response = api.create_archival_check(
        subscription_id,
        archival_check_payload(observed_version, "PORTICO", 380),
        admin,
    )
    validate_error(response, "ERR_STALE_SUBSCRIPTION_VERSION", 412)

    _, meta = validate_paginated(api.list_archival_checks(subscription_id, admin))
    assert meta["total_count"] == 0, "the stale create stored no evidence"
    assert read_subscription(subscription_id)["access_health_score"] == 92


def test_archival_check_against_a_foreign_agency_is_rejected(api, admin):
    """Evidence only counts at the agency the publisher actually deposits with.

    PRD: "The claimed agency must be the one the publisher actually deposits with:
    `agency_code` must equal the `archival_agency_code` of the subscription's
    product's vendor, and that vendor field must not be null."

    PRD: "A mismatch, or a vendor that deposits nowhere at all, is
    `ERR_ARCHIVAL_AGENCY_MISMATCH` (422)."

    Design: Corner/validations/archival_check_against_a_foreign_agency_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["vendor"]["archival_agency_code"] == "PORTICO"

    response = api.create_archival_check(
        subscription_id,
        archival_check_payload(subscription_version(subscription_id), "CLOCKSS", 380),
        admin,
    )
    validate_error(response, "ERR_ARCHIVAL_AGENCY_MISMATCH", 422)

    _, meta = validate_paginated(api.list_archival_checks(subscription_id, admin))
    assert meta["total_count"] == 0, "no check row was created for a foreign agency"
    assert read_subscription(subscription_id)["contract_status"] == "ACTIVE"


def test_verifying_an_unattested_archival_check_is_rejected(api, admin):
    """The publisher's attestation cannot be skipped on the way to VERIFIED.

    PRD: "Verification closes the loop and is a `ConsortiumAdmin` capability
    admissible only from `ATTESTED`."

    PRD: "Attestation is admissible from `PENDING`, advancing `PENDING → ATTESTED`,
    and also from `FAILED`, advancing `FAILED → ATTESTED`; the re-attestation path
    additionally clears `coverage_pct` back to null so that a stale coverage figure
    never survives a fresh claim."

    Design: Corner/errors/verifying_an_unattested_archival_check_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    check = open_archival_check(subscription_id, "PORTICO", 380)
    assert check["status"] == "PENDING"

    response = api.verify_archival_check(check["id"], admin)
    validate_error(response, "ERR_ARCHIVAL_CHECK_INVALID_STATE", 409)

    stored = _only_check(api, admin, subscription_id)
    assert_archival_check(stored)
    assert stored["status"] == "PENDING", "the refused verification moved nothing"
    assert stored["attested_title_count"] is None
    assert stored["coverage_pct"] is None, "no coverage figure was computed"
    assert stored["deposited_title_count"] == 380


def test_archival_verify_with_a_twenty_title_discrepancy_is_rejected(api, admin):
    """The tolerance check runs before coverage, so no percentage is ever written.

    PRD: "Before any coverage is computed, the two title counts must agree within
    tolerance: the absolute difference between `attested_title_count` and
    `deposited_title_count` must be no more than 5 titles, and a wider gap is
    `ERR_ARCHIVAL_COUNT_DISCREPANCY` (409) — the publisher and the agency are
    telling materially different stories and no coverage figure computed from either
    would mean anything."

    Design: Corner/validations/archival_verify_with_a_twenty_title_discrepancy_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    check = open_archival_check(subscription_id, "PORTICO", 380)
    attested = attest_archival_check(check["id"], 360, scenario["vendor"]["id"])
    assert attested["status"] == "ATTESTED"

    response = api.verify_archival_check(check["id"], admin)
    validate_error(response, "ERR_ARCHIVAL_COUNT_DISCREPANCY", 409)

    stored = _only_check(api, admin, subscription_id)
    assert stored["status"] == "ATTESTED", "the fork was never reached"
    assert stored["attested_title_count"] == 360
    assert stored["deposited_title_count"] == 380, "a gap of twenty titles"
    assert stored["coverage_pct"] is None, (
        "90.00 percent would also have failed, but it was never computed"
    )


def test_archival_coverage_just_below_the_threshold_fails_verification(api, admin):
    """94.75 percent is a quarter of a point short, so the fork goes the other way.

    PRD: "When they agree, **archival coverage** is computed as
    `attested_title_count` divided by the subscription's current
    `entitled_title_count`, multiplied by 100, and rounded half up to two decimal
    places."

    PRD: "If `coverage_pct` is greater than or equal to 95.00 percent the check
    advances `ATTESTED → VERIFIED`, and exactly 95.00 verifies; if it is strictly
    below 95.00 the check advances `ATTESTED → FAILED` instead, from where the
    publisher may attest again."

    Design: Corner/calculations/archival_coverage_just_below_the_threshold_fails_verification
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["entitled_title_count"] == 400
    check = open_archival_check(subscription_id, "PORTICO", 379)
    attest_archival_check(check["id"], 379, scenario["vendor"]["id"])

    response = api.verify_archival_check(check["id"], admin)
    data = validate_success(response)

    assert_archival_check(data)
    assert float(data["coverage_pct"]) == 94.75, "379 of 400 titles"
    assert data["status"] == "FAILED", "94.75 is strictly below the 95.00 threshold"
    assert data["attested_title_count"] == 379
    assert data["deposited_title_count"] == 379, "the two counts agree exactly"

    subscription = read_subscription(subscription_id)
    assert subscription["entitled_title_count"] == 400
    assert subscription["contract_status"] == "ACTIVE"


def test_cancellation_execution_releases_the_pledge_and_writes_the_access_axis(api, admin):
    """One call closes the contract, writes the other axis and unwinds the ledger.

    PRD: "When those gates clear, the decision advances `DECIDED_CANCEL → EXECUTED`
    and three things happen to the wider system. The subscription's contract axis
    advances `NOTICE_GIVEN → CANCELLED`. Its access axis is written — this is the
    single point at which the contract axis writes the access axis — becoming
    `POST_CANCELLATION` when `perpetual_access_mode` is either
    `POST_CANCELLATION_SUBSET` or `FULL_ARCHIVE`, and `SUSPENDED` when
    `perpetual_access_mode` is `NONE`."

    PRD: "And the money unwinds: every commitment row on the subscription whose
    `status` is `CONFIRMED` becomes `RELEASED`, with its `tier_price_cents`
    subtracted from `annual_committed_cents` on the owning member, and any member
    whose ledger falls back to a value at or below its `budget_ceiling_cents` has
    `standing` restored to `IN_GOOD_STANDING`."

    Design: Corner/state_machines/cancellation_execution_releases_the_pledge_and_writes_the_access_axis
    """
    scenario = setup_cancel_ready()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["perpetual_access_mode"] == "FULL_ARCHIVE"
    assert scenario["subscription"]["contract_status"] == "NOTICE_GIVEN"
    assert float(scenario["archival_check"]["coverage_pct"]) == 95.00
    assert scenario["archival_check"]["status"] == "VERIFIED"
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000
    set_clock("2027-06-01T00:00:00Z")

    response = api.execute_renewal(scenario["decision"]["id"], admin)
    data = validate_success(response)

    assert data["status"] == "EXECUTED"
    assert data["resolved_action"] == "CANCEL"

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["contract_status"] == "CANCELLED"
    assert subscription["access_status"] == "POST_CANCELLATION", (
        "a FULL_ARCHIVE term keeps rights after the contract closes"
    )

    commitment = read_commitment(scenario["commitment"]["id"])
    assert_commitment(commitment)
    assert commitment["status"] == "RELEASED"

    member = read_member(scenario["member"]["id"])
    assert member["annual_committed_cents"] == 0, "the exact 4,500,000 was subtracted"
    assert member["standing"] == "IN_GOOD_STANDING"


def test_cancel_execution_after_the_notice_deadline_is_rejected(api, admin):
    """Verified evidence does not buy an extra month past the deadline.

    PRD: "The second is **temporal**: the logical clock's calendar date must be less
    than or equal to the subscription's `notice_deadline_date`, otherwise
    `ERR_NOTICE_DEADLINE_PASSED` (409)."

    PRD: "Executing on the deadline date itself is timely; executing the day after is
    not, and the consortium is stuck with another term."

    Design: Corner/errors/cancel_execution_after_the_notice_deadline_is_rejected
    """
    scenario = setup_cancel_ready()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["notice_deadline_date"] == "2027-10-02"
    assert scenario["archival_check"]["status"] == "VERIFIED", "the archival gate passes"
    set_clock("2027-11-01T00:00:00Z")

    response = api.execute_renewal(scenario["decision"]["id"], admin)
    validate_error(response, "ERR_NOTICE_DEADLINE_PASSED", 409)

    stored = _only_check(api, admin, subscription_id)
    assert stored["status"] == "VERIFIED"
    assert float(stored["coverage_pct"]) == 95.00

    subscription = read_subscription(subscription_id)
    assert subscription["contract_status"] == "NOTICE_GIVEN", "the notice still stands"
    assert subscription["notice_deadline_date"] == "2027-10-02"
    assert read_commitment(scenario["commitment"]["id"])["status"] == "CONFIRMED", (
        "the money did not unwind"
    )
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000


def _cancellation_violating_both_gates():
    """A DECIDED_CANCEL whose only evidence FAILED, executed a month past the deadline."""
    scenario = setup_cancel_ready(deposited_title_count=360)
    set_clock("2027-11-01T00:00:00Z")
    return scenario


def test_cancel_execution_reports_the_unverified_archive_not_the_passed_deadline(api, admin):
    """Two gates are violated at once and the archival one at priority 14 answers.

    PRD: "A cancellation execution attempted after the notice deadline **and**
    without a verified archival deposit reports `ERR_ARCHIVAL_DEPOSIT_UNVERIFIED`,
    because the archival gate sits at priority 14 and the deadline gate at priority
    18."

    PRD: "The first gate is **archival**: at least one archival deposit check on the
    subscription must have reached `VERIFIED`, otherwise
    `ERR_ARCHIVAL_DEPOSIT_UNVERIFIED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/cancel_execution_reports_unverified_archive_before_notice_deadline
    """
    scenario = _cancellation_violating_both_gates()
    subscription_id = scenario["subscription"]["id"]
    check = scenario["archival_check"]
    assert float(check["coverage_pct"]) == 90.00, "360 attested of 400 entitled"
    assert check["status"] == "FAILED"
    assert scenario["subscription"]["notice_deadline_date"] == "2027-10-02"

    response = api.execute_renewal(scenario["decision"]["id"], admin)
    error = validate_error(response, "ERR_ARCHIVAL_DEPOSIT_UNVERIFIED", 409)
    assert error["error_id"] != "ERR_NOTICE_DEADLINE_PASSED", (
        "the temporal rule is violated too, but it sits four priorities lower"
    )

    stored = _only_check(api, admin, subscription_id)
    assert stored["status"] == "FAILED", "the refusal did not touch the evidence"
    assert float(stored["coverage_pct"]) == 90.00

    subscription = read_subscription(subscription_id)
    assert subscription["contract_status"] == "NOTICE_GIVEN"
    assert read_commitment(scenario["commitment"]["id"])["status"] == "CONFIRMED"


def test_supplying_verified_evidence_uncovers_the_deadline_violation(api, admin):
    """Repairing the higher-priority gate lets the rule it was masking surface.

    PRD: "The consequence worth internalising is that structural failures always mask
    business failures, and that within the business band the ordering above is
    authoritative."

    PRD: "Here the risk is evidentiary: a new check supersedes the value of an
    earlier `FAILED` check for the cancellation gate, and coverage is measured
    against the subscription's current entitled title count, so a stale view would
    let the collections office record coverage against a title count that a
    restructuring has already changed."

    Design: Difficulty/priority_pair_validation_conflict/cancel_execution_reports_unverified_archive_before_notice_deadline
    """
    scenario = _cancellation_violating_both_gates()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    validate_error(api.execute_renewal(decision_id, admin),
                   "ERR_ARCHIVAL_DEPOSIT_UNVERIFIED", 409)

    second = open_archival_check(subscription_id, "PORTICO", 380)
    attest_archival_check(second["id"], 380, scenario["vendor"]["id"])
    verified = validate_success(api.verify_archival_check(second["id"], admin))
    assert verified["status"] == "VERIFIED"
    assert float(verified["coverage_pct"]) == 95.00, "380 of 400 is exactly the threshold"

    response = api.execute_renewal(decision_id, admin)
    validate_error(response, "ERR_NOTICE_DEADLINE_PASSED", 409)

    rows, meta = validate_paginated(api.list_archival_checks(subscription_id, admin))
    assert meta["total_count"] == 2, "the failed check is kept alongside the new one"
    assert {row["status"] for row in rows} == {"FAILED", "VERIFIED"}

    subscription = read_subscription(subscription_id)
    assert subscription["contract_status"] == "NOTICE_GIVEN", (
        "the deadline gate is a wall the evidence cannot climb"
    )
    assert subscription["negotiated_price_cents"] == 9000000
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000
