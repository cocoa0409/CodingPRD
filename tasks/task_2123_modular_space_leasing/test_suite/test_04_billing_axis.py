"""The money axis: activation, voiding, extension and the customer credit line."""
from test_helpers import (
    RURAL,
    ApiErrorId,
    assert_credit_hold_consistent,
    assert_lease,
    book_job,
    complete_job,
    dispatch_job,
    extend_lease,
    get_branch,
    get_customer,
    get_lease,
    get_unit,
    make_leasing_agent_headers,
    set_clock,
    setup_dallas_installed_lease,
    setup_rural_finalized_assessment,
    setup_rural_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_lease_payload

RURAL_SITE = "9 County Road 12, Rural TX"


# ─── The two axes move independently ─────────────────────────────────────────

def test_activation_moves_the_money_axis_and_leaves_occupancy_pending(api):
    """PRD §3.7: "A lease starts `UNBILLED`; activation by a `LeasingAgent`
    takes it `UNBILLED → ACCRUING`; final settlement takes it
    `ACCRUING → SETTLED`; and voiding takes it to `VOIDED` from either
    `UNBILLED` or `ACCRUING`."
    PRD §3.7: "On success the lease's `billed_to_date_cents` is set to that same
    sum of mobilization fee, monthly base rate and monthly accessory rate; the
    customer's `outstanding_balance_cents` and `credit_hold` are recomputed as
    §2.11 prescribes; and the lease's `version` is incremented."
    PRD §3.7: "The occupancy axis is deliberately left exactly where it was —
    activating a lease does not put a building on the ground."

    Design: Difficulty/non_linear_state_machine/lease_occupancy_and_billing_axes_advance_independently
    """
    ctx = setup_rural_lease()

    activated = validate_success(
        api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers()))
    assert_lease(activated)

    assert activated["billing_status"] == "ACCRUING", (
        f"Expected the money axis to reach ACCRUING, got "
        f"{activated['billing_status']}")
    assert activated["occupancy_status"] == "PENDING", (
        f"Expected the occupancy axis to stay PENDING, got "
        f"{activated['occupancy_status']}")
    assert activated["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"Expected 351500 + 127065 + 0 = 478565 billed, got "
        f"{activated['billed_to_date_cents']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "RESERVED", (
        f"activation must not move the building, got unit status {unit['status']}")


def test_delivery_completion_moves_occupancy_and_leaves_billing_untouched(api):
    """PRD §3.8: "Completing a `DELIVERY_INSTALL` job takes the unit
    `IN_TRANSIT → ON_LEASE`, writes the lease's `floorplan_configuration_id`
    into the unit's `installed_config_id`, and increments the unit's `version`;
    in the same operation the lease's occupancy axis moves `PENDING → INSTALLED`
    and its `version` is incremented, while its billing axis is left
    untouched."
    PRD §3.8: "The **crew line** takes the booked `crew_hours`, rounds them
    **up** to a whole number of hours, multiplies by the origin branch's
    `labor_rate_cents_per_hour`, and applies a difficulty factor that depends on
    the job type — 1.0 for `DELIVERY_INSTALL`, 0.75 for `TEARDOWN_RETURN`, and
    1.5 for `RELOCATION`, since re-siting an occupied building is the most
    delicate of the three — with the product rounded half up to a whole cent."

    Design: Difficulty/non_linear_state_machine/lease_occupancy_and_billing_axes_advance_independently
    """
    ctx = setup_rural_lease()
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))

    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                   mileage_miles=40, crew_hours=4.0)
    assert job["transport_cost_cents"] == 36_800, (
        f"a 40-mile haul is all in the included band, so 4 crew hours at 9200 "
        f"is the whole cost; expected 36800, got {job['transport_cost_cents']}")

    dispatch_job(job["id"], ctx["branch"]["id"])
    complete_job(job["id"], ctx["branch"]["id"])

    lease = get_lease(ctx["lease"]["id"])
    assert lease["occupancy_status"] == "INSTALLED", (
        f"Expected INSTALLED occupancy after delivery, got "
        f"{lease['occupancy_status']}")
    assert lease["billing_status"] == "ACCRUING", (
        f"the money axis must be untouched by delivery, got "
        f"{lease['billing_status']}")
    assert lease["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"delivery bills nothing further, expected 478565, got "
        f"{lease['billed_to_date_cents']}")
    assert lease["final_settlement_cents"] is None
    assert lease["actual_vacated_date"] is None

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "ON_LEASE", (
        f"Expected ON_LEASE after delivery, got {unit['status']}")
    assert unit["installed_config_id"] == ctx["config"]["id"], (
        f"the lease's configuration must be written onto the unit, got "
        f"{unit['installed_config_id']}")


