"""The two conserved quantities and the consistency guarantee that binds them: the
version ladder every write and every cascade climbs by exactly one, the unbilled
accrual that reconciles across a time entry's whole status walk, and the single
mutation response that already carries every cascaded derived field.
"""
from test_helpers import (
    accept_assessment,
    activate_service_authorization,
    api_client,
    approve_time_entry,
    assert_coverage_hours,
    assert_version_increment,
    authorize_service_authorization,
    create_accepted_assessment,
    create_active_care_plan,
    create_care_plan_payload,
    deposit_retainer,
    family_approve_plan,
    get_success_data,
    issue_invoice,
    log_time_entry,
    make_care_manager_headers,
    open_assessment,
    open_invoice,
    propose_service_authorization,
    read_authorization,
    read_care_plan,
    read_client,
    read_invoice,
    read_time_entry,
    register_care_manager,
    register_client,
    register_supervisor,
    register_surrogate_contact,
    register_vendor,
    reject_time_entry,
    send_plan_for_family_approval,
    set_logical_clock,
    setup_active_care_plan_scenario,
    setup_practice,
    submit_assessment,
    submit_time_entry,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
)

_SPLIT_SHIFT_GOALS = ["Split-shift coverage"]


def _a_client_walked_to_an_accepted_assessment():
    """A prospect, its surrogate and a clean vendor, walked as far as an ACCEPTED
    assessment while every version the client passes through on the way is
    observed."""
    set_logical_clock("2026-09-15T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", credential="CMC", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Isolde Bergmann",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
        authorized_concurrent_caregivers=2,
    )
    surrogate = register_surrogate_contact(
        client["id"], full_name="Jorunn Bergmann", contact_role="POA_HEALTHCARE"
    )
    vendor = register_vendor(
        name="Northgate Home Care",
        vendor_type="HOME_CARE",
        has_referral_relationship=False,
    )
    assessment = open_assessment(
        client["id"], care_manager["id"], scores=uniform_domain_scores(2)
    )
    after_open = read_client(client["id"])
    submit_assessment(assessment["id"], care_manager["id"])
    accept_assessment(assessment["id"], supervisor["id"])
    after_accept = read_client(client["id"])
    return {
        "care_manager": care_manager,
        "supervisor": supervisor,
        "client": client,
        "surrogate": surrogate,
        "vendor": vendor,
        "assessment": assessment,
        "version_at_registration": client["version"],
        "version_after_open": after_open["version"],
        "version_after_accept": after_accept["version"],
        "status_after_open": after_open["status"],
    }


def test_01_a_registered_client_starts_at_version_one_and_each_cascade_adds_exactly_one():
    """A freshly registered client is at version 1. Creating the assessment moves the
    client to ASSESSMENT_IN_PROGRESS as a cascade nobody addressed directly, and
    accepting it re-derives the clinical fields; each adds exactly one.

    PRD: "`version` is an integer that begins at 1 when the record is created and increases by exactly 1 on every mutation of that record, including mutations the record suffers as a cascade from some other operation."

    Design: Corner/cross_cutting/version_increments_on_every_write_and_a_replayed_client_version_is_rejected
    """
    walked = _a_client_walked_to_an_accepted_assessment()

    assert walked["version_at_registration"] == 1, (
        "a newly registered client must be at version 1, got "
        f"{walked['version_at_registration']}"
    )
    assert walked["status_after_open"] == "ASSESSMENT_IN_PROGRESS", (
        "opening an assessment must cascade the client out of PROSPECT, got "
        f"{walked['status_after_open']}"
    )
    assert_version_increment(
        walked["version_after_open"],
        walked["version_at_registration"],
        label="client after the assessment cascade",
    )
    assert_version_increment(
        walked["version_after_accept"],
        walked["version_after_open"],
        label="client after assessment acceptance",
    )


