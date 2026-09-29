"""Optimistic concurrency on the two guarded writes, and counter reconciliation.

PRD 2.6 attaches ``expected_authority_version`` to exactly two writes.  These
tests drive the guard from a genuinely stale read — the client reads the
authority, a second actor moves it, and only then does the client write — and
they check the complementary invariant, that an accepted write advances the
authority's ``version`` by exactly one while a refusal advances nothing.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    MAX_LIMIT,
    REGISTRY_ADMIN,
    assert_created_at_ascending,
    authority_version,
    contract_payload,
    designate_states,
    filing_payload,
    list_designations,
    make_insurer_headers,
    read_authority,
    run_sweep,
    set_clock,
    settle_fee_balance,
    setup_active_authority,
    setup_published_authority,
    validate_error,
    validate_paginated,
    validate_success,
)


def _filings_on(api, authority_id):
    """Every insurance filing booked against one authority, in creation order."""
    rows, _ = validate_paginated(api.list_filings(REGISTRY_ADMIN, limit=MAX_LIMIT))
    return [row for row in rows if row["authority_id"] == authority_id]


def test_filing_create_against_a_stale_authority_version_is_rejected(api):
    """The insurer's pre-designation read is stale by the time it files.

    PRD 2.6: "Both require `expected_authority_version` as a mandatory,
    non-optional field in the request body carrying the client's last observed
    `version` of the target authority. If the supplied value does not equal that
    authority's current `version`, the request is rejected with
    `ERR_STALE_AUTHORITY_VERSION` (HTTP 412) and nothing is written."

    PRD 3.4: "Both fields are written on the authority, and the authority's
    `version` increases by one."

    Design: Corner/cross_cutting_complexity_layers/filing_create_against_a_stale_authority_version_is_rejected
    """
    env = setup_published_authority(api)
    minimum = env.authority["required_bipd_limit_cents"]

    # The insurer reads the authority first.
    stale_version = authority_version(api, env.authority_id)

    # The carrier then designates its process agent, moving the authority.
    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=list(env.authority["required_jurisdictions"]),
        effective_from=env.publish_at,
    )
    fresh_version = authority_version(api, env.authority_id)
    assert fresh_version == stale_version + 1

    validate_error(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum,
                stale_version,
                filing_type="BIPD",
                policy_number="BIPD-STALE",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        ApiErrorId.STALE_AUTHORITY_VERSION,
    )

    refused = read_authority(api, env.authority_id)
    assert refused["insurance_status"] == "NOT_FILED"
    assert refused["version"] == fresh_version
    assert _filings_on(api, env.authority_id) == []

    accepted = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum,
                fresh_version,
                filing_type="BIPD",
                policy_number="BIPD-FRESH",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["policy_number"] == "BIPD-FRESH"

    after = read_authority(api, env.authority_id)
    assert after["insurance_status"] == "FILED"
    assert after["version"] == fresh_version + 1
    assert len(_filings_on(api, env.authority_id)) == 1


def test_contract_create_against_a_stale_authority_version_is_rejected(api):
    """A replayed contract create carries a version its own predecessor consumed.

    PRD 2.6: "If the supplied value does not equal that authority's current
    `version`, the request is rejected with `ERR_STALE_AUTHORITY_VERSION` (HTTP 412)
    and nothing is written."

    PRD 2.6: "`POST /operating-authorities/{id}/customer-contracts` — contracts carry
    no uniqueness key, so a second create against the same authority would otherwise
    succeed on its own merits."

    PRD 3.9: "The authority's `active_contract_count` increases by one, its `version`
    increases by one, and the contract-population identities of §2.10 are
    re-asserted."

    Design: Corner/cross_cutting_complexity_layers/contract_create_against_a_stale_authority_version_is_rejected
    """
    env = setup_active_authority(api)
    version_at_activation = env.authority["version"]

    payload = contract_payload(
        version_at_activation,
        shipper_name="Terlingua Mercantile",
        term_start_at="2026-08-26T00:00:00Z",
        term_end_at="2026-12-31T00:00:00Z",
    )
    first = validate_success(
        api.create_contract(env.authority_id, payload, env.carrier_headers), 201
    )
    assert first["status"] == "ACTIVE"

    # The byte-identical replay is admissible on every other ground; only the
    # version guard stops it.
    validate_error(
        api.create_contract(env.authority_id, payload, env.carrier_headers),
        ApiErrorId.STALE_AUTHORITY_VERSION,
    )

    after = read_authority(api, env.authority_id)
    assert after["active_contract_count"] == 1
    assert after["version"] == version_at_activation + 1

    rows, meta = validate_paginated(
        api.list_authority_contracts(env.authority_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_authority_version_advances_once_per_accepted_write_and_never_on_a_refusal(api):
    """Three accepted writes advance the version by three; the refusal adds nothing.

    PRD 2.4: "`version` (an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of the record)"

    PRD 3.4: "Both fields are written on the authority, and the authority's `version`
    increases by one."

    PRD 3.5: "Every filing create and every filing cancel that moves the coverage
    dimension increases the authority's `version` by one."

    PRD 3.5: "a filing that would be booked below that minimum is rejected outright
    with `ERR_INSURANCE_BELOW_MINIMUM`."

    PRD 3.6: "The authority's `version` increases by one."

    Design: Corner/cross_cutting_complexity_layers/authority_version_advances_once_per_accepted_write_and_never_on_a_refusal
    """
    env = setup_published_authority(api)
    settle_fee_balance(api, env.carrier_id)
    minimum = env.authority["required_bipd_limit_cents"]

    baseline = authority_version(api, env.authority_id)

    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=list(env.authority["required_jurisdictions"]),
        effective_from=env.publish_at,
    )
    after_designation = authority_version(api, env.authority_id)
    assert after_designation == baseline + 1

    # A refused filing is not a mutation of the authority row, so the guarded
    # version the client already holds stays valid.
    validate_error(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum - 1,
                after_designation,
                filing_type="BIPD",
                policy_number="BIPD-SHORT",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        ApiErrorId.INSURANCE_BELOW_MINIMUM,
    )
    assert authority_version(api, env.authority_id) == after_designation

    validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum,
                after_designation,
                filing_type="BIPD",
                policy_number="BIPD-OK",
                effective_at=env.publish_at,
            ),
            make_insurer_headers(env.insurer_id),
        ),
        201,
    )
    after_filing = authority_version(api, env.authority_id)
    assert after_filing == baseline + 2

    ready = read_authority(api, env.authority_id)
    set_clock(api, ready["activation_eligible_at"])
    activated = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert activated["authority_status"] == "ACTIVE"
    assert activated["version"] == baseline + 3
    assert authority_version(api, env.authority_id) == baseline + 3


def test_the_audit_deadline_is_a_strict_boundary_for_the_sweep(api):
    """At the deadline the audit survives; one day later the sweep misses it.

    PRD 3.6: "The expiry comparison is strict: a sweep running at exactly
    `audit_deadline_at` leaves the audit `SCHEDULED`, and the next millisecond makes
    it `MISSED`."

    PRD 3.8: "Every `SafetyAudit` whose `status` is `SCHEDULED` and whose
    `audit_deadline_at` is strictly earlier than the current logical time moves
    `SCHEDULED → MISSED`"

    PRD 3.8: "for each of those authorities whose `authority_status` is `ACTIVE` a
    `RevocationProceeding` is opened with `reason` `AUDIT_WINDOW_MISSED`, `status`
    `NOTICE_ISSUED`, `notice_issued_at` at the current logical time and
    `cure_deadline_at` 30 days later, followed by the suspension cascade of §2.10
    with `suspension_reason` `AUDIT_WINDOW_MISSED`."

    PRD 3.8: "a proceeding opened by step one is not eligible for step three in that
    same sweep, precisely because step three only considers proceedings whose
    `notice_issued_at` is strictly before this sweep's current logical time."

    Design: Corner/cross_cutting_complexity_layers/the_audit_deadline_is_a_strict_boundary_for_the_sweep
    """
    env = setup_active_authority(api)
    assert env.authority["new_entrant_audit_status"] == "PENDING"
    assert env.authority["new_entrant_audit_deadline_at"] == "2028-02-26T00:00:00.000Z"
    assert env.audit is not None
    assert env.audit["status"] == "SCHEDULED"
    assert env.audit["audit_deadline_at"] == "2028-02-26T00:00:00.000Z"
    # The carrier's registration window closes well after both sweeps below, so
    # step two of the sweep has nothing to flag either time.
    assert env.carrier["biennial_update_due_at"] > "2028-02-27T00:00:00.000Z"

    set_clock(api, "2028-02-26T00:00:00Z")
    on_the_deadline = run_sweep(api)
    assert on_the_deadline["swept_at"] == "2028-02-26T00:00:00.000Z"
    assert on_the_deadline["audits_missed_count"] == 0
    assert on_the_deadline["carriers_flagged_delinquent_count"] == 0
    assert on_the_deadline["authorities_revoked_count"] == 0
    assert on_the_deadline["contracts_terminated_count"] == 0

    audits, _ = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert [row["status"] for row in audits] == ["SCHEDULED"]
    survived = read_authority(api, env.authority_id)
    assert survived["authority_status"] == "ACTIVE"
    assert survived["new_entrant_audit_status"] == "PENDING"

    set_clock(api, "2028-02-27T00:00:00Z")
    past_the_deadline = run_sweep(api)
    assert past_the_deadline["swept_at"] == "2028-02-27T00:00:00.000Z"
    assert past_the_deadline["audits_missed_count"] == 1
    assert past_the_deadline["carriers_flagged_delinquent_count"] == 0
    # The proceeding this very sweep opened is not eligible for its own step three.
    assert past_the_deadline["authorities_revoked_count"] == 0

    audits, _ = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert [row["status"] for row in audits] == ["MISSED"]

    missed = read_authority(api, env.authority_id)
    assert missed["new_entrant_audit_status"] == "MISSED"
    assert missed["authority_status"] == "SUSPENDED"
    assert missed["suspension_reason"] == "AUDIT_WINDOW_MISSED"
    assert missed["suspended_at"] == "2028-02-27T00:00:00.000Z"

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert meta["total_count"] == 1
    assert_created_at_ascending(proceedings)
    proceeding = proceedings[0]
    assert proceeding["reason"] == "AUDIT_WINDOW_MISSED"
    assert proceeding["status"] == "NOTICE_ISSUED"
    assert proceeding["notice_issued_at"] == "2028-02-27T00:00:00.000Z"
    assert proceeding["cure_deadline_at"] == "2028-03-28T00:00:00.000Z"
    assert proceeding["revoked_at"] is None


def test_designation_counters_reconcile_after_each_create_and_revoke(api):
    """The coverage counters follow the active designation set up and back down.

    PRD 3.4: "`designated_state_count` is the number of state codes that appear in
    **both** that covered set and the authority's `required_jurisdictions`.
    `designation_coverage_complete` is true exactly when no required jurisdiction is
    left uncovered — equivalently, when `designated_state_count` equals the number of
    entries in `required_jurisdictions`."

    PRD 3.4: "**Revoking a designation** is a `CarrierRep` action on its own
    designation and moves that row `ACTIVE → REVOKED` with `revoked_at` stamped at
    the current logical time. Because the row left the active set, coverage is
    recomputed, `designated_state_count` drops, and `designation_coverage_complete`
    may become false."

    PRD 3.4: "if the authority was `ACTIVE` the full suspension cascade of §2.10 runs
    with `suspension_reason` set to `DESIGNATION_GAP`"

    Design: Corner/cross_cutting_complexity_layers/designation_counters_reconcile_after_each_create_and_revoke
    """
    env = setup_published_authority(api)
    required = list(env.authority["required_jurisdictions"])
    assert len(required) == 3
    assert set(required) == {"TX", "OK", "NM"}
    assert env.authority["designated_state_count"] == 0
    assert env.authority["designation_coverage_complete"] is False

    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=["TX", "OK"],
        effective_from=env.publish_at,
    )
    partial = read_authority(api, env.authority_id)
    assert partial["designated_state_count"] == 2
    assert partial["designation_coverage_complete"] is False

    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent_id,
        state_codes=["NM"],
        effective_from=env.publish_at,
    )
    complete = read_authority(api, env.authority_id)
    assert complete["designated_state_count"] == 3
    assert complete["designation_coverage_complete"] is True

    designations = list_designations(api, env.authority_id)
    assert len(designations) == 3
    assert_created_at_ascending(designations)
    assert sorted(row["state_code"] for row in designations) == ["NM", "OK", "TX"]
    assert all(row["status"] == "ACTIVE" for row in designations)

    texas = [row for row in designations if row["state_code"] == "TX"][0]
    revoked = validate_success(api.revoke_designation(texas["id"], env.carrier_headers))
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == "2026-08-05T00:00:00.000Z"

    gapped = read_authority(api, env.authority_id)
    assert gapped["designated_state_count"] == 2
    assert gapped["designation_coverage_complete"] is False
    # The authority never reached ACTIVE, so the gap opens no cascade and no
    # suspension reason is written.
    assert gapped["authority_status"] == "PENDING"
    assert gapped["suspension_reason"] == "NONE"
    assert gapped["suspended_at"] is None

    after_revoke = list_designations(api, env.authority_id)
    assert len(after_revoke) == 3
    still_active = [row for row in after_revoke if row["status"] == "ACTIVE"]
    assert sorted(row["state_code"] for row in still_active) == ["NM", "OK"]
