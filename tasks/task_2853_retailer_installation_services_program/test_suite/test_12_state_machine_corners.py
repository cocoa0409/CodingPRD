"""State-machine corners: the admission pair, initial states, terminal lockdown,
idempotency, the transit cycle and the cascades that reach across entities.
"""

from test_helpers import (
    BASE_SCORE,
    DEFAULT_CLOCK,
    DEPOSIT_420_METRO02,
    NETWORK_MANAGER,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    PROJECT_COORDINATOR_USER_ID,
    QUOTED_420_METRO02,
    SERVICE_MANAGER,
    SERVICE_MANAGER_USER_ID,
    ApiErrorId,
    AssignmentStatus,
    BackgroundCheckResult,
    ChangeOrderStatus,
    ClaimType,
    CredentialStatus,
    DefectSeverity,
    DeliveryStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    MeasurementStatus,
    PermitStatus,
    PunchItemStatus,
    QualityResult,
    ReleaseReason,
    ScorecardEventSource,
    ScorecardEventType,
    SubfloorCondition,
    WarrantyClaimStatus,
    WarrantyDecision,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_units,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    make_installer_headers,
    validate_error,
    validate_success,
)


def _recruited_firm(api):
    """A jurisdiction and one firm still sitting in APPLIED."""
    jurisdiction = fx.create_jurisdiction(api, f.jurisdiction_payload())
    installer = validate_success(
        api.create_installer(f.installer_payload(), NETWORK_MANAGER), 201)
    return jurisdiction, installer


def test_whichever_admission_completes_the_pair_promotes_the_firm(api):
    """The licence verification alone leaves the firm in DOCS_PENDING; the background
    PASS that follows it is the act that promotes.

    PRD 3.2: "A firm sitting in `DOCS_PENDING` advances `DOCS_PENDING → VERIFIED` as
    soon as, counting the effect of the call currently being handled, its
    `verified_credential_count` is at least 1, its `background_check_result` is `PASS`,
    and at least one of its `VERIFIED` licences has a `trade_code` equal to the firm's
    `primary_trade_code`."

    Design: Corner/state_machines/credential_and_background_pair_walks_the_installer_to_verified_then_active
    """
    jurisdiction, installer = _recruited_firm(api)
    assert installer["status"] == InstallerStatus.APPLIED

    credential = validate_success(
        api.create_credential(installer["id"],
                              f.credential_payload(jurisdiction["id"]),
                              NETWORK_MANAGER),
        201)
    assert credential["verification_status"] == CredentialStatus.PENDING
    assert fx.read_installer(api, installer["id"])["status"] == \
        InstallerStatus.DOCS_PENDING

    verified = get_success_data(
        api.verify_credential(credential["id"], f.verify_payload(),
                              NETWORK_MANAGER))
    assert verified["verification_status"] == CredentialStatus.VERIFIED
    assert_instant(verified["verified_at"], DEFAULT_CLOCK, "verified_at")

    waiting = fx.read_installer(api, installer["id"])
    assert waiting["status"] == InstallerStatus.DOCS_PENDING
    assert waiting["verified_credential_count"] == 1
    assert waiting["background_check_result"] == BackgroundCheckResult.NONE

    promoted = get_success_data(
        api.record_background_check(
            installer["id"],
            f.background_check_payload(completed_at="2026-07-15T00:00:00.000Z"),
            NETWORK_MANAGER))
    assert promoted["status"] == InstallerStatus.VERIFIED
    assert promoted["background_check_result"] == BackgroundCheckResult.PASS


def test_admission_moves_the_firm_to_active_and_writes_the_scorecard(api):
    """The second act is deliberate: it needs live insurance and a passed check, and it
    writes the score fields rather than leaving them at their creation defaults.

    PRD 3.2: "It moves the firm `VERIFIED → ACTIVE`, and requires that
    `insurance_expires_on` is strictly after the logical clock and that
    `background_check_result` is `PASS`."

    Design: Corner/state_machines/credential_and_background_pair_walks_the_installer_to_verified_then_active
    """
    jurisdiction, installer = _recruited_firm(api)
    credential = fx.file_credential(api, installer["id"], jurisdiction["id"])
    fx.verify_credential(api, credential["id"])
    get_success_data(
        api.record_background_check(
            installer["id"],
            f.background_check_payload(completed_at="2026-07-15T00:00:00.000Z"),
            NETWORK_MANAGER))

    active = get_success_data(api.activate_installer(installer["id"],
                                                    NETWORK_MANAGER))
    assert active["status"] == InstallerStatus.ACTIVE
    assert_score(active["composite_score"], BASE_SCORE, "composite_score")
    assert_score(active["lifetime_composite_score"], BASE_SCORE,
                 "lifetime_composite_score")
    assert active["removal_eligible"] is False
    assert active["rolling_event_count"] == 0
    assert active["verified_credential_count"] == 1