# ─── Screening ladder: source state outranks the credit check ────────────────

def test_repeat_activation_reports_already_activated_not_the_credit_limit(api):
    """PRD §2.9: "The **first** check that fails decides the response, its error
    code is returned, and no lower-ranked check is consulted — this is what
    makes error responses predictable when a request is wrong in more than one
    way at once."
    PRD §3.7: "The lease's billing axis must still be `UNBILLED`, and a second
    attempt on a lease that has already been activated is rejected with
    `ERR_LEASE_ALREADY_ACTIVATED`."
    PRD §3.7: "If that sum would exceed the limit, activation is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402 — the only 402 in the API, because
    it is the only place where a request fails purely for want of credit."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_credit_limit_on_repeat_activate
    """
    # The limit is set to exactly the first charge, so a second charge would
    # also breach the credit rank at 26 — but source state is rank 7.
    ctx = setup_rural_lease(
        customer_overrides={"credit_limit_cents": RURAL["ACTIVATION_CHARGE_CENTS"]})
    first = validate_success(
        api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers()))
    assert first["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"]

    second = api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers())
    validate_error(second, ApiErrorId.ERR_LEASE_ALREADY_ACTIVATED.value)
    assert second.json()["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED", (
        "the rank-7 state failure must pre-empt the rank-26 credit check")


def test_repeat_activation_leaves_the_customer_ledger_untouched(api):
    """PRD §3.7: "The lease's billing axis must still be `UNBILLED`, and a
    second attempt on a lease that has already been activated is rejected with
    `ERR_LEASE_ALREADY_ACTIVATED`."
    PRD §2.11: "From that balance the system derives `credit_hold`, which is
    true when `outstanding_balance_cents` is strictly greater than
    `credit_limit_cents`. Equality is deliberately not a hold — a customer
    sitting exactly on its limit is still in good standing."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_credit_limit_on_repeat_activate
    """
    ctx = setup_rural_lease(
        customer_overrides={"credit_limit_cents": RURAL["ACTIVATION_CHARGE_CENTS"]})
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))

    validate_error(
        api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers()),
        ApiErrorId.ERR_LEASE_ALREADY_ACTIVATED.value)

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"the refused activation must not double-bill; expected 478565, got "
        f"{customer['outstanding_balance_cents']}")
    assert customer["credit_hold"] is False, (
        "sitting exactly on the limit is not a hold")
    assert_credit_hold_consistent(customer)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"]
    assert lease["billing_status"] == "ACCRUING"


# ─── Activate then void conserves the ledger ─────────────────────────────────

