"""Lifecycle transitions: the two Opportunity dimensions, the space-hold ladder,
commitment and servicing state machines, and the terminal lockdowns.

Every test below translates exactly one instance of the ``state_machines``
section of the corner design index.  The runner restarts the server and wipes
the database before each test, so every test pins the logical clock as its
first server call and builds all of its own preconditions.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assertions,
    factories,
    fixtures,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_hotel_partner_headers, make_meeting_planner_headers

BASE_CLOCK = "2026-08-01T00:00:00Z"


# --- local composite helpers -------------------------------------------------

def _setup_base(clock: str = BASE_CLOCK, qualify: bool = True, **opportunity_overrides):
    """Clock, planner, one 48h hall and one citywide lead (qualified by default)."""
    fixtures.set_clock(clock)
    planner = fixtures.register_planner()
    hall = fixtures.register_hall()
    lead = fixtures.create_lead(planner["id"], **opportunity_overrides)
    if qualify:
        lead = fixtures.qualify_lead(lead["id"])
    return {
        "planner_id": planner["id"],
        "hall_id": hall["id"],
        "lead": lead,
        "lead_id": lead["id"],
    }


RIVAL_LEAD = {
    "event_name": "Rival Congress 2028",
    "peak_rooms_requested": 700,
    "total_room_nights_requested": 1200,
    "attendance_estimate": 6000,
    "exhibit_sqft_requested": 150_000,
    "rate_ceiling_amount": 209.00,
}


def _setup_rival_holds(second_clock=None):
    """Lead A holding FIRST rank plus rival lead B queued SECOND on the same
    hall and the same buffered window."""
    scenario = _setup_base()
    hold_a = fixtures.place_hold(scenario["lead_id"], scenario["hall_id"])
    if second_clock:
        fixtures.set_clock(second_clock)
        scenario["clock"] = second_clock
    lead_b = fixtures.create_lead(scenario["planner_id"], **RIVAL_LEAD)
    lead_b = fixtures.qualify_lead(lead_b["id"])
    hold_b = fixtures.place_hold(lead_b["id"], scenario["hall_id"])
    scenario.update(
        {
            "lead_b_id": lead_b["id"],
            "hold_a": hold_a,
            "hold_a_id": hold_a["id"],
            "hold_b": hold_b,
            "hold_b_id": hold_b["id"],
        }
    )
    return scenario


def _definite_lead_with_two_orders():
    """The canonical DEFINITE chain plus a DELIVERED HOUSING order and a still
    REQUESTED TRANSPORTATION order."""
    scenario = fixtures.setup_definite_lead()
    housing = fixtures.open_servicing_order(
        scenario["opportunity_id"], category="HOUSING", requested_units=900
    )
    transport = fixtures.open_servicing_order(
        scenario["opportunity_id"], category="TRANSPORTATION", requested_units=20
    )
    fixtures.schedule_order(housing["id"], 880)
    fixtures.deliver_order(housing["id"], 860)
    scenario["housing_order_id"] = housing["id"]
    scenario["transport_order_id"] = transport["id"]
    return scenario


# --- the two independent Opportunity dimensions ------------------------------

def test_qualify_and_first_hold_move_independent_dimensions(
    sales_manager_headers, center_scheduler_headers
):
    """Qualification advances sales_stage only and a FIRST-rank hold advances
    hold_posture only.

    PRD: "A new lead is born in `sales_stage` `LEAD` with `hold_posture` `NONE`" (S3.2)
    PRD: "Crucially, `hold_posture` is driven **only** by the side effects of space holds;
    qualifying a lead, inviting a hotel, committing a block or requesting an incentive
    never touch it." (S2.8)
    PRD: "Creating a `FIRST`-rank hold moves the owning opportunity's `hold_posture` to
    `TENTATIVE` — from `NONE` for a first-ever hold" (S3.3)

    Design: Corner/state_machines/sales_stage_and_hold_posture_advance_as_independent_dimensions
    """
    fixtures.set_clock(BASE_CLOCK)
    planner = fixtures.register_planner()
    hall = fixtures.register_hall()

    created = validate_success(
        api_client.create_opportunity(
            factories.create_opportunity_payload(planner["id"]), sales_manager_headers
        ),
        201,
    )
    assert created["sales_stage"] == "LEAD", "a new lead starts in sales_stage LEAD"
    assert created["hold_posture"] == "NONE", "a new lead starts with hold_posture NONE"

    qualified = validate_success(
        api_client.qualify_opportunity(created["id"], sales_manager_headers)
    )
    assert qualified["sales_stage"] == "QUALIFIED"
    assert qualified["hold_posture"] == "NONE", (
        "qualification does not touch the space dimension"
    )

    hold = validate_success(
        api_client.create_space_hold(
            factories.create_space_hold_payload(created["id"], hall["id"]),
            center_scheduler_headers,
        ),
        201,
    )
    assert hold["hold_rank"] == "FIRST", "an unblocked hold takes FIRST rank"
    assert hold["status"] == "HELD"

    after = validate_success(api_client.get_opportunity(created["id"], sales_manager_headers))
    assertions.assert_opportunity(after)
    assert after["sales_stage"] == "QUALIFIED", (
        "holding space does not move the pipeline dimension"
    )
    assert after["hold_posture"] == "TENTATIVE"


# --- qualification gates ------------------------------------------------------

def test_qualify_inside_min_lead_window_returns_lead_time_too_short(sales_manager_headers):
    """A lead arriving 122 days after the clock cannot be qualified and the
    rejected call writes nothing.

    PRD: "The one substantive gate is lead time: `arrival_date`, interpreted at
    `00:00:00Z`, must be at least 180 days (roughly six months) after the current logical
    clock. A lead whose arrival is nearer than that cannot be worked, and qualification
    fails with `ERR_LEAD_TIME_TOO_SHORT` and HTTP 422." (S3.2)

    Design: Corner/state_machines/qualify_inside_the_min_lead_window_returns_lead_time_too_short
    """
    scenario = _setup_base(
        qualify=False,
        event_name="Short Lead Regional",
        arrival_date="2026-12-01",
        departure_date="2026-12-03",
        peak_rooms_requested=100,
        total_room_nights_requested=180,
        attendance_estimate=800,
        exhibit_sqft_requested=10_000,
        rate_ceiling_amount=189.00,
    )
    version_before = scenario["lead"]["version"]

    validate_error(
        api_client.qualify_opportunity(scenario["lead_id"], sales_manager_headers),
        ApiErrorId.ERR_LEAD_TIME_TOO_SHORT.value,
        422,
    )

    after = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    assert after["sales_stage"] == "LEAD", "the refused qualification leaves the stage alone"
    assert after["version"] == version_before, "the rejected call performs no write"


def test_qualify_at_exactly_min_lead_days_admits_the_lead(sales_manager_headers):
    """An arrival exactly 180 days after the clock is admitted: the boundary is
    inclusive.

    PRD: "`arrival_date`, interpreted at `00:00:00Z`, must be at least 180 days (roughly
    six months) after the current logical clock." (S3.2)
    PRD: "It moves `sales_stage` from `LEAD` to `QUALIFIED`" (S3.2)

    Design: Corner/state_machines/qualify_inside_the_min_lead_window_returns_lead_time_too_short
    """
    scenario = _setup_base(
        qualify=False,
        event_name="Exactly 180 Days Out",
        arrival_date="2027-01-28",
        departure_date="2027-01-30",
        peak_rooms_requested=100,
        total_room_nights_requested=180,
        attendance_estimate=800,
        exhibit_sqft_requested=10_000,
        rate_ceiling_amount=189.00,
    )

    qualified = validate_success(
        api_client.qualify_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    assert qualified["sales_stage"] == "QUALIFIED", (
        "2026-08-01 plus 180 days is 2027-01-28, which clears the minimum lead time"
    )


def test_qualify_twice_returns_invalid_opportunity_stage(sales_manager_headers):
    """The second qualification is a rejected write, not a silent no-op.

    PRD: "It moves `sales_stage` from `LEAD` to `QUALIFIED`, and it is refused with
    `ERR_INVALID_OPPORTUNITY_STAGE` if the lead is in any other stage — including a lead
    that is already `QUALIFIED`." (S3.2)
    PRD: "The opportunity's `sales_stage` being a declared from-state of the requested
    transition — `ERR_INVALID_OPPORTUNITY_STAGE`, 409, on qualify" (S2.7)

    Design: Corner/state_machines/qualify_twice_returns_invalid_opportunity_stage
    """
    scenario = _setup_base()
    version_after_first = scenario["lead"]["version"]
    assert scenario["lead"]["sales_stage"] == "QUALIFIED"

    validate_error(
        api_client.qualify_opportunity(scenario["lead_id"], sales_manager_headers),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )

    after = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    assert after["version"] == version_after_first, "the rejected call performs no write"
    assert after["sales_stage"] == "QUALIFIED"


def test_lost_opportunity_is_terminal_for_qualify_lose_hold_and_bid(
    sales_manager_headers, center_scheduler_headers
):
    """LOST refuses qualify, lose, hold creation and bid creation alike — even
    when the bid carries a perfectly fresh opportunity version.

    PRD: "`SERVICED` and `LOST` are terminal: no transition leaves either of them." (S2.8)
    PRD: "The opportunity's `sales_stage` being a declared from-state of the requested
    transition — `ERR_INVALID_OPPORTUNITY_STAGE`, 409, on qualify, lose, space-hold
    creation, room-block-commitment creation, commitment commit, bid-package creation and
    servicing-order creation." (S2.7)

    Design: Corner/state_machines/lost_opportunity_is_terminal_for_qualify_lose_hold_and_bid
    """
    scenario = _setup_base()
    lost = fixtures.lose_lead(scenario["lead_id"], "PLANNER_DECLINED_BID")
    assert lost["sales_stage"] == "LOST"
    assert lost["lost_reason"] == "PLANNER_DECLINED_BID"
    lost_version = fixtures.opportunity_version(scenario["lead_id"])

    validate_error(
        api_client.qualify_opportunity(scenario["lead_id"], sales_manager_headers),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )
    validate_error(
        api_client.lose_opportunity(
            scenario["lead_id"], {"lost_reason": "LOST_TO_COMPETITOR"}, sales_manager_headers
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )
    validate_error(
        api_client.create_space_hold(
            factories.create_space_hold_payload(scenario["lead_id"], scenario["hall_id"]),
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )
    # A matching expected_opportunity_version clears the concurrency gate (ladder
    # rung 7) and still cannot buy entry to a terminal stage (rung 9).
    validate_error(
        api_client.create_bid_package(
            factories.create_bid_package_payload(scenario["lead_id"], lost_version),
            sales_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )

    holds, meta = validate_paginated(
        api_client.list_space_holds(
            center_scheduler_headers, params={"opportunity_id": scenario["lead_id"]}
        )
    )
    assert meta["total_count"] == 0, "no hold was created against the lost lead"
    assert holds == []


# --- space-hold creation preconditions ---------------------------------------

def _setup_two_halls_and_two_leads():
    """One AVAILABLE hall, one UNDER_RENOVATION hall, one QUALIFIED lead and one
    still-LEAD lead."""
    fixtures.set_clock(BASE_CLOCK)
    planner = fixtures.register_planner()
    open_hall = fixtures.register_hall(hall_status="AVAILABLE")
    closed_hall = fixtures.register_hall(
        name="Ballroom Under Works",
        exhibit_sqft=60_000,
        capacity_persons=4_000,
        turnaround_hours=24,
        hall_status="UNDER_RENOVATION",
    )
    qualified = fixtures.create_lead(
        planner["id"], attendance_estimate=3000, exhibit_sqft_requested=50_000
    )
    qualified = fixtures.qualify_lead(qualified["id"])
    lead_stage = fixtures.create_lead(
        planner["id"],
        event_name="Untriaged Lead 2028",
        arrival_date="2028-06-10",
        departure_date="2028-06-12",
        peak_rooms_requested=200,
        total_room_nights_requested=360,
        attendance_estimate=1500,
        exhibit_sqft_requested=20_000,
        rate_ceiling_amount=199.00,
    )
    return {
        "open_hall_id": open_hall["id"],
        "closed_hall_id": closed_hall["id"],
        "qualified_id": qualified["id"],
        "lead_stage_id": lead_stage["id"],
    }


def test_hold_on_a_renovating_hall_returns_hall_unavailable(
    center_scheduler_headers, sales_manager_headers
):
    """An UNDER_RENOVATION hall refuses a hold even for a QUALIFIED lead that
    fits inside it.

    PRD: "A hall's `hall_status` defaults to `AVAILABLE`; a hall set to
    `UNDER_RENOVATION` rejects every new hold whatever its free window or spare capacity,
    with `ERR_HALL_UNAVAILABLE`." (S3.1)
    PRD: "The hall's `hall_status` being `AVAILABLE` — `ERR_HALL_UNAVAILABLE`, 409, on
    space-hold creation." (S2.7)

    Design: Corner/state_machines/hold_creation_preconditions_reject_renovating_halls_and_lead_stage
    """
    scenario = _setup_two_halls_and_two_leads()

    validate_error(
        api_client.create_space_hold(
            factories.create_space_hold_payload(
                scenario["qualified_id"], scenario["closed_hall_id"]
            ),
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_HALL_UNAVAILABLE.value,
        409,
    )

    _, meta = validate_paginated(api_client.list_space_holds(center_scheduler_headers))
    assert meta["total_count"] == 0, "the refused hold was not persisted"
    lead = validate_success(
        api_client.get_opportunity(scenario["qualified_id"], sales_manager_headers)
    )
    assert lead["hold_posture"] == "NONE", "a refused hold moves no posture"


def test_hold_for_a_lead_stage_opportunity_returns_invalid_opportunity_stage(
    center_scheduler_headers, sales_manager_headers
):
    """A still-LEAD opportunity cannot hold space even on an AVAILABLE hall.

    PRD: "Holds may only be placed for a lead in `sales_stage` `QUALIFIED` or `BIDDING`;
    anything else, `LEAD` included, is refused with `ERR_INVALID_OPPORTUNITY_STAGE`." (S3.3)

    Design: Corner/state_machines/hold_creation_preconditions_reject_renovating_halls_and_lead_stage
    """
    scenario = _setup_two_halls_and_two_leads()

    validate_error(
        api_client.create_space_hold(
            factories.create_space_hold_payload(
                scenario["lead_stage_id"], scenario["open_hall_id"],
                move_in_start="2028-06-08T00:00:00Z",
                move_out_end="2028-06-13T00:00:00Z",
            ),
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )

    _, meta = validate_paginated(api_client.list_space_holds(center_scheduler_headers))
    assert meta["total_count"] == 0, "the refused hold was not persisted"
    lead = validate_success(
        api_client.get_opportunity(scenario["lead_stage_id"], sales_manager_headers)
    )
    assert lead["sales_stage"] == "LEAD"
    assert lead["hold_posture"] == "NONE"


# --- release, expiry and the promotion ladder ---------------------------------

def test_space_hold_release_sets_scheduler_release_and_is_not_repeatable(
    center_scheduler_headers, sales_manager_headers
):
    """The first release stamps SCHEDULER_RELEASE and drops the lead's posture to
    RELEASED; the second release of the same hold is refused.

    PRD: "A successful release sets the hold's status to `RELEASED` with `release_reason`
    `SCHEDULER_RELEASE`" (S3.4)
    PRD: "**Hop 2 prime — the releasing lead's posture.** Because the released hold left the
    active set, the releasing opportunity's `hold_posture` becomes `RELEASED`" (S3.4)
    PRD: "**Releasing** a hold is the scheduler's voluntary act, permitted on a hold in
    status `HELD` or `CHALLENGED` and refused with `ERR_INVALID_HOLD_STATE` on anything
    else." (S3.4)

    Design: Corner/state_machines/space_hold_release_is_not_repeatable_and_sets_scheduler_release
    """
    scenario = _setup_base()
    hold = fixtures.place_hold(scenario["lead_id"], scenario["hall_id"])
    assert fixtures.read_hall(scenario["hall_id"])["confirmed_hold_count"] == 0

    released = validate_success(
        api_client.release_space_hold(hold["id"], center_scheduler_headers)
    )
    assertions.assert_space_hold(released)
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "SCHEDULER_RELEASE"

    lead = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    assert lead["hold_posture"] == "RELEASED", "no hold of this lead remains HELD or CHALLENGED"
    assert lead["sales_stage"] == "QUALIFIED", "only the posture dimension reacts to a release"

    validate_error(
        api_client.release_space_hold(hold["id"], center_scheduler_headers),
        ApiErrorId.ERR_INVALID_HOLD_STATE.value,
        409,
    )
    assert fixtures.read_hall(scenario["hall_id"])["confirmed_hold_count"] == 0, (
        "a released HELD hold was never confirmed"
    )


def test_challenging_a_hold_past_its_expiry_returns_hold_expired(center_scheduler_headers):
    """A FIRST hold still stored as HELD after its expiry cannot be challenged
    before the sweep runs.

    PRD: "A `FIRST`-rank hold has its `expires_at` stamped at 90 days after the current
    logical clock" (S3.3)
    PRD: "A challenged hold must also still be alive: if the current logical clock has
    passed its `expires_at`, the challenge is refused with `ERR_HOLD_EXPIRED`" (S3.4)

    Design: Corner/state_machines/expiry_run_expires_a_stale_first_hold_and_promotes_the_waiting_second
    """
    scenario = _setup_rival_holds(second_clock="2026-11-01T00:00:00Z")
    assert same_instant(scenario["hold_a"]["expires_at"], "2026-10-30T00:00:00Z"), (
        "2026-08-01 plus the 90-day first-hold life is 2026-10-30"
    )
    assert scenario["hold_b"]["hold_rank"] == "SECOND"

    validate_error(
        api_client.challenge_space_hold(
            scenario["hold_a_id"],
            {"challenging_space_hold_id": scenario["hold_b_id"]},
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_HOLD_EXPIRED.value,
        409,
    )

    still_held = fixtures.read_hold(scenario["hold_a_id"])
    assert still_held["status"] == "HELD", "the refused challenge wrote nothing"
    assert still_held["challenge_deadline"] is None


def test_expiry_run_expires_a_stale_first_hold_and_promotes_the_waiting_second(
    center_scheduler_headers, sales_manager_headers
):
    """One checkpoint expires the stale FIRST hold, promotes the queued SECOND
    hold with a fresh 30-day life, and a repeat run reports all zeros.

    PRD: "Every hold in status `HELD` whose `expires_at` is at or before the current
    logical clock moves to `EXPIRED` with `release_reason` `HOLD_EXPIRED`" (S3.4)
    PRD: "The winner's `hold_rank` becomes `FIRST`, its `expires_at` is re-stamped at 30
    days after the current logical clock, and its opportunity's `hold_posture` becomes
    `TENTATIVE`." (S3.4)

    Design: Corner/state_machines/expiry_run_expires_a_stale_first_hold_and_promotes_the_waiting_second
    """
    scenario = _setup_rival_holds(second_clock="2026-11-01T00:00:00Z")

    summary = fixtures.run_expiry()
    assert summary["expired_count"] == 1
    assert summary["lapsed_challenge_count"] == 0, "no challenge was ever raised"
    assert summary["promoted_count"] == 1
    assert summary["promoted_space_hold_ids"] == [scenario["hold_b_id"]]

    hold_a = fixtures.read_hold(scenario["hold_a_id"])
    assert hold_a["status"] == "EXPIRED"
    assert hold_a["release_reason"] == "HOLD_EXPIRED"

    hold_b = fixtures.read_hold(scenario["hold_b_id"])
    assert hold_b["status"] == "HELD"
    assert hold_b["hold_rank"] == "FIRST"
    assert same_instant(hold_b["expires_at"], "2026-12-01T00:00:00Z"), (
        "the promoted hold gets a fresh 30 days from the run's clock of 2026-11-01"
    )

    lead_a = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    lead_b = validate_success(
        api_client.get_opportunity(scenario["lead_b_id"], sales_manager_headers)
    )
    assert lead_a["hold_posture"] == "RELEASED"
    assert lead_a["sales_stage"] == "QUALIFIED", "a QUALIFIED lead is not lost by expiry"
    assert lead_b["hold_posture"] == "TENTATIVE"

    second = fixtures.run_expiry()
    assert second["expired_count"] == 0, "the backlog was already swept"
    assert second["promoted_count"] == 0


# --- challenges ----------------------------------------------------------------

def test_challenge_stamps_a_fourteen_day_deadline_and_sets_posture_challenged(
    center_scheduler_headers, sales_manager_headers
):
    """The challenge writes the challenged hold and its opportunity only: the
    challenger's own row keeps its HELD/SECOND shape.

    PRD: "A successful challenge moves the challenged hold from `HELD` to `CHALLENGED`,
    stamps its `challenge_deadline` at 14 days after the current logical clock, and records
    the challenger's identifier in the challenged hold's `challenged_by_space_hold_id`. The
    acting `SECOND`-rank hold itself does not change state — it stays `HELD`" (S3.4)
    PRD: "As a second-order effect, the challenged hold's opportunity moves `hold_posture`
    from `TENTATIVE` to `CHALLENGED`" (S3.4)

    Design: Corner/state_machines/challenge_stamps_a_fourteen_day_deadline_and_sets_posture_challenged
    """
    scenario = _setup_rival_holds()

    challenged = validate_success(
        api_client.challenge_space_hold(
            scenario["hold_a_id"],
            {"challenging_space_hold_id": scenario["hold_b_id"]},
            center_scheduler_headers,
        )
    )
    assertions.assert_space_hold(challenged)
    assert challenged["status"] == "CHALLENGED"
    assert same_instant(challenged["challenge_deadline"], "2026-08-15T00:00:00Z"), (
        "2026-08-01 plus the 14-day challenge window is 2026-08-15"
    )
    assert challenged["challenged_by_space_hold_id"] == scenario["hold_b_id"]

    challenger = fixtures.read_hold(scenario["hold_b_id"])
    assert challenger["status"] == "HELD", "the challenger does not change state"
    assert challenger["hold_rank"] == "SECOND"

    lead_a = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    lead_b = validate_success(
        api_client.get_opportunity(scenario["lead_b_id"], sales_manager_headers)
    )
    assert lead_a["hold_posture"] == "CHALLENGED"
    assert lead_b["hold_posture"] == "NONE", (
        "being somebody's backup is not a tentative booking"
    )

    rows, meta = validate_paginated(
        api_client.list_space_holds(
            center_scheduler_headers,
            params={"challenged_by_space_hold_id": scenario["hold_b_id"]},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [scenario["hold_a_id"]]


def test_challenge_by_a_first_rank_hold_returns_challenge_target_invalid(
    center_scheduler_headers
):
    """Direction matters: a FIRST hold may not challenge the SECOND, and a hold
    may not challenge itself.

    PRD: "The challenge is well-formed only when all four of these are true: the named
    challenger is a hold in status `HELD` with `hold_rank` `SECOND`; the challenged hold is
    in status `HELD` with `hold_rank` `FIRST` on the same `center_hall_id`; the two holds'
    buffered windows conflict by the rule in Section 3.3; and the two holds belong to
    different opportunities. Any of those failing yields `ERR_CHALLENGE_TARGET_INVALID`
    with HTTP 422." (S3.4)

    Design: Corner/state_machines/challenge_by_a_first_rank_hold_returns_challenge_target_invalid
    """
    scenario = _setup_rival_holds()

    validate_error(
        api_client.challenge_space_hold(
            scenario["hold_b_id"],
            {"challenging_space_hold_id": scenario["hold_a_id"]},
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_CHALLENGE_TARGET_INVALID.value,
        422,
    )
    validate_error(
        api_client.challenge_space_hold(
            scenario["hold_a_id"],
            {"challenging_space_hold_id": scenario["hold_a_id"]},
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_CHALLENGE_TARGET_INVALID.value,
        422,
    )

    untouched = fixtures.read_hold(scenario["hold_a_id"])
    assert untouched["status"] == "HELD"
    assert untouched["challenge_deadline"] is None
    assert untouched["challenged_by_space_hold_id"] is None


def test_challenge_with_a_dangling_challenger_returns_space_hold_not_found(
    center_scheduler_headers
):
    """The body foreign key is resolved before the 422 rank rules are applied.

    PRD: "The same codes are reused for foreign keys supplied in a request body: ...
    `challenging_space_hold_id` ... must all resolve to live rows, and a dangling reference
    returns the not-found code of the referenced kind." (S2.7)
    PRD: "Every foreign key in the body resolving — the matching 404 code, on every
    creation that carries a foreign key." precedes "The challenge being well-formed —
    `ERR_CHALLENGE_TARGET_INVALID`, 422" in the global ladder (S2.7)

    Design: Corner/state_machines/challenge_by_a_first_rank_hold_returns_challenge_target_invalid
    """
    scenario = _setup_rival_holds()

    validate_error(
        api_client.challenge_space_hold(
            scenario["hold_a_id"],
            {"challenging_space_hold_id": NON_EXISTENT_UUID},
            center_scheduler_headers,
        ),
        ApiErrorId.ERR_SPACE_HOLD_NOT_FOUND.value,
        404,
    )

    untouched = fixtures.read_hold(scenario["hold_a_id"])
    assert untouched["status"] == "HELD"
    assert untouched["challenge_deadline"] is None


def test_lapsed_challenge_releases_the_first_hold_and_promotes_the_challenger(
    sales_manager_headers
):
    """Letting the fortnight lapse releases the challenged hold with
    CHALLENGE_LAPSED and hands FIRST rank to the challenger.

    PRD: "Every hold in status `CHALLENGED` whose `challenge_deadline` is strictly before
    the current logical clock moves to `RELEASED` with `release_reason` `CHALLENGE_LAPSED`"
    (S3.4)
    PRD: "The winner's `hold_rank` becomes `FIRST`, its `expires_at` is re-stamped at 30
    days after the current logical clock, and its opportunity's `hold_posture` becomes
    `TENTATIVE`." (S3.4)

    Design: Corner/state_machines/lapsed_challenge_releases_the_first_hold_and_promotes_the_challenger
    """
    scenario = _setup_rival_holds()
    challenged = fixtures.challenge_hold(scenario["hold_a_id"], scenario["hold_b_id"])
    assert same_instant(challenged["challenge_deadline"], "2026-08-15T00:00:00Z")

    fixtures.set_clock("2026-08-16T00:00:00Z")
    summary = fixtures.run_expiry()
    assert summary["expired_count"] == 0, (
        "the challenged hold's own expires_at of 2026-10-30 is still in the future"
    )
    assert summary["lapsed_challenge_count"] == 1
    assert summary["promoted_count"] == 1
    assert summary["promoted_space_hold_ids"] == [scenario["hold_b_id"]]

    hold_a = fixtures.read_hold(scenario["hold_a_id"])
    assert hold_a["status"] == "RELEASED"
    assert hold_a["release_reason"] == "CHALLENGE_LAPSED"

    hold_b = fixtures.read_hold(scenario["hold_b_id"])
    assert hold_b["hold_rank"] == "FIRST"
    assert same_instant(hold_b["expires_at"], "2026-09-15T00:00:00Z")

    lead_a = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    lead_b = validate_success(
        api_client.get_opportunity(scenario["lead_b_id"], sales_manager_headers)
    )
    assert lead_a["hold_posture"] == "RELEASED"
    assert lead_b["hold_posture"] == "TENTATIVE"


# --- the room block commitment machine -----------------------------------------

def test_commit_and_pickup_on_an_invited_block_return_invalid_commitment_state(
    sales_manager_headers
):
    """INVITED is a from-state for neither commit nor pickup reporting, and an
    invitation on its own commits no rooms.

    PRD: "A new commitment starts in status `INVITED` with `offer_round` 0, `rooms_peak_offered`,
    `rate_offered_amount`, `cutoff_days_before_arrival`, `cutoff_date` and `withdraw_reason`
    all null" (S3.5)
    PRD: "Committing is the bureau's decision, taken by a `SalesManager` on a commitment in
    status `OFFERED`" (S3.5)
    PRD: "A `HotelPartner` files one **pickup record** per night against a commitment in
    status `COMMITTED` or `RELEASED`" (S3.5)
    PRD: "The commitment's `status` being a declared from-state — `ERR_INVALID_COMMITMENT_STATE`,
    409, on offer, commit, withdraw and pickup-record creation." (S2.7)

    Design: Corner/state_machines/commit_and_pickup_on_an_invited_block_return_invalid_commitment_state
    """
    scenario = _setup_base()
    hotel = fixtures.register_hotel(
        name="Harborview Grand", committable_rooms=600, walk_distance_blocks=2
    )
    commitment = fixtures.invite_hotel(scenario["lead_id"], hotel["id"], 500)
    assertions.assert_room_block_commitment(commitment)
    assert commitment["status"] == "INVITED"
    assert commitment["offer_round"] == 0

    validate_error(
        api_client.commit_room_block_commitment(commitment["id"], sales_manager_headers),
        ApiErrorId.ERR_INVALID_COMMITMENT_STATE.value,
        409,
    )
    validate_error(
        api_client.create_pickup_record(
            commitment["id"],
            factories.pickup_record_payload("2028-04-10", 100, 214.33),
            make_hotel_partner_headers(hotel["id"]),
        ),
        ApiErrorId.ERR_INVALID_COMMITMENT_STATE.value,
        409,
    )

    after = fixtures.read_commitment(commitment["id"])
    assert after["status"] == "INVITED", "both refusals are no-ops"
    assert after["rate_offered_amount"] is None
    assert after["cutoff_date"] is None

    assert fixtures.read_hotel(hotel["id"])["committed_peak_rooms"] == 0
    lead = validate_success(
        api_client.get_opportunity(scenario["lead_id"], sales_manager_headers)
    )
    assert lead["committed_peak_rooms"] == 0
    assertions.assert_money_equals(
        lead["block_coverage_pct"], 0.00, "block_coverage_pct"
    )


# --- the servicing order machine -----------------------------------------------

def test_servicing_order_before_definite_returns_invalid_opportunity_stage(
    services_manager_headers
):
    """A QUALIFIED lead cannot open a servicing order at all.

    PRD: "A `ServicesManager` opens one **servicing order** per workstream against a lead in
    `sales_stage` `DEFINITE` — attempting one before the lead is definite is refused with
    `ERR_INVALID_OPPORTUNITY_STAGE`." (S3.9)
    PRD: "The opportunity's `sales_stage` being a declared from-state of the requested
    transition — `ERR_INVALID_OPPORTUNITY_STAGE`, 409, on ... servicing-order creation." (S2.7)

    Design: Corner/state_machines/servicing_order_before_definite_returns_invalid_opportunity_stage
    """
    scenario = _setup_base()

    validate_error(
        api_client.create_servicing_order(
            factories.create_servicing_order_payload(
                scenario["lead_id"], category="HOUSING", requested_units=900
            ),
            services_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )

    orders, meta = validate_paginated(
        api_client.list_opportunity_servicing_orders(
            scenario["lead_id"], services_manager_headers
        )
    )
    assert meta["total_count"] == 0
    assert orders == []


def test_servicing_lifecycle_rejects_deliver_before_schedule_and_after_delivery(
    services_manager_headers, sales_manager_headers
):
    """The order must walk REQUESTED -> SCHEDULED -> DELIVERED, and DELIVERED is
    terminal for both deliver and cancel.

    PRD: "The order is created in status `REQUESTED` with `assigned_units` and
    `delivered_units` both 0." (S3.9)
    PRD: "Scheduling the order records `assigned_units` ... and moves the order from
    `REQUESTED` to `SCHEDULED` while the lead is still `DEFINITE`. Delivery records
    `delivered_units` ... and moves the order from `SCHEDULED` to `DELIVERED`." (S3.9)
    PRD: "A `DELIVERED` order can never be cancelled, and every one of these three
    operations attempted from the wrong status is refused with `ERR_INVALID_SERVICING_STATE`
    and HTTP 409." (S3.9)

    Design: Corner/state_machines/servicing_lifecycle_rejects_deliver_before_schedule_and_after_delivery
    """
    scenario = fixtures.setup_definite_lead()

    housing = validate_success(
        api_client.create_servicing_order(
            factories.create_servicing_order_payload(
                scenario["opportunity_id"], category="HOUSING", requested_units=900
            ),
            services_manager_headers,
        ),
        201,
    )
    assertions.assert_servicing_order(housing)
    assert housing["status"] == "REQUESTED"
    assert housing["assigned_units"] == 0, (
        "the PRD creates the order with assigned_units 0, not null"
    )
    assert housing["delivered_units"] == 0
    validate_success(
        api_client.create_servicing_order(
            factories.create_servicing_order_payload(
                scenario["opportunity_id"], category="TRANSPORTATION", requested_units=20
            ),
            services_manager_headers,
        ),
        201,
    )

    validate_error(
        api_client.deliver_servicing_order(
            housing["id"], {"delivered_units": 880}, services_manager_headers
        ),
        ApiErrorId.ERR_INVALID_SERVICING_STATE.value,
        409,
    )

    scheduled = validate_success(
        api_client.schedule_servicing_order(
            housing["id"], {"assigned_units": 880}, services_manager_headers
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["assigned_units"] == 880

    delivered = validate_success(
        api_client.deliver_servicing_order(
            housing["id"], {"delivered_units": 860}, services_manager_headers
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_units"] == 860

    validate_error(
        api_client.deliver_servicing_order(
            housing["id"], {"delivered_units": 860}, services_manager_headers
        ),
        ApiErrorId.ERR_INVALID_SERVICING_STATE.value,
        409,
    )
    validate_error(
        api_client.cancel_servicing_order(housing["id"], services_manager_headers),
        ApiErrorId.ERR_INVALID_SERVICING_STATE.value,
        409,
    )

    lead = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], sales_manager_headers)
    )
    assert lead["sales_stage"] == "DEFINITE", (
        "the TRANSPORTATION order is still REQUESTED, so no bubble-up fires"
    )


# --- the SERVICED bubble-up ----------------------------------------------------

def test_serviced_bubble_up_fires_only_when_the_last_active_order_clears(
    services_manager_headers, sales_manager_headers
):
    """A CANCELLED sibling counts as cleared: cancelling the last REQUESTED order
    bubbles the lead from DEFINITE to SERVICED, which is then terminal.

    PRD: "Whenever a delivery or a cancellation leaves no servicing order of the lead in
    status `REQUESTED` or `SCHEDULED`, and at least one order of that lead is in `DELIVERED`,
    the lead's `sales_stage` moves from `DEFINITE` to `SERVICED` and its `version` is
    incremented by one." (S3.9)
    PRD: "Cancellation is available from `REQUESTED` or `SCHEDULED` while the lead is
    `DEFINITE`, moves the order to `CANCELLED`" (S3.9)
    PRD: "attempting one before the lead is definite is refused with
    `ERR_INVALID_OPPORTUNITY_STAGE`." (S3.9)

    Design: Corner/state_machines/serviced_bubble_up_fires_only_when_the_last_active_order_clears
    """
    scenario = _definite_lead_with_two_orders()

    before = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], sales_manager_headers)
    )
    assert before["sales_stage"] == "DEFINITE", (
        "one DELIVERED order is not enough while a REQUESTED sibling is open"
    )

    cancelled = validate_success(
        api_client.cancel_servicing_order(
            scenario["transport_order_id"], services_manager_headers
        )
    )
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], sales_manager_headers)
    )
    assert after["sales_stage"] == "SERVICED"
    assert after["version"] == before["version"] + 1
    assert after["hold_posture"] == "CONFIRMED", (
        "servicing never rewinds the space dimension"
    )

    validate_error(
        api_client.create_servicing_order(
            factories.create_servicing_order_payload(
                scenario["opportunity_id"], category="VOLUNTEER", requested_units=5
            ),
            services_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_OPPORTUNITY_STAGE.value,
        409,
    )


def test_serviced_bubble_up_releases_the_hold_and_the_block_and_disburses_the_fund(
    services_manager_headers, sales_manager_headers, board_analyst_headers,
    center_scheduler_headers
):
    """Reaching SERVICED releases the confirmed hall hold and every committed
    block, and moves the fund charge from committed to disbursed.

    PRD: "Every room block commitment of the lead in status `COMMITTED` is released with
    `withdraw_reason` `EVENT_SERVICED`, freeing the properties' `committed_peak_rooms` and
    `committed_room_nights`." (S3.9)
    PRD: "The lead's fund charge moves from committed to disbursed — the fund's
    `committed_amount` falls by the package's `total_fund_charge_amount` while
    `disbursed_amount` rises by the same amount, leaving `budget_amount` and
    `uncommitted_amount` untouched" (S3.9)
    PRD: "And the lead's `CONFIRMED` space hold is released with `release_reason`
    `EVENT_SERVICED` and the hall's `confirmed_hold_count` is decremented" (S3.9)
    PRD: "a lead's `attrition_settlement_amount` remains 0.00 until the first pickup record
    exists" (S3.9)

    Design: Corner/state_machines/serviced_bubble_up_fires_only_when_the_last_active_order_clears
    """
    scenario = _definite_lead_with_two_orders()

    fund_before = validate_success(
        api_client.get_incentive_fund(scenario["fund_id"], board_analyst_headers)
    )
    assertions.assert_money_equals(
        fund_before["committed_amount"], 12600.00, "committed_amount before servicing"
    )
    assertions.assert_money_equals(
        fund_before["disbursed_amount"], 0.00, "disbursed_amount before servicing"
    )

    validate_success(
        api_client.cancel_servicing_order(
            scenario["transport_order_id"], services_manager_headers
        )
    )

    hold = validate_success(
        api_client.get_space_hold(scenario["hold_id"], center_scheduler_headers)
    )
    assert hold["status"] == "RELEASED"
    assert hold["release_reason"] == "EVENT_SERVICED"
    assert fixtures.read_hall(scenario["hall_id"])["confirmed_hold_count"] == 0

    released, meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers,
            params={
                "opportunity_id": scenario["opportunity_id"],
                "status": "RELEASED",
            },
        )
    )
    assert meta["total_count"] == 3, "all three committed properties are released at once"
    assert {row["status"] for row in released} == {"RELEASED"}
    assert {row["withdraw_reason"] for row in released} == {"EVENT_SERVICED"}
    assert fixtures.read_hotel(scenario["hotels"][0]["id"])["committed_peak_rooms"] == 0

    fund_after = validate_success(
        api_client.get_incentive_fund(scenario["fund_id"], board_analyst_headers)
    )
    assertions.assert_money_equals(
        fund_after["committed_amount"], 0.00, "committed_amount after servicing"
    )
    assertions.assert_money_equals(
        fund_after["disbursed_amount"], 12600.00, "disbursed_amount after servicing"
    )
    assertions.assert_money_equals(
        fund_after["uncommitted_amount"], 487400.00, "uncommitted_amount after servicing"
    )
    assertions.assert_fund_conservation_identity(fund_after)

    lead = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], sales_manager_headers)
    )
    assertions.assert_money_equals(
        lead["attrition_settlement_amount"], 0.00, "attrition_settlement_amount"
    )
    again = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], sales_manager_headers)
    )
    assertions.assert_money_equals(
        again["attrition_settlement_amount"], 0.00, "frozen attrition on re-read"
    )


# --- terminal lockdowns --------------------------------------------------------

def test_board_report_publish_freezes_the_report(
    board_analyst_headers, bureau_admin_headers
):
    """PUBLISHED is the board report's only terminal state and the second publish
    is a rejected no-op.

    PRD: "Every figure is computed once, at creation, and the report is born in status
    `DRAFT`." (S3.9)
    PRD: "Publishing a report stamps `published_at` from the logical clock and moves `status`
    from `DRAFT` to `PUBLISHED`. A published report is frozen forever: its aggregates are
    never recomputed no matter how the underlying data later moves, and a second publication
    attempt is refused with `ERR_BOARD_REPORT_PUBLISHED` and HTTP 409." (S3.9)

    Design: Corner/state_machines/board_report_publish_freezes_the_report
    """
    fixtures.set_clock("2027-07-01T00:00:00Z")

    report = validate_success(
        api_client.create_board_report(
            factories.create_board_report_payload("2026-07-01", "2027-07-01"),
            board_analyst_headers,
        ),
        201,
    )
    assertions.assert_board_report(report)
    assert report["status"] == "DRAFT"
    assert report["published_at"] is None, "published_at is only stamped by publication"

    published = validate_success(
        api_client.publish_board_report(report["id"], board_analyst_headers)
    )
    assert published["status"] == "PUBLISHED"
    assert same_instant(published["published_at"], "2027-07-01T00:00:00Z"), (
        "published_at is stamped from the logical clock"
    )

    validate_error(
        api_client.publish_board_report(report["id"], board_analyst_headers),
        ApiErrorId.ERR_BOARD_REPORT_PUBLISHED.value,
        409,
    )

    reread = validate_success(api_client.get_board_report(report["id"], bureau_admin_headers))
    assert reread["status"] == "PUBLISHED"
    assert same_instant(reread["published_at"], published["published_at"]), (
        "the rejected second publish is a no-op"
    )


def test_declined_bid_package_rejects_letters_and_further_planner_responses(
    sales_manager_headers
):
    """Losing a BIDDING lead drives its live package to the terminal DECLINED
    state, after which every package write is refused.

    PRD: "When the lead was in `BIDDING`, the live package — whatever its status among
    `DRAFT`, `INCENTIVE_PENDING`, `APPROVED` and `SUBMITTED` — is moved to `DECLINED` with its
    `decline_reason` mapped from the lead's `lost_reason`: `RATE_TOO_HIGH`,
    `INSUFFICIENT_INCENTIVE` and `LOST_TO_COMPETITOR` map through unchanged" (S3.8)
    PRD: "Community backing is assembled as **support letters**, which a `SalesManager`
    attaches to a package while it is still in `DRAFT` — an attachment attempted in any other
    status is refused with `ERR_INVALID_BID_STATE`." (S3.7)
    PRD: "The bid package's `status` being a declared from-state — `ERR_INVALID_BID_STATE`,
    409, on support-letter attachment, incentive request, incentive decision, submission and
    planner response." (S2.7)

    Design: Corner/state_machines/declined_bid_package_rejects_letters_and_further_planner_responses
    """
    scenario = fixtures.setup_bid_submitted()
    assert scenario["bid"]["status"] == "SUBMITTED"
    assert scenario["opportunity"]["sales_stage"] == "BIDDING"

    lost = fixtures.lose_lead(scenario["opportunity_id"], "RATE_TOO_HIGH")
    assert lost["sales_stage"] == "LOST"
    assert lost["lost_reason"] == "RATE_TOO_HIGH"

    bid = validate_success(
        api_client.get_bid_package(scenario["bid_id"], sales_manager_headers)
    )
    assertions.assert_bid_package(bid)
    assert bid["status"] == "DECLINED"
    assert bid["decline_reason"] == "RATE_TOO_HIGH", "RATE_TOO_HIGH maps through unchanged"

    validate_error(
        api_client.create_support_letter(
            scenario["bid_id"],
            factories.support_letter_payload("UNIVERSITY", "State University"),
            sales_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_BID_STATE.value,
        409,
    )
    validate_error(
        api_client.request_incentive(
            scenario["bid_id"],
            factories.request_incentive_payload(9000.00),
            sales_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_BID_STATE.value,
        409,
    )
    validate_error(
        api_client.planner_response(
            scenario["bid_id"],
            factories.planner_response_payload("ACCEPTED"),
            make_meeting_planner_headers(scenario["planner_id"]),
        ),
        ApiErrorId.ERR_INVALID_BID_STATE.value,
        409,
    )

    letters, meta = validate_paginated(
        api_client.list_support_letters(scenario["bid_id"], sales_manager_headers)
    )
    assert meta["total_count"] == 2, "the refused attachment added nothing"
    assert {letter["letter_type"] for letter in letters} == {"MAYOR", "CHAMBER"}
    frozen = validate_success(
        api_client.get_bid_package(scenario["bid_id"], sales_manager_headers)
    )
    assert frozen["support_letter_type_count"] == 2
    assert frozen["status"] == "DECLINED"
