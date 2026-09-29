"""Action endpoints, cross-reference links, snapshot reads and gated cycles.

Covers PRD section 3.1 (suspending a capture point), section 3.2 (the target
agreement rules behind approval paperwork), section 3.5 (the recount cycle and
its round cap) and section 3.8 together with section 2.9 (a revenue report as a
frozen snapshot that advertises its own staleness).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_null_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_suspending_a_capture_point_closes_it_to_new_traffic_only(api):
    """Suspension blocks new checks and batches yet keeps yesterday's revenue on the books.

    PRD section 3.1 makes suspension deliberately non-destructive: the outlet stays
    fully addressable for prior-day audit work while every later attempt to open a
    check or declare a batch naming it fails with ERR_OUTLET_SUSPENDED (HTTP 409),
    and the suspension increments the outlet's `version` while leaving its
    configuration — `requires_shift_settlement` included — alone. PRD section 3.4
    keeps the already-closed check's 160.48 total inside the day's
    `closed_outlet_ticket_count` and `outlet_revenue_amount`, and PRD section 3.8
    only demands a batch from outlets that are still ACTIVE, so the day verifies
    settlements with no batch at all. PRD section 3.1 also narrows the outlet
    listing by `status`.

    Design: Corner/endpoints/endpoint_action_endpoint_suspending_an_outlet_closes_it_to_new_traffic_only
    """
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    ticket = fx.create_outlet_ticket(
        api,
        outlet["id"],
        bd["id"],
        128.00,
        ticket_number="T-SUS-1",
        settlement_type="CASH",
        opened_at="2026-08-01T18:00:00.000Z",
    )
    fx.close_outlet_ticket(api, ticket["id"], outlet["id"], "2026-08-01T20:00:00.000Z")

    suspended = validate_success(api.suspend_outlet(outlet["id"], ADMIN))
    assert_fields(
        suspended,
        {
            "status": "SUSPENDED",
            "version": 2,
            "outlet_code": "LOBBY",
            "outlet_name": "Lobby Lounge",
            "outlet_type": "FB_OUTLET",
            "requires_shift_settlement": True,
            "property_id": prop["id"],
        },
    )

    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                outlet["id"],
                bd["id"],
                90.00,
                ticket_number="T-SUS-2",
                opened_at="2026-08-01T20:10:00.000Z",
            ),
            AUDITOR,
        ),
        E.ERR_OUTLET_SUSPENDED,
    )
    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(bd["id"], outlet["id"], 160.48), AUDITOR
        ),
        E.ERR_OUTLET_SUSPENDED,
    )

    still_closed = fx.read_ticket(api, ticket["id"])
    assert_fields(still_closed, {"status": "CLOSED"})
    assert_money(still_closed["total_amount"], 160.48, "total_amount")

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["closed_outlet_ticket_count"], 1, "closed_outlet_ticket_count")
    assert_money(day["outlet_revenue_amount"], 160.48, "outlet_revenue_amount")

    reviewed = fx.drive_to_settlement_review(api, bd["id"])
    assert_fields(reviewed, {"status": "SETTLEMENT_REVIEW"})
    assert_int(
        reviewed["unresolved_settlement_batch_count"],
        0,
        "unresolved_settlement_batch_count",
    )

    actives = validate_success(
        api.list_outlets(ADMIN, property_id=prop["id"], status="ACTIVE")
    )
    assert_row_count(actives, 0, "ACTIVE outlets")
    suspendeds = validate_success(
        api.list_outlets(ADMIN, property_id=prop["id"], status="SUSPENDED")
    )
    assert_row_count(suspendeds, 1, "SUSPENDED outlets")
    assert_fields(single(suspendeds), {"id": outlet["id"]})


def test_paperwork_binds_to_exactly_one_target_kind(api):
    """One filing endpoint, but `doc_type` decides which link is required and which forbidden.

    PRD section 3.2 requires a COMP_ROOM or RATE_OVERRIDE document to supply
    `folio_id` and to withhold `allowance_id`, requires an ALLOWANCE_APPROVAL
    document to do exactly the reverse, and additionally requires
    `authorized_rate_amount` on a RATE_OVERRIDE — any disagreement being
    ERR_DOCUMENT_TARGET_MISMATCH (HTTP 422). PRD section 2.12 places the
    referenced-record check above body validation, so a link to a folio that does
    not exist is ERR_FOLIO_NOT_FOUND (HTTP 404) even when the body shape is also
    wrong. PRD section 3.2 makes the filing discoverable from either side through
    the `folio_id` and `allowance_id` filters.

    Design: Corner/endpoints/endpoint_cross_reference_link_documents_bind_to_exactly_one_target_kind
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-LK1",
        guest_name="Ras Oyelaran",
        room_number="1401",
        credit_limit_amount=2000.00,
    )
    allowance = fx.create_allowance(
        api,
        folio["id"],
        bd["id"],
        1500.00,
        reason_code="SERVICE_RECOVERY",
        narrative="Extended outage compensation.",
    )
    assert_fields(allowance, {"status": "DRAFT", "required_approval_role": "Controller"})

    def file_document(**overrides):
        return api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"], valid_from_date="2026-08-01", valid_to_date="2026-08-04",
                **overrides
            ),
            FRONT_DESK,
        )

    validate_error(
        file_document(
            doc_type="COMP_ROOM",
            document_reference="CR-9001",
            allowance_id=allowance["id"],
        ),
        E.ERR_DOCUMENT_TARGET_MISMATCH,
    )

    comp = validate_success(
        file_document(
            doc_type="COMP_ROOM",
            document_reference="CR-9001",
            folio_id=folio["id"],
        ),
        expected_status=201,
    )
    assert_fields(comp, {"status": "PENDING", "folio_id": folio["id"]})
    assert_null_fields(comp, ["allowance_id"])

    validate_error(
        file_document(
            doc_type="ALLOWANCE_APPROVAL",
            document_reference="AA-9002",
            folio_id=folio["id"],
        ),
        E.ERR_DOCUMENT_TARGET_MISMATCH,
    )
    approval = validate_success(
        file_document(
            doc_type="ALLOWANCE_APPROVAL",
            document_reference="AA-9002",
            allowance_id=allowance["id"],
        ),
        expected_status=201,
    )
    assert_fields(approval, {"status": "PENDING", "allowance_id": allowance["id"]})
    assert_null_fields(approval, ["folio_id"])

    validate_error(
        file_document(
            doc_type="RATE_OVERRIDE",
            document_reference="RO-9003",
            folio_id=folio["id"],
        ),
        E.ERR_DOCUMENT_TARGET_MISMATCH,
    )

    validate_error(
        file_document(
            doc_type="COMP_ROOM",
            document_reference="CR-9004",
            folio_id=MISSING_UUID,
        ),
        E.ERR_FOLIO_NOT_FOUND,
    )

    by_folio = validate_success(
        api.list_authorization_documents(FRONT_DESK, folio_id=folio["id"])
    )
    assert_row_count(by_folio, 1, "documents linked to the guest account")
    assert_fields(single(by_folio), {"id": comp["id"]})

    by_allowance = validate_success(
        api.list_authorization_documents(FRONT_DESK, allowance_id=allowance["id"])
    )
    assert_row_count(by_allowance, 1, "documents linked to the allowance")
    assert_fields(single(by_allowance), {"id": approval["id"]})


