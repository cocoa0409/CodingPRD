"""Initial states, refused replays and the two loops the domain actually contains."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CHECKOUT_NOT_OPEN,
    ERR_COMMISSIONING_NOT_APPLICABLE,
    ERR_COMMISSIONING_NOT_PAIRED,
    ERR_CONSULTATION_CLOSED,
    ERR_CONSULTATION_NOT_SCHEDULED,
    ERR_INSTALL_JOB_NOT_SCHEDULED,
    ERR_KIT_NOT_AVAILABLE,
    ERR_OPENING_NOT_MEASURED,
    ERR_ORDER_NOT_SHIPPABLE,
    ERR_ORDER_NOT_SHIPPED,
    ERR_REMAKE_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_entry,
    assert_page_meta,
    assert_remake_buckets_sum,
)
from test_helpers.fixtures import (
    CLOCK_START,
    accept_quote,
    add_sample_kit,
    book_consultation,
    build_quote,
    charter_territory,
    checkout_kit,
    complete_consultation,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_opening,
    read_order,
    read_quote,
    read_territory,
    receive_order,
    record_opening,
    request_remake,
    return_kit,
    schedule_install,
    set_clock,
    ship_order,
    single_opening_job,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
    vendor_rep_headers,
)


def test_creation_stamps_nine_dimensions_and_skips_the_tenth(api):
    """Kit, appointment and opening read their declared initial state; a lead never reads NEW.

    "A lead's `status` therefore begins at `NEW` but `NEW` is never observable in any
    response body — the created lead already reads `ROUTED`, `QUEUED` or
    `UNROUTABLE`."

    "A new kit is stamped `AVAILABLE` with `loan_count` and `open_loan_count` at
    zero."

    "A newly recorded opening is stamped with `measure_status` `MEASURED`,
    `install_outcome` `PENDING`, `credited` false, `list_price_cents` zero and
    `billable_sqft` zero, and with `quote_id`, `fabric_code` and `lift_system` all
    null."

    Design: Corner/state_machines/every_declared_dimension_is_stamped_at_its_initial_state_by_creation
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    assert territory["status"] == "ACTIVE"
    assert designer["status"] == "ACTIVE"

    kit = validate_success(api.create_sample_kit(
        f.sample_kit_payload(territory["id"], kit_code="SHEERS-A"),
        franchisee_headers(territory["id"])), 201)
    assert kit["status"] == "AVAILABLE"
    assert kit["loan_count"] == 0
    assert kit["open_loan_count"] == 0

    lead = validate_success(api.create_lead(
        f.lead_payload(source="NATIONAL_CALL_CENTER"), franchisor_headers()), 201)
    assert lead["status"] == "ROUTED"
    assert lead["status"] != "NEW"
    assert lead["territory_id"] == territory["id"]
    assert_instant_equals(lead["routed_at"], CLOCK_START, "lead.routed_at")

    consultation = validate_success(api.create_consultation(
        f.consultation_payload(lead["id"], designer["id"]),
        designer_headers(designer["id"])), 201)
    assert consultation["status"] == "SCHEDULED"
    assert consultation["measured_opening_count"] == 0
    assert consultation["configured_opening_count"] == 0

    opening = validate_success(api.create_opening(
        f.opening_payload(consultation["id"]),
        designer_headers(designer["id"])), 201)
    assert opening["measure_status"] == "MEASURED"
    assert opening["install_outcome"] == "PENDING"
    assert opening["credited"] is False
    assert opening["list_price_cents"] == 0
    assert opening["billable_sqft"] == 0


