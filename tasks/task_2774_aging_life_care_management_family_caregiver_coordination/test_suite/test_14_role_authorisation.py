"""Role boundaries at their sharpest edges: the family's single write, the split
between authorship and review, the entity-backed supervisor identity, the two
opaque roles' disjoint surfaces, and the family's one-client read scope.
"""
from test_helpers import (
    accept_assessment,
    api_client,
    assessment_state_payload,
    BILLING_ADMINISTRATOR,
    care_plan_state_payload,
    convene_conference,
    create_assessment_payload,
    create_conference_decision_payload,
    create_invoice_payload,
    create_time_entry_payload,
    create_vendor_payload,
    decision_state_payload,
    deposit_retainer,
    family_approve_plan,
    get_success_data,
    log_time_entry,
    make_care_manager_headers,
    make_family_decision_maker_headers,
    make_practice_supervisor_headers,
    open_assessment,
    PRACTICE_ADMIN,
    ratify_conference_decision,
    read_assessment,
    read_care_plan,
    read_client,
    read_decision,
    read_family_contact,
    read_time_entry,
    record_conference_decision,
    register_care_manager,
    register_client,
    register_supervisor,
    register_surrogate_contact,
    register_vendor,
    retainer_deposit_payload,
    schedule_conference,
    send_plan_for_family_approval,
    set_logical_clock,
    setup_draft_care_plan_scenario,
    submit_assessment,
    time_entry_state_payload,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
)

_UNKNOWN_CLIENT_ID = "00000000-0000-4000-8000-0000000000ff"


