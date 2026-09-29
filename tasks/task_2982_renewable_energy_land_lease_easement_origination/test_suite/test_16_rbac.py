"""Role claims: two closed operations, one shared write, and both four-eyes limbs."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_SEGREGATION_OF_DUTIES, ERR_UNAUTHORIZED
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_null,
    assert_page_meta,
    assert_status,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import booking_payload, exercise_payload, parcel_payload
from test_helpers.fixtures import (
    accept_option,
    book_site_access,
    cancel_booking,
    client,
    draft_option,
    execute_option,
    ledger_rows,
    parcels_page,
    raise_curative,
    read_booking,
    read_curative,
    read_landowner,
    read_option,
    read_parcel,
    register_landowner,
    register_parcel,
    send_option,
)
from test_helpers.test_users import (
    LAND_AGENT,
    PAYMENT_ADMIN,
    PORTFOLIO_MANAGER,
    PORTFOLIO_MANAGER_2,
    PORTFOLIO_MANAGER_USER_ID,
    TITLE_COUNSEL,
    TITLE_COUNSEL_2,
    TITLE_COUNSEL_USER_ID,
)

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"

CLEAN_INPUTS = {
    "county_fips": CLEAN_COUNTY,
    "gross_acres": 200.00,
    "interconnection_distance_km": 3.50,
    "resource_capacity_factor": 0.38,
    "slope_pct": 4.0,
    "title_condition_grade": "B",
    "zoning_code": "AG2",
}


def _owner_and_tract(apn: str = "R-9001-001"):
    """One owner and one clean two-hundred-acre tract in an unregulated county."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    return landowner_id, register_parcel(landowner_id, apn=apn, **CLEAN_INPUTS)


def _accepted_option_held_by_the_land_agent():
    """Terms drafted, sent and accepted, waiting on the one hop the agent cannot make."""
    landowner_id, parcel = _owner_and_tract()
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        rent_structure_type="PER_ACRE",
        base_rent_per_acre_cents=120000,
        royalty_rate_bps=0,
        escalator_pct_bps=200,
        escalator_mode="SIMPLE",
    )
    send_option(option["id"])
    accepted = accept_option(option["id"], landowner_id)
    assert_status(accepted, "ACCEPTED", "option")
    return landowner_id, parcel["id"], option["id"]


def test_the_agent_who_negotiated_the_option_still_cannot_execute_it():
    """
    The same land agent drafted the terms, sent them and holds the instrument, so
    every earlier step of the negotiation was theirs by right. Execution is not, and
    the endpoint's own role list is what says so.

    PRD: "A `LandAgent` may not execute an instrument, may not clear title, and may not
    move money."

    Design: Corner/rbac/land_agent_cannot_execute_an_option_reserved_to_the_portfolio_manager
    """
    _landowner_id, _parcel_id, option_id = _accepted_option_held_by_the_land_agent()

    response = client().execute_option(option_id, {}, LAND_AGENT)

    validate_error(response, ERR_UNAUTHORIZED, 403)
    option = read_option(option_id)
    assert_status(option, "ACCEPTED", "option")
    assert_null(option["executed_at"], "executed_at")
    assert_null(option["executed_by_user_id"], "executed_by_user_id")


def test_the_refused_execution_mints_no_ledger_row_and_takes_no_land():
    """
    Execution is the hop that opens the payment history and takes the parcel off the
    market. Refused at the authorisation rung, none of that fires: the ledger is empty,
    the owner is owed nothing, and the tract is still merely qualified.

    PRD: "Commercial terms are negotiated between a `LandAgent` and the `Landowner`, but
    only a `PortfolioManager` may execute, extend or exercise the instrument, permit a
    corridor, grant a crossing, or drive the memorandum through submission and
    recording."

    Design: Corner/rbac/land_agent_cannot_execute_an_option_reserved_to_the_portfolio_manager
    """
    landowner_id, parcel_id, option_id = _accepted_option_held_by_the_land_agent()

    response = client().execute_option(option_id, {}, LAND_AGENT)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    assert ledger_rows(option_id) == [], "a refused execution minted a ledger row"
    assert_status(read_parcel(parcel_id), "QUALIFIED", "parcel")
    landowner = read_landowner(landowner_id)
    assert_cents_equals(landowner["total_paid_cents"], 0, "total_paid_cents")
    assert_status(landowner, "ENGAGED", "landowner")