def test_closing_an_appointment_twice_is_refused_by_its_own_status_gate(api):
    """Close-out is not idempotent, and the refusal does not re-run the lead cascade.

    "Closing out a visit is the assigned designer's action and drives `SCHEDULED →
    COMPLETED`. It requires the appointment to still be `SCHEDULED`, the acting
    designer to be the one assigned, at least one measured opening on the record, and
    — crucially — `open_sample_loan_count` to be exactly zero."

    "A lead moves `ROUTED → CONSULT_COMPLETE` when its consultation reaches
    `COMPLETED`, and the territory's `open_leads_count` is unchanged because
    `CONSULT_COMPLETE` is still an open status."

    Design: Corner/state_machines/closing_a_consultation_twice_is_refused_by_its_own_status_gate
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    record_opening(api, designer, consultation)
    dsg = designer_headers(designer["id"])

    closed = complete_consultation(api, designer, consultation)
    assert closed["status"] == "COMPLETED"
    assert_instant_equals(closed["completed_at"], CLOCK_START,
                          "consultation.completed_at")
    assert validate_success(api.get_lead(
        lead["id"], franchisee_headers(territory["id"])
    ))["status"] == "CONSULT_COMPLETE"

    validate_error(api.complete_consultation(consultation["id"], dsg),
                   ERR_CONSULTATION_NOT_SCHEDULED, 409)

    unchanged = validate_success(api.get_consultation(consultation["id"], dsg))
    assert unchanged["status"] == "COMPLETED"
    assert_instant_equals(unchanged["completed_at"], closed["completed_at"],
                          "consultation.completed_at")
    assert read_territory(api, territory)["open_leads_count"] == 1


def test_measuring_survives_a_completed_appointment_but_not_a_no_show(api):
    """One designer, two closed appointments, two different verdicts on the same call.

    "An opening may be recorded while the consultation is `SCHEDULED` or after it has
    reached `COMPLETED`, because a corrective trip and a later quote revision both
    legitimately attach to a closed-out visit; only a `CANCELLED` or `NO_SHOW`
    appointment closes the file for good, and recording against one of those is
    `ERR_CONSULTATION_CLOSED`."

    "A no-show is terminal for the appointment and fatal for the lead: it drives the
    lead `ROUTED → LOST`, which decrements the territory's `open_leads_count`, which
    in turn promotes one queued lead."

    Design: Corner/state_machines/measuring_survives_a_completed_appointment_but_not_a_no_show
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    kept = intake_lead(api, territory, customer_name="Ana Ruiz")
    missed = intake_lead(api, territory, customer_name="Bo Chen",
                         source="REFERRAL",
                         requested_at="2026-08-01T09:00:00.000Z")
    closed_out = book_consultation(api, designer, kept)
    no_show = book_consultation(api, designer, missed,
                                scheduled_start_at="2026-08-03T16:00:00.000Z",
                                scheduled_end_at="2026-08-03T17:00:00.000Z")
    dsg = designer_headers(designer["id"])
    owner = franchisee_headers(territory["id"])

    record_opening(api, designer, closed_out, label="First pass")
    complete_consultation(api, designer, closed_out)
    set_clock(api, "2026-08-03T16:30:00.000Z")
    assert validate_success(api.no_show_consultation(
        no_show["id"], dsg))["status"] == "NO_SHOW"

    corrective = validate_success(api.create_opening(
        f.opening_payload(closed_out["id"], label="Later re-measure"), dsg), 201)
    assert corrective["measure_status"] == "MEASURED"
    assert validate_success(api.get_consultation(
        closed_out["id"], dsg))["measured_opening_count"] == 2

    validate_error(api.create_opening(
        f.opening_payload(no_show["id"], label="Nobody home"), dsg),
        ERR_CONSULTATION_CLOSED, 409)

    assert validate_success(api.get_lead(
        kept["id"], owner))["status"] == "CONSULT_COMPLETE"
    assert validate_success(api.get_lead(
        missed["id"], owner))["status"] == "LOST"
    assert read_territory(api, territory)["open_leads_count"] == 1

    _rows, meta = validate_paginated(api.list_openings(
        dsg, consultation_id=no_show["id"]))
    assert_page_meta(meta, total_count=0)


