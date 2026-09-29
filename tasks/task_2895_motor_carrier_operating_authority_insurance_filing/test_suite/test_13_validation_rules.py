"""Validation rules of the motor-carrier operating-authority API.

Six rejection claims are exercised here: the inclusive activation waiting
period one day short of eligibility, the insurer-admission check against the
carrier's domicile state, the inverted designation interval as a request-shape
failure, the aggregate process-agent coverage check at activation, the blanket
agent's exemption from the per-state coverage check, and the rejection ladder's
placement of body foreign-key existence above predecessor compatibility.

Every chain is built through the public endpoints of PRD S4 from an empty
database, with the logical compliance clock of PRD S2.5 pinned at each step.
"""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    NON_EXISTENT_UUID,
    REGISTRY_ADMIN,
    T_ENROLL,
    T_PUBLISH,
    application_payload,
    assert_authority_application,
    assert_designation,
    assert_insurance_filing,
    assert_operating_authority,
    authority_for_application,
    authority_version,
    create_carrier,
    create_draft_application,
    create_insurer,
    create_process_agent,
    designation_payload,
    fee_payment_payload,
    filing_payload,
    make_carrier_headers,
    make_insurer_headers,
    read_authority,
    review_application,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local chains.  Each one walks the registry -> application -> publication
# sequence of PRD S3 with the atomic steps, so every test starts from an empty
# database.
# ---------------------------------------------------------------------------
def _published_authority(api, *, application_kwargs=None, carrier_kwargs=None):
    """PRD S3.3 + S3.4: a PUBLISHED application and the authority it minted."""
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, **(carrier_kwargs or {}))
    env = SimpleNamespace(
        carrier=carrier,
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
    )
    env.application = create_draft_application(
        api, env.carrier_id, **(application_kwargs or {})
    )
    env.application_id = env.application["id"]
    env.application = submit_application(api, env.carrier_id, env.application_id)
    set_clock(api, T_PUBLISH)
    env.application = review_application(api, env.application_id, disposition="PUBLISH")
    env.authority = authority_for_application(api, env.application_id)
    env.authority_id = env.authority["id"]
    return env


def _designate(api, env, agent_id, state_codes, **kwargs):
    """PRD S3.4: the all-or-nothing designation bulk write, as its owner."""
    return api.create_designations(
        env.authority_id,
        designation_payload(agent_id, state_codes=state_codes, **kwargs),
        env.carrier_headers,
    )


def _file_bipd(api, env, insurer_id, limit_cents, policy_number, **kwargs):
    """PRD S3.5: one BIPD filing against the authority's current version."""
    return api.create_filing(
        filing_payload(
            env.authority_id,
            insurer_id,
            limit_cents,
            authority_version(api, env.authority_id),
            filing_type="BIPD",
            policy_number=policy_number,
            effective_at=kwargs.pop("effective_at", T_PUBLISH),
            **kwargs,
        ),
        make_insurer_headers(insurer_id),
    )


def _settle(api, env, amount_cents):
    """PRD S3.1: clear the docket's filing fee so the money gate is satisfied."""
    return validate_success(
        api.record_fee_payment(
            env.carrier_id, fee_payment_payload(amount_cents), env.carrier_headers
        ),
        201,
    )