def _a_draft_plan_awaiting_the_family():
    """An accepted assessment and the DRAFT plan the family will eventually be asked
    to approve."""
    return setup_draft_care_plan_scenario(
        clock="2026-09-07T09:00:00Z",
        client_overrides={
            "full_name": "Umberto Salas",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        surrogate_role="POA_HEALTHCARE",
        scores=uniform_domain_scores(2),
        goals=["Weekly coordination"],
    )


def test_01_the_family_holds_no_clinical_or_billing_authorship_at_all():
    """Assessments, time entries and invoices are closed to the family decision
    maker outright, and none of the three refused requests left a row behind.

    PRD: "It may never write clinical, authorization or billing state."

    Design: Corner/rbac/family_decision_maker_cannot_author_clinical_or_billing_writes
    """
    scenario = _a_draft_plan_awaiting_the_family()
    family = make_family_decision_maker_headers(scenario.surrogate_id)

    validate_error(
        api_client.create_assessment(
            create_assessment_payload(
                scenario.client_id,
                scenario.care_manager_id,
                scores=uniform_domain_scores(3),
            ),
            family,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_time_entry(
            create_time_entry_payload(
                scenario.client_id,
                scenario.care_manager_id,
                "2026-09-07T10:00:00Z",
                "2026-09-07T11:00:00Z",
                service_type="CARE_COORDINATION",
                service_location_id="OFFICE",
            ),
            family,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_invoice(
            create_invoice_payload(
                scenario.client_id, period_start="2026-09-01", period_end="2026-09-15"
            ),
            family,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    _rows, assessments = validate_paginated(
        api_client.list_assessments(
            PRACTICE_ADMIN, params={"client_id": scenario.client_id}
        )
    )
    assert assessments["total_count"] == 1
    _rows, entries = validate_paginated(
        api_client.list_time_entries(
            PRACTICE_ADMIN, params={"client_id": scenario.client_id}
        )
    )
    assert entries["total_count"] == 0
    _rows, invoices = validate_paginated(
        api_client.list_invoices(
            BILLING_ADMINISTRATOR, params={"client_id": scenario.client_id}
        )
    )
    assert invoices["total_count"] == 0


def test_02_the_care_plan_endpoint_splits_by_target_state_between_the_two_roles():
    """One endpoint, two owners: the family is refused the care manager's
    send-for-approval step and then performs its own approval step on the same row.

    PRD: "On care-plan state changes, `PENDING_FAMILY_APPROVAL` and the return to `DRAFT` belong to `CareManager`, while `ACTIVE` and `REJECTED` belong to `FamilyDecisionMaker`."

    Design: Corner/rbac/family_decision_maker_cannot_author_clinical_or_billing_writes
    """
    scenario = _a_draft_plan_awaiting_the_family()

    response = api_client.patch_care_plan_state(
        scenario.care_plan_id,
        care_plan_state_payload("PENDING_FAMILY_APPROVAL"),
        make_family_decision_maker_headers(scenario.surrogate_id),
    )
    error = validate_error(response, "ERR_UNAUTHORIZED", 403)
    assert error["error_id"] not in ("ERR_INVALID_REQUEST", "ERR_INVALID_STATE_TRANSITION")
    assert read_care_plan(scenario.care_plan_id)["status"] == "DRAFT"

    pending = send_plan_for_family_approval(
        scenario.care_plan_id, scenario.care_manager_id
    )
    assert pending["status"] == "PENDING_FAMILY_APPROVAL"

    active = family_approve_plan(scenario.care_plan_id, scenario.surrogate_id)
    assert active["status"] == "ACTIVE"
    assert read_client(scenario.client_id)["status"] == "ACTIVE_CARE"


def _a_recorded_decision_awaiting_ratification():
    """A convened conference and the one decision its facilitator recorded, still
    waiting for a second pair of eyes."""
    set_logical_clock("2026-09-08T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Wanda Oyelaran", residence_setting="PRIVATE_HOME"
    )
    surrogate = register_surrogate_contact(
        client["id"], full_name="Xan Oyelaran", contact_role="POA_HEALTHCARE"
    )
    conference = schedule_conference(
        client["id"],
        [surrogate["id"]],
        care_manager["id"],
        scheduled_start="2026-09-09T14:00:00Z",
        scheduled_end="2026-09-09T15:00:00Z",
        agenda="Vendor engagement",
    )
    conference = convene_conference(
        conference["id"], [surrogate["id"]], care_manager["id"]
    )
    decision = record_conference_decision(
        conference["id"],
        surrogate["id"],
        care_manager["id"],
        decision_type="VENDOR_ENGAGEMENT",
        decision_text="Retain Northgate Home Care",
    )
    assert decision["status"] == "RECORDED"
    return care_manager, supervisor, client, surrogate, conference, decision


def test_03_the_facilitator_may_not_ratify_the_decision_she_recorded():
    """Ratification is the supervisor's act, so the care manager who documented the
    decision cannot also ratify it, and the row waits for the supervisor.

    PRD: "A care manager may never ratify or escalate a documented family decision, and may never touch the invoice or payment surfaces, the client / care-manager / vendor registration surfaces, or the logical clock."

    Design: Corner/rbac/care_manager_cannot_ratify_decisions_and_supervisor_cannot_author_them
    """
    care_manager, supervisor, _client, _surrogate, _conference, decision = (
        _a_recorded_decision_awaiting_ratification()
    )

    validate_error(
        api_client.patch_conference_decision_state(
            decision["id"],
            decision_state_payload("RATIFIED"),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert read_decision(decision["id"])["status"] == "RECORDED"

    ratified = ratify_conference_decision(decision["id"], supervisor["id"])
    assert ratified["status"] == "RATIFIED"


def test_04_the_supervisor_may_not_author_what_she_reviews():
    """The reviewer holds no authorship: neither a conference decision nor a time
    entry may be created under the supervisor role, and the conference still carries
    exactly the one decision its facilitator wrote.

    PRD: "A supervisor may not author the record it approves — it may not create time entries or conference decisions — and holds no billing authority."

    Design: Corner/rbac/care_manager_cannot_ratify_decisions_and_supervisor_cannot_author_them
    """
    _care_manager, supervisor, client, surrogate, conference, decision = (
        _a_recorded_decision_awaiting_ratification()
    )
    supervisor_headers = make_practice_supervisor_headers(supervisor["id"])

    validate_error(
        api_client.create_conference_decision(
            create_conference_decision_payload(
                conference["id"],
                surrogate["id"],
                decision_type="VENDOR_ENGAGEMENT",
                decision_text="Retain Northgate Home Care",
            ),
            supervisor_headers,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_time_entry(
            create_time_entry_payload(
                client["id"],
                supervisor["id"],
                "2026-09-08T10:00:00Z",
                "2026-09-08T11:00:00Z",
                service_type="CARE_COORDINATION",
                service_location_id="OFFICE",
            ),
            supervisor_headers,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    rows, meta = validate_paginated(
        api_client.list_conference_decisions(
            supervisor_headers, params={"family_conference_id": conference["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [decision["id"]]


def _two_submitted_assessments_and_a_borrowed_role():
    """Two non-supervisor care managers, one real supervisor, and two submitted
    assessments — one authored by a care manager, one authored by the supervisor
    herself."""
    set_logical_clock("2026-09-10T09:00:00Z")
    dana = register_care_manager(full_name="Dana Reyes", hourly_rate_cents=22_500)
    assert dana["is_supervisor"] is False
    yuki = register_care_manager(
        full_name="Yuki Tanaka", credential="CMAC", hourly_rate_cents=21_000
    )
    assert yuki["is_supervisor"] is False
    iris = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(full_name="Zola Mkhize", residence_setting="PRIVATE_HOME")

    by_dana = open_assessment(client["id"], dana["id"], scores=uniform_domain_scores(2))
    submit_assessment(by_dana["id"], dana["id"])
    by_iris = open_assessment(client["id"], iris["id"], scores=uniform_domain_scores(3))
    submit_assessment(by_iris["id"], iris["id"])
    return dana, yuki, iris, client, by_dana, by_iris


def test_05_a_non_supervisor_cannot_present_itself_as_the_practice_supervisor():
    """The supervisor role is entity-backed by a flag on the care-manager record, so
    a care manager without it is refused the role itself and the assessment she aimed
    at is untouched.

    PRD: "`PracticeSupervisor` is a senior care manager, and is likewise entity-backed: when `X-User-Role` is `PracticeSupervisor`, `X-User-ID` is the `id` of the acting `CareManager` record, which must exist and must carry `is_supervisor` set to true — an `X-User-ID` that resolves to no care manager, or to a care manager whose `is_supervisor` is false, is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/non_supervisor_care_manager_cannot_borrow_the_practice_supervisor_role
    """
    _dana, yuki, _iris, _client, by_dana, _by_iris = (
        _two_submitted_assessments_and_a_borrowed_role()
    )

    response = api_client.patch_assessment_state(
        by_dana["id"],
        assessment_state_payload("ACCEPTED"),
        make_practice_supervisor_headers(yuki["id"]),
    )
    validate_error(response, "ERR_UNAUTHORIZED", 403)
    assert response.status_code != 422

    unchanged = read_assessment(by_dana["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["comprehensive_acuity"] is None


def test_06_a_genuine_supervisor_is_refused_her_own_work_for_a_different_reason():
    """Role borrowing and self-review are two different failures: the real supervisor
    is admitted to the operation and then refused her own authorship, while the
    assessment authored by somebody else is accepted.

    PRD: "Both fork branches require that the assessment is `SUBMITTED`, that the acting user resolves to a care manager whose `is_supervisor` is true, and that the acting `X-User-ID` differs from the assessment's `care_manager_id` — a supervisor reviewing their own authored assessment is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/non_supervisor_care_manager_cannot_borrow_the_practice_supervisor_role
    """
    _dana, _yuki, iris, _client, by_dana, by_iris = (
        _two_submitted_assessments_and_a_borrowed_role()
    )

    validate_error(
        api_client.patch_assessment_state(
            by_iris["id"],
            assessment_state_payload("ACCEPTED"),
            make_practice_supervisor_headers(iris["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        422,
    )

    accepted = accept_assessment(by_dana["id"], iris["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["comprehensive_acuity"] is not None
    assert read_assessment(by_iris["id"])["status"] == "SUBMITTED"


def _one_submitted_hour_of_coordination():
    """A submitted hour of coordination waiting for its supervisor, and a client with
    no money on account."""
    set_logical_clock("2026-09-12T09:00:00Z")
    dana = register_care_manager(full_name="Dana Reyes", hourly_rate_cents=22_500)
    register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Aurel Dumitru",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    entry = log_time_entry(
        client["id"],
        dana["id"],
        "2026-09-11T10:00:00Z",
        "2026-09-11T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    entry = get_success_data(
        api_client.patch_time_entry_state(
            entry["id"],
            time_entry_state_payload("SUBMITTED"),
            make_care_manager_headers(dana["id"]),
        )
    )
    assert entry["status"] == "SUBMITTED"
    return dana, client, entry


def test_07_the_billing_administrator_holds_no_clinical_authority_whatsoever():
    """Approving time, opening an assessment and onboarding a vendor are all closed
    to the money role, and the submitted hour is still submitted afterwards.

    PRD: "The billing administrator owns the retainer ledger, the invoice lifecycle and payment posting, and holds no clinical authority whatsoever; the practice administrator onboards clients, care managers, vendors and family contacts, maintains vendor standing, may discharge a client, and is the only role permitted to move the logical clock."

    Design: Corner/rbac/billing_administrator_cannot_write_clinical_state_and_practice_admin_cannot_bill
    """
    dana, client, entry = _one_submitted_hour_of_coordination()

    validate_error(
        api_client.patch_time_entry_state(
            entry["id"], time_entry_state_payload("APPROVED"), BILLING_ADMINISTRATOR
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_assessment(
            create_assessment_payload(
                client["id"], dana["id"], scores=uniform_domain_scores(2)
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_vendor(
            create_vendor_payload(
                name="Northgate Home Care",
                vendor_type="HOME_CARE",
                has_referral_relationship=False,
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    assert read_time_entry(entry["id"])["status"] == "SUBMITTED"
    _rows, meta = validate_paginated(
        api_client.list_assessments(PRACTICE_ADMIN, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 0


def test_08_the_practice_administrator_holds_no_money_surface():
    """Invoicing and the retainer ledger answer only to the billing administrator,
    and the vendor the money role could not create is created by the onboarding role
    without complaint.

    PRD: "2. Role admission: `X-User-Role` appears in the addressed operation's authorized-role list, else `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/billing_administrator_cannot_write_clinical_state_and_practice_admin_cannot_bill
    """
    _dana, client, _entry = _one_submitted_hour_of_coordination()

    validate_error(
        api_client.create_invoice(
            create_invoice_payload(
                client["id"], period_start="2026-09-01", period_end="2026-09-15"
            ),
            PRACTICE_ADMIN,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.post_retainer_deposit(
            client["id"],
            retainer_deposit_payload(
                amount_cents=100_000, received_at="2026-09-12T09:00:00Z"
            ),
            PRACTICE_ADMIN,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    funded = deposit_retainer(
        client["id"], 100_000, received_at="2026-09-12T09:00:00Z"
    )
    assert funded["retainer_balance_cents"] == 100_000
    assert funded["retainer_deposits_total_cents"] == 100_000

    vendor = register_vendor(
        name="Northgate Home Care",
        vendor_type="HOME_CARE",
        has_referral_relationship=False,
    )
    assert vendor["name"] == "Northgate Home Care"

    _rows, meta = validate_paginated(
        api_client.list_invoices(
            BILLING_ADMINISTRATOR, params={"client_id": client["id"]}
        )
    )
    assert meta["total_count"] == 0


def _two_unrelated_families_each_with_a_surrogate():
    """Two clients who have nothing to do with each other, each with her own
    surrogate decision maker."""
    set_logical_clock("2026-09-13T09:00:00Z")
    bea = register_client(full_name="Bea Lindqvist", residence_setting="PRIVATE_HOME")
    dov = register_client(full_name="Dov Halevi", residence_setting="ASSISTED_LIVING")
    cyd = register_surrogate_contact(
        bea["id"], full_name="Cyd Lindqvist", contact_role="POA_HEALTHCARE"
    )
    eve = register_surrogate_contact(
        dov["id"], full_name="Eve Halevi", contact_role="POA_HEALTHCARE"
    )
    return bea, dov, cyd, eve


def test_09_a_family_decision_makers_reads_stop_at_her_own_client():
    """The surrogate reads her own client freely and is refused both the other
    client's record and the other family's contact row.

    PRD: "It may drive the family-approval decision on a care plan pending its approval, acknowledge a conflict-of-interest disclosure, and read that one client's record; every read it performs must resolve to its own client, and a read that resolves to a different client's record is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/family_decision_maker_cannot_read_or_acknowledge_across_clients
    """
    bea, dov, cyd, eve = _two_unrelated_families_each_with_a_surrogate()
    cyd_headers = make_family_decision_maker_headers(cyd["id"])

    own = get_success_data(api_client.get_client(bea["id"], cyd_headers))
    assert own["id"] == bea["id"]
    assert own["status"] == "PROSPECT"

    validate_error(
        api_client.get_client(dov["id"], cyd_headers), "ERR_UNAUTHORIZED", 403
    )
    validate_error(
        api_client.get_family_contact(eve["id"], cyd_headers), "ERR_UNAUTHORIZED", 403
    )


def test_10_existence_is_decided_before_the_readers_scope_is_checked():
    """An id that names nobody answers 404 while a sibling client's real id answers
    403, and neither read moved either client.

    PRD: "5. Existence of every addressed and referenced record, in the per-entity order given in §2.5, yielding the matching not-found error."

    Design: Corner/rbac/family_decision_maker_cannot_read_or_acknowledge_across_clients
    """
    bea, dov, cyd, _eve = _two_unrelated_families_each_with_a_surrogate()
    cyd_headers = make_family_decision_maker_headers(cyd["id"])

    validate_error(
        api_client.get_client(_UNKNOWN_CLIENT_ID, cyd_headers),
        "ERR_CLIENT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_client(dov["id"], cyd_headers), "ERR_UNAUTHORIZED", 403
    )

    assert read_client(bea["id"])["version"] == bea["version"]
    assert read_client(dov["id"])["version"] == dov["version"]
    assert read_family_contact(cyd["id"])["client_id"] == bea["id"]