def test_returning_a_kit_twice_is_refused_on_the_checkout_dimension(api):
    """The replay is refused by the check-out's own status while the kit is AVAILABLE.

    "Returning a kit is the moment lateness is priced, and everything about it is read
    from the logical clock at that instant."

    "The check-out must still be `OPEN`; a record already `RETURNED` or `LOST` yields
    `ERR_CHECKOUT_NOT_OPEN`."

    "If `returned_at` is at or before `due_at`, `days_late` is zero."

    Design: Corner/state_machines/returning_a_kit_twice_is_refused_on_the_checkout_dimension
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    kit = add_sample_kit(api, territory, kit_code="SHEERS-A",
                         replacement_value_cents=50000)
    lead = intake_lead(api, territory)
    consultation = book_consultation(
        api, designer, lead,
        scheduled_start_at="2026-08-05T14:00:00.000Z",
        scheduled_end_at="2026-08-05T15:00:00.000Z")
    checkout = checkout_kit(api, designer, kit, consultation,
                            "2026-08-02T09:00:00.000Z",
                            "2026-08-04T17:00:00.000Z")
    set_clock(api, "2026-08-04T10:00:00.000Z")

    returned = return_kit(api, designer, checkout)
    assert returned["status"] == "RETURNED"
    assert returned["days_late"] == 0
    assert returned["late_fee_cents"] == 0

    owner = franchisee_headers(territory["id"])
    assert validate_success(api.get_sample_kit(
        kit["id"], owner))["status"] == "AVAILABLE"
    validate_error(api.return_sample_checkout(
        checkout["id"], designer_headers(designer["id"])),
        ERR_CHECKOUT_NOT_OPEN, 409)

    replayed = validate_success(api.get_sample_kit(kit["id"], owner))
    assert replayed["loan_count"] == 1
    assert replayed["open_loan_count"] == 0

    counters = read_territory(api, territory)
    assert counters["available_kit_count"] == 1
    assert counters["on_loan_kit_count"] == 0
    assert counters["lost_kit_count"] == 0

    _rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner))
    assert_page_meta(meta, total_count=0)


def test_checking_out_an_on_loan_kit_reports_the_kit_state(api):
    """Kit availability outranks the hold-overlap test, so rule 22 answers first.

    "The kit must be `AVAILABLE` — `ON_LOAN` and `LOST` both yield
    `ERR_KIT_NOT_AVAILABLE` — and the appointment must still be `SCHEDULED`, since a
    closed file cannot take out samples, which is why `ERR_CONSULTATION_NOT_SCHEDULED`
    guards this operation as well as appointment close-out and no-show."

    "**Per-endpoint state preconditions** — the status checks described in §3, in the
    order given there: quote draft, presented and accepted checks, the revision cap,
    consultation status, kit availability, check-out openness, opening measure status,
    quote-has-openings, opening-already-ordered, the three vendor-order status checks,
    the install-job status check, and the three commissioning-status checks."

    Design: Corner/state_machines/checking_out_an_on_loan_kit_reports_the_kit_state_not_the_hold_clash
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    kit = add_sample_kit(api, territory, kit_code="SHEERS-A",
                         replacement_value_cents=50000)
    lead = intake_lead(api, territory)
    consultation = book_consultation(
        api, designer, lead,
        scheduled_start_at="2026-08-07T14:00:00.000Z",
        scheduled_end_at="2026-08-07T15:00:00.000Z")
    first = checkout_kit(api, designer, kit, consultation,
                         "2026-08-02T09:00:00.000Z",
                         "2026-08-06T17:00:00.000Z")
    assert first["status"] == "OPEN"

    # The requested hold sits inside the recorded one, so rules 22 and 43 both fail.
    validate_error(api.create_sample_checkout(
        f.sample_checkout_payload(kit["id"], consultation["id"],
                                  "2026-08-04T09:00:00.000Z",
                                  "2026-08-05T17:00:00.000Z"),
        designer_headers(designer["id"])), ERR_KIT_NOT_AVAILABLE, 409)

    owner = franchisee_headers(territory["id"])
    held = validate_success(api.get_sample_kit(kit["id"], owner))
    assert held["status"] == "ON_LOAN"
    assert held["loan_count"] == 1
    assert held["open_loan_count"] == 1

    rows, meta = validate_paginated(api.list_sample_checkouts(
        designer_headers(designer["id"]), sample_kit_id=kit["id"]))
    assert_page_meta(meta, total_count=1)
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "OPEN"

    counters = read_territory(api, territory)
    assert counters["available_kit_count"] == 0
    assert counters["on_loan_kit_count"] == 1