def test_activate_one_day_before_eligibility_is_rejected(api):
    """PRD S3.6: "The waiting period must have elapsed — the current logical
    time must be at or after `activation_eligible_at`, which was stamped at
    publication as `publication_at` plus 21 days. The boundary is inclusive:
    activation at exactly `activation_eligible_at` succeeds, and one millisecond
    earlier fails with `ERR_WAITING_PERIOD_NOT_ELAPSED`."
    PRD S3.3: "`publication_at` is stamped with the current logical time and
    `activation_eligible_at` is set to `publication_at` plus 21 days."
    PRD S3.6: "When all eight conditions hold, activation writes a great deal at
    once. The authority's `authority_status` becomes `ACTIVE`, its `activated_at`
    is stamped with the current logical time, and its `insurance_status` is set
    to `FILED`. The originating application moves `PUBLISHED → GRANTED`. On the
    owning carrier, `unified_registration_status` becomes `REGISTERED` and
    `active_authority_count` increases by one."
    PRD S3.7: "If the carrier's `entrant_status` is `NEW_ENTRANT` at the moment
    of activation, the authority's `new_entrant_audit_status` becomes `PENDING`,
    its `new_entrant_audit_deadline_at` is set to the audit window described
    below, and a `SafetyAudit` is created for that carrier with `status`
    `SCHEDULED`"
    PRD S3.4: "Everything else on the new authority opens at its resting value:
    `authority_status` is `PENDING`, `insurance_status` is `NOT_FILED`,
    `designated_state_count` is 0 and `designation_coverage_complete` is false,
    `suspension_reason` is `NONE`, `active_contract_count` and
    `suspended_contract_count` are both 0, `new_entrant_audit_status` is
    `NOT_REQUIRED` with `new_entrant_audit_deadline_at` null, and `activated_at`,
    `suspended_at`, `revoked_at` and `rescinded_at` are all null."
    PRD S3.4: "`designation_coverage_complete` is true exactly when no required
    jurisdiction is left uncovered — equivalently, when `designated_state_count`
    equals the number of entries in `required_jurisdictions`."
    PRD S3.5: "`NOT_FILED → FILED` when the authority has exactly one required
    slot and the new filing satisfies it."

    Design: Corner/validations/activate_one_day_before_eligibility_is_rejected
    """
    env = _published_authority(
        api, carrier_kwargs={"legal_name": "Comal Springs Transport LLC"}
    )
    assert env.authority["activation_eligible_at"] == "2026-08-26T00:00:00.000Z", (
        "publication on 2026-08-05 plus 21 days lands the eligibility instant on "
        f"2026-08-26, got {env.authority['activation_eligible_at']}"
    )
    agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])
    insurer = create_insurer(api, authorized_states=["TX", "OK", "NM"])
    validate_success(
        _designate(
            api, env, agent["id"], env.authority["required_jurisdictions"]
        ),
        201,
    )
    validate_success(_file_bipd(api, env, insurer["id"], 75000000, "BIPD-44"), 201)
    _settle(api, env, 64791)
    ready = read_authority(api, env.authority_id)
    assert ready["designation_coverage_complete"] is True
    assert ready["insurance_status"] == "FILED"

    set_clock(api, "2026-08-25T00:00:00Z")
    validate_error(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER),
        ApiErrorId.WAITING_PERIOD_NOT_ELAPSED,
    )

    unchanged = read_authority(api, env.authority_id)
    assert_operating_authority(unchanged)
    assert unchanged["authority_status"] == "PENDING", (
        "a refused activation leaves the authority where it was, got "
        f"{unchanged['authority_status']}"
    )
    assert unchanged["activated_at"] is None, (
        f"activated_at is stamped only by a successful activation, got "
        f"{unchanged['activated_at']}"
    )
    assert unchanged["new_entrant_audit_status"] == "NOT_REQUIRED", (
        "the new-entrant branch runs inside activation, got "
        f"{unchanged['new_entrant_audit_status']}"
    )
    assert unchanged["new_entrant_audit_deadline_at"] is None

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "NOT_REGISTERED", (
        "unified registration is minted by a successful activation, got "
        f"{carrier['unified_registration_status']}"
    )
    assert carrier["active_authority_count"] == 0, (
        f"no authority became ACTIVE, got {carrier['active_authority_count']}"
    )

    audits, meta = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 0, (
        "the SafetyAudit is created at the moment of activation, so a refused "
        f"activation schedules none, got {meta['total_count']}"
    )
    assert audits == []

    application = validate_success(
        api.get_application(env.application_id, env.carrier_headers)
    )
    assert_authority_application(application)
    assert application["status"] == "PUBLISHED", (
        f"the application does not move to GRANTED, got {application['status']}"
    )


