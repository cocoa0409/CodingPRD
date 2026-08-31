"""Filing, approving and unwinding deferral elections."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_attribution_sums_to_elected_amount,
    create_election_payload,
    determine_eligibility,
    file_notice,
    make_officer_headers,
    make_participant_headers,
    make_sponsor_headers,
    open_contract,
    participant_version,
    register_participant,
    report_balance,
    set_clock,
    setup_election_ready,
    setup_plan_env,
    submit_election,
    approve_election,
    update_participant,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pre_snapshot_env():
    """A 403(b) participant carrying 1,200,000 cents of consumed special catch-up and a
    SUBMITTED 1,000,000-cent election electing both 403(b) catch-ups."""
    env = setup_election_ready(
        participant_overrides={
            "full_name": "Dana Prewitt", "date_of_birth": "1970-01-01",
            "hire_date": "2004-01-01", "years_of_service": 20,
            "cumulative_special_catchup_used_cents": 1_200_000,
        },
        contract_overrides={
            "contract_number": "NLA-D001", "accumulated_benefit_cents": 4_000_000,
            "prior_years_elective_deferrals_cents": 2_000_000,
        },
        run_determination=False,
    )
    report_balance(
        env["account_id"], env["vendor_id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=4_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=2_300_000,
    )
    determine_eligibility(env["plan_id"], env["participant_id"], "co-1")
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=1_000_000, effective_from="2026-09-01",
        effective_through="2026-12-31", catchup_election="AGE_50_AND_SERVICE_15_YEAR",
    )
    env["election_id"] = election["id"]
    return env


def test_attribution_uses_the_pre_approval_catchup_snapshot(api):
    """PRD §3.6: "Step one fills `basic_deferral_attributed_cents` with the lesser of the
    elected amount and the basic limit reduced by the gross year-to-date deferrals, that
    reduction itself floored at zero."
    PRD §3.6: "Step two fills `service_catchup_attributed_cents` — on a `PLAN_403B` plan
    and only when `catchup_election` is `SERVICE_15_YEAR` or
    `AGE_50_AND_SERVICE_15_YEAR` — with the lesser of the carried-forward remainder and
    the fifteen-year service capacity; in every other case it is zero."
    PRD §3.6: "Step four, and last, fills `age50_catchup_attributed_cents` — only when
    `catchup_election` is `AGE_50` or `AGE_50_AND_SERVICE_15_YEAR` — with the lesser of
    the remaining amount and the age-50 capacity; otherwise zero."

    Design: Difficulty/combinatorial_formula/deferral_attribution_pre_snapshot_capacity_order
    """
    env = _pre_snapshot_env()

    approved = validate_success(
        api.decide_election(
            env["election_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )

    assert approved["state"] == "EFFECTIVE"
    assert approved["basic_deferral_attributed_cents"] == 150_000
    assert approved["service_catchup_attributed_cents"] == 300_000
    assert approved["age50_catchup_attributed_cents"] == 550_000
    assert approved["final3yr_catchup_attributed_cents"] == 0
    assert_attribution_sums_to_elected_amount(approved)


def test_approved_election_increments_lifetime_special_catchup_and_projection(api):
    """PRD §3.6: "The participant's `cumulative_special_catchup_used_cents` is increased
    by the `service_catchup_attributed_cents` just attributed — the snapshot value plus
    the service amount, and no other addend."
    PRD §3.6: "When the approval succeeds, the four attributed figures always sum to
    exactly `annual_deferral_amount_cents`, and no bucket can be negative."
    PRD §2.10: "And `projected_annual_deferral_cents` is the sum of
    `annual_deferral_amount_cents` over the participant's elections in state
    `EFFECTIVE`."

    Design: Difficulty/combinatorial_formula/deferral_attribution_pre_snapshot_capacity_order
    """
    env = _pre_snapshot_env()

    approve_election(env["election_id"], "co-2")

    participant = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert participant["cumulative_special_catchup_used_cents"] == 1_500_000, (
        "the snapshot 1200000 plus the 300000 service attribution, and no other addend"
    )
    assert participant["projected_annual_deferral_cents"] == 1_000_000


def test_election_window_sharing_one_day_collides(api):
    """PRD §3.6: "Election windows are **closed intervals** and they collide on a shared
    endpoint."
    PRD §3.6: "A new window for the same participant and the same plan conflicts with any
    existing election in state `SUBMITTED` or `EFFECTIVE` when the new `effective_from`
    falls on or before that election's `effective_through` and that election's
    `effective_from` falls on or before the new `effective_through`. Two windows that
    merely abut — one ending on the very day the next begins — therefore do collide, and
    the filing is refused with `ERR_ELECTION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/election_window_closed_adjacency_rejected
    """
    env = setup_election_ready()
    standing = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=500_000, effective_from="2026-01-01",
        effective_through="2026-06-30",
    )
    effective = approve_election(standing["id"], "co-2")
    assert effective["state"] == "EFFECTIVE"
    assert effective["effective_through"] == "2026-06-30"

    response = api.create_election(
        create_election_payload(
            env["participant_id"], env["plan_id"], env["account_id"],
            participant_version(env["participant_id"], env["employer_id"]),
            annual_deferral_amount_cents=500_000, effective_from="2026-06-30",
            effective_through="2026-12-31",
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_ELECTION_WINDOW_OVERLAP.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": env["participant_id"]})
    )
    assert len(rows) == 1, "the colliding window must not have been filed"


def test_election_window_starting_the_next_day_is_admitted(api):
    """PRD §3.6: "A new window for the same participant and the same plan conflicts with
    any existing election in state `SUBMITTED` or `EFFECTIVE` when the new
    `effective_from` falls on or before that election's `effective_through` and that
    election's `effective_from` falls on or before the new `effective_through`."
    PRD §3.6: "The election is created in state `SUBMITTED`, its `submitted_by_user_id`
    is recorded from the acting `X-User-ID`, and the participant's `version` is
    incremented by one — which is precisely why a second election filed from the same
    stale read will be turned away."

    Design: Difficulty/resource_temporal_overlap/election_window_closed_adjacency_rejected
    """
    env = setup_election_ready()
    standing = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=500_000, effective_from="2026-01-01",
        effective_through="2026-06-30",
    )
    approve_election(standing["id"], "co-2")

    admitted = validate_success(
        api.create_election(
            create_election_payload(
                env["participant_id"], env["plan_id"], env["account_id"],
                participant_version(env["participant_id"], env["employer_id"]),
                annual_deferral_amount_cents=500_000, effective_from="2026-07-01",
                effective_through="2026-12-31",
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert admitted["state"] == "SUBMITTED"
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": env["participant_id"]})
    )
    assert len(rows) == 2


def test_election_approval_refused_while_determination_reads_excluded(api):
    """PRD §3.6: "It requires that the election is currently `SUBMITTED`, that the
    governing plan's `status` is `ACTIVE` — a frozen plan cannot have elections approved
    — that the latest non-superseded eligibility determination for this election's
    plan-and-participant pair exists and reads `ELIGIBLE`, failing which the answer is
    `ERR_PARTICIPANT_NOT_ELIGIBLE`; that the same determination's `notice_status` is
    `CURRENT`, failing which the answer is `ERR_UA_NOTICE_MISSING`; that the approving
    officer's `X-User-ID` differs from that determination's `determined_by_user_id`,
    failing which the answer is `ERR_SEGREGATION_OF_DUTIES`; and that the attribution
    waterfall below leaves nothing unattributed."
    PRD §3.3: "otherwise if `is_student_performing_services` is true the status is
    `EXCLUDED_STUDENT`"

    Design: Difficulty/cross_entity_state_dependency/election_approval_gated_by_eligibility_determination_status
    """
    env = setup_election_ready(
        participant_overrides={
            "full_name": "Sam Student", "date_of_birth": "1998-02-02",
            "hire_date": "2024-09-01", "scheduled_hours_per_week": 25,
            "prior_year_hours_worked": 1200, "includible_compensation_cents": 2_000_000,
            "years_of_service": 2, "is_student_performing_services": True,
        },
        contract_overrides={"contract_number": "NLA-S001", "accumulated_benefit_cents": 500_000},
    )
    assert env["determination"]["status"] == "EXCLUDED_STUDENT"
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=1_000_000, effective_from="2026-09-01",
        effective_through="2026-12-31",
    )

    response = api.decide_election(
        election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value)
    assert validate_success(
        api.get_election(election["id"], make_officer_headers())
    )["state"] == "SUBMITTED"


def test_election_approval_succeeds_after_a_fresh_eligible_determination(api):
    """PRD §3.3: "The determination records `determined_at` from the logical clock and
    `determined_by_user_id` from the acting officer's `X-User-ID`, and marks `superseded`
    true on every earlier determination for the same plan-and-participant pair, leaving
    exactly one live determination per pair."
    PRD §3.6: "Approval moves the election `SUBMITTED → EFFECTIVE` and is the most
    heavily guarded transition in the system."
    PRD §3.3: "Employment facts drift, so a sponsor admin may revise a registered
    employee's `scheduled_hours_per_week`, `prior_year_hours_worked`,
    `employment_status`, `termination_date`, `includible_compensation_cents`,
    `years_of_service`, `is_select_management_or_hce`, `is_student_performing_services`
    and `is_nonresident_alien_no_us_income`."

    Design: Difficulty/cross_entity_state_dependency/election_approval_gated_by_eligibility_determination_status
    """
    env = setup_election_ready(
        participant_overrides={
            "full_name": "Sam Student", "date_of_birth": "1998-02-02",
            "hire_date": "2024-09-01", "scheduled_hours_per_week": 25,
            "prior_year_hours_worked": 1200, "includible_compensation_cents": 2_000_000,
            "years_of_service": 2, "is_student_performing_services": True,
        },
        contract_overrides={"contract_number": "NLA-S001", "accumulated_benefit_cents": 500_000},
    )
    first_determination = env["determination"]
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=1_000_000, effective_from="2026-09-01",
        effective_through="2026-12-31",
    )
    validate_error(
        api.decide_election(election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")),
        ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value,
    )

    update_participant(
        env["participant_id"], env["employer_id"], is_student_performing_services=False
    )
    second_determination = determine_eligibility(env["plan_id"], env["participant_id"], "co-1")
    approved = validate_success(
        api.decide_election(
            election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
        )
    )

    assert validate_success(
        api.get_eligibility_determination(first_determination["id"], make_officer_headers())
    )["superseded"] is True
    assert second_determination["status"] == "ELIGIBLE"
    assert second_determination["notice_status"] == "CURRENT"
    assert approved["state"] == "EFFECTIVE"
    assert approved["basic_deferral_attributed_cents"] == 1_000_000


def test_supersession_exempts_the_named_election_from_the_window_test(api):
    """PRD §3.6: "The one exception is the supersession case: an existing election is
    exempt from this test when the new election's `supersedes_election_id` names that
    very row."
    PRD §3.6: "When `supersedes_election_id` is non-null, the named election transitions
    `EFFECTIVE → SUPERSEDED`, its own `effective_through` is truncated to the day
    immediately before the new election's `effective_from`, and its `version` increments
    by one."

    Design: Corner/entities/contribution_election_self_reference_reverse_lookup_by_supersedes_election_id
    """
    env = setup_election_ready()
    first = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=500_000, effective_from="2026-01-01",
        effective_through="2026-06-30",
    )
    approve_election(first["id"], "co-2")

    second = validate_success(
        api.create_election(
            create_election_payload(
                env["participant_id"], env["plan_id"], env["account_id"],
                participant_version(env["participant_id"], env["employer_id"]),
                annual_deferral_amount_cents=600_000, effective_from="2026-04-01",
                effective_through="2026-12-31", supersedes_election_id=first["id"],
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )
    approve_election(second["id"], "co-2")

    superseded = validate_success(api.get_election(first["id"], make_officer_headers()))
    assert superseded["state"] == "SUPERSEDED"
    assert superseded["effective_through"] == "2026-03-31"
    assert validate_success(
        api.get_election(second["id"], make_officer_headers())
    )["state"] == "EFFECTIVE"

    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"supersedes_election_id": first["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == second["id"]
    assert validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )["projected_annual_deferral_cents"] == 600_000


def test_final_three_year_catchup_on_a_403b_plan_is_rejected(api):
    """PRD §3.6: "`FINAL_3_YEAR` is permitted only on a `PLAN_457B` plan."
    PRD §3.6: "A structurally impossible combination is refused with
    `ERR_CATCHUP_COMBINATION_NOT_PERMITTED`."

    Design: Corner/validations/catchup_election_final_three_year_on_403b_plan_is_rejected
    """
    env = setup_election_ready(
        participant_overrides={
            "full_name": "Fern Vela", "date_of_birth": "1963-01-01",
            "hire_date": "2000-01-01", "years_of_service": 26,
            "underutilized_prior_limit_cents": 1_000_000,
        },
        contract_overrides={"contract_number": "NLA-F001"},
    )

    response = api.create_election(
        create_election_payload(
            env["participant_id"], env["plan_id"], env["account_id"],
            participant_version(env["participant_id"], env["employer_id"]),
            annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
            effective_through="2026-12-31", catchup_election="FINAL_3_YEAR",
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_CATCHUP_COMBINATION_NOT_PERMITTED.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": env["participant_id"]})
    )
    assert rows == []


def test_age_fifty_catchup_below_the_age_threshold_is_rejected(api):
    """PRD §3.6: "Separately, every bucket the election actually names must have non-zero
    capacity for this particular participant: naming `AGE_50` requires
    `attained_age_at_year_end` of at least 50 and, on a 457(b), `is_governmental_457`
    true; naming `SERVICE_15_YEAR` requires the sponsor's `is_qualified_organization`
    true and `years_of_service` of at least 15; naming `FINAL_3_YEAR` requires
    `attained_age_at_year_end` to be 62, 63 or 64. A named bucket with zero capacity is
    refused with `ERR_CATCHUP_NOT_AVAILABLE`."
    PRD §3.3: "`attained_age_at_year_end` is the calendar year of the current logical
    clock minus the calendar year of `date_of_birth` — a whole-year difference, not a
    birthday-adjusted age."

    Design: Corner/validations/catchup_election_age_fifty_below_threshold_is_rejected
    """
    env = setup_election_ready(
        participant_overrides={
            "full_name": "Ben Okafor", "date_of_birth": "1980-01-01",
            "hire_date": "2010-01-01", "includible_compensation_cents": 8_000_000,
            "years_of_service": 16,
        },
        contract_overrides={"contract_number": "NLA-B001"},
    )
    assert validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )["attained_age_at_year_end"] == 46

    response = api.create_election(
        create_election_payload(
            env["participant_id"], env["plan_id"], env["account_id"],
            participant_version(env["participant_id"], env["employer_id"]),
            annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
            effective_through="2026-12-31", catchup_election="AGE_50",
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_CATCHUP_NOT_AVAILABLE.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": env["participant_id"]})
    )
    assert rows == []


def test_determining_officer_cannot_approve_the_election(api):
    """PRD §2.6 rung 7: "Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). This rung guards exactly two operations: the compliance decision on a
    participant request, where `X-User-ID` must differ from the stored
    `reviewed_by_user_id` whenever the decision is an approval or a denial; and the
    compliance decision on a contribution election, where `X-User-ID` must differ from
    the `determined_by_user_id` of the latest non-superseded eligibility determination
    for that election's plan-and-participant pair."
    PRD §3.6: "Approval moves the election `SUBMITTED → EFFECTIVE` and is the most
    heavily guarded transition in the system."

    Design: Corner/validations/determining_officer_cannot_approve_the_election_it_governs
    """
    env = setup_election_ready(determining_officer="co-1")
    assert env["determination"]["determined_by_user_id"] == "co-1"
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
        effective_through="2026-12-31",
    )

    refused = api.decide_election(
        election["id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    blocked = validate_success(api.get_election(election["id"], make_officer_headers()))
    assert blocked["state"] == "SUBMITTED"
    assert blocked["approved_by_user_id"] is None

    approved = validate_success(
        api.decide_election(election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2"))
    )
    assert approved["state"] == "EFFECTIVE"
    assert approved["approved_by_user_id"] == "co-2"


def test_election_approval_without_a_notice_is_refused(api):
    """PRD §3.6: "that the same determination's `notice_status` is `CURRENT`, failing
    which the answer is `ERR_UA_NOTICE_MISSING`"
    PRD §3.3: "if there are none, `notice_status` is `MISSING`; if at least one of them
    has `is_valid` true, `notice_status` is `CURRENT`; if some exist but none is valid,
    `notice_status` is `INVALID`."

    Design: Corner/errors/error_ua_notice_missing_on_election_approval
    """
    env = setup_election_ready(file_valid_notice=False)
    assert env["determination"]["notice_status"] == "MISSING"
    assert env["determination"]["status"] == "ELIGIBLE"
    election = submit_election(
        env["participant_id"], env["plan_id"], env["account_id"], env["employer_id"],
        annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
        effective_through="2026-12-31",
    )

    validate_error(
        api.decide_election(election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")),
        ApiErrorId.ERR_UA_NOTICE_MISSING.value,
    )

    file_notice(env["plan_id"], env["employer_id"])
    refreshed = determine_eligibility(env["plan_id"], env["participant_id"], "co-1")
    assert refreshed["notice_status"] == "CURRENT"
    approved = validate_success(
        api.decide_election(election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2"))
    )
    assert approved["state"] == "EFFECTIVE"


def test_contract_creation_against_a_draft_plan_is_refused(api):
    """PRD §2.6 rung 10: "The governing plan is neither `DRAFT` nor `TERMINATED` —
    otherwise `ERR_PLAN_NOT_ACTIVE` (HTTP 409). This rung guards agreement creation,
    notice filing, contract opening, election submission, remittance batch creation,
    participant request submission and movement request submission."
    PRD §3.4: "The governing plan must be `ACTIVE` or `FROZEN`."

    Design: Corner/validations/election_creation_against_a_draft_plan_returns_plan_not_active
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1, activate=False)
    participant = register_participant(env["employer_id"])

    response = api.create_vendor_account(
        {
            "participant_id": participant["id"], "plan_id": env["plan_id"],
            "vendor_id": env["vendor_id"], "contract_number": "NLA-0001",
            "accumulated_benefit_cents": 1_000_000,
        },
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)
    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["status"] == "DRAFT"
    rows, _meta = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert rows == []


def test_unknown_supersedes_election_id_is_not_found(api):
    """PRD §3.6: "A `supersedes_election_id` that resolves to no election at all is a
    not-found condition and yields `ERR_ELECTION_NOT_FOUND`."

    Design: Corner/validations/election_creation_with_unknown_supersedes_election_id_returns_not_found
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        accumulated_benefit_cents=1_000_000,
    )

    response = api.create_election(
        create_election_payload(
            participant["id"], env["plan_id"], account["id"],
            participant_version(participant["id"], env["employer_id"]),
            annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
            effective_through="2026-12-31", supersedes_election_id=NON_EXISTENT_UUID,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_ELECTION_NOT_FOUND.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": participant["id"]})
    )
    assert rows == []


def test_stale_participant_version_on_election_creation_is_rejected(api):
    """PRD §2.5: "A `POST /plan-admin/contribution-elections` request must carry
    `expected_participant_version` as a required, non-optional field, holding the
    `version` of the target `Participant` as the client last observed it. If that value
    does not equal the participant's current `version`, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "Each such revision increments the participant's `version` by one — which
    matters, because that same counter is what the optimistic concurrency guard of §2.5
    checks when an election is filed."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_participant_version_on_election_create
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        accumulated_benefit_cents=5_000_000,
    )
    stale_version = participant_version(participant["id"], env["employer_id"])
    update_participant(
        participant["id"], env["employer_id"], includible_compensation_cents=9_500_000
    )

    stale = api.create_election(
        create_election_payload(
            participant["id"], env["plan_id"], account["id"], stale_version,
            annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
            effective_through="2026-12-31",
        ),
        make_sponsor_headers(env["employer_id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": participant["id"]})
    )
    assert rows == []

    fresh_version = participant_version(participant["id"], env["employer_id"])
    created = validate_success(
        api.create_election(
            create_election_payload(
                participant["id"], env["plan_id"], account["id"], fresh_version,
                annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
                effective_through="2026-12-31",
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )
    assert created["state"] == "SUBMITTED"
    assert participant_version(participant["id"], env["employer_id"]) > fresh_version


def test_participant_cannot_file_an_election_for_another_participant(api):
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the
    acting `Participant`; ownership checks on any resource that references a
    `Participant` compare the resource's `participant_id` to `X-User-ID`. An
    entity-backed role that addresses a resource it does not own is refused with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to every mutating
    endpoint."

    Design: Corner/validations/participant_cannot_create_election_for_another_participant
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    owner = register_participant(env["employer_id"])
    other = register_participant(
        env["employer_id"], full_name="Ben Okafor", date_of_birth="1980-01-01",
        hire_date="2010-01-01", includible_compensation_cents=8_000_000, years_of_service=16,
    )
    account = open_contract(
        owner["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-A", accumulated_benefit_cents=1_000_000,
    )

    response = api.create_election(
        create_election_payload(
            owner["id"], env["plan_id"], account["id"],
            participant_version(owner["id"], env["employer_id"]),
            annual_deferral_amount_cents=100_000, effective_from="2026-09-01",
            effective_through="2026-12-31",
        ),
        make_participant_headers(other["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    rows, _meta = validate_paginated(
        api.list_elections(make_officer_headers(), {"participant_id": owner["id"]})
    )
    assert rows == []