def test_the_payables_role_cannot_register_a_parcel():
    """
    The payables role holds the only partial update in the API and the whole rent
    lifecycle, but origination is closed to it: a body the land agent would have had
    accepted outright is refused, and nothing is screened or stored.

    PRD: "If `X-User-Role` is not one of those five spellings, or is a valid role that is
    not authorised for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/payment_administrator_cannot_register_a_parcel
    """
    landowner_id = register_landowner(**SANDHILL)["id"]

    response = client().create_parcel(
        parcel_payload(landowner_id, apn="R-9001-001", **CLEAN_INPUTS), PAYMENT_ADMIN
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    _rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(meta, total_count=0)


def test_the_closed_endpoint_answers_before_it_looks_for_the_owner():
    """
    The body now names an owner that does not exist as well as being sent by a role
    that may not send it. Authorisation is two rungs above existence, so the answer is
    the four-oh-three and not the four-oh-four.

    PRD: "The ladder runs authentication, then authorisation, then existence, then
    request shape, then optimistic concurrency, then instrument expiry, then generic
    state admissibility, then title and security compliance, then deal-structure
    constraints, then temporal conflicts, and finally money."

    Design: Corner/rbac/payment_administrator_cannot_register_a_parcel
    """
    register_landowner(**SANDHILL)

    response = client().create_parcel(
        parcel_payload(UNKNOWN_UUID, apn="R-9001-001", **CLEAN_INPUTS), PAYMENT_ADMIN
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    _rows, meta = parcels_page(LAND_AGENT)
    assert_page_meta(meta, total_count=0)


def _parcel_with_two_crews_already_booked():
    """A staging crew pair booked by the agent over one five-day window."""
    _landowner_id, parcel = _owner_and_tract()
    first = book_site_access(
        parcel["id"],
        LAND_AGENT,
        purpose="CONSTRUCTION_STAGING",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
        crew_count=2,
    )
    assert_status(first, "BOOKED", "first booking")
    assert first["crew_count"] == 2, first["crew_count"]
    assert first["purpose"] == "CONSTRUCTION_STAGING", first["purpose"]
    return parcel["id"], first


def test_both_operator_roles_can_book_a_crew_onto_the_same_parcel():
    """
    This is the only write in the API shared by two operator roles, and the second
    booking proves it: the title attorney's surveyor lands on the parcel the agent's
    staging crews are already on, in the same window.

    PRD: "Field work on a parcel is scheduled through site-access bookings, which a
    `LandAgent` or a `TitleCounsel` may create."

    Design: Corner/rbac/site_access_booking_is_shared_by_the_land_agent_and_title_counsel
    """
    parcel_id, _first = _parcel_with_two_crews_already_booked()

    response = client().create_site_access_booking(
        booking_payload(
            parcel_id,
            purpose="TITLE_SURVEY",
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-10T00:00:00Z",
            crew_count=1,
        ),
        TITLE_COUNSEL,
    )

    second = validate_success(response, 201)
    assert_status(second, "BOOKED", "second booking")
    assert second["crew_count"] == 1, second["crew_count"]
    assert second["purpose"] == "TITLE_SURVEY", second["purpose"]
    _rows, meta = validate_paginated(
        client().list_site_access_bookings(TITLE_COUNSEL, {"parcel_id": parcel_id})
    )
    assert_page_meta(meta, total_count=2)


def test_crews_booked_by_the_two_roles_aggregate_to_exactly_the_limit():
    """
    The two bookings belong to different roles but to one parcel and one window, so
    they compete for the same three crew slots. Two plus one reaches the ceiling
    exactly, which the gate must admit rather than refuse.

    PRD: "Over every booking on the same parcel in status `BOOKED` or `COMPLETED` whose
    half-open window intersects the requested window, the sum of their `crew_count` plus
    the requested `crew_count` must not exceed 3; otherwise the booking is refused with
    `ERR_CREW_CAPACITY_EXCEEDED` (409)."

    Design: Corner/rbac/site_access_booking_is_shared_by_the_land_agent_and_title_counsel
    """
    parcel_id, first = _parcel_with_two_crews_already_booked()

    second = book_site_access(
        parcel_id,
        TITLE_COUNSEL,
        purpose="TITLE_SURVEY",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
        crew_count=1,
    )

    assert_status(read_booking(first["id"]), "BOOKED", "first booking")
    assert_status(read_booking(second["id"], TITLE_COUNSEL), "BOOKED", "second booking")
    assert read_booking(first["id"])["crew_count"] == 2
    assert read_booking(second["id"], TITLE_COUNSEL)["crew_count"] == 1


def test_either_role_may_cancel_the_other_roles_booking():
    """
    Cancellation is shared on the same terms as creation, so the attorney can stand
    down the agent's staging crews — and the booking they never made is the one that
    moves.

    PRD: "Withdrawal from an option is the one action shared between a `LandAgent` and a
    `PortfolioManager`; site-access bookings and their cancellation are shared between a
    `LandAgent` and a `TitleCounsel`."

    Design: Corner/rbac/site_access_booking_is_shared_by_the_land_agent_and_title_counsel
    """
    parcel_id, first = _parcel_with_two_crews_already_booked()
    second = book_site_access(
        parcel_id,
        TITLE_COUNSEL,
        purpose="TITLE_SURVEY",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
        crew_count=1,
    )

    cancelled = cancel_booking(first["id"], TITLE_COUNSEL)

    assert_status(cancelled, "CANCELLED", "first booking")
    assert_status(read_booking(second["id"], TITLE_COUNSEL), "BOOKED", "second booking")


def _material_defect_raised_by_the_first_attorney():
    """A ninety-thousand-cent tax lien on the record, signed by its finder."""
    _landowner_id, parcel = _owner_and_tract()
    item = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="TAX_LIEN",
        severity="MATERIAL",
        curative_cost_cents=90000,
    )
    assert item["created_by_user_id"] == TITLE_COUNSEL_USER_ID, (
        item["created_by_user_id"]
    )
    assert_status(item, "OPEN", "item")
    return parcel["id"], item


def test_the_attorney_who_raised_the_defect_cannot_sign_it_off():
    """
    Both principals carry the same role, so role-based authorisation passes and the
    refusal can only come from comparing the acting identifier against the one recorded
    when the defect was found.

    PRD: "When that item is later cleared or waived, the acting `X-User-ID` must differ
    from `created_by_user_id`; the attorney who found the defect may not be the attorney
    who signs it off."

    Design: Corner/rbac/same_title_counsel_user_cannot_clear_the_item_they_raised
    """
    parcel_id, item = _material_defect_raised_by_the_first_attorney()

    response = client().clear_curative_item(item["id"], {}, TITLE_COUNSEL)

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 422)
    after = read_curative(item["id"])
    assert_status(after, "OPEN", "item")
    assert_null(after["cleared_at"], "cleared_at")
    parcel = read_parcel(parcel_id)
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")
    assert_status(parcel, "QUALIFIED", "parcel")