def test_02_a_client_version_read_before_the_assessment_cascade_is_already_stale():
    """Authoring the plan against the version the client carried at registration is
    refused with the stale-client pin, and nothing is created: the author never saw
    the two cascades that moved the client forward.

    PRD: "If `expected_client_version` does not equal the target client's current `version`, the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412): a stale value means the author never saw the intervening capacity determination, assessment acceptance or plan activation that moved the client forward."

    Design: Corner/cross_cutting/version_increments_on_every_write_and_a_replayed_client_version_is_rejected
    """
    walked = _a_client_walked_to_an_accepted_assessment()
    author = make_care_manager_headers(walked["care_manager"]["id"])

    replayed = create_care_plan_payload(
        walked["client"]["id"],
        walked["assessment"]["id"],
        walked["version_at_registration"],
        goals=_SPLIT_SHIFT_GOALS,
    )
    validate_error(
        api_client.create_care_plan(replayed, author),
        "ERR_STALE_CLIENT_VERSION",
        412,
    )

    _rows, meta = validate_paginated(
        api_client.list_care_plans(author, params={"client_id": walked["client"]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused create must leave no plan behind, got {meta}"
    )
    assert read_client(walked["client"]["id"])["version"] == walked["version_after_accept"], (
        "a refused create must not advance the client's version"
    )


def test_03_the_freshly_read_version_succeeds_and_every_later_write_bumps_the_plan_by_one():
    """Retried against the version read after both cascades the create succeeds, and
    from there the plan's own ladder climbs one step per write — including the step it
    suffers when an authorization is proposed against it.

    PRD: "A parent's `version` therefore advances not only when a caller edits it directly but whenever a child operation reaches back into it, which is precisely why the version-pinning rules of §2.7 exist."

    Design: Corner/cross_cutting/version_increments_on_every_write_and_a_replayed_client_version_is_rejected
    """
    walked = _a_client_walked_to_an_accepted_assessment()
    author = make_care_manager_headers(walked["care_manager"]["id"])

    response = api_client.create_care_plan(
        create_care_plan_payload(
            walked["client"]["id"],
            walked["assessment"]["id"],
            walked["version_after_accept"],
            goals=_SPLIT_SHIFT_GOALS,
        ),
        author,
    )
    assert response.status_code == 201, (
        f"the retry at the fresh version must be created, got {response.status_code}"
    )
    plan = get_success_data(response)
    plan_v0 = plan["version"]

    sent = send_plan_for_family_approval(plan["id"], walked["care_manager"]["id"])
    plan_v1 = sent["version"]
    activated = family_approve_plan(plan["id"], walked["surrogate"]["id"])
    plan_v2 = activated["version"]
    propose_service_authorization(
        plan["id"],
        walked["vendor"]["id"],
        walked["care_manager"]["id"],
        coverage_start="2026-09-28T08:00:00Z",
        coverage_end="2026-09-28T12:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    plan_v3 = read_care_plan(plan["id"])["version"]

    assert sent["status"] == "PENDING_FAMILY_APPROVAL", f"got {sent['status']}"
    assert activated["status"] == "ACTIVE", f"got {activated['status']}"
    assert_version_increment(plan_v1, plan_v0, label="care plan sent for approval")
    assert_version_increment(plan_v2, plan_v1, label="care plan activated")
    assert_version_increment(plan_v3, plan_v2, label="care plan after the authorization")

    rows, meta = validate_paginated(
        api_client.list_care_plans(author, params={"client_id": walked["client"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one plan must exist for the client, got {meta}"
    )
    assert [row["id"] for row in rows] == [plan["id"]], (
        "the only plan on file must be the one the retry created"
    )


def _an_active_client_with_nothing_logged():
    """An ACTIVE_CARE quarter-hour client with no retainer floor and not a minute of
    time captured against it yet."""
    return setup_active_care_plan_scenario(
        clock="2026-09-16T09:00:00Z",
        client_overrides={
            "full_name": "Halina Nowak",
            "residence_setting": "PRIVATE_HOME",
            "billing_increment_min": 15,
            "retainer_floor_cents": 0,
        },
        scores=uniform_domain_scores(2),
        goals=["Weekday coordination"],
    )


def _the_approved_morning_hour(scenario):
    """One 10:00-11:00 office hour, submitted by its author and approved by the
    supervisor."""
    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T10:00:00Z",
        "2026-09-14T11:00:00Z",
        service_location_id="OFFICE",
    )
    submit_time_entry(entry["id"], scenario.care_manager_id)
    return approve_time_entry(entry["id"], scenario.supervisor_id)


def _the_rejected_afternoon_call(scenario):
    """A twenty-minute office call, submitted and then rejected as a duplicate."""
    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T13:00:00Z",
        "2026-09-14T13:20:00Z",
        service_location_id="OFFICE",
    )
    submit_time_entry(entry["id"], scenario.care_manager_id)
    return reject_time_entry(
        entry["id"], scenario.supervisor_id, reason="Duplicate of the morning call"
    )


def _accrual_of(scenario):
    return read_client(scenario.client_id)["unbilled_accrual_cents"]


def test_04_a_draft_entry_already_accrues_and_approving_it_moves_nothing():
    """The accrual starts at zero, the freshly logged DRAFT hour is already inside the
    input set, and moving that hour on to APPROVED leaves the total exactly where it
    was because both statuses accrue.

    PRD: "Approval — `SUBMITTED → APPROVED` — records the approver in `approved_by_care_manager_id` and increases the entry's `version` by 1; because both `SUBMITTED` and `APPROVED` sit inside the accrual input set, the client's `unbilled_accrual_cents` does not move."

    Design: Corner/cross_cutting/unbilled_accrual_reconciles_across_time_entry_status_transitions
    """
    scenario = _an_active_client_with_nothing_logged()
    assert _accrual_of(scenario) == 0, "an unbilled client accrues nothing"

    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T10:00:00Z",
        "2026-09-14T11:00:00Z",
        service_location_id="OFFICE",
    )
    assert entry["billable_amount_cents"] == 22_500, (
        f"a daytime hour at 22500/h bills 22500, got {entry['billable_amount_cents']}"
    )
    assert entry["status"] == "DRAFT", f"got {entry['status']}"
    assert _accrual_of(scenario) == 22_500, "a DRAFT entry already counts toward the accrual"

    submit_time_entry(entry["id"], scenario.care_manager_id)
    approved = approve_time_entry(entry["id"], scenario.supervisor_id)
    assert approved["status"] == "APPROVED", f"got {approved['status']}"
    assert _accrual_of(scenario) == 22_500, "approval must not move the accrual"


def test_05_a_second_draft_entry_adds_in_and_its_rejection_removes_it_again():
    """A twenty-minute call bills as half an hour and lifts the accrual; rejecting it
    takes exactly its own amount back out, returning the total to the morning hour
    alone.

    PRD: "Rejection — `SUBMITTED → REJECTED` — recomputes the client's `unbilled_accrual_cents` downward, since a rejected entry leaves the accrual set, and increases both the entry's `version` and the client's `version` by 1."

    Design: Corner/cross_cutting/unbilled_accrual_reconciles_across_time_entry_status_transitions
    """
    scenario = _an_active_client_with_nothing_logged()
    _the_approved_morning_hour(scenario)

    call = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T13:00:00Z",
        "2026-09-14T13:20:00Z",
        service_location_id="OFFICE",
    )
    assert call["billable_amount_cents"] == 11_250, (
        f"20 minutes ceilinged to 30 bills 11250, got {call['billable_amount_cents']}"
    )
    assert _accrual_of(scenario) == 33_750, "the second DRAFT entry must add in"

    submit_time_entry(call["id"], scenario.care_manager_id)
    rejected = reject_time_entry(
        call["id"], scenario.supervisor_id, reason="Duplicate of the morning call"
    )
    assert rejected["status"] == "REJECTED", f"got {rejected['status']}"
    assert _accrual_of(scenario) == 22_500, "rejection must remove exactly that entry"


def test_06_an_after_hours_hour_accrues_and_the_draft_invoice_moves_no_money():
    """The evening hour carries the after-hours factor and lifts the accrual to the
    full billable total; opening the DRAFT invoice projects that same subtotal without
    touching the accrual at all.

    PRD: "The new invoice is created in `DRAFT` status with `variant` at `PROVISIONAL`, `amount_paid_cents` at 0, `issued_at` null and `voided_reason` null, and no money moves."

    Design: Corner/cross_cutting/unbilled_accrual_reconciles_across_time_entry_status_transitions
    """
    scenario = _an_active_client_with_nothing_logged()
    _the_approved_morning_hour(scenario)
    _the_rejected_afternoon_call(scenario)

    evening = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T19:00:00Z",
        "2026-09-14T20:00:00Z",
        service_location_id="CLIENT_HOME",
    )
    assert evening["billable_amount_cents"] == 27_000, (
        f"an hour from 19:00 UTC bills at 1.20, got {evening['billable_amount_cents']}"
    )
    submit_time_entry(evening["id"], scenario.care_manager_id)
    approve_time_entry(evening["id"], scenario.supervisor_id)
    assert _accrual_of(scenario) == 49_500, "the approved evening hour must add in"

    invoice = open_invoice(
        scenario.client_id, period_start="2026-09-01", period_end="2026-09-30"
    )
    assert invoice["status"] == "DRAFT", f"got {invoice['status']}"
    assert invoice["variant"] == "PROVISIONAL", f"got {invoice['variant']}"
    assert invoice["line_subtotal_cents"] == 49_500, (
        f"the provisional subtotal must be 49500, got {invoice['line_subtotal_cents']}"
    )
    assert _accrual_of(scenario) == 49_500, "opening a draft invoice must not move the accrual"


def test_07_issuing_the_invoice_drains_the_accrual_and_never_touches_the_rejected_entry():
    """Issue flips both accruing entries to INVOICED, so the accrual returns to zero
    with no stored counter left drifting; the rejected entry was never a candidate and
    keeps a null invoice.

    PRD: "When an invoice is issued, each approved entry appearing in that invoice's line set moves `APPROVED → INVOICED`, has its `invoice_id` set to the issuing invoice, and has its `version` increased by 1, while the client's `unbilled_accrual_cents` is recomputed downward."

    Design: Corner/cross_cutting/unbilled_accrual_reconciles_across_time_entry_status_transitions
    """
    scenario = _an_active_client_with_nothing_logged()
    morning = _the_approved_morning_hour(scenario)
    rejected = _the_rejected_afternoon_call(scenario)
    evening = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T19:00:00Z",
        "2026-09-14T20:00:00Z",
        service_location_id="CLIENT_HOME",
    )
    submit_time_entry(evening["id"], scenario.care_manager_id)
    approve_time_entry(evening["id"], scenario.supervisor_id)
    invoice = open_invoice(
        scenario.client_id, period_start="2026-09-01", period_end="2026-09-30"
    )

    issued = issue_invoice(invoice["id"])
    assert issued["line_subtotal_cents"] == 49_500, f"got {issued['line_subtotal_cents']}"
    assert issued["admin_fee_cents"] == 3_465, f"got {issued['admin_fee_cents']}"
    assert issued["total_due_cents"] == 52_965, f"got {issued['total_due_cents']}"

    client = read_client(scenario.client_id)
    assert client["unbilled_accrual_cents"] == 0, (
        f"every accruing entry is now invoiced, got {client['unbilled_accrual_cents']}"
    )
    assert client["status"] == "ACTIVE_CARE", (
        f"a zero retainer floor cannot trigger nonpayment, got {client['status']}"
    )
    assert read_time_entry(morning["id"])["invoice_id"] == invoice["id"]
    assert read_time_entry(evening["id"])["invoice_id"] == invoice["id"]
    assert read_time_entry(rejected["id"])["invoice_id"] is None, (
        "a rejected entry is never invoiced"
    )