def test_ship_and_receive_out_of_order_each_report_their_own_gate(api):
    """The pipeline is linear: each premature trigger names the state it needed.

    "An order that is not `PLACED` yields `ERR_ORDER_NOT_SHIPPABLE`. A shipped order
    keeps occupying its production window, so shipping releases no capacity."

    "The franchise owner records the goods arriving, driving `SHIPPED → RECEIVED` and
    stamping `received_at`. An order that is not `SHIPPED` yields
    `ERR_ORDER_NOT_SHIPPED`."

    Design: Corner/state_machines/ship_and_receive_out_of_order_each_report_their_own_gate
    """
    world = single_opening_job(api, vendor_kwargs={"concurrent_capacity": 5},
                               stop_after="placed")
    territory, vendor, order = world["territory"], world["vendor"], world["order"]
    assert order["status"] == "PLACED"
    assert order["order_cost_cents"] == 2083

    validate_error(api.receive_vendor_order(
        order["id"], franchisee_headers(territory["id"])),
        ERR_ORDER_NOT_SHIPPED, 409)

    shipped = validate_success(api.ship_vendor_order(
        order["id"], vendor_rep_headers(vendor["id"])))
    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_at"] is not None

    validate_error(api.ship_vendor_order(
        order["id"], vendor_rep_headers(vendor["id"])),
        ERR_ORDER_NOT_SHIPPABLE, 409)

    # Shipping released nothing: the exposure still carries this order's cost.
    assert read_territory(api, territory)["open_order_exposure_cents"] == 2083

    received = receive_order(api, territory, order)
    assert received["status"] == "RECEIVED"
    assert received["received_at"] is not None
    assert read_territory(api, territory)["open_order_exposure_cents"] == 0

    # Neither refusal wrote anything on the order.
    final = read_order(api, territory, order["id"])
    assert final["remake_count"] == 0
    assert final["credit_scope"] == "NONE"


def test_a_completed_install_job_reports_the_job_dimension_for_every_trigger(api):
    """Sign-off locks the first dimension, and rule order hides the second one.

    "Commissioning, exception-raising and sign-off all require `install_status` to be
    `SCHEDULED`, reported as `ERR_INSTALL_JOB_NOT_SCHEDULED`. That check is made on the
    **first** dimension before anything on the second is examined, so a job that has
    already completed reports the job state rather than a commissioning state."

    "Sign-off stamps `completed_at` from the logical clock and sets `install_outcome` to
    `INSTALLED` on every opening in the order's `opening_ids` whose `install_outcome` is
    still `PENDING`."

    Design: Corner/state_machines/a_completed_install_job_reports_the_job_dimension_for_every_further_trigger
    """
    world = single_opening_job(api, vendor_kwargs={"concurrent_capacity": 5},
                               stop_after="scheduled")
    territory, designer = world["territory"], world["designer"]
    opening, job = world["opening"], world["install_job"]
    dsg = designer_headers(designer["id"])

    assert job["motorized_channel_count"] == 0
    assert job["commissioning_status"] == "NOT_REQUIRED"
    assert job["install_status"] == "SCHEDULED"

    signed = validate_success(api.complete_install_job(job["id"], dsg))
    assert signed["install_status"] == "COMPLETED"
    assert signed["completed_at"] is not None
    assert read_opening(api, designer,
                        opening["id"])["install_outcome"] == "INSTALLED"

    validate_error(api.complete_install_job(job["id"], dsg),
                   ERR_INSTALL_JOB_NOT_SCHEDULED, 409)
    validate_error(api.raise_install_exception(
        job["id"], f.exception_payload(opening["id"], "OBSTRUCTION"), dsg),
        ERR_INSTALL_JOB_NOT_SCHEDULED, 409)
    # Rule 30 answers first, so the NOT_REQUIRED commissioning state is never reached.
    validate_error(api.pair_commissioning(
        job["id"], f.pair_payload(1, "ALEXA"), dsg),
        ERR_INSTALL_JOB_NOT_SCHEDULED, 409)

    # The provisional basis already equalled the final one, so no true-up row.
    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], franchisee_headers(territory["id"])))
    assert_page_meta(meta, total_count=1)
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 273, 4960,
                        "quote_accepted", "QUOTE",
                        territory_id=territory["id"])

    settled = validate_success(api.get_install_job(job["id"], dsg))
    assert settled["exception_reason"] == "NONE"
    assert settled["liable_party"] == "NONE"
    assert settled["paired_channel_count"] == 0
    assert settled["commissioning_attempt_count"] == 0