def test_voiding_an_activated_lease_credits_back_exactly_what_was_billed(api):
    """PRD §3.7: "The billing axis goes `UNBILLED → VOIDED` or
    `ACCRUING → VOIDED` depending on where it stood, and in both cases the
    lease's `credited_cents` is set equal to its `billed_to_date_cents`, which
    is an exact reversal of whatever activation charged; on an un-activated
    lease both figures are zero and the reversal is a formality."
    PRD §3.7: "The occupancy axis goes `PENDING → CANCELLED`, which requires
    that the axis is still `PENDING` and that no logistics job on this lease has
    reached `DISPATCHED` or `COMPLETED` — once a crew is on the road, the deal
    is no longer voidable."

    Design: Difficulty/compensating_invariant/activate_then_void_conserves_the_customer_ledger
    """
    ctx = setup_rural_lease()
    activated = validate_success(
        api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers()))
    assert activated["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"]
    assert get_customer(ctx["customer"]["id"])["outstanding_balance_cents"] == (
        RURAL["ACTIVATION_CHARGE_CENTS"])

    voided = validate_success(api.void_lease(
        ctx["lease"]["id"], make_leasing_agent_headers(),
        {"void_reason": "Customer cancelled the project"}))

    assert voided["occupancy_status"] == "CANCELLED", (
        f"Expected CANCELLED occupancy, got {voided['occupancy_status']}")
    assert voided["billing_status"] == "VOIDED", (
        f"Expected VOIDED billing, got {voided['billing_status']}")
    assert voided["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        "voiding credits back rather than erasing what was billed")
    assert voided["credited_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"credited_cents must exactly reverse the charge; expected 478565, got "
        f"{voided['credited_cents']}")


def test_voiding_releases_the_unit_and_zeroes_the_customer_exposure(api):
    """PRD §2.11: "A customer's `outstanding_balance_cents` is not a stored
    running total that gets nudged; it is recomputed as the sum, over every
    lease belonging to that customer, of that lease's `billed_to_date_cents`
    minus its `credited_cents`, with the leases processed in ascending order of
    their creation timestamp."
    PRD §3.7: "Finally the unit is released `RESERVED → IN_FLEET`, its `version`
    is incremented, and its custody branch's `units_available` and
    `utilization_pct` are recomputed — but only when no **other** lease on that
    same unit still sits at `PENDING` occupancy, because a surviving forward
    booking keeps the unit reserved."

    Design: Difficulty/compensating_invariant/activate_then_void_conserves_the_customer_ledger
    """
    ctx = setup_rural_lease()
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))
    validate_success(api.void_lease(ctx["lease"]["id"], make_leasing_agent_headers(),
                                    {"void_reason": "Customer cancelled the project"}))

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == 0, (
        f"billed minus credited is zero after the reversal, got "
        f"{customer['outstanding_balance_cents']}")
    assert customer["credit_hold"] is False
    assert_credit_hold_consistent(customer)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billed_to_date_cents"] - lease["credited_cents"] == 0, (
        "the voided lease must contribute exactly zero to the credit line")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"the sole PENDING lease is gone, so the unit is released; got "
        f"{unit['status']}")
    branch = get_branch(ctx["branch"]["id"])
    assert branch["units_available"] == 1, (
        f"the released unit is leasable again, got {branch['units_available']}")


# ─── Corner coverage ─────────────────────────────────────────────────────────

def test_activation_beyond_the_credit_limit_is_rejected(api):
    """PRD §3.7: "And the customer must have the headroom to absorb the first
    charge: the customer's current `outstanding_balance_cents` plus the sum of
    the lease's `mobilization_fee_cents`, `monthly_base_rate_cents` and
    `monthly_accessory_rate_cents` must be less than or equal to the customer's
    `credit_limit_cents`, with equality allowed."
    PRD §3.7: "If that sum would exceed the limit, activation is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED` and HTTP 402 — the only 402 in the API, because
    it is the only place where a request fails purely for want of credit."

    Design: Corner/validations/activate_beyond_the_credit_limit_is_rejected
    """
    ctx = setup_rural_lease(customer_overrides={
        "name": "Thin Margin LLC", "billing_email": "ap@thin.test",
        "credit_limit_cents": RURAL["ACTIVATION_CHARGE_CENTS"] - 1})

    response = api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billing_status"] == "UNBILLED", (
        f"the refused activation must leave the money axis UNBILLED, got "
        f"{lease['billing_status']}")
    assert lease["billed_to_date_cents"] == 0, (
        f"nothing may be billed, got {lease['billed_to_date_cents']}")

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == 0
    assert customer["credit_hold"] is False