def test_a_revenue_report_is_a_frozen_snapshot_that_flags_its_own_staleness(api):
    """Every figure is copied off the day at creation, so a later reversal moves none of them.

    PRD section 3.8 makes report creation copy the day's nine statistics and revenue
    figures into the report row and freeze them there, stamping `generated_by_user_id`
    and DRAFT, and freezes the pace comparison from the day's CALENDAR_ALIGNED
    benchmark as one hundred times `room_revenue_amount` over that benchmark. PRD
    section 2.9 then makes any journal line that changes the day's revenue aggregates
    set every DRAFT or DISTRIBUTED report of that day to SUPERSEDED — a status that is
    terminal and can never be distributed — while PRD section 2.8 leaves the reversal
    as an appended line that cannot reach back into the snapshot. PRD section 3.7
    permits the reversal itself even under settlement review.

    Design: Corner/endpoints/endpoint_computed_read_a_revenue_report_is_a_frozen_snapshot
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RP1",
        guest_name="Sig Ahlberg",
        room_number="1501",
        contracted_rate_amount=200.00,
        credit_limit_amount=2000.00,
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_settlement_review(api, bd["id"])

    report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(
                bd["id"],
                fx.business_date_version(api, bd["id"]),
                ["Controller", "RevenueManager"],
                pace_basis="CALENDAR_ALIGNED",
            ),
            REVENUE_MANAGER,
        ),
        expected_status=201,
    )
    assert_int(report["rooms_available_count"], 96, "rooms_available_count")
    assert_int(report["rooms_occupied_count"], 1, "rooms_occupied_count")
    assert_money_fields(
        report,
        {
            "occupancy_pct": 1.04,
            "adr_amount": 200.00,
            "revpar_amount": 2.08,
            "room_revenue_amount": 200.00,
            "tax_revenue_amount": 17.75,
            "outlet_revenue_amount": 0.00,
            "total_revenue_amount": 217.75,
            "benchmark_room_revenue_amount": 400.00,
            "pace_index_pct": 50.00,
        },
    )
    assert_fields(
        report,
        {
            "pace_basis": "CALENDAR_ALIGNED",
            "status": "DRAFT",
            "generated_by_user_id": REVENUE_MANAGER["X-User-ID"],
            "business_date_id": bd["id"],
        },
    )
    assert_null_fields(report, ["distributed_at"])

    room_line = single(
        fx.list_postings(api, folio_id=folio["id"], charge_type="ROOM"), "the ROOM line"
    )
    validate_success(
        api.reverse_journal_posting(room_line["id"], CONTROLLER), expected_status=201
    )

    day = fx.read_business_date(api, bd["id"])
    assert_money_fields(
        day, {"room_night_revenue_amount": 0.00, "total_revenue_amount": 17.75}
    )

    frozen = fx.read_report(api, report["id"])
    assert_money_fields(
        frozen,
        {
            "room_revenue_amount": 200.00,
            "tax_revenue_amount": 17.75,
            "total_revenue_amount": 217.75,
            "adr_amount": 200.00,
            "revpar_amount": 2.08,
            "pace_index_pct": 50.00,
        },
    )
    assert_int(frozen["rooms_occupied_count"], 1, "rooms_occupied_count")
    assert_fields(frozen, {"status": "SUPERSEDED"})

    validate_error(
        api.distribute_revenue_report(report["id"], REVENUE_MANAGER),
        E.ERR_REPORT_NOT_DRAFT,
    )


def test_the_recount_cycle_is_gated_at_every_hop_and_capped_at_two_rounds(api):
    """Each of the three batch actions is legal in exactly one state, and the counter caps the cycle.

    PRD section 3.5 pins requesting a recount and accepting a variance to
    VARIANCE_FLAGGED (ERR_BATCH_NOT_FLAGGED, HTTP 409) and redeclaring to
    RECOUNT_REQUESTED (ERR_BATCH_NOT_AWAITING_RECOUNT, HTTP 409); a batch out for
    recount leaves the day's `settlement_variance_total_amount` while still counting
    as unresolved; a redeclaration clears `variance_amount` back to null and leaves
    `recount_round` untouched, so only a recount request advances the counter; and a
    third request on a batch whose `recount_round` has reached two is refused with
    ERR_RECOUNT_LIMIT_REACHED. PRD section 3.8 makes re-running settlement
    verification on a day already under review the one way a redeclared batch is
    judged again. An OutletManager reaching outside their own outlet is refused with
    ERR_OUTLET_SCOPE_VIOLATION.

    Design: Corner/endpoints/endpoint_conditional_action_recount_cycle_is_gated_at_every_hop
    """
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    grill = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="GRILL",
        outlet_name="Harbor Grill",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    ticket = fx.create_outlet_ticket(
        api,
        lounge["id"],
        bd["id"],
        128.00,
        ticket_number="T-RC-1",
        settlement_type="CASH",
        opened_at="2026-08-01T18:00:00.000Z",
    )
    fx.close_outlet_ticket(api, ticket["id"], lounge["id"], "2026-08-01T20:00:00.000Z")
    batch = fx.create_settlement_batch(api, bd["id"], lounge["id"], 100.00)
    lounge_manager = make_outlet_manager_headers(lounge["id"])

    validate_error(
        api.redeclare_batch(batch["id"], f.build_redeclare_payload(100.00), lounge_manager),
        E.ERR_BATCH_NOT_AWAITING_RECOUNT,
    )

    fx.drive_to_settlement_review(api, bd["id"])
    flagged = fx.read_batch(api, batch["id"])
    assert_fields(flagged, {"status": "VARIANCE_FLAGGED"})
    assert_money_fields(
        flagged, {"system_amount": 160.48, "variance_amount": -60.48}
    )

    requested = validate_success(api.request_recount(batch["id"], AUDITOR))
    assert_fields(requested, {"status": "RECOUNT_REQUESTED"})
    assert_int(requested["recount_round"], 1, "recount_round")

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["unresolved_settlement_batch_count"], 1, "unresolved_settlement_batch_count")
    assert_money(
        day["settlement_variance_total_amount"], 0.00, "settlement_variance_total_amount"
    )

    validate_error(api.request_recount(batch["id"], AUDITOR), E.ERR_BATCH_NOT_FLAGGED)
    validate_error(
        api.accept_variance(batch["id"], REVENUE_MANAGER), E.ERR_BATCH_NOT_FLAGGED
    )
    validate_error(
        api.redeclare_batch(
            batch["id"],
            f.build_redeclare_payload(100.00),
            make_outlet_manager_headers(grill["id"]),
        ),
        E.ERR_OUTLET_SCOPE_VIOLATION,
    )

    redeclared = validate_success(
        api.redeclare_batch(batch["id"], f.build_redeclare_payload(100.00), lounge_manager)
    )
    assert_fields(redeclared, {"status": "DECLARED"})
    assert_null_fields(redeclared, ["variance_amount"])
    assert_int(redeclared["recount_round"], 1, "recount_round")
    validate_error(
        api.redeclare_batch(batch["id"], f.build_redeclare_payload(100.00), lounge_manager),
        E.ERR_BATCH_NOT_AWAITING_RECOUNT,
    )

    reviewed = validate_success(api.verify_settlements(bd["id"], AUDITOR))
    assert_fields(reviewed, {"status": "SETTLEMENT_REVIEW"})
    reflagged = fx.read_batch(api, batch["id"])
    assert_fields(reflagged, {"status": "VARIANCE_FLAGGED"})
    assert_money(reflagged["variance_amount"], -60.48, "variance_amount")

    second = validate_success(api.request_recount(batch["id"], AUDITOR))
    assert_int(second["recount_round"], 2, "recount_round")

    validate_success(
        api.redeclare_batch(batch["id"], f.build_redeclare_payload(100.00), lounge_manager)
    )
    validate_success(api.verify_settlements(bd["id"], AUDITOR))
    assert_fields(fx.read_batch(api, batch["id"]), {"status": "VARIANCE_FLAGGED"})
    validate_error(api.request_recount(batch["id"], AUDITOR), E.ERR_RECOUNT_LIMIT_REACHED)

    accepted = validate_success(api.accept_variance(batch["id"], REVENUE_MANAGER))
    assert_fields(
        accepted,
        {
            "status": "ACCEPTED_WITH_VARIANCE",
            "accepted_by_user_id": REVENUE_MANAGER["X-User-ID"],
        },
    )
    settled_day = fx.read_business_date(api, bd["id"])
    assert_int(
        settled_day["unresolved_settlement_batch_count"],
        0,
        "unresolved_settlement_batch_count",
    )
    assert_money(
        settled_day["settlement_variance_total_amount"],
        60.48,
        "settlement_variance_total_amount",
    )
