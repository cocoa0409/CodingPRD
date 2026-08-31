"""Sponsor registration, plan creation and the plan lifecycle."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_employer,
    assert_plan,
    assert_universal_availability_notice,
    assert_vendor_account,
    create_plan_payload,
    determine_eligibility,
    file_notice,
    make_officer_headers,
    make_sponsor_headers,
    make_operator_headers,
    open_contract,
    register_church_employer,
    register_employer,
    register_nonqualified_employer,
    register_participant,
    register_second_vendor,
    register_vendor,
    set_clock,
    setup_basic_403b,
    setup_election_ready,
    setup_plan_env,
    submit_election,
    approve_election,
    move_plan,
    create_plan,
    create_active_plan,
    setup_active_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)


def test_employer_registration_derives_governmental_and_qualified_flags(api):
    """PRD §2.8: "`is_governmental` is true exactly when the sponsor's `entity_type`
    is `PUBLIC_SCHOOL` or `GOVERNMENTAL_NON_SCHOOL`."
    PRD §2.8: "`is_qualified_organization` — the gate for the 403(b) fifteen-year
    service catch-up — is true exactly when the sponsor's `entity_type` is
    `PUBLIC_SCHOOL` or `CHURCH`, or when the `entity_type` is `TAX_EXEMPT_501C3`
    and the `organization_subtype` is one of `HOSPITAL`, `HOME_HEALTH_AGENCY` or
    `HEALTH_AND_WELFARE_AGENCY`."

    Design: Corner/entities/employer_creation_derives_governmental_and_qualified_organization_flags
    """
    set_clock()
    gov = validate_success(
        api.create_employer(
            {
                "legal_name": "Riverbend Unified School District",
                "ein": "11-1111111",
                "entity_type": "PUBLIC_SCHOOL",
                "organization_subtype": "SCHOOL",
                "total_employee_count": 400,
            },
            make_operator_headers(),
        ),
        expected_status=201,
    )
    nonqualified = validate_success(
        api.create_employer(
            {
                "legal_name": "Lakeside Community Trust",
                "ein": "33-3333333",
                "entity_type": "TAX_EXEMPT_501C3",
                "organization_subtype": "OTHER",
                "total_employee_count": 300,
            },
            make_operator_headers(),
        ),
        expected_status=201,
    )
    hospital = validate_success(
        api.create_employer(
            {
                "legal_name": "Harborview Hospital",
                "ein": "44-4444444",
                "entity_type": "TAX_EXEMPT_501C3",
                "organization_subtype": "HOSPITAL",
                "total_employee_count": 900,
            },
            make_operator_headers(),
        ),
        expected_status=201,
    )

    assert gov["is_governmental"] is True
    assert gov["is_qualified_organization"] is True
    assert nonqualified["is_governmental"] is False
    assert nonqualified["is_qualified_organization"] is False
    assert hospital["is_governmental"] is False
    assert hospital["is_qualified_organization"] is True
    for row in (gov, nonqualified, hospital):
        assert_employer(row)
        assert row["version"] == 1, "a freshly created row starts at version 1"


def test_plan_creation_without_plan_type_is_rejected(api):
    """PRD §2.6 rung 3: "Request body and query string well formed — every required
    field present, every enum value a member of its declared set, every
    cent-denominated field an integer inside its declared bounds, every date field
    a parseable ISO 8601 date, `limit` inside 1 to 100 and `offset` at least 0, and
    `line_items` a non-empty array of objects each carrying `vendor_account_id`,
    `elective_deferral_cents` and `employer_contribution_cents`. Otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "A `PlanSponsorAdmin` then creates a plan against a sponsor by naming
    its `employer_id`, giving it a `plan_name`, declaring its `plan_type` as either
    `PLAN_403B` or `PLAN_457B`, and stating the `plan_year` it governs — a calendar
    year no earlier than 2000 and no later than 2100 — together with the
    `reported_participant_count` as of the first day of that year, which may be zero
    but never negative."

    Design: Corner/entities/plan_creation_missing_required_plan_type_returns_invalid_request
    """
    set_clock()
    employer = register_employer()

    payload = create_plan_payload(employer["id"])
    payload.pop("plan_type")
    response = api.create_plan(payload, make_sponsor_headers(employer["id"]))

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, _meta = validate_paginated(api.list_plans(make_officer_headers()))
    assert rows == [], "a rejected creation must leave no plan behind"


def test_plan_creation_with_unknown_plan_type_is_rejected(api):
    """PRD §3.1: "A `PlanSponsorAdmin` then creates a plan against a sponsor by naming
    its `employer_id`, giving it a `plan_name`, declaring its `plan_type` as either
    `PLAN_403B` or `PLAN_457B`, and stating the `plan_year` it governs — a calendar
    year no earlier than 2000 and no later than 2100 — together with the
    `reported_participant_count` as of the first day of that year, which may be zero
    but never negative."
    PRD §2.6 rung 3: "every enum value a member of its declared set"

    Design: Corner/entities/plan_creation_with_unknown_plan_type_enum_returns_invalid_request
    """
    set_clock()
    employer = register_employer()

    response = api.create_plan(
        create_plan_payload(employer["id"], plan_name="Riverbend 401(k)", plan_type="PLAN_401K"),
        make_sponsor_headers(employer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, _meta = validate_paginated(api.list_plans(make_officer_headers()))
    assert rows == [], "an unknown plan_type must create nothing"


def test_plan_permission_flags_default_to_true(api):
    """PRD §3.1: "Six plan-document permissions may be supplied and each defaults to
    true when omitted: `permits_loans`, `permits_hardship`,
    `permits_unforeseeable_emergency`, `permits_contract_exchanges`,
    `permits_incoming_transfers` and `permits_outgoing_transfers`. The plan is born
    in `DRAFT`."
    PRD §3.1: "sets `is_small_plan` true exactly when `reported_participant_count` is
    below one hundred, which is what selects the shorter remittance safe harbour
    later on"

    Design: Corner/entities/plan_permission_flags_default_to_true_when_omitted
    """
    set_clock()
    employer = register_employer()

    plan = validate_success(
        api.create_plan(
            create_plan_payload(employer["id"]), make_sponsor_headers(employer["id"])
        ),
        expected_status=201,
    )

    assert_plan(plan)
    assert plan["permits_loans"] is True
    assert plan["permits_hardship"] is True
    assert plan["permits_unforeseeable_emergency"] is True
    assert plan["permits_contract_exchanges"] is True
    assert plan["permits_incoming_transfers"] is True
    assert plan["permits_outgoing_transfers"] is True
    assert plan["status"] == "DRAFT"
    assert plan["open_correction_count"] == 0
    assert plan["compliance_posture"] == "CLEAR"
    assert plan["is_small_plan"] is False, "250 reported participants is not below one hundred"


def test_vendor_account_vested_balance_is_floored(api):
    """PRD §3.4: "`vested_balance_cents` is always derived, never supplied: it is
    `accumulated_benefit_cents` multiplied by `vested_percentage_bps`, divided by
    10000, with the result floored to a whole cent."
    PRD §3.4: "The contract is created with `status` `OPEN`, and the server
    immediately computes `vested_balance_cents` and refreshes the owning
    participant's `total_accumulated_benefit_cents`, `total_vested_balance_cents`
    and `lifetime_elective_deferrals_cents`."

    Design: Corner/entities/vendor_account_vested_balance_computed_by_floor_of_basis_points
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    participant = register_participant(env["employer_id"])

    account = validate_success(
        api.create_vendor_account(
            {
                "participant_id": participant["id"],
                "plan_id": env["plan_id"],
                "vendor_id": env["vendor_id"],
                "contract_number": "NLA-0001",
                "accumulated_benefit_cents": 3_333_333,
                "vested_percentage_bps": 6667,
            },
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert_vendor_account(account)
    assert account["vested_balance_cents"] == 2_222_333
    assert account["status"] == "OPEN"
    assert account["outstanding_loan_balance_cents"] == 0
    assert account["ytd_elective_deferrals_cents"] == 0
    assert account["pending_lost_earnings_cents"] == 0

    refreshed = validate_success(
        api.get_participant(participant["id"], make_officer_headers())
    )
    assert refreshed["total_accumulated_benefit_cents"] == 3_333_333
    assert refreshed["total_vested_balance_cents"] == 2_222_333


def test_unknown_participant_id_is_not_found(api):
    """PRD §2.6 rung 4: "Every resource named by a path segment exists, checked left to
    right in path order: employer, plan, vendor, participant, information sharing
    agreement, eligibility determination, vendor account, contribution election,
    remittance batch, remittance correction, participant request, transfer/exchange
    request. The corresponding refusals are `ERR_EMPLOYER_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
    `ERR_ISA_NOT_FOUND`, `ERR_ELIGIBILITY_NOT_FOUND`, `ERR_VENDOR_ACCOUNT_NOT_FOUND`,
    `ERR_ELECTION_NOT_FOUND`, `ERR_REMITTANCE_BATCH_NOT_FOUND`,
    `ERR_CORRECTION_NOT_FOUND`, `ERR_PARTICIPANT_REQUEST_NOT_FOUND` and
    `ERR_TRANSFER_REQUEST_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/participant_retrieval_with_unknown_id_returns_not_found
    """
    set_clock()

    response = api.get_participant(NON_EXISTENT_UUID, make_officer_headers())

    validate_error(response, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_plan_listing_reports_pagination_meta(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit`
    controls page size: it defaults to 10 when omitted, its minimum accepted value is
    1 and its maximum accepted value is 100."
    PRD §2.3: "The `meta` object of a list response carries `limit` and `offset`
    echoing the effective values, `total_count` giving the number of rows matching the
    filter before the page window is applied, and `has_more` indicating whether any
    matching row falls beyond the current window."

    Design: Corner/entities/plans_listing_returns_pagination_envelope
    """
    set_clock()
    employer = register_employer()
    for name, plan_type in (
        ("Plan One", "PLAN_403B"),
        ("Plan Two", "PLAN_403B"),
        ("Plan Three", "PLAN_457B"),
    ):
        create_plan(employer["id"], plan_name=name, plan_type=plan_type)

    first_page = api.list_plans(make_officer_headers(), {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True, "a third plan falls beyond the first window"

    rows, meta = validate_paginated(api.list_plans(make_officer_headers(), {"limit": 2, "offset": 1}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["offset"] == 1
    assert meta["has_more"] is False, "no matching row falls beyond rows two and three"


def test_pagination_limit_above_one_hundred_is_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range from 1 to 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/pagination_limit_above_maximum_returns_invalid_request
    """
    set_clock()
    employer = register_employer()
    create_plan(employer["id"], plan_name="Plan One")

    validate_error(
        api.list_plans(make_officer_headers(), {"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api.list_plans(make_officer_headers(), {"limit": 100}))
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_universal_availability_notice_carries_no_version(api):
    """PRD §2.4: "A `UniversalAvailabilityNotice` is an immutable record of a compliance
    event and carries only `id` and `created_at`. It has no `updated_at` and no
    `version`, and no operation exists that would mutate one after it is filed."
    PRD §3.3: "The server sets `is_valid` true exactly when all three of the following
    hold: `describes_effective_opportunity` is true; `recipient_count` is greater than
    or equal to the plan's `reported_participant_count`, so a count exactly equal to
    the participant count is sufficient; and `delivery_method` is anything other than
    `INTRANET_POSTING`."

    Design: Corner/entities/universal_availability_notice_is_immutable_with_no_version_field
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=0)

    notice = validate_success(
        api.create_notice(
            env["plan_id"],
            {
                "plan_year": 2026,
                "issued_date": "2026-01-05",
                "delivery_method": "EMAIL",
                "recipient_count": 250,
                "describes_effective_opportunity": True,
            },
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert_universal_availability_notice(notice)
    assert notice["is_valid"] is True

    rows, _meta = validate_paginated(
        api.list_notices(env["plan_id"], make_officer_headers(), {"plan_year": 2026})
    )
    assert len(rows) == 1
    assert "updated_at" not in rows[0]
    assert "version" not in rows[0]


def test_vendor_account_reachable_from_each_foreign_key(api):
    """PRD §3.4: "Either a sponsor admin or the provider's own representative opens one
    by naming the `participant_id`, the `plan_id` under which the contract is held,
    the `vendor_id` holding it, and the provider's `contract_number`, optionally
    seeding `accumulated_benefit_cents` (default zero), `vested_percentage_bps`
    (default 10000, meaning fully vested, and constrained to the inclusive range from
    0 to 10000) and `prior_years_elective_deferrals_cents` (default zero)."
    PRD §2.10: "`total_accumulated_benefit_cents` sums `accumulated_benefit_cents`."

    Design: Corner/entities/vendor_account_junction_reverse_lookup_across_three_foreign_keys
    """
    set_clock()
    employer = register_employer()
    vendor_one = register_vendor()
    vendor_two = register_second_vendor()
    plan_one = create_active_plan(employer["id"], plan_name="Riverbend 403(b)")
    plan_two = create_active_plan(employer["id"], plan_name="Riverbend Legacy 403(b)")
    participant_a = register_participant(employer["id"])
    participant_b = register_participant(
        employer["id"], full_name="Ben Okafor", date_of_birth="1980-01-01",
        hire_date="2010-01-01", includible_compensation_cents=8_000_000, years_of_service=16,
    )
    for participant, plan, vendor, number in (
        (participant_a, plan_one, vendor_one, "C1"),
        (participant_a, plan_one, vendor_two, "C2"),
        (participant_a, plan_two, vendor_one, "C3"),
        (participant_b, plan_two, vendor_two, "C4"),
    ):
        open_contract(
            participant["id"], plan["id"], vendor["id"], employer["id"],
            contract_number=number, accumulated_benefit_cents=100_000,
        )

    by_participant, _ = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"participant_id": participant_a["id"]})
    )
    by_plan, _ = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"plan_id": plan_two["id"]})
    )
    by_vendor, _ = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"vendor_id": vendor_two["id"]})
    )

    assert len(by_participant) == 3
    assert len(by_plan) == 2
    assert len(by_vendor) == 2

    refreshed = validate_success(
        api.get_participant(participant_a["id"], make_officer_headers())
    )
    assert refreshed["total_accumulated_benefit_cents"] == 300_000


def test_new_plan_is_draft_and_cannot_be_frozen_directly(api):
    """PRD §3.1: "The plan is born in `DRAFT`."
    PRD §3.1: "A freeze moves the plan `ACTIVE → FROZEN` and requires the plan to be
    `ACTIVE`; an unfreeze moves it `FROZEN → ACTIVE` and requires the plan to be
    `FROZEN`."
    PRD §2.6 rung 9: "The addressed row's current state is a declared origin state for
    the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/plan_initial_state_is_draft_and_direct_freeze_is_rejected
    """
    set_clock()
    employer = register_employer()
    plan = create_plan(employer["id"])
    assert plan["status"] == "DRAFT"

    response = api.set_plan_status(
        plan["id"], {"to_status": "FROZEN"}, make_sponsor_headers(employer["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    unchanged = validate_success(api.get_plan(plan["id"], make_officer_headers()))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1


def test_terminated_plan_cannot_return_to_active(api):
    """PRD §3.1: "`TERMINATED` is terminal: no transition leads out of it."
    PRD §2.6 rung 9: "The addressed row's current state is a declared origin state for
    the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/terminated_plan_status_change_is_locked_down
    """
    set_clock()
    employer = register_employer()
    plan = create_active_plan(employer["id"])
    move_plan(plan["id"], employer["id"], "TERMINATED")

    response = api.set_plan_status(
        plan["id"], {"to_status": "ACTIVE"}, make_sponsor_headers(employer["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    unchanged = validate_success(api.get_plan(plan["id"], make_officer_headers()))
    assert unchanged["status"] == "TERMINATED"


def test_plan_termination_cascades_to_elections_agreements_and_contracts(api):
    """PRD §3.1: "Every contribution election of the plan in state `SUBMITTED` or
    `EFFECTIVE` transitions to `REVOKED`. Every information sharing agreement of the
    plan whose `status` is `PENDING`, `ACTIVE` or `SUSPENDED` transitions to
    `TERMINATED`. Every provider contract of the plan whose `status` is `OPEN`
    transitions to `CLOSED` and therefore leaves every aggregation set described in
    §2.10 — a participant's totals shrink accordingly."
    PRD §2.10: "And `projected_annual_deferral_cents` is the sum of
    `annual_deferral_amount_cents` over the participant's elections in state
    `EFFECTIVE`."

    Design: Corner/state_machines/plan_termination_cascades_election_revocation_and_agreement_termination
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    agreement = setup_active_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"], feed_date=None
    )
    file_notice(env["plan_id"], env["employer_id"])
    participant = register_participant(
        env["employer_id"], full_name="Dana Prewitt", date_of_birth="1970-01-01",
        hire_date="2004-01-01", years_of_service=20,
    )
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-D001", accumulated_benefit_cents=4_000_000,
    )
    determine_eligibility(env["plan_id"], participant["id"])
    election = submit_election(
        participant["id"], env["plan_id"], account["id"], env["employer_id"],
        annual_deferral_amount_cents=2_750_000, effective_from="2026-01-01",
        effective_through="2026-12-31", catchup_election="SERVICE_15_YEAR",
    )
    effective = approve_election(election["id"])
    assert effective["state"] == "EFFECTIVE"
    assert effective["basic_deferral_attributed_cents"] == 2_450_000
    assert effective["service_catchup_attributed_cents"] == 300_000

    terminated = validate_success(
        api.set_plan_status(
            env["plan_id"], {"to_status": "TERMINATED"}, make_sponsor_headers(env["employer_id"])
        )
    )

    assert terminated["status"] == "TERMINATED"
    assert validate_success(
        api.get_election(election["id"], make_officer_headers())
    )["state"] == "REVOKED"
    assert validate_success(
        api.get_agreement(agreement["id"], make_officer_headers())
    )["status"] == "TERMINATED"
    assert validate_success(
        api.get_vendor_account(account["id"], make_officer_headers())
    )["status"] == "CLOSED"
    assert validate_success(
        api.get_participant(participant["id"], make_officer_headers())
    )["projected_annual_deferral_cents"] == 0


def test_nondiscrimination_regime_matrix(api):
    """PRD §2.8: "If the sponsor's `entity_type` is `CHURCH`, the regime is
    `CHURCH_EXEMPT` — neither universal availability nor the coverage rules attach.
    Otherwise, if the plan's `plan_type` is `PLAN_403B`, the regime is `UA_ONLY` when
    the sponsor is governmental and `UA_PLUS_410B_401A4` when it is not. Otherwise the
    plan is a `PLAN_457B`, and the regime is `GOVERNMENTAL_457_ALL_EMPLOYEES` when the
    sponsor is governmental and `TOP_HAT_457` when it is not."
    PRD §3.1: "sets `is_governmental_457` true exactly when the `plan_type` is
    `PLAN_457B` and the sponsor is governmental, which is the only condition under
    which a 457(b) plan may offer an age-50 catch-up at all"

    Design: Corner/calculations/nondiscrimination_regime_matrix_across_employer_and_plan_type
    """
    set_clock()
    governmental = register_employer()
    nonqualified = register_nonqualified_employer()
    church = register_church_employer()

    gov_403b = create_plan(governmental["id"], plan_name="Gov 403(b)", plan_type="PLAN_403B")
    np_403b = create_plan(
        nonqualified["id"], plan_name="NP 403(b)", plan_type="PLAN_403B",
        reported_participant_count=120,
    )
    gov_457b = create_plan(governmental["id"], plan_name="Gov 457(b)", plan_type="PLAN_457B")
    np_457b = create_plan(
        nonqualified["id"], plan_name="NP 457(b)", plan_type="PLAN_457B",
        reported_participant_count=40,
    )
    church_403b = create_plan(
        church["id"], plan_name="Church 403(b)", plan_type="PLAN_403B",
        reported_participant_count=40,
    )

    assert gov_403b["nondiscrimination_regime"] == "UA_ONLY"
    assert gov_403b["is_governmental_457"] is False
    assert np_403b["nondiscrimination_regime"] == "UA_PLUS_410B_401A4"
    assert gov_457b["nondiscrimination_regime"] == "GOVERNMENTAL_457_ALL_EMPLOYEES"
    assert gov_457b["is_governmental_457"] is True
    assert np_457b["nondiscrimination_regime"] == "TOP_HAT_457"
    assert np_457b["is_governmental_457"] is False
    assert church_403b["nondiscrimination_regime"] == "CHURCH_EXEMPT"
    assert np_457b["is_small_plan"] is True, "40 reported participants is below one hundred"
    assert gov_403b["is_small_plan"] is False