def test_voiding_an_already_voided_lease_is_rejected(api):
    """PRD §3.9: "Submitting an assessment that is in neither `DRAFT` nor
    `DISPUTED` is refused with `ERR_INVALID_STATE`, and so is voiding a lease
    whose occupancy axis has already left `PENDING`."
    PRD §3.7: "The billing axis goes `UNBILLED → VOIDED` or
    `ACCRUING → VOIDED` depending on where it stood, and in both cases the
    lease's `credited_cents` is set equal to its `billed_to_date_cents`, which
    is an exact reversal of whatever activation charged; on an un-activated
    lease both figures are zero and the reversal is a formality."

    Design: Corner/state_machines/void_an_already_voided_lease_is_rejected
    """
    ctx = setup_rural_lease()
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))
    validate_success(api.void_lease(ctx["lease"]["id"], make_leasing_agent_headers(),
                                    {"void_reason": "Project cancelled"}))

    second = api.void_lease(ctx["lease"]["id"], make_leasing_agent_headers(),
                            {"void_reason": "Second attempt"})
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["credited_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"the refused second void must not double the credit; expected 478565, "
        f"got {lease['credited_cents']}")
    assert get_customer(ctx["customer"]["id"])["outstanding_balance_cents"] == 0
    assert get_unit(ctx["unit"]["id"])["status"] == "IN_FLEET"


def test_activation_response_already_carries_the_updated_ledger(api):
    """PRD §3.7: "On success the lease's `billed_to_date_cents` is set to that
    same sum of mobilization fee, monthly base rate and monthly accessory rate;
    the customer's `outstanding_balance_cents` and `credit_hold` are recomputed
    as §2.11 prescribes; and the lease's `version` is incremented."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/activation_response_already_carries_the_updated_ledger
    """
    ctx = setup_rural_lease()

    activated = validate_success(
        api.activate_lease(ctx["lease"]["id"], make_leasing_agent_headers()))
    assert activated["billing_status"] == "ACCRUING", (
        "the activate response body itself must already show the new axis")
    assert activated["billed_to_date_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"the activate response body itself must already show 478565 billed, got "
        f"{activated['billed_to_date_cents']}")

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == RURAL["ACTIVATION_CHARGE_CENTS"], (
        f"the very next read must already show the exposure, got "
        f"{customer['outstanding_balance_cents']}")
    assert customer["credit_hold"] is False
    assert get_lease(ctx["lease"]["id"])["occupancy_status"] == "PENDING"


def test_extension_successor_pays_no_mobilization_and_reprices_on_its_own_term(api):
    """PRD §3.7: "The successor names the same customer, unit, jurisdiction,
    floorplan configuration and site address as its parent, records the parent's
    identifier in its own `extends_lease_id`, and takes as its `start_date` the
    day immediately after the parent's `end_date`, from which its own `end_date`
    follows by the usual thirty-days-per-month rule."
    PRD §3.7: "The successor's `mobilization_fee_cents` is 0 and the four-step
    mobilization derivation is skipped entirely — the building is already
    standing on the site, so there is nothing to mobilize."
    PRD §3.7: "Its `monthly_base_rate_cents` is recomputed from scratch using
    the successor's own `term_months` — which is precisely the point of an
    extension, since a longer commitment earns a better term factor — while the
    credit factor is taken from the parent's `pinned_credit_tier` rather than
    from the customer's present standing — the successor's own
    `pinned_credit_tier` carries that same inherited value."
    PRD §3.7: "Because the building is already installed, the successor is born
    with `occupancy_status` at `INSTALLED` and `billing_status` at `UNBILLED`,
    so it still has to be activated in its own right before anything is
    charged."

    Design: Corner/calculations/extension_successor_pays_no_mobilization_and_reprices_on_its_own_term
    """
    ctx = setup_dallas_installed_lease()

    response = api.extend_lease(ctx["lease"]["id"], {"term_months": 6},
                                make_leasing_agent_headers())
    successor = validate_success(response, 201)
    assert_lease(successor)

    assert successor["extends_lease_id"] == ctx["lease"]["id"]
    assert successor["start_date"] == "2027-08-27", (
        f"the successor must start the day after the parent's 2027-08-26 end, "
        f"got {successor['start_date']}")
    assert successor["end_date"] == "2028-02-22", (
        f"Expected a 6-month term to run to 2028-02-22, got "
        f"{successor['end_date']}")
    assert successor["mobilization_fee_cents"] == 0, (
        f"the successor mobilizes nothing, got "
        f"{successor['mobilization_fee_cents']}")
    assert successor["monthly_base_rate_cents"] == 164_598, (
        f"a 6-month term earns the 1.10 factor: expected 164598, got "
        f"{successor['monthly_base_rate_cents']}")
    assert successor["monthly_accessory_rate_cents"] == 0, (
        "no accessory package has been attached to the successor")
    assert successor["quoted_total_cents"] == 987_588, (
        f"Expected 164598 * 6 = 987588 with no mobilization, got "
        f"{successor['quoted_total_cents']}")
    assert successor["occupancy_status"] == "INSTALLED", (
        f"Expected the successor to be born INSTALLED, got "
        f"{successor['occupancy_status']}")
    assert successor["billing_status"] == "UNBILLED", (
        f"Expected the successor to be born UNBILLED, got "
        f"{successor['billing_status']}")
    assert successor["pinned_credit_tier"] == "GOLD", (
        f"the parent's pinned tier is inherited, got "
        f"{successor['pinned_credit_tier']}")
    assert get_unit(ctx["unit"]["id"])["status"] == "ON_LEASE"


