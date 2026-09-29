"""Validation rules read at their edges: to the cent, to the whole minute, to the
whole day, and against the entity that actually owns the limit.

Each test drives one rule to the point where it just holds and to the point where
it just fails, and checks that the refusal left nothing behind.
"""

import pytest

from test_helpers import (
    MAX_COMMITTED_MINUTES,
    MISSING_PROJECT_ID,
    NETWORK_MANAGER,
    PROJECT_COORDINATOR,
    ApiErrorId,
    AssignmentStatus,
    ChangeOrderDecision,
    ChangeOrderStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    PermitStatus,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_units,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    validate_error,
)

# A 420.00-unit FLOOR-DIRECT sale in a jurisdiction whose multiplier is 1.00.
QUOTED = 171020
DEPOSIT = 51306


def _sold_project(api):
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    base["project"] = fx.sell_project(api, base, estimated_units=420.00)
    return base


@pytest.mark.parametrize("amount_cents", [DEPOSIT - 1, DEPOSIT + 1])
def test_a_deposit_one_cent_out_either_way_is_refused(api, amount_cents):
    """Underpayment and overpayment are symmetric: both miss the required amount
    and both answer with the same identifier.

    PRD 2.8 rank 34: "A deposit payment's `amount_cents` equals the project's
    `deposit_required_cents` exactly — otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`
    (422)."

    Design: Corner/validations/deposit_must_match_the_required_amount_to_the_cent
    """
    ctx = _sold_project(api)
    project = ctx["project"]
    assert_money(project["deposit_required_cents"], DEPOSIT,
                 "deposit_required_cents")

    response = api.pay_deposit(project["id"], f.deposit_payload(amount_cents),
                               make_customer_headers(ctx["customer"]["id"]))
    validate_error(response, ApiErrorId.DEPOSIT_AMOUNT_MISMATCH)


def test_two_refused_payments_leave_the_project_payable(api):
    """Neither near miss moves a bucket or a version, and the exact amount is still
    accepted afterwards.

    PRD 3.3: "A successful payment moves `financial_status` from `QUOTED` to
    `DEPOSIT_HELD`, sets `deposit_paid_cents` and `deposit_held_cents` both to the
    paid amount, re-checks the conservation identity of §2.10, and increments the
    project's `version`."

    Design: Corner/validations/deposit_must_match_the_required_amount_to_the_cent
    """
    ctx = _sold_project(api)
    project = ctx["project"]
    headers = make_customer_headers(ctx["customer"]["id"])

    for amount in (DEPOSIT - 1, DEPOSIT + 1):
        validate_error(
            api.pay_deposit(project["id"], f.deposit_payload(amount), headers),
            ApiErrorId.DEPOSIT_AMOUNT_MISMATCH,
        )
    refused = fx.read_project(api, project["id"])
    assert_project_dimensions(refused, financial=FinancialStatus.QUOTED)
    assert_deposit_buckets(refused, paid=0, held=0, applied=0, refunded=0,
                           forfeited=0)
    assert_version(refused, project["version"], "project")

    paid = get_success_data(
        api.pay_deposit(project["id"], f.deposit_payload(DEPOSIT), headers)
    )
    assert_project_dimensions(paid, financial=FinancialStatus.DEPOSIT_HELD)
    assert_deposit_buckets(paid, paid=DEPOSIT, held=DEPOSIT, applied=0,
                           refunded=0, forfeited=0)
    assert_version(paid, project["version"] + 1, "project")


def test_an_unknown_project_in_the_path_outranks_the_deposit_amount(api):
    """A deposit sent to an id that was never stored answers on the path, even
    though its amount would also have failed the amount rule.

    PRD 2.8 rank 6: "Every identifier appearing in the URL path resolves to a
    stored row, checked left to right — otherwise that entity's not-found code
    (404)."

    Design: Corner/validations/unknown_project_in_the_path_is_rejected_before_the_deposit_amount
    """
    ctx = _sold_project(api)

    response = api.pay_deposit(MISSING_PROJECT_ID, f.deposit_payload(1),
                               make_customer_headers(ctx["customer"]["id"]))
    body = validate_error(response, ApiErrorId.PROJECT_NOT_FOUND)
    assert body["message"], "an error body must carry a human-readable message"


