"""Windows that have closed, budgets that never open and floors that must be
cleared exactly."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_integer,
    assert_money,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

LAKESIDE_UNIT = {
    "unit_name": "Solaris Lakeside",
    "market_code": "SEADT",
    "x_miles": 1.20,
    "y_miles": 1.60,
    "room_count": 100,
    "adr_amount": 310.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}
GUESTROOM_MAJOR_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}
LIFE_SAFETY_CRITICAL_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}


def _only_item(api, plan_id):
    rows, _ = validate_paginated_list(api.list_pip_items(plan_id, BSD_HEADERS, {"limit": 100}))
    assert len(rows) == 1, f"the plan carries one scope line, got {len(rows)}"
    return rows[0]


def test_a_claim_filed_the_day_after_the_window_closes_is_refused(api):
    """PRD §3.4: the preliminary pass opens a 21-day claim window, so a
    protest filed on 2026-08-27 against a window that closed at
    2026-08-26T00:00:00Z is out of time.  The refusal moves nothing: the window
    instant is not extended by the attempt, the study is untouched and no claim
    row is created.

    Design: Corner/validations/encroachment_claim_filed_after_the_window_closes_is_rejected
    """
    world = fixtures.setup_reviewable_application(api, existing_units=[LAKESIDE_UNIT])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    application = fixtures.run_impact_analysis(api, world["application_id"])
    assert_instant(
        application["claim_window_closes_at"], "2026-08-26T00:00:00.000Z", "claim_window_closes_at"
    )

    fixtures.set_clock(api, "2026-08-27T00:00:00Z")
    response = api.file_encroachment_claim(
        world["application_id"],
        factories.build_encroachment_claim_payload(
            world["units"][0]["id"],
            claimed_revenue_loss_pct=14.00,
            narrative="Rate compression on the shoulder season.",
        ),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.CLAIM_WINDOW_CLOSED)
    assert response.status_code == 422

    after = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert_instant(
        after["claim_window_closes_at"], "2026-08-26T00:00:00.000Z", "claim_window_closes_at"
    )
    assert after["status"] == "UNDER_REVIEW"
    assert_integer(after["sustained_claim_count"], 0, "sustained_claim_count")
    assert after["encroachment_verdict"] is None

    _, meta = validate_paginated_list(
        api.list_encroachment_claims(BSD_HEADERS, {"application_id": world["application_id"]})
    )
    assert_integer(meta["total_count"], 0, "total_count")


def test_reporting_a_scope_line_finished_one_day_past_its_due_date_is_refused(api):
    """PRD §3.7: a completion must arrive at or before the line's due_date, and
    a day later is refused - even though no sweep has run, so the line is still
    PENDING rather than OVERDUE.  Nothing is stored: no evidence, no completion
    stamp, and the plan's counters and status stand where acceptance left them.

    Design: Corner/validations/pip_item_completed_after_its_due_date_is_rejected
    """
    world = fixtures.setup_accepted_plan(api, scope_lines=[GUESTROOM_MAJOR_LINE])
    fixtures.set_clock(api, "2027-04-04T00:00:00Z")
    response = api.complete_pip_item(
        world["items"][0]["id"],
        factories.build_item_completion_payload(
            completion_evidence="Punch list closed on all 120 keys."
        ),
        make_owner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.PIP_ITEM_PAST_DUE)
    assert response.status_code == 422

    item = _only_item(api, world["plan_id"])
    assert_instant(
        item["due_date"],
        "2027-04-03T00:00:00.000Z",
        "due_date (180 priority days beaten by 210 category days)",
    )
    assert item["status"] == "PENDING", (
        f"no sweep has run, so the line is not OVERDUE either, got {item['status']}"
    )
    assert item["completed_at"] is None
    assert item["completion_evidence"] is None

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert_integer(plan["items_pending_count"], 1, "items_pending_count")
    assert_integer(plan["items_submitted_count"], 0, "items_submitted_count")
    assert plan["status"] == "ACCEPTED"


def test_a_life_safety_line_is_never_extendable_however_much_budget_remains(api):
    """PRD §3.7: life-safety work is never extendable, so relief is refused on
    the category alone - the request arrives well inside the line's own window
    and inside both the 60-day line budget and the 120-day plan pool, and is
    still refused.  The extension axis stays at NONE with no request counted and
    neither deadline moves.

    Design: Corner/validations/life_safety_item_extension_request_is_rejected
    """
    world = fixtures.setup_accepted_plan(api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE])
    fixtures.set_clock(api, "2026-10-10T00:00:00Z")
    response = api.request_pip_item_extension(
        world["items"][0]["id"],
        factories.build_extension_request_payload(30, reason="Fire marshal scheduling backlog."),
        make_owner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.LIFE_SAFETY_NOT_EXTENDABLE)
    assert response.status_code == 422

    item = _only_item(api, world["plan_id"])
    assert item["extension_status"] == "NONE"
    assert_integer(item["extension_request_count"], 0, "extension_request_count")
    assert_integer(item["extension_granted_days_total"], 0, "extension_granted_days_total")
    assert_instant(
        item["due_date"],
        "2026-11-19T00:00:00.000Z",
        "due_date (45 category days beating 90 priority days)",
    )
    assert item["extension_reason"] is None

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert_integer(plan["extension_granted_days_total"], 0, "extension_granted_days_total")
    assert_instant(plan["overall_deadline"], "2026-11-19T00:00:00.000Z", "overall_deadline")


def test_an_overdue_line_may_not_be_extended_while_its_plan_is_not_defaulted(api):
    """PRD §3.7: an OVERDUE line may be extended only while its plan is
    DEFAULTED, and a sweep over a lone GUESTROOM line does not default the plan
    because the newly overdue line is neither CRITICAL nor LIFE_SAFETY.  So the
    line is overdue on a plan that is merely ACCEPTED, and relief is refused -
    with the agreement's compliance axis never having been touched.

    Design: Corner/validations/overdue_item_on_a_non_defaulted_plan_cannot_request_an_extension
    """
    world = fixtures.setup_accepted_plan(api, scope_lines=[GUESTROOM_MAJOR_LINE])
    fixtures.set_clock(api, "2027-04-04T00:00:00Z")
    fixtures.run_compliance_sweep(api, world["plan_id"])

    response = api.request_pip_item_extension(
        world["items"][0]["id"],
        factories.build_extension_request_payload(45, reason="Freight delay on case goods."),
        make_owner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.EXTENSION_WINDOW_CLOSED)
    assert response.status_code == 422

    item = _only_item(api, world["plan_id"])
    assert item["status"] == "OVERDUE"
    assert_instant(item["overdue_at"], "2027-04-04T00:00:00.000Z", "overdue_at")
    assert item["extension_status"] == "NONE"
    assert_integer(item["extension_request_count"], 0, "extension_request_count")

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "ACCEPTED", (
        f"a non-critical overdue line does not default the plan, got {plan['status']}"
    )
    assert_integer(plan["items_overdue_count"], 1, "items_overdue_count")
    assert_integer(plan["items_pending_count"], 0, "items_pending_count")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["transfer_consent_blocked"] is False


def _breached_de_identification_world(api):
    """A mutually terminated license with no revenue behind it, whose
    de-identification arrived five days after the deadline."""
    world = fixtures.setup_open_agreement(api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE])
    world = fixtures.setup_termination_pending_agreement(
        api, world, cause="MUTUAL", terminate_clock="2026-11-05T00:00:00Z"
    )
    agreement = world["agreement"]
    assert agreement["liquidated_damages_formula"] == "DISCOUNTED_PV"
    assert_money(agreement["trailing_avg_monthly_fee"], 0.00, "trailing_avg_monthly_fee")
    assert_integer(
        agreement["remaining_term_months_at_termination"], 239,
        "remaining_term_months_at_termination",
    )
    assert_integer(
        agreement["liquidated_damages_cap_months"], 36, "liquidated_damages_cap_months"
    )
    assert_money(agreement["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")
    assert_instant(
        agreement["de_identification_deadline"], "2026-12-05T00:00:00.000Z",
        "de_identification_deadline",
    )

    fixtures.set_clock(api, "2026-12-10T00:00:00Z")
    certified = fixtures.certify_de_identification(api, world)
    assert certified["de_identification_status"] == "BREACHED"
    assert_money(
        certified["de_identification_breach_penalty"], 50_000.00, "de_identification_breach_penalty"
    )
    return world


def test_a_settlement_one_cent_below_the_two_component_floor_is_refused(api):
    """PRD §3.9: the settlement must cover the liquidated damages plus the
    breach penalty together, so 49,999.99 against a floor of 0.00 plus
    50,000.00 leaves the obligations open.  A discounted present value of a
    0.00 trailing average is 0.00 however many months are charged, so the whole
    floor here is the penalty - and the refusal records no payment and no
    close-out stamp.

    Design: Corner/validations/close_out_below_the_two_component_settlement_floor_is_rejected
    """
    world = _breached_de_identification_world(api)
    response = api.close_out_agreement(
        world["agreement_id"], factories.build_close_out_payload(49_999.99), BSD_HEADERS
    )
    validate_error(response, ApiErrorId.POST_TERMINATION_OBLIGATIONS_OPEN)
    assert response.status_code == 422

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_money(agreement["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")
    assert agreement["de_identification_status"] == "BREACHED"
    assert_money(
        agreement["de_identification_breach_penalty"], 50_000.00, "de_identification_breach_penalty"
    )
    assert agreement["status"] == "TERMINATION_PENDING"
    assert agreement["post_termination_status"] == "OPEN"
    assert_money(
        agreement["liquidated_damages_paid_amount"], 0.00, "liquidated_damages_paid_amount"
    )
    assert agreement["closed_out_at"] is None


def test_a_settlement_at_exactly_the_two_component_floor_closes_the_file(api):
    """PRD §3.9: the floor is inclusive, so one cent more than the refused
    tender - exactly 50,000.00 - discharges both obligations and closes the
    file.  The agreement reaches its terminal state, de-identification is
    VERIFIED and the tendered amount is recorded, while the frozen damages and
    the penalty that set the floor are not rewritten by the payment.

    Design: Corner/validations/close_out_at_exactly_the_settlement_floor_succeeds
    """
    world = _breached_de_identification_world(api)
    fixtures.set_clock(api, "2026-12-12T00:00:00Z")
    agreement = get_success_data(
        api.close_out_agreement(
            world["agreement_id"], factories.build_close_out_payload(50_000.00), BSD_HEADERS
        )
    )

    assert agreement["status"] == "TERMINATED"
    assert agreement["post_termination_status"] == "CLOSED"
    assert agreement["de_identification_status"] == "VERIFIED"
    assert_money(
        agreement["liquidated_damages_paid_amount"], 50_000.00, "liquidated_damages_paid_amount"
    )
    assert_instant(agreement["closed_out_at"], "2026-12-12T00:00:00.000Z", "closed_out_at")
    assert_money(
        agreement["de_identification_breach_penalty"], 50_000.00, "de_identification_breach_penalty"
    )
    assert_money(agreement["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")
