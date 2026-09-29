"""State-machine transitions: opening states, refused triggers and cascades.

Each test drives one lifecycle from an empty database — the harness restarts the
API server and empties the database before every test — moving the logical
compliance clock of PRD §2.5 explicitly so that every stamped instant asserted
below is deterministic.
"""

from test_helpers import (
    ACTIVATING_OFFICER,
    REGISTRY_ADMIN,
    T_ENROLL,
    T_PUBLISH,
    VETTING_ANALYST,
    VETTING_ANALYST_ALT,
    ApiErrorId,
    assert_customer_contract,
    assert_designation,
    assert_operating_authority,
    assert_risk_score,
    assert_safety_audit,
    assert_shipment,
    cancel_filing,
    create_carrier,
    create_draft_application,
    factories,
    file_insurance,
    list_designations,
    read_authority,
    set_clock,
    setup_active_authority,
    setup_active_authority_with_shipment,
    setup_pending_authority_with_coverage,
    setup_published_authority,
    setup_submitted_application,
    setup_suspended_with_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

# The frozen filing fee of a NEW / FOR_HIRE_PROPERTY application naming three
# operating states, in cents.
NEW_FOR_HIRE_THREE_STATES_FEE_CENTS = 64791


def test_application_starts_in_draft_before_anything_is_charged(api):
    """PRD §3.2: "A `CarrierRep` opens an application in `DRAFT` status by naming its own
    carrier through `carrier_id`, choosing the track it follows through `application_kind` —
    one of `NEW`, `NAME_CHANGE`, `REINSTATEMENT` or `SUCCESSOR_IN_INTEREST` — and choosing
    the class of authority requested through `transportation_type`, one of
    `FOR_HIRE_PROPERTY`, `HOUSEHOLD_GOODS`, `PASSENGER`, `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER`."
    PRD §3.2: "`submission_count` opens at zero."
    PRD §3.2: "Opening the draft immediately previews two calculations, and nothing is
    charged yet."
    PRD §3.3: "When `submission_count` becomes 1, the three required insurance minimums and
    the filing fee are recomputed and then **frozen**: `filing_fee_cents` and
    `filing_fee_breakdown` take their final values, a ledger entry with `entry_type`
    `FILING_FEE_DEBIT` and an `amount_cents` equal to positive `filing_fee_cents` is
    appended with its `docket_ref` naming this application, and both
    `fees_assessed_total_cents` and `fee_balance_cents` on the owning carrier increase by
    that amount."
    PRD §3.3: "It also creates a brand-new `OperatingAuthority`, described in §3.4."
    PRD §3.4: "The authority is found by listing authorities filtered on `application_id`."

    Design: Corner/state_machines/application_starts_in_draft_with_a_zero_fee
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Caprock Motor Lines LLC")

    application = create_draft_application(
        api,
        carrier["id"],
        application_kind="NEW",
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=["TX", "OK", "NM"],
    )

    assert application["status"] == "DRAFT", (
        f"a freshly opened application is DRAFT, got {application['status']}"
    )
    assert application["submission_count"] == 0

    # Nothing is charged yet: no ledger entry and no movement on the carrier.
    after = validate_success(api.get_carrier(carrier["id"], REGISTRY_ADMIN))
    assert after["fee_balance_cents"] == 0
    assert after["fees_assessed_total_cents"] == 0
    assert after["fees_reversed_total_cents"] == 0
    assert after["fees_paid_total_cents"] == 0

    _entries, ledger_meta = validate_paginated(
        api.list_fee_ledger_entries(carrier["id"], REGISTRY_ADMIN)
    )
    assert ledger_meta["total_count"] == 0, (
        "a draft appends no ledger entry, got total_count "
        f"{ledger_meta['total_count']}"
    )

    # No authority exists until a publish disposition mints one.
    _rows, authority_meta = validate_paginated(
        api.list_authorities(REGISTRY_ADMIN, application_id=application["id"])
    )
    assert authority_meta["total_count"] == 0, (
        "an authority is minted only by a publish disposition, got total_count "
        f"{authority_meta['total_count']}"
    )


def test_submit_on_a_published_application_is_rejected(api):
    """PRD §3.3: "Submitting an application that is already `PUBLISHED`, `GRANTED` or
    `DENIED`, or reviewing one that is not `SUBMITTED`, is rejected with
    `ERR_APPLICATION_INVALID_STATE`."
    PRD §3.3: "Every successful submission increases `submission_count` by one, and the
    first one is special."
    PRD §3.3: "The fee is assessed exactly once per application no matter how many
    correction loops it makes."
    PRD §3.3: "When `submission_count` becomes 1, the three required insurance minimums and
    the filing fee are recomputed and then **frozen**: `filing_fee_cents` and
    `filing_fee_breakdown` take their final values, a ledger entry with `entry_type`
    `FILING_FEE_DEBIT` and an `amount_cents` equal to positive `filing_fee_cents` is
    appended with its `docket_ref` naming this application, and both
    `fees_assessed_total_cents` and `fee_balance_cents` on the owning carrier increase by
    that amount."
    PRD §3.2: "`line_docket_cents` — the docket base of 30000 cents, multiplied by the track
    multiplier and then by the administrative surcharge factor, rounded half-up to whole
    cents."
    PRD §3.2: "`line_states_cents` — a per-state surcharge of 137 cents multiplied by the
    number of entries in `requested_operating_states` and then by the administrative
    surcharge factor, rounded half-up to whole cents."
    PRD §3.2: "`line_type_cents` — the class fee keyed on `transportation_type` (45000 cents
    for `HOUSEHOLD_GOODS` and for `PASSENGER`; 30000 cents for `FOR_HIRE_PROPERTY`,
    `PROPERTY_BROKER` and `FREIGHT_FORWARDER`), multiplied by the track multiplier and then
    by the administrative surcharge factor, rounded half-up to whole cents."
    PRD §3.2: "when it is false, this line is exactly zero."
    PRD §3.2: "`filing_fee_cents` is the sum of those four already-rounded lines, and
    `filing_fee_breakdown` records all four of them under the keys `line_docket_cents`,
    `line_states_cents`, `line_type_cents` and `line_hazmat_cents`."

    Design: Corner/state_machines/submit_on_a_published_application_is_rejected
    """
    env = setup_published_authority(
        api,
        application_kwargs={
            "application_kind": "NEW",
            "transportation_type": "FOR_HIRE_PROPERTY",
            "requested_operating_states": ["TX", "OK", "NM"],
        },
    )
    assert env.application["status"] == "PUBLISHED"
    assert env.filing_fee_cents == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS, (
        "the four per-line rounded amounts sum to 64791 cents, got "
        f"{env.filing_fee_cents}"
    )

    validate_error(
        api.submit_application(env.application_id, env.carrier_headers),
        ApiErrorId.APPLICATION_INVALID_STATE,
    )

    # The refused trigger moved nothing: not the application, not the fee.
    application = validate_success(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "PUBLISHED"
    assert application["submission_count"] == 1, (
        f"the refused submit did not count, got {application['submission_count']}"
    )

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fee_balance_cents"] == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS
    assert carrier["fees_assessed_total_cents"] == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS
    assert carrier["fees_reversed_total_cents"] == 0

    _entries, ledger_meta = validate_paginated(
        api.list_fee_ledger_entries(env.carrier_id, REGISTRY_ADMIN)
    )
    assert ledger_meta["total_count"] == 1, (
        "the fee is assessed exactly once and the refused submit appends nothing, "
        f"got total_count {ledger_meta['total_count']}"
    )


def test_vetting_review_on_a_denied_application_is_rejected(api):
    """PRD §3.3: "Submitting an application that is already `PUBLISHED`, `GRANTED` or
    `DENIED`, or reviewing one that is not `SUBMITTED`, is rejected with
    `ERR_APPLICATION_INVALID_STATE`."
    PRD §3.3: "The application's own terminal states are `GRANTED` and `DENIED`; `GRANTED` is
    never reached by a review, only as a consequence of activation (§3.6)."
    PRD §3.3: "**`DENY`** moves the application `SUBMITTED → DENIED`, which is terminal, and
    captures the findings text into `denied_reason`. No authority is created. Denial is the
    compensating action for submission: a ledger entry with `entry_type`
    `FILING_FEE_REVERSAL_CREDIT` and an `amount_cents` equal to the negation of
    `filing_fee_cents` is appended with `docket_ref` naming this application,
    `fees_reversed_total_cents` increases by `filing_fee_cents`, and `fee_balance_cents`
    decreases by the same amount."
    PRD §3.3: "Because denial is the true inverse of submission, a submit-then-deny round
    trip must leave `fee_balance_cents` and the difference between
    `fees_assessed_total_cents` and `fees_reversed_total_cents` at exactly the values they
    held before the submission."
    PRD §3.3: "**`PUBLISH`** moves the application `SUBMITTED → PUBLISHED`, stamps
    `published_at` with the current logical time and records the acting analyst into
    `published_by_user_id` as well as `vetted_by_user_id`."
    PRD §3.2: "`line_docket_cents` — the docket base of 30000 cents, multiplied by the track
    multiplier and then by the administrative surcharge factor, rounded half-up to whole
    cents."
    PRD §3.2: "`line_states_cents` — a per-state surcharge of 137 cents multiplied by the
    number of entries in `requested_operating_states` and then by the administrative
    surcharge factor, rounded half-up to whole cents."
    PRD §3.2: "`line_type_cents` — the class fee keyed on `transportation_type` (45000 cents
    for `HOUSEHOLD_GOODS` and for `PASSENGER`; 30000 cents for `FOR_HIRE_PROPERTY`,
    `PROPERTY_BROKER` and `FREIGHT_FORWARDER`), multiplied by the track multiplier and then
    by the administrative surcharge factor, rounded half-up to whole cents."
    PRD §3.2: "`filing_fee_cents` is the sum of those four already-rounded lines, and
    `filing_fee_breakdown` records all four of them under the keys `line_docket_cents`,
    `line_states_cents`, `line_type_cents` and `line_hazmat_cents`."

    Design: Corner/state_machines/vetting_review_on_a_denied_application_is_rejected
    """
    env = setup_submitted_application(
        api,
        application_kwargs={
            "application_kind": "NEW",
            "transportation_type": "FOR_HIRE_PROPERTY",
            "requested_operating_states": ["TX", "OK", "NM"],
        },
    )
    assert env.filing_fee_cents == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS, (
        "the four per-line rounded amounts sum to 64791 cents, got "
        f"{env.filing_fee_cents}"
    )

    set_clock(api, T_PUBLISH)
    denied = validate_success(
        api.review_application(
            env.application_id,
            factories.vetting_review_payload(
                disposition="DENY",
                findings="adverse safety history on the predecessor fleet",
                denied_reason="adverse safety history on the predecessor fleet",
            ),
            VETTING_ANALYST,
        )
    )
    assert denied["status"] == "DENIED"

    # DENIED is terminal: a second review cannot reopen it, not even a publish.
    validate_error(
        api.review_application(
            env.application_id,
            factories.vetting_review_payload(disposition="PUBLISH"),
            VETTING_ANALYST_ALT,
        ),
        ApiErrorId.APPLICATION_INVALID_STATE,
    )

    application = validate_success(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "DENIED"
    assert application["published_at"] is None, (
        "the refused publish stamped no published_at"
    )
    assert application["published_by_user_id"] is None

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fee_balance_cents"] == 0, (
        "the submit-then-deny round trip returns the balance to zero, got "
        f"{carrier['fee_balance_cents']}"
    )
    assert carrier["fees_assessed_total_cents"] == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS
    assert carrier["fees_reversed_total_cents"] == NEW_FOR_HIRE_THREE_STATES_FEE_CENTS

    _entries, ledger_meta = validate_paginated(
        api.list_fee_ledger_entries(env.carrier_id, REGISTRY_ADMIN)
    )
    assert ledger_meta["total_count"] == 2, (
        "the debit and its reversal both stand in the append-only ledger, got "
        f"total_count {ledger_meta['total_count']}"
    )

    _rows, authority_meta = validate_paginated(
        api.list_authorities(REGISTRY_ADMIN, application_id=env.application_id)
    )
    assert authority_meta["total_count"] == 0, (
        f"a denial creates no authority, got total_count {authority_meta['total_count']}"
    )


def test_cancelling_an_already_cancelled_filing_is_rejected(api):
    """PRD §2.8: "The target filing is still `ACTIVE` — `ERR_FILING_NOT_ACTIVE` (HTTP 409).
    Applies to `POST /insurance-filings/{id}/cancel`. A filing already `CANCELLED`, whether
    by an explicit cancel or by being superseded, cannot be cancelled again."
    PRD §3.5: "Four conditions must hold: the filing is still `ACTIVE` (a filing already
    `CANCELLED`, whether explicitly or by supersession, is rejected with
    `ERR_FILING_NOT_ACTIVE`), the acting user is the filing's insurer, the authority behind
    the filing is neither `REVOKED` nor `RESCINDED`, and the submitted
    `cancellation_effective_at` is at or after the filing's own `effective_at`."
    PRD §3.5: "The filing then moves `ACTIVE → CANCELLED` with `cancellation_effective_at`
    set to the submitted instant."
    PRD §3.5: "`NOT_FILED → FILED` when the authority has exactly one required slot and the
    new filing satisfies it. A single-slot authority therefore never passes through
    `PARTIAL`."
    PRD §3.5: "If, after the cancellation, at least one required slot no longer holds an
    `ACTIVE` filing whose interval contains the current logical time, `insurance_status`
    moves `FILED → LAPSED`."
    PRD §3.5: "And because that proceeding was opened, if the authority's `authority_status`
    was `ACTIVE`, the suspension cascade of §2.10 runs with `suspension_reason`
    `INSURANCE_LAPSE` — suspending the authority, suspending its active contracts with their
    liability estimated, and embargoing those contracts' tendered and in-transit shipments."

    Design: Corner/state_machines/cancelling_an_already_cancelled_filing_is_rejected
    """
    env = setup_published_authority(api)
    filing = file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        env.authority["required_bipd_limit_cents"],
        filing_type="BIPD",
        effective_at=T_PUBLISH,
        policy_number="BIPD-CANCEL-1",
    )
    assert filing["status"] == "ACTIVE"
    assert read_authority(api, env.authority_id)["insurance_status"] == "FILED", (
        "a single required slot moves NOT_FILED straight to FILED"
    )

    set_clock(api, "2026-08-10T00:00:00Z")
    cancelled = cancel_filing(api, env.insurer_id, filing["id"], "2026-08-10T00:00:00Z")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_effective_at"] == "2026-08-10T00:00:00.000Z"

    # The second cancel is refused, and the first cancellation instant stands.
    set_clock(api, "2026-08-12T00:00:00Z")
    validate_error(
        api.cancel_filing(
            filing["id"],
            factories.cancel_filing_payload("2026-08-12T00:00:00Z"),
            env.insurer_headers,
        ),
        ApiErrorId.FILING_NOT_ACTIVE,
    )

    reread = validate_success(api.get_filing(filing["id"], REGISTRY_ADMIN))
    assert reread["status"] == "CANCELLED"
    assert reread["cancellation_effective_at"] == "2026-08-10T00:00:00.000Z", (
        "the refused cancel must not rewrite the effective instant, got "
        f"{reread['cancellation_effective_at']}"
    )

    authority = read_authority(api, env.authority_id)
    assert_operating_authority(authority)
    assert authority["insurance_status"] == "LAPSED", (
        "the only required slot no longer holds active coverage, got "
        f"{authority['insurance_status']}"
    )
    assert authority["authority_status"] == "PENDING", (
        "the suspension cascade runs only when the authority was ACTIVE, got "
        f"{authority['authority_status']}"
    )


def test_designation_repair_restores_a_designation_gap_suspension(api):
    """PRD §3.4: "**Revoking a designation** is a `CarrierRep` action on its own designation
    and moves that row `ACTIVE → REVOKED` with `revoked_at` stamped at the current logical
    time."
    PRD §3.4: "And because coverage became incomplete, if the authority was `ACTIVE` the full
    suspension cascade of §2.10 runs with `suspension_reason` set to `DESIGNATION_GAP` — the
    authority moves `ACTIVE → SUSPENDED`, its active contracts move `ACTIVE →
    SUSPENDED_BY_AUTHORITY` with their liability estimated, and those contracts' tendered and
    in-transit shipments become `EMBARGOED`."
    PRD §3.4: "No revocation proceeding is opened for a designation gap, because the defect
    is self-curable: the carrier simply files a replacement designation."
    PRD §3.4: "`designated_state_count` is the number of state codes that appear in **both**
    that covered set and the authority's `required_jurisdictions`.
    `designation_coverage_complete` is true exactly when no required jurisdiction is left
    uncovered — equivalently, when `designated_state_count` equals the number of entries in
    `required_jurisdictions`."
    PRD §3.4: "A designation **create** is admitted against an authority that is `SUSPENDED`
    when — and only when — its `suspension_reason` is `DESIGNATION_GAP`; every other
    suspended authority, and every `REVOKED` or `RESCINDED` authority, refuses both
    designation operations with `ERR_AUTHORITY_INVALID_STATE`, and a designation **revoke**
    is never admitted against a suspended authority at all."
    PRD §3.4: "When the new designations make `designation_coverage_complete` true, the
    authority is restored: the compensating cascade of §2.10 runs in full and
    `suspension_reason` returns to `NONE`."
    PRD §3.4: "Restoration is guarded by three conditions, all evaluated after this request's
    own writes have landed: `designation_coverage_complete` must be true, `insurance_status`
    must be `FILED`, and no revocation proceeding on this authority may remain in
    `NOTICE_ISSUED`."
    PRD §2.10: "Hop one returns the authority's `authority_status` to `ACTIVE`, resets
    `suspension_reason` to `NONE` and clears `suspended_at` to null."
    PRD §2.10: "The authority's `suspended_contract_count` decreases by the number of
    contracts hop two moved, its `active_contract_count` increases by that same number, and
    the carrier's `active_authority_count` increases by one."
    PRD §3.4: "Because revoked designations are ignored by this check, revoking a designation
    is exactly how a gap is legitimately re-filled with a fresh one."

    Design: Corner/state_machines/designation_repair_restores_a_designation_gap_suspension
    """
    env = setup_active_authority(api)
    required = env.authority["required_jurisdictions"]
    assert len(required) == 3 and "NM" in required

    gap_state = "NM"
    active_nm = list_designations(
        api, env.authority_id, state_code=gap_state, status="ACTIVE"
    )
    assert len(active_nm) == 1, f"expected one ACTIVE {gap_state} designation"
    revoked = validate_success(
        api.revoke_designation(active_nm[0]["id"], env.carrier_headers)
    )
    assert_designation(revoked)
    assert revoked["status"] == "REVOKED"

    gapped = read_authority(api, env.authority_id)
    assert gapped["authority_status"] == "SUSPENDED"
    assert gapped["suspension_reason"] == "DESIGNATION_GAP"
    assert gapped["designated_state_count"] == 2, (
        f"one of three required jurisdictions is uncovered, got "
        f"{gapped['designated_state_count']}"
    )
    assert gapped["designation_coverage_complete"] is False

    # The repair path: a create is admitted on a DESIGNATION_GAP suspension.
    replacement = validate_success(
        api.create_designations(
            env.authority_id,
            factories.designation_payload(
                env.agent_id,
                state_codes=[gap_state],
                effective_from=env.activate_at,
            ),
            env.carrier_headers,
        ),
        201,
    )
    assert len(replacement) == 1
    assert_designation(replacement[0])
    assert replacement[0]["state_code"] == gap_state
    assert replacement[0]["status"] == "ACTIVE"

    restored = read_authority(api, env.authority_id)
    assert_operating_authority(restored)
    assert restored["authority_status"] == "ACTIVE", (
        f"closing the gap restores the authority, got {restored['authority_status']}"
    )
    assert restored["suspension_reason"] == "NONE"
    assert restored["suspended_at"] is None
    assert restored["designated_state_count"] == 3
    assert restored["designation_coverage_complete"] is True
    assert restored["insurance_status"] == "FILED"

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["active_authority_count"] == 1, (
        "restoration returns the carrier's active authority count to one, got "
        f"{carrier['active_authority_count']}"
    )

    _rows, proceeding_meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert proceeding_meta["total_count"] == 0, (
        "a designation gap opens no revocation proceeding, got total_count "
        f"{proceeding_meta['total_count']}"
    )

    stale = validate_success(api.get_designation(active_nm[0]["id"], REGISTRY_ADMIN))
    assert stale["status"] == "REVOKED", "the revoked row stays revoked"


def test_activation_applies_every_declared_side_effect(api):
    """PRD §3.6: "When all eight conditions hold, activation writes a great deal at once. The
    authority's `authority_status` becomes `ACTIVE`, its `activated_at` is stamped with the
    current logical time, and its `insurance_status` is set to `FILED`. The originating
    application moves `PUBLISHED → GRANTED`. On the owning carrier,
    `unified_registration_status` becomes `REGISTERED` and `active_authority_count` increases
    by one. The carrier is also scored for the first time: `compliance_risk_score` is written
    from the self-reported variant below and `compliance_risk_variant` becomes
    `SELF_REPORTED`. The authority's `version` increases by one."
    PRD §3.6: "If the carrier's `entrant_status` is `NEW_ENTRANT` at the moment of
    activation, the authority's `new_entrant_audit_status` becomes `PENDING`, its
    `new_entrant_audit_deadline_at` is set to the audit window described below, and a
    `SafetyAudit` is created for that carrier with `status` `SCHEDULED`,
    `audit_window_opens_at` equal to the current logical time (that is, the authority's
    `activated_at`) and `audit_deadline_at` equal to the same window figure."
    PRD §3.6: "That audit's `result_recorded_at`, `audited_oos_rate_pct`,
    `audited_driver_violation_count`, `audited_vehicle_defect_count`,
    `acute_violation_count` and `audit_score` all open at null."
    PRD §3.6: "The audit is **not** returned by the activation response; it is discoverable
    only by listing that carrier's safety audits."
    PRD §3.6: "The audit window runs 18 calendar months from `activated_at`, preserving the
    day of month and the time of day; when the target month has fewer days than the source
    day-of-month, the deadline clamps to that month's last day with the time of day
    unchanged. Both the authority's `new_entrant_audit_deadline_at` and the audit's
    `audit_deadline_at` receive that instant."
    PRD §3.6: "The out-of-service component is `self_reported_oos_rate_pct` multiplied by 2,
    capped at 100."
    PRD §3.6: "The driver component is the carrier's `self_reported_driver_count` divided by
    its `self_reported_vehicle_count` — using 1 as the divisor if the vehicle count is
    somehow smaller than 1 — then multiplied by 20, capped at 100."
    PRD §3.6: "The vehicle component is `self_reported_vehicle_count` divided by a fleet
    normaliser of 10 power units and then multiplied by 10, capped at 100."
    PRD §3.6: "The raw score is the out-of-service component weighted at 0.45, plus the
    driver component weighted at 0.30, plus the vehicle component weighted at 0.25."
    PRD §3.6: "That raw score is then clamped to the range 0.0 through 100.0 — never below
    the floor, never above the ceiling — and the clamped value is rounded half-up to exactly
    two decimal places once."
    PRD §3.6: "The waiting period must have elapsed — the current logical time must be at or
    after `activation_eligible_at`, which was stamped at publication as `publication_at` plus
    21 days."

    Design: Corner/state_machines/activation_applies_every_declared_side_effect
    """
    env = setup_pending_authority_with_coverage(
        api,
        carrier_kwargs={
            "self_reported_vehicle_count": 40,
            "self_reported_driver_count": 60,
            "self_reported_oos_rate_pct": 12.5,
        },
    )
    version_before = env.authority["version"]
    eligible_at = env.authority["activation_eligible_at"]
    assert eligible_at == "2026-08-26T00:00:00.000Z"

    set_clock(api, eligible_at)
    response = api.activate_authority(env.authority_id, ACTIVATING_OFFICER)
    authority = validate_success(response)
    assert_operating_authority(authority)

    assert authority["authority_status"] == "ACTIVE"
    assert authority["activated_at"] == "2026-08-26T00:00:00.000Z"
    assert authority["insurance_status"] == "FILED"
    assert authority["version"] == version_before + 1, (
        f"activation increases version by one, got {authority['version']} from "
        f"{version_before}"
    )

    application = validate_success(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "GRANTED"

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "REGISTERED"
    assert carrier["active_authority_count"] == 1
    assert carrier["compliance_risk_variant"] == "SELF_REPORTED"
    assert_risk_score(carrier["compliance_risk_score"], 30.25)

    # The new-entrant branch.
    assert authority["new_entrant_audit_status"] == "PENDING"
    assert authority["new_entrant_audit_deadline_at"] == "2028-02-26T00:00:00.000Z", (
        "the audit window runs 18 calendar months from activated_at, got "
        f"{authority['new_entrant_audit_deadline_at']}"
    )

    for hidden in ("safety_audit", "audit_window_opens_at", "audit_deadline_at"):
        assert hidden not in authority, (
            f"the audit is not returned by the activation response, found {hidden}"
        )

    audits, audit_meta = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    assert audit_meta["total_count"] == 1, (
        f"activation schedules exactly one audit, got {audit_meta['total_count']}"
    )
    audit = audits[0]
    assert_safety_audit(audit)
    assert audit["carrier_id"] == env.carrier_id
    assert audit["status"] == "SCHEDULED"
    assert audit["audit_window_opens_at"] == "2026-08-26T00:00:00.000Z"
    assert audit["audit_deadline_at"] == "2028-02-26T00:00:00.000Z"
    for opener in (
        "result_recorded_at",
        "audited_oos_rate_pct",
        "audited_driver_violation_count",
        "audited_vehicle_defect_count",
        "acute_violation_count",
        "audit_score",
    ):
        assert audit[opener] is None, f"{opener} opens at null, got {audit[opener]}"


def test_depart_moves_a_tendered_shipment_to_in_transit(api):
    """PRD §3.9: "Two operator transitions move a shipment forward. Departing it advances
    `TENDERED → IN_TRANSIT`, and requires that the shipment is `TENDERED`, that the acting
    user is the carrier owning the shipment's contract's authority, that the contract's
    `status` is `ACTIVE`, and that the authority behind that contract has `authority_status`
    `ACTIVE`."
    PRD §3.9: "Delivering it advances `IN_TRANSIT → DELIVERED` and stamps `delivered_at` with
    the current logical time, requiring only that the shipment is `IN_TRANSIT` and that the
    acting user owns it."
    PRD §3.9: "A new shipment opens with `status` `TENDERED`, `pre_embargo_status` `NONE`,
    `embargo_days_accrued` zero, and `embargoed_at`, `embargo_released_at`, `delivered_at`
    and `diverted_at` all null."
    PRD §3.9: "A brand-new contract opens with `status` `ACTIVE`, `embargoed_shipment_count`
    zero, `disruption_liability_cents` zero, `disruption_liability_variant` `NONE`, and
    `suspended_at`, `resumed_at` and `terminated_at` all null."
    PRD §4: "Every other endpoint — all reads, all state-transition writes, the sweep and the
    clock control — answers with HTTP 200 OK on success."

    Design: Corner/state_machines/depart_moves_a_tendered_shipment_to_in_transit
    """
    env = setup_active_authority_with_shipment(api, tender_at="2026-09-02T00:00:00Z")
    assert env.shipment["status"] == "TENDERED"
    assert env.shipment["pre_embargo_status"] == "NONE"

    departed = validate_success(
        api.depart_shipment(env.shipment_id, env.carrier_headers), 200
    )
    assert_shipment(departed)

    assert departed["id"] == env.shipment_id
    assert departed["status"] == "IN_TRANSIT", (
        f"depart advances TENDERED to IN_TRANSIT, got {departed['status']}"
    )
    assert departed["pre_embargo_status"] == "NONE"
    assert departed["embargoed_at"] is None
    assert departed["embargo_released_at"] is None
    assert departed["embargo_days_accrued"] == 0
    assert departed["delivered_at"] is None, "only delivery stamps delivered_at"
    assert departed["diverted_at"] is None

    contract = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert_customer_contract(contract)
    assert contract["status"] == "ACTIVE"
    assert contract["embargoed_shipment_count"] == 0
    assert contract["disruption_liability_cents"] == 0
    assert contract["disruption_liability_variant"] == "NONE"

    rows, meta = validate_paginated(
        api.list_shipments(
            env.carrier_headers, contract_id=env.contract_id, status="IN_TRANSIT"
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one shipment is in transit, got {meta['total_count']}"
    )
    assert rows[0]["id"] == env.shipment_id


def test_depart_and_deliver_on_an_embargoed_shipment_are_both_rejected(api):
    """PRD §2.8: "The shipment admits the requested trigger — `ERR_SHIPMENT_INVALID_STATE`
    (HTTP 409). Applies to `POST /shipments/{id}/depart` (requires `TENDERED`) and
    `POST /shipments/{id}/deliver` (requires `IN_TRANSIT`); an `EMBARGOED` shipment admits
    neither."
    PRD §3.9: "Departing anything that is not `TENDERED`, or delivering anything that is not
    `IN_TRANSIT`, is rejected with `ERR_SHIPMENT_INVALID_STATE`; an `EMBARGOED` shipment
    admits neither and must wait for the authority to be restored."
    PRD §2.10: "Because each of those contracts became `SUSPENDED_BY_AUTHORITY`, hop three
    visits every `Shipment` whose `contract_id` names that contract and whose `status` is
    either `TENDERED` or `IN_TRANSIT`: each records its current status into
    `pre_embargo_status`, becomes `EMBARGOED`, and has `embargoed_at` set to the current
    logical time; the contract's `embargoed_shipment_count` is then set to the number of
    shipments this hop moved for it."
    PRD §2.10: "Because the authority became `SUSPENDED`, hop two visits every
    `CustomerContract` whose `authority_id` names it and whose `status` is `ACTIVE`: each
    becomes `SUSPENDED_BY_AUTHORITY`, its `suspended_at` is set to the current logical time,
    its `resumed_at` is reset to null, its `disruption_liability_cents` is written from the
    suspension-estimate variant described in §3.9, and its `disruption_liability_variant`
    becomes `SUSPENSION_ESTIMATE`."
    PRD §3.9: "Delivering it advances `IN_TRANSIT → DELIVERED` and stamps `delivered_at` with
    the current logical time, requiring only that the shipment is `IN_TRANSIT` and that the
    acting user owns it."

    Design: Corner/state_machines/depart_and_deliver_on_an_embargoed_shipment_are_both_rejected
    """
    env = setup_suspended_with_shipment(
        api,
        depart=True,
        tender_at="2026-09-02T00:00:00Z",
        cancel_at="2026-09-10T00:00:00Z",
    )
    assert env.shipment["status"] == "EMBARGOED"
    assert env.shipment["pre_embargo_status"] == "IN_TRANSIT"

    # An EMBARGOED shipment admits neither trigger.
    validate_error(
        api.deliver_shipment(env.shipment_id, env.carrier_headers),
        ApiErrorId.SHIPMENT_INVALID_STATE,
    )
    validate_error(
        api.depart_shipment(env.shipment_id, env.carrier_headers),
        ApiErrorId.SHIPMENT_INVALID_STATE,
    )

    shipment = validate_success(
        api.get_shipment(env.shipment_id, env.carrier_headers)
    )
    assert_shipment(shipment)
    assert shipment["status"] == "EMBARGOED"
    assert shipment["pre_embargo_status"] == "IN_TRANSIT", (
        "the embargo recorded the status the shipment held when it was frozen, got "
        f"{shipment['pre_embargo_status']}"
    )
    assert shipment["embargoed_at"] == "2026-09-10T00:00:00.000Z"
    assert shipment["delivered_at"] is None, "the refused delivery stamped nothing"
    assert shipment["embargo_released_at"] is None

    contract = validate_success(api.get_contract(env.contract_id, env.carrier_headers))
    assert_customer_contract(contract)
    assert contract["status"] == "SUSPENDED_BY_AUTHORITY"
    assert contract["embargoed_shipment_count"] == 1, (
        "hop three moved exactly one shipment for this contract, got "
        f"{contract['embargoed_shipment_count']}"
    )