def test_second_extension_on_the_same_lease_is_rejected(api):
    """PRD §3.7: "A lease may carry at most one successor whose occupancy axis
    is not `CANCELLED`; a second attempt is refused with
    `ERR_LEASE_ALREADY_EXTENDED`."
    PRD §2.9: "The **first** check that fails decides the response, its error
    code is returned, and no lower-ranked check is consulted — this is what
    makes error responses predictable when a request is wrong in more than one
    way at once."

    Design: Corner/validations/second_extension_on_the_same_lease_is_rejected
    """
    ctx = setup_dallas_installed_lease()
    successor = extend_lease(ctx["lease"]["id"], 6)
    assert successor["start_date"] == "2027-08-27"

    second = api.extend_lease(ctx["lease"]["id"], {"term_months": 3},
                              make_leasing_agent_headers())
    validate_error(second, ApiErrorId.ERR_LEASE_ALREADY_EXTENDED.value)
    assert second.json()["data"]["error_id"] != "ERR_UNIT_OCCUPANCY_CONFLICT", (
        "the rank-18 successor check must pre-empt the rank-20 occupancy "
        "calendar")

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(),
        params={"extends_lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 1, (
        f"Expected exactly one successor, got {meta['total_count']}")


def test_backdated_extension_is_rejected_as_not_contiguous(api):
    """PRD §3.7: "The derived successor start day must not fall before the
    logical clock's calendar date — a handoff cannot be back-dated onto a term
    that has already run out — and an attempt to do so is refused with
    `ERR_EXTENSION_NOT_CONTIGUOUS`."
    PRD §2.6: "Everything derived from "today" reads this clock: the
    `submitted_on` stamp on a permit application, the `decided_on` stamp on a
    permit decision, the `actual_vacated_date` stamp on a lease whose building
    has come home, the permit lead-time arithmetic, and the contiguity check on
    a lease extension."

    Design: Corner/validations/backdated_extension_is_rejected_as_not_contiguous
    """
    ctx = setup_dallas_installed_lease()
    assert ctx["lease"]["end_date"] == "2027-08-26"

    # The only contiguous handoff day is 2027-08-27, already in the past.
    set_clock("2027-09-15T00:00:00Z")
    response = api.extend_lease(ctx["lease"]["id"], {"term_months": 6},
                                make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_EXTENSION_NOT_CONTIGUOUS.value)

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(),
        params={"extends_lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no successor may be created, got {meta['total_count']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["end_date"] == "2027-08-26"
    assert lease["occupancy_status"] == "INSTALLED"


def test_leases_can_be_traced_through_the_extends_lease_id_filter(api):
    """PRD §3.4: "Leases may be listed and narrowed by `customer_id`, by
    `unit_id`, by `jurisdiction_id`, by `floorplan_configuration_id`, by the
    self-referential `extends_lease_id` (which is how the successor chain on a
    unit is traced), by `occupancy_status`, and by `billing_status`."
    PRD §3.7: "The successor names the same customer, unit, jurisdiction,
    floorplan configuration and site address as its parent, records the parent's
    identifier in its own `extends_lease_id`, and takes as its `start_date` the
    day immediately after the parent's `end_date`, from which its own `end_date`
    follows by the usual thirty-days-per-month rule."

    Design: Corner/endpoints/list_leases_filtered_by_extends_lease_id_finds_the_successor
    """
    ctx = setup_dallas_installed_lease()
    successor = extend_lease(ctx["lease"]["id"], 6)

    chain, chain_meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(),
        params={"extends_lease_id": ctx["lease"]["id"]}))
    assert chain_meta["total_count"] == 1, (
        f"Expected one successor row, got {chain_meta['total_count']}")
    assert chain[0]["id"] == successor["id"], (
        "the extends_lease_id filter must return the successor itself")

    _, unit_meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert unit_meta["total_count"] == 2, (
        f"Expected parent and successor on the unit, got "
        f"{unit_meta['total_count']}")

    assert get_lease(successor["id"])["extends_lease_id"] == ctx["lease"]["id"]
    assert get_lease(ctx["lease"]["id"])["extends_lease_id"] is None