def test_verify_before_pair_and_pair_on_a_non_motorized_job_differ(api):
    """Two jobs, two commissioning verdicts, both while the install dimension is fine.

    "A new job is stamped `install_status` `SCHEDULED`, and its
    `motorized_channel_count` is **frozen** at creation as the number of openings in the
    order's `opening_ids` whose `motorization_option` is anything other than `NONE`."

    "`commissioning_status` must be `PENDING` or `FAILED`; `NOT_REQUIRED` means the
    order carries no motorized channel at all, and `PAIRED` or `VERIFIED` mean pairing
    has already succeeded, so all three fail with `ERR_COMMISSIONING_NOT_APPLICABLE`."

    "Verification is the assigned designer's second commissioning action and requires
    `commissioning_status` to be `PAIRED`, or it fails with
    `ERR_COMMISSIONING_NOT_PAIRED`."

    Design: Corner/state_machines/verify_before_pair_and_pair_on_a_non_motorized_job_are_different_refusals
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    vendor = onboard_vendor(api, motorization_extra_days=3, cutoff_hour_utc=15,
                            concurrent_capacity=5,
                            supported_lift_systems=["CORDED", "MOTORIZED"],
                            supported_hub_platforms=["ALEXA"])
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    motorized = record_opening(api, designer, consultation, label="Motor bay",
                               room_type="LIVING_ROOM")
    corded = record_opening(api, designer, consultation, label="Corded bay",
                            room_type="OFFICE")
    motorized = configure_opening(api, designer, motorized,
                                  fabric_code="LT-SHEER",
                                  lift_system="MOTORIZED",
                                  motorization_option="BATTERY")
    corded = configure_opening(api, designer, corded, fabric_code="LT-SHEER",
                               lift_system="CORDED")
    assert motorized["list_price_cents"] == 17460
    assert corded["list_price_cents"] == 4960

    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    accept_quote(api, designer, quote)
    motor_order = place_order(api, territory, quote, [motorized["id"]], vendor)
    corded_order = place_order(api, territory, quote, [corded["id"]], vendor)
    for order in (motor_order, corded_order):
        ship_order(api, vendor, order)
        receive_order(api, territory, order)

    motor_job = schedule_install(api, territory, motor_order, designer,
                                 scheduled_start_at="2026-08-25T09:00:00.000Z",
                                 scheduled_end_at="2026-08-25T11:00:00.000Z")
    corded_job = schedule_install(api, territory, corded_order, designer,
                                  scheduled_start_at="2026-08-25T13:00:00.000Z",
                                  scheduled_end_at="2026-08-25T15:00:00.000Z")
    assert motor_job["motorized_channel_count"] == 1
    assert motor_job["commissioning_status"] == "PENDING"
    assert corded_job["motorized_channel_count"] == 0
    assert corded_job["commissioning_status"] == "NOT_REQUIRED"

    dsg = designer_headers(designer["id"])
    validate_error(api.verify_commissioning(motor_job["id"], dsg),
                   ERR_COMMISSIONING_NOT_PAIRED, 409)
    validate_error(api.pair_commissioning(
        corded_job["id"], f.pair_payload(1, "ALEXA"), dsg),
        ERR_COMMISSIONING_NOT_APPLICABLE, 409)

    # Neither refusal touched the first dimension, and no counter moved.
    settled_motor = validate_success(api.get_install_job(motor_job["id"], dsg))
    settled_corded = validate_success(api.get_install_job(corded_job["id"], dsg))
    assert settled_motor["install_status"] == "SCHEDULED"
    assert settled_corded["install_status"] == "SCHEDULED"
    assert settled_motor["commissioning_attempt_count"] == 0
    assert settled_corded["paired_channel_count"] == 0


def test_superseding_a_quote_hands_its_openings_back_to_the_newer_quote(api):
    """A second quote releases and re-sweeps the same opening inside one request.

    "Any earlier quote on that consultation still in `DRAFT` moves `DRAFT →
    SUPERSEDED`, and any earlier quote still in `PRESENTED` — provided the logical clock
    is strictly before its `expires_at` — moves `PRESENTED → SUPERSEDED` and has its
    `expires_at` cleared to null."

    "In either case every opening carrying the superseded quote's id moves `QUOTED →
    CONFIGURED` with its `quote_id` cleared to null, which is exactly what makes those
    openings available for the superseding quote to sweep in."

    "A `QUOTED` opening fails with `ERR_OPENING_NOT_MEASURED` — the quote holding it
    must be superseded first so the opening detaches — and a `REMEASURE_REQUIRED`
    opening fails with the same error permanently."

    Design: Corner/state_machines/superseding_a_quote_hands_its_openings_back_to_the_newer_quote
    """
    world = single_opening_job(api, stop_after="presented")
    territory, designer = world["territory"], world["designer"]
    consultation, opening = world["consultation"], world["opening"]
    first = world["quote"]
    dsg = designer_headers(designer["id"])

    assert first["status"] == "PRESENTED"
    assert read_opening(api, designer, opening["id"])["measure_status"] == "QUOTED"
    validate_error(api.configure_opening(
        opening["id"], f.configuration_payload(fabric_code="CL-LINEN",
                                               lift_system="CORDLESS"), dsg),
        ERR_OPENING_NOT_MEASURED, 409)

    second = build_quote(api, designer, consultation)
    assert second["status"] == "DRAFT"

    superseded = read_quote(api, territory, first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["expires_at"] is None

    # Released and re-attached inside that one request, so never observably CONFIGURED.
    swept = read_opening(api, designer, opening["id"])
    assert swept["quote_id"] == second["id"]
    assert swept["measure_status"] == "QUOTED"
    validate_error(api.configure_opening(
        opening["id"], f.configuration_payload(fabric_code="CL-LINEN",
                                               lift_system="CORDLESS"), dsg),
        ERR_OPENING_NOT_MEASURED, 409)

    # The superseded quote keeps the money it was presented for.
    assert superseded["subtotal_cents"] == 4960
    assert superseded["install_fee_cents"] == 10000
    assert superseded["total_cents"] == 14960

    fresh = read_quote(api, territory, second["id"])
    for money in ("subtotal_cents", "install_fee_cents",
                  "pre_discount_total_cents", "discount_cents", "total_cents",
                  "net_sales_cents"):
        assert fresh[money] == 0, money

    rows, meta = validate_paginated(api.list_quotes(
        dsg, consultation_id=consultation["id"]))
    assert_page_meta(meta, total_count=2)
    assert {row["status"] for row in rows} == {"SUPERSEDED", "DRAFT"}


def _received_order_placed_on_the_fifth(api):
    """One accepted 4960-cent opening placed at 09:00 on 2026-08-05, then received."""
    world = single_opening_job(api, vendor_kwargs={"cutoff_hour_utc": 15,
                                                  "concurrent_capacity": 5},
                               stop_after="accepted")
    set_clock(api, "2026-08-05T09:00:00.000Z")
    order = place_order(api, world["territory"], world["quote"],
                        [world["opening"]["id"]], world["vendor"])
    ship_order(api, world["vendor"], order)
    world["order"] = receive_order(api, world["territory"], order)
    world["placement"] = order
    return world


def test_a_replacement_remake_returns_the_order_to_placed_in_one_request(api):
    """One POST walks the order out of RECEIVED and back to PLACED on a new window.

    "The observable outcome is therefore `RECEIVED → REMAKE_REQUESTED → PLACED` with
    `remake_count` one higher: `placed_at` is re-stamped from the logical clock,
    `shipped_at` and `received_at` are cleared to null, the lead-time calculation is
    re-run and now applies the four-day expedite before the five-day floor, storing a
    fresh `effective_placement_date`, `lead_time_days` and `promised_ship_date`, and the
    vendor's `open_order_count` and the territory's `open_order_exposure_cents` rise
    again by the order's cost."

    "A `SHARED_50_50` vendor's target is half of `remake_cost_cents` rounded **down** to
    a whole cent, and the territory's target is whatever remains — so on an odd cost of
    7403 cents the vendor takes 3701 and the territory 3702, the extra cent landing on
    the territory rather than on the manufacturer."

    "Whenever `territory_absorbed_cents` is greater than zero, a ledger row of type
    `REMAKE_CHARGEBACK` is appended for that amount, with `basis_cents` equal to
    `remake_cost_cents`, `source_entity_type` `VENDOR_ORDER` and `memo`
    `remake_replacement`, and the amount is added to the territory's
    `remake_chargeback_cents`."

    Design: Corner/state_machines/a_replacement_remake_returns_the_order_to_placed_inside_one_request
    """
    world = _received_order_placed_on_the_fifth(api)
    territory, designer = world["territory"], world["designer"]
    order, opening = world["order"], world["opening"]

    # Hour 9 is below the cutoff of 15, so the placement keeps its own date.
    assert world["placement"]["effective_placement_date"] == "2026-08-05"
    assert world["placement"]["lead_time_days"] == 10
    assert world["placement"]["promised_ship_date"] == "2026-08-15"
    assert order["order_cost_cents"] == 2083

    set_clock(api, "2026-08-20T09:00:00.000Z")
    remade = request_remake(api, territory, order, credit_scope="REPLACEMENT")

    assert remade["status"] == "PLACED"
    assert remade["remake_count"] == 1
    assert remade["credit_scope"] == "REPLACEMENT"
    assert remade["shipped_at"] is None
    assert remade["received_at"] is None
    assert remade["lead_time_days"] == 6
    assert remade["effective_placement_date"] == "2026-08-20"
    assert remade["promised_ship_date"] == "2026-08-26"

    assert remade["remake_cost_cents"] == 2083
    assert remade["vendor_absorbed_cents"] == 1041
    assert remade["territory_absorbed_cents"] == 1042
    assert remade["customer_absorbed_cents"] == 0
    assert_remake_buckets_sum(remade)

    owner = franchisee_headers(territory["id"])
    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMAKE_CHARGEBACK"))
    assert_page_meta(meta, total_count=1)
    assert_ledger_entry(rows[0], "REMAKE_CHARGEBACK", 1042, 2083,
                        "remake_replacement", "VENDOR_ORDER",
                        source_entity_id=order["id"],
                        territory_id=territory["id"])

    counters = read_territory(api, territory)
    assert counters["remake_chargeback_cents"] == 1042
    assert counters["net_sales_cents"] == 4960
    assert counters["royalty_accrued_cents"] == 273
    assert counters["open_order_exposure_cents"] == 2083
    assert read_opening(api, designer, opening["id"])["credited"] is False


def test_the_remake_loop_terminates_at_the_declared_order_ceiling(api):
    """Two cycles are legal; the third is refused on the counter, not on the state.

    "The order's `remake_count` must be strictly less than two, the cap on remake cycles
    per order, or the request fails with `ERR_REMAKE_LIMIT_REACHED`."

    "Each remake is allocated on its own — prior remakes on the same order do not change
    the split — and the four stored fields hold the **most recent** allocation only."

    Design: Corner/state_machines/the_remake_loop_terminates_at_the_declared_order_ceiling
    """
    world = _received_order_placed_on_the_fifth(api)
    territory, designer = world["territory"], world["designer"]
    vendor, order, opening = world["vendor"], world["order"], world["opening"]

    for _cycle in range(2):
        request_remake(api, territory, order, credit_scope="REPLACEMENT")
        ship_order(api, vendor, order)
        receive_order(api, territory, order)

    settled = read_order(api, territory, order["id"])
    assert settled["status"] == "RECEIVED"
    assert settled["remake_count"] == 2
    assert settled["credit_scope"] == "REPLACEMENT"
    assert settled["remake_cost_cents"] == 2083
    assert settled["vendor_absorbed_cents"] == 1041
    assert settled["territory_absorbed_cents"] == 1042

    owner = franchisee_headers(territory["id"])
    for scope in ("REPLACEMENT", "FULL_CREDIT"):
        validate_error(api.remake_vendor_order(
            order["id"], f.remake_payload(scope), owner),
            ERR_REMAKE_LIMIT_REACHED, 409)

    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMAKE_CHARGEBACK"))
    assert_page_meta(meta, total_count=2)
    assert [row["amount_cents"] for row in rows] == [1042, 1042]
    assert read_territory(api, territory)["remake_chargeback_cents"] == 2084
    assert read_territory(api, territory)["net_sales_cents"] == 4960
    assert read_opening(api, designer, opening["id"])["credited"] is False


def test_a_no_show_frees_the_weekly_slot_and_promotes_one_queued_lead(api):
    """The promotion is driven by a lead leaving the open set, not by any operator.

    "When a lead leaves that pair — reaching `CONVERTED` because a quote for it was
    accepted, or `LOST` because its appointment was a no-show or its presented quote
    expired — the count drops by one and the territory's `version` increments, and that
    freed unit of capacity immediately promotes a queued lead."

    "That lead moves `QUEUED → ROUTED` with its `territory_id` and `routed_at` stamped,
    and the territory's `open_leads_count` and `version` each rise by one again. A second
    queued lead stays queued."

    Design: Corner/state_machines/a_no_show_frees_the_weekly_slot_and_promotes_exactly_one_queued_lead
    """
    territory = charter_territory(api, lead_capacity_per_week=1)
    designer = hire_designer(api, territory)
    routed = intake_lead(api, territory, customer_name="Ana Ruiz",
                         source="NATIONAL_CALL_CENTER",
                         requested_at="2026-08-01T08:00:00.000Z")
    waiting = intake_lead(api, territory, customer_name="Bo Chen",
                          source="WEB_FORM",
                          requested_at="2026-08-01T09:00:00.000Z")
    last = intake_lead(api, territory, customer_name="Cy Doyle",
                       source="REFERRAL",
                       requested_at="2026-08-01T10:00:00.000Z")
    owner = franchisee_headers(territory["id"])
    assert routed["status"] == "ROUTED"
    assert waiting["status"] == "QUEUED"
    assert waiting["territory_id"] is None
    assert last["status"] == "QUEUED"

    consultation = book_consultation(api, designer, routed)
    set_clock(api, "2026-08-03T15:30:00.000Z")
    missed = validate_success(api.no_show_consultation(
        consultation["id"], designer_headers(designer["id"])))
    assert missed["status"] == "NO_SHOW"

    assert validate_success(api.get_lead(routed["id"], owner))["status"] == "LOST"

    promoted = validate_success(api.get_lead(waiting["id"], owner))
    assert promoted["status"] == "ROUTED"
    assert promoted["territory_id"] == territory["id"]
    assert_instant_equals(promoted["routed_at"], "2026-08-03T15:30:00.000Z",
                          "lead.routed_at")

    still_queued = validate_success(api.get_lead(last["id"], owner))
    assert still_queued["status"] == "QUEUED"
    assert still_queued["territory_id"] is None

    counters = read_territory(api, territory)
    assert counters["open_leads_count"] == 1
    assert counters["lead_capacity_per_week"] == 1

    rows, meta = validate_paginated(api.list_leads(owner, status="QUEUED"))
    assert_page_meta(meta, total_count=1)
    assert rows[0]["id"] == last["id"]
