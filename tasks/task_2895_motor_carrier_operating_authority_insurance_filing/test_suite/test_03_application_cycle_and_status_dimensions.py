"""Correction cycles on an application, and the authority's two status dimensions.

Both concerns are non-linear.  The submit / return / resubmit loop of PRD S3.3
may be traversed without bound while the filing fee is charged exactly once, so
``submission_count`` advances past 1 with the fee ledger holding a single
``FILING_FEE_DEBIT``.  And an ``OperatingAuthority`` carries two dimensions that
move under different triggers, so a household-goods docket walks
``insurance_status`` ``NOT_FILED -> PARTIAL -> FILED`` across two filings while
``authority_status`` stays pinned at ``PENDING``.

Every test builds its own registry, application and authority from scratch: the
harness restarts the server and empties the database before each test.
"""

from types import SimpleNamespace

from test_helpers import (
    MAX_LIMIT,
    REGISTRY_ADMIN,
    assert_authority_application,
    assert_fee_ledger_identities,
    assert_insurance_filing,
    assert_operating_authority,
    authority_for_application,
    authority_version,
    create_carrier,
    create_draft_application,
    create_insurer,
    create_process_agent,
    designate_states,
    expected_filing_fee,
    expected_required_minimums,
    file_insurance,
    make_carrier_headers,
    read_authority,
    review_application,
    set_clock,
    submit_application,
    validate_paginated,
    validate_success,
)

T_ENROLL_AT = "2026-08-01T00:00:00Z"
T_PUBLISH_AT = "2026-08-05T00:00:00Z"
T_ELIGIBLE_AT = "2026-08-26T00:00:00.000Z"

CORRECTION_FINDINGS = "process agent list incomplete; correct and resubmit"

# PRD S3.2 filing fee for a NEW FOR_HIRE_PROPERTY application naming three states.
FEE_NEW_FOR_HIRE_THREE_STATES = 64791

FOR_HIRE_STATES = ["TX", "OK", "NM"]
HOUSEHOLD_GOODS_STATES = ["OK", "TX", "AR"]


# ---------------------------------------------------------------------------
# Local chain builders (the atomic PRD S4 calls, in the order S3 pins them)
# ---------------------------------------------------------------------------
def _draft_for_hire_application(api) -> SimpleNamespace:
    """One TX carrier with a DRAFT NEW FOR_HIRE_PROPERTY application, no fees yet."""
    set_clock(api, T_ENROLL_AT)
    carrier = create_carrier(
        api,
        legal_name="Brazos Valley Trucking LLC",
        domicile_state="TX",
        self_reported_vehicle_count=40,
        self_reported_driver_count=60,
        self_reported_oos_rate_pct=12.5,
    )
    application = create_draft_application(
        api,
        carrier["id"],
        application_kind="NEW",
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=list(FOR_HIRE_STATES),
    )
    return SimpleNamespace(
        carrier=carrier,
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
        application=application,
        application_id=application["id"],
    )