def test_filing_by_an_insurer_unauthorized_in_the_domicile_state_is_rejected(api):
    """PRD S3.5: "The insurer must be admitted where the carrier lives: the
    owning carrier's `domicile_state` must appear in the insurer's
    `authorized_states`, failing which the filing is rejected with
    `ERR_INSURER_NOT_AUTHORIZED_IN_STATE`."
    PRD S3.1: "An **insurer** — which in this system also means a surety company
    — is registered with a `company_name` (non-blank, 1 to 200 characters), a
    `naic_code` of exactly five digits that is unique across all insurers, and an
    `authorized_states` list of 1 to 51 distinct valid state codes naming where
    it is admitted to write filings."
    PRD S3.5: "`NOT_FILED → FILED` when the authority has exactly one required
    slot and the new filing satisfies it."
    PRD S3.5: "And the coverage must be adequate: `meets_required_minimum` is set
    from the comparison of `coverage_limit_cents` against the authority's
    required limit for this `filing_type`"
    PRD S3.5: "If the slot was empty, `supersedes_filing_id` stays null."
    PRD S3.5: "Every filing create and every filing cancel that moves the
    coverage dimension increases the authority's `version` by one."

    Design: Corner/validations/filing_by_an_insurer_unauthorized_in_the_domicile_state_is_rejected
    """
    env = _published_authority(
        api,
        carrier_kwargs={
            "legal_name": "Guadalupe Peak Freight LLC",
            "domicile_state": "TX",
        },
    )
    unadmitted = create_insurer(
        api,
        company_name="Sooner Plains Indemnity",
        naic_code="54321",
        authorized_states=["OK", "NM"],
    )
    admitted = create_insurer(
        api,
        company_name="Permian Mutual Casualty",
        naic_code="12345",
        authorized_states=["TX", "OK", "NM"],
    )
    version_before = authority_version(api, env.authority_id)

    validate_error(
        api.create_filing(
            filing_payload(
                env.authority_id,
                unadmitted["id"],
                75000000,
                version_before,
                filing_type="BIPD",
                policy_number="BIPD-45-BAD",
                effective_at=T_PUBLISH,
            ),
            make_insurer_headers(unadmitted["id"]),
        ),
        ApiErrorId.INSURER_NOT_AUTHORIZED_IN_STATE,
    )

    accepted = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                admitted["id"],
                75000000,
                version_before,
                filing_type="BIPD",
                policy_number="BIPD-45-GOOD",
                effective_at=T_PUBLISH,
            ),
            make_insurer_headers(admitted["id"]),
        ),
        201,
    )
    assert_insurance_filing(accepted)
    assert accepted["insurer_id"] == admitted["id"], (
        "the accepted filing names the TX-admitted insurer, got "
        f"{accepted['insurer_id']}"
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["supersedes_filing_id"] is None, (
        "the BIPD slot was empty, which shows the refused filing never occupied it, "
        f"got {accepted['supersedes_filing_id']}"
    )
    assert accepted["meets_required_minimum"] is True, (
        "75000000 cents is exactly the required BIPD minimum, got "
        f"{accepted['meets_required_minimum']}"
    )

    after = read_authority(api, env.authority_id)
    assert after["insurance_status"] == "FILED", (
        "the FOR_HIRE_PROPERTY authority has exactly one required slot and the "
        f"accepted filing satisfies it, got {after['insurance_status']}"
    )
    assert after["version"] == version_before + 1, (
        "only the accepted filing moved the coverage dimension, so the version rose "
        f"by exactly one from {version_before}, got {after['version']}"
    )

    rows, meta = validate_paginated(
        api.list_filings(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert meta["total_count"] == 1, (
        f"the rejected filing was never persisted, got {meta['total_count']}"
    )
    assert rows[0]["id"] == accepted["id"]
    assert rows[0]["insurer_id"] == admitted["id"]


def test_designation_with_effective_to_before_effective_from_is_rejected(api):
    """PRD S2.8: "The request body is structurally valid — `ERR_INVALID_REQUEST`
    (HTTP 400). Applies to every write endpoint. The body must carry all
    required fields; enum-typed fields must hold a value from their declared set;
    integers declared non-negative must be non-negative; instants must be
    parseable ISO 8601; every state code must be one of the 51 valid two-letter
    USPS codes; `requested_operating_states` must be non-empty and free of
    duplicates; `term_start_at` must be strictly before `term_end_at`; and
    `effective_to`, when supplied, must not be earlier than `effective_from`."
    PRD S3.4: "The request is strictly all-or-nothing: if **any** requested state
    code fails either of the two checks below, no row at all is created."
    PRD S3.4: "`designated_state_count` is the number of state codes that appear
    in **both** that covered set and the authority's `required_jurisdictions`."
    PRD S3.4: "`designation_coverage_complete` is true exactly when no required
    jurisdiction is left uncovered — equivalently, when `designated_state_count`
    equals the number of entries in `required_jurisdictions`."
    PRD S3.4: "Both fields are written on the authority, and the authority's
    `version` increases by one."
    PRD S3.4: "One `ProcessAgentDesignation` row is created per requested state
    code, each carrying the authority from the path, the single `state_code` it
    covers, the shared `effective_from` and `effective_to`, `status` `ACTIVE` and
    `revoked_at` null."

    Design: Corner/validations/designation_with_effective_to_before_effective_from_is_rejected
    """
    env = _published_authority(
        api, carrier_kwargs={"legal_name": "Bandera Pass Motor Freight LLC"}
    )
    agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])
    version_before = authority_version(api, env.authority_id)

    validate_error(
        _designate(
            api,
            env,
            agent["id"],
            ["TX", "OK", "NM"],
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-08-15T00:00:00Z",
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    rows, meta = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert meta["total_count"] == 0, (
        "an inverted interval is a request-shape failure, so none of the three "
        f"requested rows was created, got {meta['total_count']}"
    )
    assert rows == []

    after = read_authority(api, env.authority_id)
    assert after["designated_state_count"] == 0, (
        f"no state is covered, got {after['designated_state_count']}"
    )
    assert after["designation_coverage_complete"] is False, (
        "three required jurisdictions remain uncovered, got "
        f"{after['designation_coverage_complete']}"
    )
    assert after["version"] == version_before, (
        "the coverage recompute never ran, so the authority's version did not "
        f"move, got {after['version']} against {version_before}"
    )

    accepted = validate_success(
        _designate(
            api,
            env,
            agent["id"],
            ["TX", "OK", "NM"],
            effective_from="2026-08-15T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        ),
        201,
    )
    assert len(accepted) == 3, (
        f"the same interval the right way round is accepted, got {len(accepted)} rows"
    )
    for row in accepted:
        assert_designation(row)
        assert row["effective_from"] == "2026-08-15T00:00:00.000Z"
        assert row["effective_to"] == "2026-09-01T00:00:00.000Z"


def test_activate_with_one_required_jurisdiction_undesignated_is_rejected(api):
    """PRD S3.6: "Process-agent coverage must be complete —
    `designation_coverage_complete` must be true, or the request is refused with
    `ERR_PROCESS_AGENT_COVERAGE_INCOMPLETE`."
    PRD S3.4: "`designation_coverage_complete` is true exactly when no required
    jurisdiction is left uncovered — equivalently, when `designated_state_count`
    equals the number of entries in `required_jurisdictions`."
    PRD S3.4: "Its `required_jurisdictions` is the distinct union of the
    application's `requested_operating_states` and the owning carrier's
    `domicile_state`, sorted ascending by state code"
    PRD S3.6: "Finally, money is checked last: the carrier's `fee_balance_cents`
    must be zero or negative, meaning nothing is outstanding."
    PRD S3.6: "When all eight conditions hold, activation writes a great deal at
    once. The authority's `authority_status` becomes `ACTIVE`, its `activated_at`
    is stamped with the current logical time, and its `insurance_status` is set
    to `FILED`."

    Design: Corner/validations/activate_with_one_required_jurisdiction_undesignated_is_rejected
    """
    env = _published_authority(
        api, carrier_kwargs={"legal_name": "Uvalde Junction Freight LLC"}
    )
    assert env.authority["required_jurisdictions"] == ["NM", "OK", "TX"], (
        "the required jurisdictions are the requested states unioned with the TX "
        f"domicile, sorted ascending, got {env.authority['required_jurisdictions']}"
    )
    agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])
    insurer = create_insurer(api, authorized_states=["TX", "OK", "NM"])

    validate_success(_designate(api, env, agent["id"], ["TX", "OK"]), 201)
    validate_success(_file_bipd(api, env, insurer["id"], 75000000, "BIPD-47"), 201)
    _settle(api, env, 64791)

    set_clock(api, "2026-08-26T00:00:00Z")
    validate_error(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER),
        ApiErrorId.PROCESS_AGENT_COVERAGE_INCOMPLETE,
    )

    after = read_authority(api, env.authority_id)
    assert_operating_authority(after)
    assert after["designated_state_count"] == 2, (
        "TX and OK are covered and NM is not, so two of three required "
        f"jurisdictions are designated, got {after['designated_state_count']}"
    )
    assert after["designation_coverage_complete"] is False, (
        "the aggregate fails even though each individual designation is valid, got "
        f"{after['designation_coverage_complete']}"
    )
    assert len(after["required_jurisdictions"]) == 3
    assert after["insurance_status"] == "FILED", (
        "insurance is on file at the minimum, so the coverage gate was satisfied, "
        f"got {after['insurance_status']}"
    )
    assert after["authority_status"] == "PENDING", (
        f"the refused activation leaves the authority PENDING, got "
        f"{after['authority_status']}"
    )
    assert after["activated_at"] is None

    carrier = validate_success(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fee_balance_cents"] == 0, (
        "nothing is outstanding, so the money gate was satisfied too, got "
        f"{carrier['fee_balance_cents']}"
    )
    assert carrier["active_authority_count"] == 0


def test_blanket_agent_covers_a_state_a_non_blanket_agent_cannot(api):
    """PRD S3.4: "The first check is agent coverage — every requested
    `state_code` must appear in the designated agent's `coverage_states`, unless
    that agent has `blanket_agent` true, in which case all fifty-one codes count
    as covered; a shortfall is rejected with
    `ERR_PROCESS_AGENT_STATE_NOT_COVERED`."
    PRD S3.1: "A blanket agent is a special case worth stating plainly: when
    `blanket_agent` is true, the organization is treated as covering all
    fifty-one jurisdictions regardless of what its `coverage_states` list
    actually contains."
    PRD S3.4: "The request is strictly all-or-nothing: if **any** requested state
    code fails either of the two checks below, no row at all is created."
    PRD S3.4: "Rows are created in the order the `state_codes` array lists them
    and the response array follows that same order."
    PRD S3.4: "`designation_coverage_complete` is true exactly when no required
    jurisdiction is left uncovered — equivalently, when `designated_state_count`
    equals the number of entries in `required_jurisdictions`."

    Design: Corner/validations/blanket_agent_covers_a_state_a_non_blanket_agent_cannot
    """
    env = _published_authority(
        api,
        carrier_kwargs={"legal_name": "Panhandle Plains Carriers LLC"},
        application_kwargs={"requested_operating_states": ["TX", "OK", "WY"]},
    )
    assert env.authority["required_jurisdictions"] == ["OK", "TX", "WY"]
    narrow = create_process_agent(
        api,
        company_name="Gulf Coast Process Agents",
        coverage_states=["TX", "OK", "NM"],
        blanket_agent=False,
    )
    blanket = create_process_agent(
        api,
        company_name="National Blanket Agents Inc",
        coverage_states=["TX"],
        blanket_agent=True,
    )

    validate_error(
        _designate(api, env, narrow["id"], ["TX", "OK", "WY"]),
        ApiErrorId.PROCESS_AGENT_STATE_NOT_COVERED,
    )
    rows, meta = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, authority_id=env.authority_id)
    )
    assert meta["total_count"] == 0, (
        "WY is outside the non-blanket agent's coverage_states, and the bulk write "
        f"is all-or-nothing, so TX and OK were not created either, got {rows}"
    )

    accepted = validate_success(
        _designate(api, env, blanket["id"], ["TX", "OK", "WY"]), 201
    )
    assert len(accepted) == 3, (
        "the blanket agent covers all fifty-one jurisdictions regardless of its "
        f"one-entry coverage_states, got {len(accepted)} rows"
    )
    for row in accepted:
        assert_designation(row)
        assert row["process_agent_id"] == blanket["id"]
        assert row["status"] == "ACTIVE"
        assert row["authority_id"] == env.authority_id
    assert [row["state_code"] for row in accepted] == ["TX", "OK", "WY"], (
        "the returned array follows the submitted state_codes order, got "
        f"{[row['state_code'] for row in accepted]}"
    )

    after = read_authority(api, env.authority_id)
    assert after["designated_state_count"] == 3, (
        f"all three required jurisdictions are covered, got "
        f"{after['designated_state_count']}"
    )
    assert after["designation_coverage_complete"] is True, (
        f"no required jurisdiction is left uncovered, got "
        f"{after['designation_coverage_complete']}"
    )