def test_activating_a_firm_still_gathering_its_papers_is_refused(api):
    """VERIFIED is the only door into ACTIVE, so the refusal leaves both the status and
    the untouched score fields exactly as they were.

    PRD 3.2: "Attempting to admit a firm that is not in `VERIFIED` answers
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activating_an_installer_from_docs_pending_is_rejected_as_invalid_state
    """
    jurisdiction, installer = _recruited_firm(api)
    fx.file_credential(api, installer["id"], jurisdiction["id"])
    waiting = fx.read_installer(api, installer["id"])
    assert waiting["status"] == InstallerStatus.DOCS_PENDING

    validate_error(api.activate_installer(installer["id"], NETWORK_MANAGER),
                   ApiErrorId.INVALID_STATE)

    after = fx.read_installer(api, installer["id"])
    assert after["status"] == InstallerStatus.DOCS_PENDING
    assert_score(after["composite_score"], BASE_SCORE, "composite_score")
    assert after["removal_eligible"] is False
    assert_version(after, waiting["version"], "installer")


def test_verifying_an_already_verified_licence_a_second_time_is_refused(api):
    """VERIFY is defined only out of PENDING, so the replay is refused and the first
    `verified_at` stands.

    PRD 3.2: "A `VERIFY` moves the licence `PENDING → VERIFIED` provided its
    `license_expires_on` is strictly after the logical clock, stamps `verified_at` with
    the clock, and recomputes the firm's `verified_credential_count`."

    Design: Corner/state_machines/verifying_an_already_verified_credential_a_second_time_is_rejected
    """
    jurisdiction, installer = _recruited_firm(api)
    credential = fx.file_credential(api, installer["id"], jurisdiction["id"])
    first = fx.verify_credential(api, credential["id"])

    validate_error(
        api.verify_credential(credential["id"], f.verify_payload(),
                              NETWORK_MANAGER),
        ApiErrorId.INVALID_STATE)

    replayed = fx.read_credential(api, credential["id"])
    assert replayed["verification_status"] == CredentialStatus.VERIFIED
    assert_instant(replayed["verified_at"], DEFAULT_CLOCK, "verified_at")
    assert_version(replayed, first["version"], "credential")

    after = fx.read_installer(api, installer["id"])
    assert after["verified_credential_count"] == 1
    assert after["status"] == InstallerStatus.DOCS_PENDING