def _ledger(api, carrier_id):
    entries, meta = validate_paginated(
        api.list_fee_ledger_entries(carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    return entries, meta


def _carrier(api, carrier_id):
    return validate_success(api.get_carrier(carrier_id, REGISTRY_ADMIN))


# ---------------------------------------------------------------------------
# The RETURN / resubmit cycle
# ---------------------------------------------------------------------------
def test_return_resubmit_cycle_charges_the_filing_fee_exactly_once(api):
    """PRD S3.3: "Every successful submission increases `submission_count` by one,
    and the first one is special."
    PRD S3.3: "When `submission_count` becomes 2 or more, nothing is recomputed,
    no ledger entry is appended, and no carrier fee field moves at all."
    PRD S3.3: "The fee is assessed exactly once per application no matter how many
    correction loops it makes."
    PRD S3.3: "a ledger entry with `entry_type` `FILING_FEE_DEBIT` and an
    `amount_cents` equal to positive `filing_fee_cents` is appended with its
    `docket_ref` naming this application, and both `fees_assessed_total_cents` and
    `fee_balance_cents` on the owning carrier increase by that amount."

    Design: Difficulty/non_linear_state_machine/application_return_resubmit_cycle_charges_the_fee_once
    """
    env = _draft_for_hire_application(api)

    first = validate_success(
        api.submit_application(env.application_id, env.carrier_headers)
    )
    assert first["status"] == "SUBMITTED", first
    assert first["submission_count"] == 1, first
    assert first["filing_fee_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, first
    assert (
        expected_filing_fee("NEW", "FOR_HIRE_PROPERTY", len(FOR_HIRE_STATES))[
            "filing_fee_cents"
        ]
        == FEE_NEW_FOR_HIRE_THREE_STATES
    )

    review_application(
        api, env.application_id, disposition="RETURN", findings=CORRECTION_FINDINGS
    )

    second = validate_success(
        api.submit_application(env.application_id, env.carrier_headers)
    )
    assert_authority_application(second)
    assert second["status"] == "SUBMITTED", second
    assert second["submission_count"] == 2, (
        f"the second traversal of the loop must advance submission_count to 2, "
        f"got {second['submission_count']}"
    )
    assert second["vetting_findings"] == CORRECTION_FINDINGS, second

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1, (
        f"exactly one FeeLedgerEntry may exist after a return/resubmit cycle, "
        f"got {meta['total_count']}: {entries}"
    )
    assert entries[0]["entry_type"] == "FILING_FEE_DEBIT", entries[0]
    assert entries[0]["amount_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, entries[0]

    carrier = _carrier(api, env.carrier_id)
    assert carrier["fees_assessed_total_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, carrier
    assert carrier["fees_reversed_total_cents"] == 0, carrier
    assert carrier["fee_balance_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, carrier
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)


def test_return_leaves_the_filing_fee_debit_standing_and_mints_no_authority(api):
    """PRD S3.3: "a return is not a compensating action, so the ledger is untouched
    and `fee_balance_cents` does not move"
    PRD S3.3: "moves the application `SUBMITTED → RETURNED_FOR_CORRECTION`. No
    authority is created."
    PRD S3.3: "Whichever disposition is chosen, the review writes the submitted
    narrative into `vetting_findings` and records the acting analyst into
    `vetted_by_user_id`."

    Design: Difficulty/non_linear_state_machine/application_return_resubmit_cycle_charges_the_fee_once
    """
    env = _draft_for_hire_application(api)
    submit_application(api, env.carrier_id, env.application_id)
    before = _carrier(api, env.carrier_id)
    assert before["fee_balance_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, before

    returned = review_application(
        api, env.application_id, disposition="RETURN", findings=CORRECTION_FINDINGS
    )
    assert returned["status"] == "RETURNED_FOR_CORRECTION", returned
    assert returned["vetting_findings"] == CORRECTION_FINDINGS, returned
    assert returned["submission_count"] == 1, returned

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1, (
        f"the return must leave the single FILING_FEE_DEBIT standing, got {entries}"
    )
    after = _carrier(api, env.carrier_id)
    assert after["fee_balance_cents"] == before["fee_balance_cents"], after
    assert after["fees_reversed_total_cents"] == 0, after
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    rows, authority_meta = validate_paginated(
        api.list_authorities(REGISTRY_ADMIN, application_id=env.application_id)
    )
    assert authority_meta["total_count"] == 0, (
        f"a RETURN disposition creates no OperatingAuthority, got {rows}"
    )


def test_repeated_correction_loops_advance_submission_count_without_recharging(api):
    """PRD S3.3: "From `RETURNED_FOR_CORRECTION` the carrier may submit again,
    closing the loop `SUBMITTED → RETURNED_FOR_CORRECTION → SUBMITTED`, and that
    loop may be traversed without bound."
    PRD S3.3: "Each traversal increments `submission_count` and charges nothing."

    Design: Difficulty/non_linear_state_machine/application_return_resubmit_cycle_charges_the_fee_once
    """
    env = _draft_for_hire_application(api)
    submit_application(api, env.carrier_id, env.application_id)

    for loop in range(2):
        review_application(
            api,
            env.application_id,
            disposition="RETURN",
            findings=f"{CORRECTION_FINDINGS} (loop {loop})",
        )
        resubmitted = validate_success(
            api.submit_application(env.application_id, env.carrier_headers)
        )
        assert resubmitted["status"] == "SUBMITTED", resubmitted
        assert resubmitted["submission_count"] == loop + 2, resubmitted

    final = validate_success(api.get_application(env.application_id, REGISTRY_ADMIN))
    assert final["submission_count"] == 3, final
    assert final["filing_fee_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, final

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1, (
        f"three submissions must still leave one ledger entry, got {entries}"
    )
    carrier = _carrier(api, env.carrier_id)
    assert carrier["fees_assessed_total_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, carrier
    assert carrier["fee_balance_cents"] == FEE_NEW_FOR_HIRE_THREE_STATES, carrier
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)


# ---------------------------------------------------------------------------
# The two independent status dimensions of one authority
# ---------------------------------------------------------------------------
def _pending_household_goods_authority(api) -> SimpleNamespace:
    """A PENDING HOUSEHOLD_GOODS authority for AR/OK/TX with coverage designated.

    Two insurance slots are required (BIPD and CARGO) and none is filed yet, so
    ``insurance_status`` is still ``NOT_FILED``.
    """
    set_clock(api, T_ENROLL_AT)
    carrier = create_carrier(
        api,
        legal_name="Sooner Household Movers LLC",
        domicile_state="OK",
        self_reported_vehicle_count=12,
        self_reported_driver_count=15,
        self_reported_oos_rate_pct=3.0,
    )
    agent = create_process_agent(
        api,
        company_name="Heartland Agents of Record",
        coverage_states=list(HOUSEHOLD_GOODS_STATES),
        blanket_agent=False,
    )
    insurer = create_insurer(
        api,
        company_name="Cimarron Indemnity",
        naic_code="22334",
        authorized_states=list(HOUSEHOLD_GOODS_STATES),
    )
    application = create_draft_application(
        api,
        carrier["id"],
        application_kind="NEW",
        transportation_type="HOUSEHOLD_GOODS",
        requested_operating_states=list(HOUSEHOLD_GOODS_STATES),
    )
    submit_application(api, carrier["id"], application["id"])
    set_clock(api, T_PUBLISH_AT)
    application = review_application(
        api,
        application["id"],
        disposition="PUBLISH",
        findings="household goods tariff on file",
    )
    authority = authority_for_application(api, application["id"])
    designate_states(
        api,
        carrier["id"],
        authority["id"],
        agent["id"],
        state_codes=list(authority["required_jurisdictions"]),
        effective_from=T_PUBLISH_AT,
    )
    return SimpleNamespace(
        carrier_id=carrier["id"],
        insurer_id=insurer["id"],
        application_id=application["id"],
        authority=read_authority(api, authority["id"]),
        authority_id=authority["id"],
    )


def test_household_goods_insurance_dimension_walks_partial_then_filed_while_pending(api):
    """PRD S3.4: "The two dimensions are recomputed by different triggers and neither
    is derivable from the other: an authority may sit `SUSPENDED` while its
    `insurance_status` reads `FILED` — that is exactly what a designation gap looks
    like — and `insurance_status` moves on filing creates and cancels regardless of
    what `authority_status` currently reads."
    PRD S3.5: "Those required slots are: `BIPD` whenever `required_bipd_limit_cents`
    is greater than zero, `CARGO` whenever `required_cargo_limit_cents` is greater
    than zero, and one filing of type either `SURETY_BOND` or `TRUST_FUND` whenever
    `required_bond_limit_cents` is greater than zero."
    PRD S3.5: "`NOT_FILED → PARTIAL` when at least one, but not all, of the required
    slots is satisfied."
    PRD S3.5: "`PARTIAL → FILED` when every required slot is satisfied."

    Design: Difficulty/non_linear_state_machine/authority_status_and_insurance_status_dimensions_advance_independently
    """
    env = _pending_household_goods_authority(api)
    minimums = expected_required_minimums("HOUSEHOLD_GOODS", len(HOUSEHOLD_GOODS_STATES))

    opening = env.authority
    assert_operating_authority(opening)
    assert opening["authority_status"] == "PENDING", opening
    assert opening["insurance_status"] == "NOT_FILED", opening
    assert opening["required_bipd_limit_cents"] == 75000000, opening
    assert opening["required_cargo_limit_cents"] == 1000000, opening
    assert opening["required_bipd_limit_cents"] == minimums["required_bipd_limit_cents"]
    assert opening["required_cargo_limit_cents"] == minimums["required_cargo_limit_cents"]
    assert opening["designation_coverage_complete"] is True, opening

    file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        1000000,
        filing_type="CARGO",
        effective_at=T_PUBLISH_AT,
        policy_number="CARGO-1",
    )
    partial = read_authority(api, env.authority_id)
    assert partial["insurance_status"] == "PARTIAL", (
        f"one of two required slots is satisfied, so insurance_status must be "
        f"PARTIAL, got {partial['insurance_status']}"
    )
    assert partial["authority_status"] == "PENDING", (
        f"a filing must not move authority_status, got {partial['authority_status']}"
    )

    file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        75000000,
        filing_type="BIPD",
        effective_at=T_PUBLISH_AT,
        policy_number="BIPD-1",
    )
    filed = read_authority(api, env.authority_id)
    assert filed["insurance_status"] == "FILED", filed
    assert filed["authority_status"] == "PENDING", (
        "both required slots are satisfied, but only the insurance dimension moved; "
        f"authority_status must still be PENDING, got {filed['authority_status']}"
    )


def test_reaching_insurance_filed_leaves_the_authority_unactivated(api):
    """PRD S3.4: "Everything else on the new authority opens at its resting value:
    `authority_status` is `PENDING`, `insurance_status` is `NOT_FILED`,
    `designated_state_count` is 0 and `designation_coverage_complete` is false,
    `suspension_reason` is `NONE`, `active_contract_count` and
    `suspended_contract_count` are both 0, `new_entrant_audit_status` is
    `NOT_REQUIRED` with `new_entrant_audit_deadline_at` null, and `activated_at`,
    `suspended_at`, `revoked_at` and `rescinded_at` are all null."
    PRD S3.4: "`publication_at` is stamped with the current logical time and
    `activation_eligible_at` is set to `publication_at` plus 21 days."

    Design: Difficulty/non_linear_state_machine/authority_status_and_insurance_status_dimensions_advance_independently
    """
    env = _pending_household_goods_authority(api)
    file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        1000000,
        filing_type="CARGO",
        effective_at=T_PUBLISH_AT,
        policy_number="CARGO-1",
    )
    file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        75000000,
        filing_type="BIPD",
        effective_at=T_PUBLISH_AT,
        policy_number="BIPD-1",
    )

    authority = read_authority(api, env.authority_id)
    assert authority["insurance_status"] == "FILED", authority
    assert authority["authority_status"] == "PENDING", authority
    assert authority["activated_at"] is None, (
        "reaching insurance_status FILED must not activate the authority; "
        f"activated_at is {authority['activated_at']}"
    )
    assert authority["publication_at"] == "2026-08-05T00:00:00.000Z", authority
    assert authority["activation_eligible_at"] == T_ELIGIBLE_AT, authority
    assert authority["suspension_reason"] == "NONE", authority
    assert authority["active_contract_count"] == 0, authority
    assert authority["suspended_contract_count"] == 0, authority


def test_each_insurance_filing_bumps_the_authority_version_exactly_once(api):
    """PRD S3.5: "Every filing create and every filing cancel that moves the coverage
    dimension increases the authority's `version` by one."
    PRD S3.5: "`meets_required_minimum` is set from the comparison of
    `coverage_limit_cents` against the authority's required limit for this
    `filing_type` — `required_bipd_limit_cents` for a `BIPD` filing,
    `required_cargo_limit_cents` for a `CARGO` filing, and `required_bond_limit_cents`
    for a `SURETY_BOND` or `TRUST_FUND` filing"
    PRD S3.5: "If the slot was empty, `supersedes_filing_id` stays null."

    Design: Difficulty/non_linear_state_machine/authority_status_and_insurance_status_dimensions_advance_independently
    """
    env = _pending_household_goods_authority(api)
    version_before_cargo = authority_version(api, env.authority_id)

    cargo = file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        1000000,
        filing_type="CARGO",
        effective_at=T_PUBLISH_AT,
        policy_number="CARGO-1",
    )
    version_after_cargo = authority_version(api, env.authority_id)
    assert version_after_cargo == version_before_cargo + 1, (
        f"the CARGO filing moved insurance_status NOT_FILED -> PARTIAL, so the "
        f"authority version must advance by exactly one: "
        f"{version_before_cargo} -> {version_after_cargo}"
    )

    bipd = file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        75000000,
        filing_type="BIPD",
        effective_at=T_PUBLISH_AT,
        policy_number="BIPD-1",
    )
    version_after_bipd = authority_version(api, env.authority_id)
    assert version_after_bipd == version_after_cargo + 1, (
        f"the BIPD filing moved insurance_status PARTIAL -> FILED, so the authority "
        f"version must advance by exactly one again: "
        f"{version_after_cargo} -> {version_after_bipd}"
    )

    assert_insurance_filing(cargo)
    assert_insurance_filing(bipd)
    assert cargo["status"] == "ACTIVE", cargo
    assert bipd["status"] == "ACTIVE", bipd
    assert cargo["meets_required_minimum"] is True, cargo
    assert bipd["meets_required_minimum"] is True, bipd
    assert cargo["supersedes_filing_id"] is None, (
        f"the CARGO slot was empty, so supersedes_filing_id stays null: {cargo}"
    )
    assert bipd["supersedes_filing_id"] is None, (
        f"the BIPD slot was empty, so supersedes_filing_id stays null: {bipd}"
    )
    assert read_authority(api, env.authority_id)["authority_status"] == "PENDING"