def _a_client_exactly_at_its_retainer_floor_with_live_coverage():
    """A quarter-hour client whose retainer deposit exactly meets its floor, carrying
    one ACTIVE six-hour engagement, one approved four-hour entry and a DRAFT invoice
    over the month that entry falls in."""
    scenario = setup_practice(
        clock="2026-09-17T09:00:00Z",
        client_overrides={
            "full_name": "Kalev Saar",
            "residence_setting": "PRIVATE_HOME",
            "billing_increment_min": 15,
            "retainer_floor_cents": 50_000,
            "authorized_concurrent_caregivers": 2,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
    )
    deposited = deposit_retainer(
        scenario.client_id, 50_000, received_at="2026-09-17T09:00:00Z"
    )
    scenario.assessment = create_accepted_assessment(
        scenario.client_id,
        scenario.care_manager_id,
        scenario.supervisor_id,
        scores=uniform_domain_scores(2),
    )
    scenario.care_plan = create_active_care_plan(
        scenario.client_id,
        scenario.assessment_id,
        scenario.care_manager_id,
        scenario.surrogate_id,
        goals=["Evening coverage"],
    )
    proposed = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-20T08:00:00Z",
        coverage_end="2026-09-20T14:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    authorized = authorize_service_authorization(proposed["id"], scenario.supervisor_id)
    scenario.authorization = activate_service_authorization(
        proposed["id"], scenario.care_manager_id
    )
    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-09-14T10:00:00Z",
        "2026-09-14T14:00:00Z",
        service_location_id="OFFICE",
    )
    submit_time_entry(entry["id"], scenario.care_manager_id)
    entry = approve_time_entry(entry["id"], scenario.supervisor_id)
    invoice = open_invoice(
        scenario.client_id, period_start="2026-09-01", period_end="2026-09-30"
    )
    return scenario, deposited, authorized, entry, invoice