def test_occupancy_conflict_is_reported_before_the_credit_hold(api):
    """PRD §2.9: "The **first** check that fails decides the response, its error
    code is returned, and no lower-ranked check is consulted — this is what
    makes error responses predictable when a request is wrong in more than one
    way at once."
    PRD §3.4: "A candidate interval is therefore rejected with
    `ERR_UNIT_OCCUPANCY_CONFLICT` whenever its first day falls on or before
    fourteen days after an existing interval's last day **and** its last day
    falls on or after fourteen days before that existing interval's first day."
    PRD §3.4: "A lessee already over its limit may not take on new obligations:
    if the customer's `credit_hold` is true, the quote is refused with
    `ERR_CUSTOMER_ON_CREDIT_HOLD`."

    Design: Corner/validations/occupancy_conflict_outranks_credit_hold_then_hold_blocks_the_clear_date
    """
    ctx = setup_rural_finalized_assessment(
        customer_overrides={"credit_limit_cents": 500_000})

    customer = get_customer(ctx["customer"]["id"])
    assert customer["outstanding_balance_cents"] == 1_097_265, (
        f"Expected the settlement to leave 1097265 outstanding, got "
        f"{customer['outstanding_balance_cents']}")
    assert customer["credit_hold"] is True, (
        "1097265 is strictly over the 500000 limit, so the hold must be on")
    assert customer["credit_tier"] == "WATCH", (
        f"the false-to-true hold flip demotes the tier, got "
        f"{customer['credit_tier']}")

    # 2026-10-25 falls inside the fourteen-day window behind the 2026-10-20
    # vacate, so the calendar decides at rank 20.
    inside_buffer = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address=RURAL_SITE, start_date="2026-10-25",
                             term_months=6),
        make_leasing_agent_headers())
    validate_error(inside_buffer, ApiErrorId.ERR_UNIT_OCCUPANCY_CONFLICT.value)

    # 2026-11-04 clears the window, so the request falls through to rank 25.
    clear_of_buffer = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address=RURAL_SITE, start_date="2026-11-04",
                             term_months=6),
        make_leasing_agent_headers())
    validate_error(clear_of_buffer, ApiErrorId.ERR_CUSTOMER_ON_CREDIT_HOLD.value)

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"customer_id": ctx["customer"]["id"]}))
    assert meta["total_count"] == 1, (
        f"neither rejected quote may persist, got {meta['total_count']}")