def test_predecessor_existence_is_checked_before_predecessor_compatibility(api):
    """PRD S2.8: "When a single request violates more than one rule, exactly one
    error is returned, and which one is determined by a fixed ladder." The ladder
    is published "in full, highest priority first", with body foreign keys at
    priority 6 and predecessor compatibility at priority 25.
    PRD S2.8 priority 6: "Every foreign key supplied in the request **body**
    resolves to an existing row — `carrier_id`, `predecessor_authority_id`,
    `authority_id`, `insurer_id`, `process_agent_id` — yielding
    `ERR_REFERENCE_NOT_FOUND`. Applies to `POST /authority-applications`, `POST
    /insurance-filings` and `POST /operating-authorities/{id}/process-agent-designations`."
    PRD S2.8 priority 25: "The predecessor authority is compatible with the
    application kind — `ERR_PREDECESSOR_INVALID` (HTTP 422). Applies to `POST
    /authority-applications` and `POST /authority-applications/{id}/submit`."
    PRD S3.2: "A `NEW` application must omit the predecessor entirely."
    PRD S3.2: "A `REINSTATEMENT` application's predecessor must belong to the
    same carrier and must currently be `REVOKED` — reinstatement is how a carrier
    comes back from revocation."

    Design: Corner/validations/predecessor_existence_is_checked_before_predecessor_compatibility
    """
    env = _published_authority(
        api, carrier_kwargs={"legal_name": "Red River Valley Transport LLC"}
    )
    assert env.authority["authority_status"] == "PENDING", (
        "the one existing authority is PENDING, so it is compatible with neither a "
        f"REINSTATEMENT nor a NEW application, got {env.authority['authority_status']}"
    )

    validate_error(
        api.create_application(
            application_payload(
                env.carrier_id,
                application_kind="REINSTATEMENT",
                transportation_type="FOR_HIRE_PROPERTY",
                requested_operating_states=["TX", "OK", "NM"],
                predecessor_authority_id=NON_EXISTENT_UUID,
            ),
            env.carrier_headers,
        ),
        ApiErrorId.REFERENCE_NOT_FOUND,
    )

    validate_error(
        api.create_application(
            application_payload(
                env.carrier_id,
                application_kind="NEW",
                transportation_type="FOR_HIRE_PROPERTY",
                requested_operating_states=["TX", "OK", "NM"],
                predecessor_authority_id=env.authority_id,
            ),
            env.carrier_headers,
        ),
        ApiErrorId.PREDECESSOR_INVALID,
    )

    applications, meta = validate_paginated(
        api.list_applications(REGISTRY_ADMIN, carrier_id=env.carrier_id)
    )
    assert meta["total_count"] == 1, (
        "neither rejected request created a draft, so only the original published "
        f"application remains, got {meta['total_count']}"
    )
    assert_authority_application(applications[0])
    assert applications[0]["id"] == env.application_id
    assert applications[0]["status"] == "PUBLISHED"

    referencing, ref_meta = validate_paginated(
        api.list_applications(
            REGISTRY_ADMIN, predecessor_authority_id=env.authority_id
        )
    )
    assert ref_meta["total_count"] == 0, (
        "no application ended up pointing at the existing authority, got "
        f"{ref_meta['total_count']}"
    )
    assert referencing == []