def test_08_every_mutation_response_already_carries_the_derived_fields_it_moved():
    """No follow-up read is needed to watch a derived field settle: the deposit's own
    response shows the balance at the floor, the authorizing response shows the coverage
    hours it added, the entry's response shows its rating, and the draft invoice's
    response shows the whole arithmetic.

    PRD: "Each is recomputed after every mutation that can change its inputs, and a read of a record returns the recomputed value rather than a stale cache."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_response
    """
    scenario, deposited, authorized, entry, invoice = (
        _a_client_exactly_at_its_retainer_floor_with_live_coverage()
    )

    assert deposited["retainer_balance_cents"] == 50_000, (
        f"the deposit response must already show the balance, got {deposited}"
    )
    assert deposited["retainer_deposits_total_cents"] == 50_000, (
        f"got {deposited['retainer_deposits_total_cents']}"
    )
    assert authorized["coverage_hours"] == 6, (
        f"a six-hour window for one caregiver is 6 hours, got {authorized['coverage_hours']}"
    )
    assert entry["billable_amount_cents"] == 90_000, (
        f"four daytime hours at 22500/h bill 90000, got {entry['billable_amount_cents']}"
    )
    assert invoice["line_subtotal_cents"] == 90_000, f"got {invoice['line_subtotal_cents']}"
    assert invoice["admin_fee_cents"] == 6_300, f"got {invoice['admin_fee_cents']}"
    assert invoice["total_due_cents"] == 96_300, f"got {invoice['total_due_cents']}"

    assert_coverage_hours(read_client(scenario.client_id), 6)