def test_the_identical_clearing_by_a_second_attorney_is_admitted():
    """
    Nothing about the item has changed — only who is asking — so the check is on
    identity rather than on the defect, and the replay capitalises the full budgeted
    cost against the parcel.

    PRD: "On success, hop one moves the item `OPEN → CLEARED`, stamps `cleared_at` from
    the logical clock and `cleared_by_user_id` from the acting identifier, and **adds
    this item's `curative_cost_cents` to the parcel's `curative_cost_cents`**."

    Design: Corner/rbac/same_title_counsel_user_cannot_clear_the_item_they_raised
    """
    parcel_id, item = _material_defect_raised_by_the_first_attorney()
    refused = client().clear_curative_item(item["id"], {}, TITLE_COUNSEL)
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 422)

    response = client().clear_curative_item(item["id"], {}, TITLE_COUNSEL_2)

    cleared = validate_success(response, 200)
    assert_status(cleared, "CLEARED", "item")
    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 90000, "curative_cost_cents"
    )


def _option_executed_by_the_first_manager():
    """A binding instrument whose executing principal is on the record."""
    landowner_id, parcel_id, option_id = _accepted_option_held_by_the_land_agent()
    executed = execute_option(option_id, PORTFOLIO_MANAGER)
    assert executed["executed_by_user_id"] == PORTFOLIO_MANAGER_USER_ID, (
        executed["executed_by_user_id"]
    )
    return landowner_id, parcel_id, option_id