def test_a_booked_visit_and_a_planned_drop_open_in_their_declared_states(api):
    """Neither child moves the parent: the project was already MEASURE_PENDING when it
    was sold and is still MEASURE_PENDING after both children exist.

    PRD 3.6: "The delivery opens at `status` `PLANNED` with `actual_delivered_at` null
    and `delay_days` zero."

    Design: Corner/state_machines/newly_created_children_start_in_their_declared_initial_states
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING)

    measurement = validate_success(
        api.create_measurement(project["id"],
                               f.measurement_payload("2026-08-05T09:00:00.000Z"),
                               PROJECT_COORDINATOR),
        201)
    assert measurement["status"] == MeasurementStatus.SCHEDULED
    assert measurement["completed_at"] is None
    assert measurement["measured_units"] is None
    assert measurement["variance_pct"] is None
    assert measurement["change_order_triggered"] is False

    delivery = validate_success(
        api.create_material_delivery(project["id"], f.delivery_payload(),
                                     PROJECT_COORDINATOR),
        201)
    assert delivery["status"] == DeliveryStatus.PLANNED
    assert delivery["delay_days"] == 0
    assert delivery["actual_delivered_at"] is None

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING)


def test_completing_an_already_completed_visit_rewrites_nothing(api):
    """The second report is refused as terminal, and none of its values reach either the
    appointment or the project.

    PRD 2.8 rank 13: "The target entity is not already in a terminal state for its
    machine — a `CLOSED` project, an `ACCEPTED`, `DECLINED` or `SUPERSEDED` change order,
    a `VERIFIED` punch item, an `UPHELD` or `DENIED` warranty claim, a `REMOVED`
    installer, a `COMPLETED` or `VOIDED` measurement, a `RETURNED` material delivery, or
    a permit dimension already at `CLOSED` — otherwise `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/completing_an_already_completed_measurement_is_rejected_as_already_terminal
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    booked = fx.book_measurement(api, project["id"])
    first = fx.complete_measurement(api, booked["id"], 420.00,
                                    subfloor_condition=SubfloorCondition.MINOR,
                                    obstruction_count=2, stair_flight_count=1)
    assert first["status"] == MeasurementStatus.COMPLETED

    validate_error(
        api.complete_measurement(
            booked["id"],
            f.measurement_completion_payload(
                500.00, subfloor_condition=SubfloorCondition.MAJOR,
                obstruction_count=9, stair_flight_count=4),
            PROJECT_COORDINATOR),
        ApiErrorId.ALREADY_TERMINAL)

    replayed = get_success_data(api.get_measurement(booked["id"],
                                                   PROJECT_COORDINATOR))
    assert_units(replayed["measured_units"], 420.00, "measured_units")
    assert replayed["subfloor_condition"] == SubfloorCondition.MINOR
    assert replayed["obstruction_count"] == 2
    assert replayed["stair_flight_count"] == 1
    assert_version(replayed, first["version"], "measurement")

    after = fx.read_project(api, project["id"])
    assert_units(after["effective_units"], 420.00, "effective_units")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED)


def test_the_transit_cycle_may_be_walked_twice_and_still_arrive_on_time(api):
    """Two full turns of the slip-and-recover cycle leave no mark on the arrival
    arithmetic: landing exactly on the promised end is not late.

    PRD 3.6: "`PLANNED` or `DELAYED` may move to `IN_TRANSIT`; `PLANNED` or `IN_TRANSIT`
    may move to `DELAYED`; and the pair `IN_TRANSIT ↔ DELAYED` therefore forms a cycle
    that may repeat without limit as the supplier's promises slip and recover."

    Design: Corner/state_machines/delivery_cycles_planned_delayed_in_transit_then_delivers_on_the_promise
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    delivery = fx.plan_delivery(api, project["id"])

    for new_status in (DeliveryStatus.DELAYED, DeliveryStatus.IN_TRANSIT,
                       DeliveryStatus.DELAYED, DeliveryStatus.IN_TRANSIT):
        moved = fx.move_delivery(api, delivery["id"], new_status)
        assert moved["status"] == new_status

    arrived = fx.move_delivery(api, delivery["id"], DeliveryStatus.DELIVERED,
                               "2026-08-24T08:00:00.000Z")
    assert arrived["status"] == DeliveryStatus.DELIVERED
    assert arrived["delay_days"] == 0
    assert_instant(arrived["actual_delivered_at"], "2026-08-24T08:00:00.000Z",
                   "actual_delivered_at")
    # One version bump per status write, on top of version 1 at creation.
    assert_version(arrived, 6, "material delivery")

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED)


def test_a_resubmitted_permit_application_returns_to_pending(api):
    """Only a filing that says so returns the dimension to PENDING_APPLICATION; each
    accepted filing overwrites the reference.

    PRD 3.5: "A jurisdiction that rejects the paperwork is handled by filing again from
    `APPLIED` **with `resubmit` true**, which returns `permit_status` to
    `PENDING_APPLICATION` and clears `permit_application_reference` so the fresh
    reference can be filed cleanly on the next call; the flag exists precisely so that
    an accidental double-apply, which omits it, is caught and refused with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/permit_resubmission_returns_the_dimension_to_pending_application
    """
    base = fx.program_baseline(api, f.quick_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00,
                              site_address="22 Larch Way")
    assert_project_dimensions(project, permit=PermitStatus.PENDING_APPLICATION)

    applied = get_success_data(
        api.apply_permit(project["id"], f.permit_apply_payload("PA-1001"),
                         PROJECT_COORDINATOR))
    assert applied["permit_status"] == PermitStatus.APPLIED

    resubmitted = get_success_data(
        api.apply_permit(project["id"],
                         f.permit_apply_payload("PA-1002", resubmit=True),
                         PROJECT_COORDINATOR))
    assert resubmitted["permit_status"] == PermitStatus.PENDING_APPLICATION

    refiled = get_success_data(
        api.apply_permit(project["id"], f.permit_apply_payload("PA-1003"),
                         PROJECT_COORDINATOR))
    assert refiled["permit_status"] == PermitStatus.APPLIED
    assert refiled["permit_application_reference"] == "PA-1003"

    issued = get_success_data(
        api.issue_permit(project["id"],
                         f.permit_issue_payload(25000, "2026-08-03T00:00:00.000Z"),
                         PROGRAM_ADMIN))
    assert issued["permit_status"] == PermitStatus.ISSUED
    assert_instant(issued["permit_issued_on"], "2026-08-03T00:00:00.000Z",
                   "permit_issued_on")
    assert_money(issued["permit_fee_cents_billed"], 25000,
                 "permit_fee_cents_billed")


def test_a_billed_permit_fee_alone_does_not_open_the_invoice(api):
    """Four permit hops later the invoice is still empty, because the total is zero while
    the final labour charge is unwritten — and the other two dimensions never moved.

    PRD 3.6: "The invoice is then assembled: `change_order_upcharge_cents` is the sum of
    `upcharge_cents` over this project's `ACCEPTED` change orders whose `origin` is
    `CUSTOMER_REQUEST` or `SITE_CONDITION`, with `MEASUREMENT_VARIANCE` change orders
    excluded; `total_due_cents` is `final_labor_cents` plus `change_order_upcharge_cents`
    plus `permit_fee_cents_billed`, and is zero whenever `final_labor_cents` is still
    null."

    Design: Corner/state_machines/permit_resubmission_returns_the_dimension_to_pending_application
    """
    base = fx.program_baseline(api, f.quick_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00,
                              site_address="22 Larch Way")
    get_success_data(api.apply_permit(project["id"],
                                      f.permit_apply_payload("PA-1001"),
                                      PROJECT_COORDINATOR))
    get_success_data(api.apply_permit(project["id"],
                                      f.permit_apply_payload("PA-1002",
                                                             resubmit=True),
                                      PROJECT_COORDINATOR))
    get_success_data(api.apply_permit(project["id"],
                                      f.permit_apply_payload("PA-1003"),
                                      PROJECT_COORDINATOR))
    issued = get_success_data(
        api.issue_permit(project["id"],
                         f.permit_issue_payload(25000, "2026-08-03T00:00:00.000Z"),
                         PROGRAM_ADMIN))

    assert issued["final_labor_cents"] is None
    assert_money(issued["total_due_cents"], 0, "total_due_cents")
    assert_money(issued["balance_due_cents"], 0, "balance_due_cents")
    assert_project_dimensions(issued, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED,
                              permit=PermitStatus.ISSUED)


def _probation_firm_holding_one_window(api):
    """A METRO-02 project with its deposit paid and one 480-minute hold, held by a firm
    whose three no-shows have already made it removal-eligible."""
    ctx = fx.deposited_project(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    network = fx.activated_installer(api, ctx["jurisdiction"]["id"])
    ctx.update(network)
    fx.file_events(api, ctx["installer"]["id"], [
        f.scorecard_event_payload(ScorecardEventType.NO_SHOW,
                                  "2026-07-05T00:00:00.000Z"),
        f.scorecard_event_payload(ScorecardEventType.NO_SHOW,
                                  "2026-07-12T00:00:00.000Z"),
        f.scorecard_event_payload(ScorecardEventType.NO_SHOW,
                                  "2026-07-19T00:00:00.000Z"),
    ])
    ctx["assignment"] = fx.hold_assignment(api, ctx["project"]["id"],
                                           ctx["installer"]["id"],
                                           fx.project_version(api,
                                                              ctx["project"]["id"]))
    ctx["installer"] = fx.read_installer(api, ctx["installer"]["id"])
    ctx["project"] = fx.read_project(api, ctx["project"]["id"])
    return ctx


def test_removing_a_firm_hands_its_window_and_its_project_back(api):
    """One request reaches three rows: the firm, its live hold and the project that hold
    had scheduled.

    PRD 3.9: "A successful removal sets `status` to `REMOVED`, stamps `removed_at` from
    the clock and records `removal_reason`; releases **every** assignment of that firm
    still `HELD` or `CONFIRMED` with `release_reason` `INSTALLER_REMOVED`; reduces the
    firm's `committed_minutes` by each released assignment's `duration_minutes`; reverts
    each affected project from `SCHEDULED` back to `MEASURED` so it can be given to
    somebody else; and increments the firm's `version`."

    Design: Corner/state_machines/installer_removal_releases_its_holds_and_reverts_the_project_to_measured
    """
    ctx = _probation_firm_holding_one_window(api)
    firm = ctx["installer"]
    assert_committed_minutes(firm, 480)
    assert firm["status"] == InstallerStatus.PROBATION
    assert firm["rolling_no_show_count"] == 3
    assert firm["removal_eligible"] is True
    assert_score(firm["composite_score"], 54.10, "composite_score")
    assert_project_dimensions(ctx["project"],
                              fulfillment=FulfillmentStatus.SCHEDULED)

    removed = get_success_data(
        api.remove_installer(
            firm["id"],
            f.removal_payload(firm["version"],
                              reason="Three no-shows inside the rolling window"),
            SERVICE_MANAGER))

    assert removed["status"] == InstallerStatus.REMOVED
    assert_instant(removed["removed_at"], DEFAULT_CLOCK, "removed_at")
    assert removed["removal_reason"] == "Three no-shows inside the rolling window"
    assert_committed_minutes(removed, 0)
    assert_version(removed, firm["version"] + 1, "installer")

    assignment = fx.read_assignment(api, ctx["assignment"]["id"])
    assert assignment["status"] == AssignmentStatus.RELEASED
    assert assignment["release_reason"] == ReleaseReason.INSTALLER_REMOVED

    project = fx.read_project(api, ctx["project"]["id"])
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
    assert_money(project["deposit_held_cents"], DEPOSIT_420_METRO02,
                 "deposit_held_cents")


def _closed_project_with_a_claim(api):
    """A METRO-02 project taken all the way to CLOSED, with one warranty claim filed."""
    ctx = fx.closed_project(api, jurisdiction_payload=f.plain_jurisdiction_payload())
    ctx["claim"] = validate_success(
        api.create_warranty_claim(
            f.warranty_claim_payload(ctx["project"]["id"],
                                     description="Seam lifting in the hallway run"),
            make_customer_headers(ctx["customer"]["id"])),
        201)
    return ctx


def test_escalating_a_warranty_claim_files_nothing_against_the_crew(api):
    """The escalation opens the claim for a second look and stamps the acting handle, but
    it leaves the firm's ledger and its score exactly where the completion left them.

    PRD 3.7: "`ESCALATE` is available only from `SUBMITTED`: it sets `status` to
    `ESCALATED`, increments `escalation_level` by one and records `escalated_to_user_id`
    as the acting opaque handle, leaving the claim open for a second look."

    Design: Corner/state_machines/upholding_a_warranty_claim_files_a_scorecard_event_against_the_installer
    """
    ctx = _closed_project_with_a_claim(api)
    project = ctx["project"]
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.CLOSED,
                              financial=FinancialStatus.SETTLED)
    assert_instant(project["closed_at"], "2026-08-25T15:30:00.000Z", "closed_at")
    assert_money(project["final_labor_cents"], QUOTED_420_METRO02,
                 "final_labor_cents")
    assert_money(project["total_due_cents"], QUOTED_420_METRO02, "total_due_cents")
    assert_money(project["deposit_applied_cents"], DEPOSIT_420_METRO02,
                 "deposit_applied_cents")
    assert_money(project["balance_due_cents"], 0, "balance_due_cents")

    claim = ctx["claim"]
    assert claim["status"] == WarrantyClaimStatus.SUBMITTED
    assert claim["escalation_level"] == 0
    assert claim["claim_type"] == ClaimType.LABOR_DEFECT

    escalated = get_success_data(
        api.triage_warranty_claim(
            claim["id"],
            f.triage_payload(WarrantyDecision.ESCALATE,
                             decision_note="Needs a site revisit"),
            SERVICE_MANAGER))
    assert escalated["status"] == WarrantyClaimStatus.ESCALATED
    assert escalated["escalation_level"] == 1
    assert escalated["escalated_to_user_id"] == SERVICE_MANAGER_USER_ID

    firm = fx.read_installer(api, ctx["installer"]["id"])
    assert_score(firm["composite_score"], 87.95, "composite_score")
    assert firm["rolling_event_count"] == 1


def test_upholding_the_claim_appends_the_system_event_and_rescores(api):
    """The UPHOLD is the hop that reaches the network: one system event lands on the
    ledger and drops the rolling composite by six points.

    PRD 3.7: "`UPHOLD` is available from `SUBMITTED` or `ESCALATED`: it sets `status` to
    `UPHELD`, stamps `triaged_at`, records the note, appends a system scorecard event of
    `event_type` `WARRANTY_UPHELD` against the `installer_id` of the project's
    `COMPLETED` assignment with `occurred_at` at the clock, and recomputes the score,
    which may in turn drive the firm `ACTIVE → PROBATION`."

    Design: Corner/state_machines/upholding_a_warranty_claim_files_a_scorecard_event_against_the_installer
    """
    ctx = _closed_project_with_a_claim(api)
    get_success_data(
        api.triage_warranty_claim(
            ctx["claim"]["id"],
            f.triage_payload(WarrantyDecision.ESCALATE,
                             decision_note="Needs a site revisit"),
            SERVICE_MANAGER))
    upheld = get_success_data(
        api.triage_warranty_claim(
            ctx["claim"]["id"],
            f.triage_payload(WarrantyDecision.UPHOLD,
                             decision_note="Workmanship defect confirmed"),
            SERVICE_MANAGER))

    assert upheld["status"] == WarrantyClaimStatus.UPHELD
    assert_instant(upheld["triaged_at"], "2026-08-25T15:30:00.000Z", "triaged_at")

    rows = fx.list_installer_events(api, ctx["installer"]["id"])
    by_type = {row["event_type"]: row for row in rows}
    assert len(rows) == 2
    assert by_type[ScorecardEventType.ON_TIME_COMPLETION]["source"] == \
        ScorecardEventSource.SYSTEM
    warranty_event = by_type[ScorecardEventType.WARRANTY_UPHELD]
    assert warranty_event["source"] == ScorecardEventSource.SYSTEM
    assert_instant(warranty_event["occurred_at"], "2026-08-25T15:30:00.000Z",
                   "occurred_at")

    firm = fx.read_installer(api, ctx["installer"]["id"])
    assert_score(firm["quality_score"], 77.00, "quality_score")
    assert_score(firm["timeliness_score"], 91.00, "timeliness_score")
    assert_score(firm["satisfaction_score"], 80.00, "satisfaction_score")
    assert_score(firm["composite_score"], 81.95, "composite_score")
    # 81.95 is above 78.00 and only two events are inside the rolling window, so
    # neither probation route opens.
    assert firm["status"] == InstallerStatus.ACTIVE
    assert firm["rolling_event_count"] == 2


def _safety_punch_project(api):
    """A settled METRO-02 project whose quality inspection reported one SAFETY defect."""
    ctx = fx.punch_open_project(
        api,
        defects=[f.defect(DefectSeverity.SAFETY,
                          "Exposed tack strip at the threshold",
                          due_at="2026-08-30T17:00:00.000Z")],
        quality_result=QualityResult.FAIL,
        workmanship_score=55,
        jurisdiction_payload=f.plain_jurisdiction_payload())
    ctx["item"] = ctx["punch_items"][0]
    return ctx


def test_a_safety_defect_refuses_the_two_shortcuts_around_it(api):
    """The crew may not report a safety defect fixed straight from OPEN, and a
    coordinator may not sign one off — both refusals carry the same identifier.

    PRD 3.7: "There is one hard exception: a `SAFETY` defect may **not** be resolved from
    `OPEN`."

    Design: Corner/state_machines/safety_punch_item_cannot_be_resolved_before_escalation_or_verified_by_a_coordinator
    """
    ctx = _safety_punch_project(api)
    project = ctx["project"]
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.PUNCH_OPEN)
    assert project["quality_result"] == QualityResult.FAIL
    assert project["workmanship_score"] == 55
    item = ctx["item"]
    assert item["status"] == PunchItemStatus.OPEN
    assert item["severity"] == DefectSeverity.SAFETY

    installer_headers = make_installer_headers(ctx["installer"]["id"])
    validate_error(
        api.resolve_punch_item(item["id"],
                               f.resolution_payload("Strip nailed down"),
                               installer_headers),
        ApiErrorId.PUNCH_LIST_NOT_CLEARED)

    get_success_data(
        api.escalate_punch_item(
            item["id"],
            f.escalation_payload("Safety defect needs a manager sign-off"),
            PROJECT_COORDINATOR))
    get_success_data(
        api.resolve_punch_item(item["id"],
                               f.resolution_payload("Strip nailed down and capped"),
                               installer_headers))

    # A resolved SAFETY item is still beyond a coordinator's authority to sign off.
    validate_error(api.verify_punch_item(item["id"], PROJECT_COORDINATOR),
                   ApiErrorId.PUNCH_LIST_NOT_CLEARED)
    assert fx.list_punch_items(api, project["id"])[0]["status"] == \
        PunchItemStatus.RESOLVED


def test_the_escalated_count_rises_and_falls_and_then_the_close_opens(api):
    """The project's escalated count tracks the item in and out of ESCALATED, and the
    close is unblocked only once the single item reaches VERIFIED.

    PRD 3.7: "Caused by that, the project's `escalated_punch_count` increases by one and,
    when the item's `severity` is `SAFETY`, its `service_manager_review_required` becomes
    true."

    Design: Corner/state_machines/safety_punch_item_cannot_be_resolved_before_escalation_or_verified_by_a_coordinator
    """
    ctx = _safety_punch_project(api)
    project_id = ctx["project"]["id"]
    item_id = ctx["item"]["id"]
    installer_headers = make_installer_headers(ctx["installer"]["id"])

    escalated = get_success_data(
        api.escalate_punch_item(
            item_id,
            f.escalation_payload("Safety defect needs a manager sign-off"),
            PROJECT_COORDINATOR))
    assert escalated["status"] == PunchItemStatus.ESCALATED
    assert escalated["escalated_to_user_id"] == PROJECT_COORDINATOR_USER_ID
    project = fx.read_project(api, project_id)
    assert project["escalated_punch_count"] == 1
    assert project["service_manager_review_required"] is True

    resolved = get_success_data(
        api.resolve_punch_item(item_id,
                               f.resolution_payload("Strip nailed down and capped"),
                               installer_headers))
    assert resolved["status"] == PunchItemStatus.RESOLVED
    assert fx.read_project(api, project_id)["escalated_punch_count"] == 0

    verified = get_success_data(api.verify_punch_item(item_id, SERVICE_MANAGER))
    assert verified["status"] == PunchItemStatus.VERIFIED
    assert_instant(verified["verified_at"], "2026-08-25T15:30:00.000Z",
                   "verified_at")

    closed = get_success_data(api.close_project(project_id, PROJECT_COORDINATOR))
    assert_project_dimensions(closed, fulfillment=FulfillmentStatus.CLOSED,
                              financial=FinancialStatus.SETTLED)


def _project_with_mixed_children(api):
    """A deposited METRO-02 project carrying one DECLINED change order, one DRAFT change
    order, a DELIVERED material drop and one live 480-minute hold."""
    ctx = fx.deposited_project(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    network = fx.activated_installer(api, ctx["jurisdiction"]["id"])
    ctx.update(network)
    project_id = ctx["project"]["id"]
    customer_headers = make_customer_headers(ctx["customer"]["id"])

    declined = fx.raise_change_order(api, project_id, [f.primary_line(10.00)])
    get_success_data(api.submit_change_order(declined["id"], PROJECT_COORDINATOR))
    ctx["declined_change_order"] = get_success_data(
        api.decide_change_order(declined["id"],
                               f.decision_payload("DECLINE"),
                               customer_headers))

    ctx["delivery"] = fx.plan_delivery(
        api, project_id,
        f.delivery_payload(promised_window_start="2026-07-20T08:00:00.000Z",
                           promised_window_end="2026-07-22T08:00:00.000Z",
                           sku_count=14))
    fx.move_delivery(api, ctx["delivery"]["id"], DeliveryStatus.IN_TRANSIT)
    ctx["delivery"] = fx.move_delivery(api, ctx["delivery"]["id"],
                                       DeliveryStatus.DELIVERED,
                                       "2026-07-22T08:00:00.000Z")

    ctx["draft_change_order"] = fx.raise_change_order(api, project_id,
                                                     [f.primary_line(10.00)])
    ctx["assignment"] = fx.hold_assignment(api, project_id, ctx["installer"]["id"],
                                           fx.project_version(api, project_id))
    ctx["project"] = fx.read_project(api, project_id)
    return ctx


def test_the_cancellation_cascade_leaves_the_terminal_child_alone(api):
    """The DRAFT change order, the delivered material and the live hold are all swept, but
    the change order the household already declined keeps its status and its decision
    instant.

    PRD 3.8: "Beyond the settlement, a cancellation sets `fulfillment_status` to
    `CANCELLED`, stamps `cancelled_at` from the clock, records `cancel_reason`, and then
    sweeps the project's children: every measurement still `SCHEDULED` becomes `VOIDED`
    with `voided_reason` `PROJECT_CANCELLED`; every change order still `DRAFT`,
    `PENDING_CUSTOMER` or `REVISION_REQUESTED` becomes `SUPERSEDED`; every assignment
    still `HELD`, `CONFIRMED` or `IN_PROGRESS` becomes `RELEASED` with `release_reason`
    `PROJECT_CANCELLED`, each one reducing its installer's `committed_minutes` by that
    assignment's `duration_minutes`; and the material delivery, unless already
    `RETURNED`, becomes `RETURNED`."

    Design: Corner/state_machines/cancellation_cascade_touches_only_the_non_terminal_children
    """
    ctx = _project_with_mixed_children(api)
    declined = ctx["declined_change_order"]
    draft = ctx["draft_change_order"]
    assert declined["status"] == ChangeOrderStatus.DECLINED
    assert draft["status"] == ChangeOrderStatus.DRAFT
    assert_money(draft["upcharge_cents"], 4505, "upcharge_cents")
    assert ctx["delivery"]["status"] == DeliveryStatus.DELIVERED
    assert ctx["delivery"]["delay_days"] == 0
    assert ctx["assignment"]["status"] == AssignmentStatus.HELD

    cancelled = fx.cancel_project(
        api, ctx["project"]["id"], PROJECT_COORDINATOR,
        reason="Customer moved out of the service area")
    assert_project_dimensions(cancelled, fulfillment=FulfillmentStatus.CANCELLED)
    assert_instant(cancelled["cancelled_at"], DEFAULT_CLOCK, "cancelled_at")
    assert cancelled["cancel_reason"] == "Customer moved out of the service area"

    by_id = {row["id"]: row for row in
             fx.list_project_change_orders(api, ctx["project"]["id"])}
    untouched = by_id[declined["id"]]
    assert untouched["status"] == ChangeOrderStatus.DECLINED
    assert_instant(untouched["decided_at"], declined["decided_at"], "decided_at")
    swept = by_id[draft["id"]]
    assert swept["status"] == ChangeOrderStatus.SUPERSEDED
    assert_money(swept["upcharge_cents"], 4505, "upcharge_cents")
    # Neither change order was ever accepted, so no upcharge entered the invoice.
    assert_money(cancelled["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents")

    assert fx.read_delivery(api, ctx["delivery"]["id"])["status"] == \
        DeliveryStatus.RETURNED
    assignment = fx.read_assignment(api, ctx["assignment"]["id"])
    assert assignment["status"] == AssignmentStatus.RELEASED
    assert assignment["release_reason"] == ReleaseReason.PROJECT_CANCELLED
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 0)


def test_the_cooling_off_tier_waives_the_forfeit_and_the_restocking_fee(api):
    """Cancelled on the day it was sold, the project refunds the whole deposit even though
    it was SCHEDULED with the material already delivered.

    PRD 3.8: "Tier two, `COOLING_OFF`, holds when the logical clock is within 72 hours of
    the project's `created_at`, an **inclusive** bound, and retains zero."

    Design: Corner/state_machines/cancellation_cascade_touches_only_the_non_terminal_children
    """
    ctx = _project_with_mixed_children(api)
    assert_project_dimensions(ctx["project"],
                              fulfillment=FulfillmentStatus.SCHEDULED,
                              financial=FinancialStatus.DEPOSIT_HELD)

    cancelled = fx.cancel_project(
        api, ctx["project"]["id"], PROJECT_COORDINATOR,
        reason="Customer moved out of the service area")

    assert cancelled["financial_status"] == FinancialStatus.REFUNDED
    assert_deposit_buckets(cancelled, paid=DEPOSIT_420_METRO02, held=0, applied=0,
                           refunded=DEPOSIT_420_METRO02, forfeited=0)
    # The 0.25 labour forfeit and the 0.12 restocking fee were both waived outright.
    assert_money(cancelled["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")
