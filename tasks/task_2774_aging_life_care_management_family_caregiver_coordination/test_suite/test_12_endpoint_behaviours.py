"""Endpoint-level behaviour: post-acceptance corrections and the pin they stale,
the invoice payment ledger, the client roster's window and filters, and a clean
vendor's closed disclosure dimension.
"""
from test_helpers import (
    accept_assessment,
    api_client,
    assert_timestamps_equal,
    author_care_plan,
    authorize_service_authorization,
    BILLING_ADMINISTRATOR,
    coi_event_payload,
    create_approved_time_entry,
    get_success_data,
    invoice_payment_payload,
    issue_invoice,
    make_care_manager_headers,
    make_family_decision_maker_headers,
    open_assessment,
    open_invoice,
    pay_invoice,
    PRACTICE_ADMIN,
    propose_service_authorization,
    read_assessment,
    read_authorization,
    read_care_plan,
    read_client,
    read_invoice,
    register_care_manager,
    register_client,
    register_supervisor,
    register_surrogate_contact,
    send_plan_for_family_approval,
    set_logical_clock,
    setup_active_care_plan_scenario,
    submit_assessment,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
)

_CORRECTED_NARRATIVE = "Corrected narrative: PCP name misspelled in the accepted version."


def _accepted_assessment_with_a_plan_pinned_to_it():
    """An accepted assessment carrying prose, and a DRAFT plan that pinned that
    assessment's version at the moment it was authored.
    """
    set_logical_clock("2026-08-27T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Bea Lindgren",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    surrogate = register_surrogate_contact(
        client["id"], full_name="Cai Lindgren", contact_role="POA_HEALTHCARE"
    )
    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores=uniform_domain_scores(2),
        narrative="Initial narrative.",
    )
    submit_assessment(assessment["id"], care_manager["id"])
    accepted = accept_assessment(assessment["id"], supervisor["id"])
    assert accepted["comprehensive_acuity"] == 40

    plan = author_care_plan(
        client["id"],
        assessment["id"],
        care_manager["id"],
        goals=["Weekly medication oversight"],
    )
    assert plan["pinned_assessment_version"] == accepted["version"]
    return client, care_manager, surrogate, accepted, plan