def test_the_misaddressed_deposit_leaves_the_real_project_alone(api):
    """The project that does exist keeps its version, its money dimension and its
    empty buckets.

    PRD 3.3: "The household pays the deposit by supplying `amount_cents`, which
    must equal `deposit_required_cents` **exactly**: both underpayment and
    overpayment are rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Corner/validations/unknown_project_in_the_path_is_rejected_before_the_deposit_amount
    """
    ctx = _sold_project(api)
    project = ctx["project"]

    validate_error(
        api.pay_deposit(MISSING_PROJECT_ID, f.deposit_payload(1),
                        make_customer_headers(ctx["customer"]["id"])),
        ApiErrorId.PROJECT_NOT_FOUND,
    )

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED)
    assert_deposit_buckets(after, paid=0, held=0, applied=0, refunded=0,
                           forfeited=0)
    assert_money(after["quoted_labor_cents"], QUOTED, "quoted_labor_cents")


def _firm_with_two_long_windows(api):
    """One firm holding two 2160-minute windows days apart, and a third deposited
    project waiting for a window of its own."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    base.update(fx.activated_installer(api, base["jurisdiction"]["id"]))
    base["projects"] = []
    for address in ("1 Cap Way", "2 Cap Way", "3 Cap Way"):
        project = fx.sell_project(api, base, estimated_units=420.00,
                                  site_address=address)
        base["projects"].append(fx.pay_deposit(api, project,
                                               base["customer"]["id"]))

    first, second, _third = base["projects"]
    installer_id = base["installer"]["id"]
    base["first_assignment"] = fx.hold_assignment(
        api, first["id"], installer_id,
        window_start="2026-09-01T00:00:00.000Z",
        window_end="2026-09-02T12:00:00.000Z")
    base["second_assignment"] = fx.hold_assignment(
        api, second["id"], installer_id,
        window_start="2026-09-03T00:00:00.000Z",
        window_end="2026-09-04T12:00:00.000Z")
    base["installer"] = fx.read_installer(api, installer_id)
    return base


def test_capacity_is_judged_on_the_sum_of_every_committed_window(api):
    """Two windows that were each legal on their own leave 480 minutes of headroom,
    so a third window of 600 minutes is refused on the aggregate.

    PRD 3.6: "Next, the firm's `committed_minutes` plus the new `duration_minutes`
    must not exceed 4800 minutes, or the answer is
    `ERR_INSTALLER_CAPACITY_EXCEEDED`; note that `committed_minutes` counts
    `COMPLETED` rows as well as live ones, so the cap is a lifetime workload
    ceiling rather than a rolling one."

    Design: Corner/validations/installer_capacity_is_an_aggregate_over_every_live_assignment
    """
    ctx = _firm_with_two_long_windows(api)
    third = ctx["projects"][2]

    assert ctx["first_assignment"]["duration_minutes"] == 2160
    assert ctx["second_assignment"]["duration_minutes"] == 2160
    assert_committed_minutes(ctx["installer"], 4320)

    response = api.create_assignment(
        f.assignment_payload(third["id"], ctx["installer"]["id"],
                             fx.project_version(api, third["id"]),
                             window_start="2026-09-05T00:00:00.000Z",
                             window_end="2026-09-05T10:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_CAPACITY_EXCEEDED)

    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 4320)
    refused = fx.read_project(api, third["id"])
    assert_project_dimensions(refused, fulfillment=FulfillmentStatus.MEASURED)
    assert_version(refused, third["version"], "the refused project")


def test_a_window_that_lands_exactly_on_the_ceiling_is_accepted(api):
    """Retried at 480 minutes the same booking succeeds and takes the firm to
    exactly 4800 committed minutes, so the ceiling is inclusive.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`,
    increases the installer's `committed_minutes` by `duration_minutes`, drives the
    project `MEASURED → SCHEDULED`, and increments both the project's and the
    installer's `version`."

    Design: Corner/validations/installer_capacity_is_an_aggregate_over_every_live_assignment
    """
    ctx = _firm_with_two_long_windows(api)
    third = ctx["projects"][2]

    assignment = fx.hold_assignment(
        api, third["id"], ctx["installer"]["id"], third["version"],
        window_start="2026-09-05T00:00:00.000Z",
        window_end="2026-09-05T08:00:00.000Z")

    assert assignment["duration_minutes"] == 480
    assert assignment["status"] == AssignmentStatus.HELD
    installer = fx.read_installer(api, ctx["installer"]["id"])
    assert_committed_minutes(installer, MAX_COMMITTED_MINUTES)
    assert_project_dimensions(fx.read_project(api, third["id"]),
                              fulfillment=FulfillmentStatus.SCHEDULED,
                              financial=FinancialStatus.DEPOSIT_HELD)


def _one_firm_two_counties(api):
    """A firm licensed in its home county only, with a deposited project in a
    county that demands a licence and another in a county that does not."""
    category = fx.create_category(api, f.service_category_payload())
    home = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    open_county = fx.create_jurisdiction(api, f.unlicensed_jurisdiction_payload())
    licensed_county = fx.create_jurisdiction(api, f.licensed_jurisdiction_payload())
    customer = fx.create_customer(api, open_county["id"],
                                  f.customer_payload(open_county["id"]))
    base = {"category": category, "jurisdiction": home, "customer": customer}
    base.update(fx.activated_installer(api, home["id"]))

    projects = {}
    for key, jurisdiction, address in (
            ("licensed", licensed_county, "4 Licence Row"),
            ("open", open_county, "3 Open Row")):
        project = fx.sell_project(api, base, estimated_units=420.00,
                                  jurisdiction=jurisdiction, site_address=address)
        projects[key] = fx.pay_deposit(api, project, customer["id"])
    base["projects"] = projects
    base["open_county"] = open_county
    base["licensed_county"] = licensed_county
    return base


def test_the_licence_rule_bites_only_where_the_county_demands_a_licence(api):
    """The same uncredentialed firm is refused in the county that requires a trade
    licence, and the refusal leaves both the project and the firm untouched.

    PRD 2.8 rank 17: "Whenever the jurisdiction's `license_required` is true, the
    installer holds a credential whose `verification_status` is `VERIFIED` for that
    project's `jurisdiction_id` and for the service category's `trade_code` —
    otherwise `ERR_INSTALLER_NOT_LICENSED` (409)."

    Design: Corner/validations/licence_check_applies_only_where_the_jurisdiction_requires_a_licence
    """
    ctx = _one_firm_two_counties(api)
    project = ctx["projects"]["licensed"]
    assert ctx["licensed_county"]["license_required"] is True

    response = api.create_assignment(
        f.assignment_payload(project["id"], ctx["installer"]["id"],
                             project["version"],
                             window_start="2026-09-01T08:00:00.000Z",
                             window_end="2026-09-01T16:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_NOT_LICENSED)

    assert_project_dimensions(fx.read_project(api, project["id"]),
                              fulfillment=FulfillmentStatus.MEASURED)
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 0)


def test_the_identical_booking_is_accepted_where_no_licence_is_demanded(api):
    """In the county whose `license_required` is false the firm needs no credential
    at all, and only that accepted window is counted against its capacity.

    PRD 3.1: "`license_required`, which defaults to true, decides whether a
    verified trade licence is demanded at all."

    Design: Corner/validations/licence_check_applies_only_where_the_jurisdiction_requires_a_licence
    """
    ctx = _one_firm_two_counties(api)
    project = ctx["projects"]["open"]
    assert ctx["open_county"]["license_required"] is False

    assignment = fx.hold_assignment(
        api, project["id"], ctx["installer"]["id"], project["version"],
        window_start="2026-09-03T08:00:00.000Z",
        window_end="2026-09-03T16:00:00.000Z")

    assert assignment["status"] == AssignmentStatus.HELD
    assert assignment["duration_minutes"] == 480
    assert_project_dimensions(fx.read_project(api, project["id"]),
                              fulfillment=FulfillmentStatus.SCHEDULED)
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 480)


LEAD_TIME_SLOT = ("2026-08-04T00:00:00.000Z", "2026-08-04T08:00:00.000Z")


def _issued_permit(api):
    """A retailer-pulled permit already issued in a county that inspects, with the
    clock still at the programme default."""
    return fx.permit_issued_project(api, 25000, "2026-08-03T00:00:00.000Z",
                                    reference="PA-1001")


def test_a_slot_two_whole_days_out_misses_the_lead_time_floor(api):
    """With a lead time of three whole days a slot on the third of August is one day
    short, and the refusal books nothing.

    PRD 3.5: "The lead-time floor requires `inspection_slot_start` to be at or after
    the current logical-clock value advanced by the jurisdiction's
    `inspection_lead_days` whole days; a nearer slot is refused with
    `ERR_INSPECTION_LEAD_TIME`."

    Design: Corner/validations/inspection_slot_must_respect_the_jurisdiction_lead_time
    """
    ctx = _issued_permit(api)
    project = ctx["project"]
    assert project["permit_status"] == PermitStatus.ISSUED
    assert ctx["jurisdiction"]["inspection_lead_days"] == 3

    response = api.reserve_inspection_slot(
        project["id"],
        f.inspection_slot_payload("2026-08-03T09:00:00.000Z",
                                  "2026-08-03T17:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSPECTION_LEAD_TIME)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, permit=PermitStatus.ISSUED)
    assert after["inspection_slot_start"] is None
    assert after["inspection_slot_end"] is None


def test_a_slot_that_ends_when_it_starts_is_refused_by_the_same_rule(api):
    """An empty interval far beyond the lead time is still refused, because the end
    must be strictly after the start.

    PRD 2.8 rank 26: "A requested inspection slot begins at least the jurisdiction's
    `inspection_lead_days` whole days after the logical clock, inclusive, and
    `inspection_slot_end` is strictly after `inspection_slot_start` — otherwise
    `ERR_INSPECTION_LEAD_TIME` (422)."

    Design: Corner/validations/inspection_slot_must_respect_the_jurisdiction_lead_time
    """
    ctx = _issued_permit(api)
    project = ctx["project"]

    response = api.reserve_inspection_slot(
        project["id"],
        f.inspection_slot_payload("2026-08-06T09:00:00.000Z",
                                  "2026-08-06T09:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSPECTION_LEAD_TIME)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, permit=PermitStatus.ISSUED)
    assert after["inspection_slot_start"] is None


def test_a_slot_exactly_three_whole_days_out_is_booked(api):
    """Midnight on the fourth of August is exactly three whole days after the clock,
    which the inclusive floor admits.

    PRD 3.5: "A successful reservation records both instants and moves
    `permit_status` to `INSPECTION_SCHEDULED`."

    Design: Corner/validations/inspection_slot_must_respect_the_jurisdiction_lead_time
    """
    ctx = _issued_permit(api)
    project = ctx["project"]

    booked = get_success_data(
        api.reserve_inspection_slot(project["id"],
                                    f.inspection_slot_payload(*LEAD_TIME_SLOT),
                                    PROJECT_COORDINATOR)
    )

    assert_project_dimensions(booked, permit=PermitStatus.INSPECTION_SCHEDULED)
    assert_instant(booked["inspection_slot_start"], LEAD_TIME_SLOT[0],
                   "inspection_slot_start")
    assert_instant(booked["inspection_slot_end"], LEAD_TIME_SLOT[1],
                   "inspection_slot_end")
    assert booked["inspection_attempt_count"] == 0
    assert_money(booked["permit_fee_cents_billed"], 25000,
                 "permit_fee_cents_billed")


def _thin_cover_firm(api):
    """An admitted firm whose liability limit is half of what the project's county
    demands, and one deposited project there."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.insured_jurisdiction_payload())
    jurisdiction_id = base["jurisdiction"]["id"]
    base.update(fx.activated_installer(
        api, jurisdiction_id,
        installer_payload=f.installer_payload(
            legal_name="Thin Cover Flooring LLC",
            contact_email="ops@thincover.example",
            liability_coverage_cents=50000000),
        credential_payload=f.credential_payload(
            jurisdiction_id, license_number="FL-77004",
            permit_pulling_authorized=False),
    ))
    project = fx.sell_project(api, base, estimated_units=420.00,
                              site_address="5 Cover Court")
    base["project"] = fx.pay_deposit(api, project, base["customer"]["id"])
    return base


def test_the_insurance_floor_is_read_from_the_projects_own_county(api):
    """The firm's row is perfectly valid in isolation; the booking fails only
    because the county it would work in demands twice the cover.

    PRD 2.8 rank 19: "`insurance_expires_on` is strictly after the logical clock and
    `liability_coverage_cents` is at least the jurisdiction's
    `min_liability_coverage_cents` — otherwise `ERR_INSURANCE_INSUFFICIENT` (409)."

    Design: Corner/validations/insurance_floor_is_read_from_the_projects_jurisdiction
    """
    ctx = _thin_cover_firm(api)
    project = ctx["project"]
    assert_money(ctx["installer"]["liability_coverage_cents"], 50000000,
                 "liability_coverage_cents")
    assert_money(ctx["jurisdiction"]["min_liability_coverage_cents"], 100000000,
                 "min_liability_coverage_cents")

    response = api.create_assignment(
        f.assignment_payload(project["id"], ctx["installer"]["id"],
                             project["version"],
                             window_start="2026-09-01T08:00:00.000Z",
                             window_end="2026-09-01T16:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSURANCE_INSUFFICIENT)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
    assert_version(after, project["version"], "the refused project")
    assert ctx["installer"]["status"] == InstallerStatus.ACTIVE


def test_raising_the_cover_on_the_firm_alone_unblocks_the_booking(api):
    """Amending the installer's liability limit is enough: the project never
    changed, so the retry reuses the same concurrency token.

    PRD 3.2: "A firm's `contact_email`, `liability_coverage_cents` and
    `insurance_expires_on` may be amended later; each amendment bumps the firm's
    `version` and does **not** re-validate assignments already on the books,
    because the insurance test is applied at the moment a window is held and not
    retroactively."

    Design: Corner/validations/insurance_floor_is_read_from_the_projects_jurisdiction
    """
    ctx = _thin_cover_firm(api)
    project = ctx["project"]
    installer_id = ctx["installer"]["id"]

    validate_error(
        api.create_assignment(
            f.assignment_payload(project["id"], installer_id, project["version"],
                                 window_start="2026-09-01T08:00:00.000Z",
                                 window_end="2026-09-01T16:00:00.000Z"),
            PROJECT_COORDINATOR),
        ApiErrorId.INSURANCE_INSUFFICIENT,
    )

    amended = get_success_data(
        api.patch_installer(installer_id,
                            {"liability_coverage_cents": 150000000},
                            NETWORK_MANAGER)
    )
    assert_money(amended["liability_coverage_cents"], 150000000,
                 "liability_coverage_cents")
    assert amended["status"] == InstallerStatus.ACTIVE

    assignment = get_success_data(
        api.create_assignment(
            f.assignment_payload(project["id"], installer_id, project["version"],
                                 window_start="2026-09-01T08:00:00.000Z",
                                 window_end="2026-09-01T16:00:00.000Z"),
            PROJECT_COORDINATOR)
    )
    assert assignment["status"] == AssignmentStatus.HELD
    assert_project_dimensions(fx.read_project(api, project["id"]),
                              fulfillment=FulfillmentStatus.SCHEDULED)


def _credit_sent_to_the_household(api):
    """A credit of 188.00 primary units, priced and sent for the household to
    answer. The cap on a quote of 171020 is -85510, so this one clears it."""
    ctx = _sold_project(api)
    project = ctx["project"]
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")

    ctx["change_order"] = fx.raise_change_order(api, project["id"],
                                               [f.primary_line(-188.00)],
                                               expected_project_version=project["version"])
    ctx["submitted"] = get_success_data(
        api.submit_change_order(ctx["change_order"]["id"], PROJECT_COORDINATOR)
    )
    return ctx


def test_a_credit_inside_half_the_frozen_quote_is_priced_and_sent(api):
    """A credit of 84694 cents sits above the -85510 floor, so it prices at DRAFT
    and reaches the household.

    PRD 3.4: "The cap is measured against the frozen quote, not against the current
    balance, so it does not move as the project accumulates upcharges."

    Design: Corner/validations/credit_cap_is_checked_against_the_freshly_priced_lines
    """
    ctx = _credit_sent_to_the_household(api)

    # -188.00 * 425 * 1.00 * 1.06.
    assert_money(ctx["change_order"]["upcharge_cents"], -84694, "upcharge_cents")
    assert ctx["change_order"]["status"] == ChangeOrderStatus.DRAFT
    assert_units(ctx["change_order"]["net_primary_units_delta"], -188.00,
                 "net_primary_units_delta")
    assert ctx["submitted"]["status"] == ChangeOrderStatus.PENDING_CUSTOMER
    assert_project_dimensions(fx.read_project(api, ctx["project"]["id"]),
                              fulfillment=FulfillmentStatus.CHANGE_PENDING)


def test_a_revision_that_deepens_the_credit_past_the_cap_is_refused(api):
    """The replacement lines are priced first and then capped: 85595 cents of credit
    is more than half the frozen quote, so the revision is refused.

    PRD 3.4: "A change order whose `upcharge_cents` is below the negative of the
    project's `quoted_labor_cents` multiplied by 0.50 and rounded half up — that is,
    a credit larger than half the frozen quote — is refused on submission with
    `ERR_CREDIT_EXCEEDS_CAP`."

    Design: Corner/validations/credit_cap_is_checked_against_the_freshly_priced_lines
    """
    ctx = _credit_sent_to_the_household(api)
    change_order_id = ctx["change_order"]["id"]

    returned = get_success_data(
        api.decide_change_order(
            change_order_id,
            f.decision_payload(ChangeOrderDecision.REQUEST_REVISION,
                               revision_note="Keep the hall run in scope"),
            make_customer_headers(ctx["customer"]["id"]))
    )
    assert returned["status"] == ChangeOrderStatus.REVISION_REQUESTED

    response = api.submit_change_order(
        change_order_id, PROJECT_COORDINATOR,
        f.submit_payload([f.primary_line(-190.00)]))
    validate_error(response, ApiErrorId.CREDIT_EXCEEDS_CAP)

    after = get_success_data(api.get_change_order(change_order_id,
                                                  PROJECT_COORDINATOR))
    assert after["status"] == ChangeOrderStatus.REVISION_REQUESTED
    assert_money(after["upcharge_cents"], -84694, "upcharge_cents")
    assert after["revision_count"] == 0
    assert_project_dimensions(fx.read_project(api, ctx["project"]["id"]),
                              fulfillment=FulfillmentStatus.CHANGE_PENDING)