def test_the_manager_who_executed_the_option_cannot_exercise_it():
    """
    Executing the instrument is exactly what disqualifies this principal from
    converting it, and the second limb of the four-eyes rule lives on a different
    entity and a different pair of users from the title limb.

    PRD: "The acting `X-User-ID` must differ from `executed_by_user_id`, or the attempt
    is refused with `ERR_SEGREGATION_OF_DUTIES` (422)."

    Design: Corner/rbac/exercise_cannot_be_performed_by_the_user_who_executed
    """
    landowner_id, parcel_id, option_id = _option_executed_by_the_first_manager()

    response = client().exercise_option(
        option_id, exercise_payload("NOE-2026-0001"), PORTFOLIO_MANAGER
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 422)
    option = read_option(option_id)
    assert_status(option, "EXECUTED", "option")
    assert_null(option["exercised_at"], "exercised_at")
    _rows, meta = validate_paginated(
        client().list_leases(PORTFOLIO_MANAGER, {"option_agreement_id": option_id})
    )
    assert_page_meta(meta, total_count=0)
    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")
    assert_status(read_landowner(landowner_id), "UNDER_OPTION", "landowner")


def test_the_identical_exercise_by_a_second_manager_originates_the_lease():
    """
    The refused notice is re-sent unchanged by the other manager and converts the
    option, sizing the reclamation security off two hundred as-built acres: a hundred
    thousand dollars of gross loaded at four hundred and fifty basis points.

    PRD: "Step two reads `admin_rate_bps` off a three-band ladder against that gross
    figure: a gross below fifty thousand dollars carries 600 basis points, a gross of
    fifty thousand dollars or more but below one hundred and fifty thousand dollars
    carries 450 basis points, and a gross of one hundred and fifty thousand dollars or
    more carries 300 basis points."

    Design: Corner/rbac/exercise_cannot_be_performed_by_the_user_who_executed
    """
    _landowner_id, _parcel_id, option_id = _option_executed_by_the_first_manager()
    refused = client().exercise_option(
        option_id, exercise_payload("NOE-2026-0001"), PORTFOLIO_MANAGER
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 422)

    response = client().exercise_option(
        option_id, exercise_payload("NOE-2026-0001"), PORTFOLIO_MANAGER_2
    )

    lease = validate_success(response, 201)
    assert_acres_equals(
        lease["acre_basis_at_exercise"], 200.00, "acre_basis_at_exercise"
    )
    assert_cents_equals(lease["gross_security_cents"], 10000000, "gross_security_cents")
    assert lease["admin_rate_bps"] == 450, lease["admin_rate_bps"]
    assert_cents_equals(
        lease["total_security_required_cents"], 10450000, "total_security_required_cents"
    )