def test_01_scores_are_frozen_once_the_assessment_is_accepted():
    """The clinical figures are not editable after review: a score correction on an
    accepted assessment is refused and leaves the row, its acuity and its version
    exactly as accepted.

    PRD: "A `domain_scores` edit is permitted only while `status` is `DRAFT`; attempting one on an assessment in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/narrative_correction_on_accepted_assessment_stales_the_pinned_plan
    """
    _client, care_manager, _surrogate, accepted, plan = (
        _accepted_assessment_with_a_plan_pinned_to_it()
    )

    validate_error(
        api_client.update_assessment(
            accepted["id"],
            {"domain_scores": uniform_domain_scores(5)},
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    unchanged = read_assessment(accepted["id"])
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["version"] == accepted["version"]
    assert unchanged["comprehensive_acuity"] == 40
    assert read_care_plan(plan["id"])["pinned_assessment_version"] == accepted["version"]


def test_02_a_narrative_correction_is_allowed_and_re_derives_nothing():
    """Prose may be fixed after acceptance: the correction lands, the status holds
    and neither acuity figure is recomputed — but the row's version moves.

    PRD: "A `narrative`-only correction is permitted while `status` is `DRAFT` or `ACCEPTED` — the practice must be able to fix a typo in an accepted report — and such a correction never re-derives `screening_acuity` or `comprehensive_acuity` and never changes `status`."

    Design: Corner/endpoints/narrative_correction_on_accepted_assessment_stales_the_pinned_plan
    """
    _client, care_manager, _surrogate, accepted, _plan = (
        _accepted_assessment_with_a_plan_pinned_to_it()
    )

    corrected = get_success_data(
        api_client.update_assessment(
            accepted["id"],
            {"narrative": _CORRECTED_NARRATIVE},
            make_care_manager_headers(care_manager["id"]),
        ),
        200,
    )
    assert corrected["status"] == "ACCEPTED"
    assert corrected["narrative"] == _CORRECTED_NARRATIVE
    assert corrected["version"] == accepted["version"] + 1
    assert corrected["comprehensive_acuity"] == 40
    assert corrected["screening_acuity"] == accepted["screening_acuity"]


def test_03_the_correction_permanently_stales_the_plan_that_pinned_it():
    """The plan authored before the correction can no longer be sent for family
    approval, and only a plan re-authored against the corrected assessment moves.

    PRD: "The plan's `pinned_assessment_version` must still equal the source assessment's current `version`; if the assessment has been edited or has gone around a revision lap since the plan was authored, the plan is out of date and the request is rejected with `ERR_PINNED_ASSESSMENT_STALE`."

    Design: Corner/endpoints/narrative_correction_on_accepted_assessment_stales_the_pinned_plan
    """
    client, care_manager, _surrogate, accepted, plan = (
        _accepted_assessment_with_a_plan_pinned_to_it()
    )
    headers = make_care_manager_headers(care_manager["id"])
    corrected = get_success_data(
        api_client.update_assessment(
            accepted["id"], {"narrative": _CORRECTED_NARRATIVE}, headers
        ),
        200,
    )

    validate_error(
        api_client.patch_care_plan_state(
            plan["id"], {"to_state": "PENDING_FAMILY_APPROVAL"}, headers
        ),
        "ERR_PINNED_ASSESSMENT_STALE",
        409,
    )
    assert read_care_plan(plan["id"])["status"] == "DRAFT"

    re_authored = author_care_plan(
        client["id"],
        accepted["id"],
        care_manager["id"],
        goals=["Weekly medication oversight (re-authored)"],
    )
    assert re_authored["pinned_assessment_version"] == corrected["version"]

    sent = send_plan_for_family_approval(re_authored["id"], care_manager["id"])
    assert sent["status"] == "PENDING_FAMILY_APPROVAL"
    assert read_assessment(accepted["id"])["status"] == "ACCEPTED"


def _issued_invoice_with_nothing_drawn():
    """An issued invoice for one billable hour against a client holding no
    retainer, so the whole total is outstanding as a family balance.
    """
    set_logical_clock("2026-08-11T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Dov Halvorsen",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-10T10:00:00Z",
        "2026-08-10T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    invoice = open_invoice(
        client["id"], period_start="2026-08-01", period_end="2026-08-31"
    )
    issued = issue_invoice(invoice["id"])
    assert issued["status"] == "ISSUED"
    assert issued["total_due_cents"] == 24_075
    assert issued["retainer_applied_cents"] == 0
    assert issued["balance_due_cents"] == 24_075
    assert issued["amount_paid_cents"] == 0
    return client, issued


def test_04_a_partial_payment_accumulates_and_an_overpayment_is_refused():
    """Paying less than the balance is not a transition — the running total moves
    and the invoice stays issued — while a payment that would carry the total past
    the balance is refused outright and records nothing.

    PRD: "When `amount_paid_cents` plus the new `amount_cents` exactly equals the invoice's `balance_due_cents`, the invoice moves `ISSUED → PAID`; when it is less, the invoice stays `ISSUED` and the family may pay again; when it is more, the payment is refused outright with `ERR_PAYMENT_EXCEEDS_BALANCE` and nothing is recorded."

    Design: Corner/endpoints/invoice_payments_partial_then_exact_and_overpayment_rejected
    """
    _client, invoice = _issued_invoice_with_nothing_drawn()

    part = pay_invoice(
        invoice["id"], 10_000, received_at="2026-08-11T10:00:00Z", method="ACH"
    )
    assert part["amount_paid_cents"] == 10_000
    assert part["status"] == "ISSUED"

    validate_error(
        api_client.post_invoice_payment(
            invoice["id"],
            invoice_payment_payload(
                20_000, received_at="2026-08-11T10:05:00Z", method="ACH"
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_PAYMENT_EXCEEDS_BALANCE",
        422,
    )
    assert read_invoice(invoice["id"])["amount_paid_cents"] == 10_000


def test_05_only_the_exact_remainder_settles_the_invoice_and_paid_is_terminal():
    """The remaining cents to the penny move the invoice to paid; one cent after
    that is refused as unreachable, and no payment ever touched the retainer.

    PRD: "When `amount_paid_cents` plus the new `amount_cents` exactly equals the invoice's `balance_due_cents`, the invoice moves `ISSUED → PAID`; when it is less, the invoice stays `ISSUED` and the family may pay again; when it is more, the payment is refused outright with `ERR_PAYMENT_EXCEEDS_BALANCE` and nothing is recorded."

    Design: Corner/endpoints/invoice_payments_partial_then_exact_and_overpayment_rejected
    """
    client, invoice = _issued_invoice_with_nothing_drawn()
    pay_invoice(invoice["id"], 10_000, received_at="2026-08-11T10:00:00Z", method="ACH")

    settled = pay_invoice(
        invoice["id"], 14_075, received_at="2026-08-11T10:10:00Z", method="CHECK"
    )
    assert settled["amount_paid_cents"] == 24_075
    assert settled["status"] == "PAID"

    validate_error(
        api_client.post_invoice_payment(
            invoice["id"],
            invoice_payment_payload(
                1, received_at="2026-08-11T10:15:00Z", method="CHECK"
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    observed = read_client(client["id"])
    assert observed["retainer_balance_cents"] == 0
    assert observed["retainer_deposits_total_cents"] == 0


def _three_clients_an_hour_apart():
    """An intake queue built one hour at a time, with the newest client pulled out
    of prospect status by an assessment.
    """
    set_logical_clock("2026-08-28T10:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    first = register_client(
        full_name="Elm Sanchez",
        residence_setting="PRIVATE_HOME",
        retainer_floor_cents=0,
    )
    set_logical_clock("2026-08-28T11:00:00Z")
    second = register_client(
        full_name="Fig Sanchez",
        residence_setting="ASSISTED_LIVING",
        retainer_floor_cents=0,
    )
    set_logical_clock("2026-08-28T12:00:00Z")
    third = register_client(
        full_name="Gil Sanchez",
        residence_setting="SKILLED_NURSING",
        retainer_floor_cents=0,
    )
    open_assessment(third["id"], care_manager["id"], scores=uniform_domain_scores(2))
    assert read_client(third["id"])["status"] == "ASSESSMENT_IN_PROGRESS"
    return first, second, third


def test_06_the_client_roster_is_an_intake_queue_read_newest_first():
    """The roster is the one collection returned newest first, and the two pages of
    a three-client practice come back in descending creation order with the count
    of the whole matching set on both.

    PRD: "Collections are returned in ascending `created_at` order, oldest record first, with one deliberate exception: the client roster is returned newest first, in descending `created_at` order, because the practice reads it as an intake queue."

    Design: Corner/endpoints/client_listing_pagination_and_status_filter_interact
    """
    first, second, third = _three_clients_an_hour_apart()

    rows, meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, params={"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in rows] == [third["id"], second["id"]]
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert_timestamps_equal(rows[0]["created_at"], "2026-08-28T12:00:00Z")

    rows, meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in rows] == [first["id"]]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_07_the_status_filter_narrows_the_set_before_the_window_is_taken():
    """The filtered count is the count of matching clients, not of the table, and
    the last page of a filtered query reports nothing more to come.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object of the response together with `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true exactly when records matching the filters remain beyond the current page."

    Design: Corner/endpoints/client_listing_pagination_and_status_filter_interact
    """
    first, second, _third = _three_clients_an_hour_apart()

    rows, meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, params={"status": "PROSPECT"})
    )
    assert [row["id"] for row in rows] == [second["id"], first["id"]]
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_clients(
            PRACTICE_ADMIN, params={"status": "PROSPECT", "limit": 1, "offset": 1}
        )
    )
    assert [row["id"] for row in rows] == [first["id"]]
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, params={"status": "DISCHARGED"})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def _proposed_engagement_of_an_unconflicted_vendor():
    """A proposed engagement of a vendor the practice has no referral relationship
    with, so the conflict dimension opens closed.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-29T09:00:00Z",
        client_overrides={
            "full_name": "Hugo Meireles",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        surrogate_role="POA_HEALTHCARE",
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        goals=["Daily aide visits"],
    )
    authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-21T08:00:00Z",
        coverage_end="2026-09-21T12:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    assert authorization["coi_status"] == "NOT_REQUIRED"
    assert authorization["disclosure_text"] is None
    return scenario, authorization


def test_08_neither_disclosure_nor_acknowledgement_is_accepted_when_none_is_required():
    """A clean vendor's conflict dimension is already closed, so both conflict
    events are refused as transitions out of a terminal state and nothing about the
    authorization moves.

    PRD: "`NOT_REQUIRED` and `ACKNOWLEDGED` are both terminal on this dimension: a disclosure event submitted against an authorization whose `coi_status` is `NOT_REQUIRED`, or already `ACKNOWLEDGED`, is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/coi_events_rejected_on_a_not_required_authorization
    """
    scenario, authorization = _proposed_engagement_of_an_unconflicted_vendor()

    validate_error(
        api_client.post_coi_event(
            authorization["id"],
            coi_event_payload(
                "DISCLOSE", note="Attempted disclosure on a clean vendor"
            ),
            scenario.cm_headers,
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )
    validate_error(
        api_client.post_coi_event(
            authorization["id"],
            coi_event_payload(
                "ACKNOWLEDGE", acknowledged_by_contact_id=scenario.surrogate_id
            ),
            make_family_decision_maker_headers(scenario.surrogate_id),
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    observed = read_authorization(authorization["id"])
    assert observed["coi_status"] == "NOT_REQUIRED"
    assert observed["disclosure_text"] is None
    assert observed["coi_acknowledged_by_contact_id"] is None
    assert observed["auth_status"] == "PROPOSED"
    assert observed["version"] == authorization["version"]


def test_09_an_unconflicted_engagement_authorizes_while_still_not_required():
    """The disclosure dimension is only read at the authorizing step, and it is
    satisfied there by `NOT_REQUIRED` — the engagement authorizes with the conflict
    field never having moved. Before the authorization the client is ELEVATED because
    its ACTIVE plan still carries a coverage gap; closing that gap returns it to
    ROUTINE.

    PRD: "The two do not gate each other except at one point: a `PROPOSED` authorization can reach `ACKNOWLEDGED` on the disclosure dimension while sitting still on the commercial one, and an `AUTHORIZED` authorization can perfectly well remain at `NOT_REQUIRED`; only the step from `PROPOSED` to `AUTHORIZED` reads the disclosure dimension at all."

    Design: Corner/endpoints/coi_events_rejected_on_a_not_required_authorization
    """
    scenario, authorization = _proposed_engagement_of_an_unconflicted_vendor()
    assert read_client(scenario.client_id)["risk_posture"] == "ELEVATED"

    authorized = authorize_service_authorization(
        authorization["id"], scenario.supervisor_id
    )
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coi_status"] == "NOT_REQUIRED"
    assert authorized["coverage_hours"] == 4

    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 4
    assert client["risk_posture"] == "ROUTINE"