def test_09_the_issue_response_and_the_read_that_follows_it_report_the_same_money():
    """The retainer is drawn first and only the remainder is billed, and the issue
    response itself carries both figures; the client read that follows immediately
    agrees, and re-reading the invoice returns identical money fields.

    PRD: "Fourth comes the retainer waterfall: `retainer_applied_cents` is the lesser of the client's `retainer_balance_cents` and `total_due_cents`, and `balance_due_cents` is `total_due_cents` less `retainer_applied_cents` — the retainer is drawn first and the family is billed only the remainder."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_response
    """
    scenario, _deposited, _authorized, _entry, invoice = (
        _a_client_exactly_at_its_retainer_floor_with_live_coverage()
    )

    issued = issue_invoice(invoice["id"])
    assert issued["status"] == "ISSUED", f"got {issued['status']}"
    assert issued["retainer_applied_cents"] == 50_000, (
        f"the whole retainer is drawn against 96300 due, got {issued['retainer_applied_cents']}"
    )
    assert issued["balance_due_cents"] == 46_300, f"got {issued['balance_due_cents']}"

    client = read_client(scenario.client_id)
    assert client["retainer_balance_cents"] == 0, f"got {client['retainer_balance_cents']}"
    assert client["unbilled_accrual_cents"] == 0, f"got {client['unbilled_accrual_cents']}"

    reread = read_invoice(invoice["id"])
    assert reread["status"] == issued["status"], "the invoice status must not settle later"
    assert reread["retainer_applied_cents"] == issued["retainer_applied_cents"]
    assert reread["balance_due_cents"] == issued["balance_due_cents"]
    assert reread["total_due_cents"] == issued["total_due_cents"]


def test_10_the_nonpayment_cascade_is_already_visible_in_the_same_round():
    """Draining the retainer below the floor while a balance stands slides the client
    into nonpayment, and the reads issued straight afterwards already show the
    suspended engagement and the coverage hours withdrawn.

    PRD: "If, after that final retainer draw, the client's recomputed `retainer_balance_cents` has fallen below its `retainer_floor_cents` and the invoice's `balance_due_cents` is greater than zero, an `ACTIVE_CARE` client slides to `SUSPENDED_NONPAYMENT`, which in turn moves every authorization of that client whose `auth_status` is `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `NONPAYMENT` and recomputes the client's `authorized_coverage_hours` downward as those rows leave the authorized set."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_response
    """
    scenario, _deposited, authorized, _entry, invoice = (
        _a_client_exactly_at_its_retainer_floor_with_live_coverage()
    )
    assert authorized["coverage_hours"] == 6, f"got {authorized['coverage_hours']}"

    issue_invoice(invoice["id"])

    client = read_client(scenario.client_id)
    assert client["status"] == "SUSPENDED_NONPAYMENT", (
        f"a drained retainer under a standing balance suspends, got {client['status']}"
    )
    authorization = read_authorization(scenario.authorization_id)
    assert authorization["auth_status"] == "SUSPENDED", f"got {authorization['auth_status']}"
    assert authorization["suspension_reason"] == "NONPAYMENT", (
        f"got {authorization['suspension_reason']}"
    )
    assert_coverage_hours(client, 0)
