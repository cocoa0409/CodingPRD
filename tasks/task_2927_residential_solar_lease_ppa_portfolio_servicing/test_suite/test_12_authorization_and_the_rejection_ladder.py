"""Who may call what, and which of several broken rules is reported.

The first seven rungs of the ladder are all about the caller rather than the
data: authentication, role permission, payload shape, path existence, body
reference existence, homeowner ownership and two-person control. Each of them
fires ahead of every business rule, so a request that is wrong in two ways at
once is answered by the higher rung and nothing is written either way.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import (
    activate,
    book_ppa,
    dispatch,
    make_buyer,
    make_claim,
    make_homeowner,
    make_tariff,
    open_outage,
    read_agreement,
    set_clock,
    submit_claim,
    triage,
)

A1_TERMS = {
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "guarantee_band_pct": 0.05,
}
CLOCK = "2026-08-01T00:00:00Z"


def _draft_ppa(api, homeowner_id, tariff_id, **overrides):
    terms = dict(A1_TERMS)
    terms.update(overrides)
    return book_ppa(api, homeowner_id, tariff_id, **terms)


def _active_ppa(api, homeowner_id, tariff_id, **overrides):
    agreement = _draft_ppa(api, homeowner_id, tariff_id, **overrides)
    activate(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def _one_active_ppa(api, clock=CLOCK, **overrides):
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    return owner, _active_ppa(api, owner["id"], schedule["id"], **overrides)


def test_authentication_is_settled_before_the_path_and_before_the_body(api):
    """Five header shapes are all 401, and the clock endpoint needs no headers.

    §2.1: "Every request other than the logical-clock control endpoint must
    carry two headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the capacity in which they act. If either header is
    absent, or is present but carries the empty string, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else —
    before the role is examined, before the path identifiers are resolved, and
    before the request body is even parsed." §2.5: "This endpoint sits
    deliberately outside the `/servicing` prefix and outside the authentication
    rules: headers are not required on it, and when they are supplied they are
    ignored."

    Design: Corner/rbac/missing_or_empty_auth_headers_are_unauthenticated_before_anything_else
    """
    echoed = set_clock(api, CLOCK)
    # §2.5 pins the instant the endpoint reports back, not its sub-second width;
    # every instant comparison in this suite is made on the canonical form.
    assert_instant_equals(echoed, CLOCK, "echoed current_utc")

    for _label, headers in U.AUTH_FAILURE_HEADER_VARIANTS:
        validate_error(
            api.list_agreements(headers), E.ERR_UNAUTHENTICATED, 401
        )

    # An unresolvable path id would be 404 for an authenticated caller.
    unresolvable = api.get_agreement(NON_EXISTENT_UUID, U.no_headers())
    validate_error(unresolvable, E.ERR_UNAUTHENTICATED, 401)
    assert unresolvable.status_code != 404

    # A body missing `period_month` would be 400 for an authenticated caller.
    malformed = api.create_period(
        {"agreement_id": NON_EXISTENT_UUID, "period_year": 2026}, U.no_headers()
    )
    validate_error(malformed, E.ERR_UNAUTHENTICATED, 401)
    assert malformed.status_code != 400

    _, meta = validate_paginated(api.list_agreements(U.admin_headers()))
    assert meta["total_count"] == 0


def test_no_role_inherits_another_roles_exclusive_operation(api):
    """Ten cross-role attempts, ten 403s, and an admin that is not a superuser.

    §2.1: "Each endpoint in §4 lists the roles authorised to invoke it. A
    request whose `X-User-Role` is not in that endpoint's list — including a value
    that is not one of the six role names at all — is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403). Authorisation is decided before the body is
    validated, so a forbidden role that also submits a malformed payload receives
    the 403 rather than a schema error." §2.1: "it does not inherit the
    `CreditUnderwriter`'s credit review, the `TitleAgent`'s three title
    operations, or the `FieldOpsCoordinator`'s triage, dispatch, completion,
    roof-handling and claim-submission operations."

    Design: Corner/rbac/each_role_reaching_for_another_roles_exclusive_operation_is_unauthorized
    """
    set_clock(api, CLOCK)

    attempts = [
        api.create_tariff(F.tariff_payload(), U.agent_headers()),
        api.run_credit_review(NON_EXISTENT_UUID, U.admin_headers()),
        api.clear_title(NON_EXISTENT_UUID, U.admin_headers()),
        api.create_transfer_case(
            F.prepayment_payload(NON_EXISTENT_UUID, "2026-09-15"),
            U.underwriter_headers(),
        ),
        api.triage_outage_event(NON_EXISTENT_UUID, U.agent_headers()),
        api.reconcile_period(NON_EXISTENT_UUID, None, U.ops_headers()),
        api.execute_election(NON_EXISTENT_UUID, U.agent_headers()),
        api.remove_panels(NON_EXISTENT_UUID, U.admin_headers()),
        api.create_agreement(
            F.ppa_agreement_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            U.homeowner_headers(NON_EXISTENT_UUID),
        ),
        api.list_agreements(U.unknown_role_headers()),
    ]

    for response in attempts:
        validate_error(response, E.ERR_UNAUTHORIZED, 403)
        assert response.status_code not in (400, 404)

    _, tariffs = validate_paginated(api.list_tariffs(U.admin_headers()))
    assert tariffs["total_count"] == 0
    _, agreements = validate_paginated(api.list_agreements(U.admin_headers()))
    assert agreements["total_count"] == 0


def _two_owners_with_their_own_sites(api):
    """Two homeowners, one schedule, one ACTIVE agreement each, one month on the second."""
    set_clock(api, CLOCK)
    schedule = make_tariff(api)
    first = make_homeowner(api)
    second = make_buyer(api)
    mine = _active_ppa(api, first["id"], schedule["id"])
    theirs = _active_ppa(
        api,
        second["id"],
        schedule["id"],
        site_address="44 Juniper Ct, Fremont, CA",
    )
    their_month = validate_success(
        api.create_period(
            F.period_payload(theirs["id"], 2026, 6, 950), U.agent_headers()
        ),
        201,
    )
    return first, mine, second, theirs, their_month


def test_a_homeowner_may_not_reach_a_peers_agreement_or_its_children(api):
    """The identical request is 200 on my roof and 403 on the neighbour's.

    §2.1: "On every endpoint whose authorised-role list includes `Homeowner`, a
    request presenting `X-User-Role` of `Homeowner` is rejected with
    `ERR_NOT_AGREEMENT_HOMEOWNER` (HTTP 403) when the resolved target agreement's
    `homeowner_id` is not the acting user's own homeowner id. A homeowner may read
    and act only on their own agreement and that agreement's children". §2.1:
    "Operator roles are not subject to this check."

    Design: Corner/rbac/homeowner_touching_another_homeowners_agreement_is_forbidden
    """
    first, mine, _, theirs, their_month = _two_owners_with_their_own_sites(api)
    intruder = U.homeowner_headers(first["id"])

    validate_error(
        api.get_agreement(theirs["id"], intruder),
        E.ERR_NOT_AGREEMENT_HOMEOWNER,
        403,
    )
    validate_error(
        api.savings_projection(theirs["id"], intruder),
        E.ERR_NOT_AGREEMENT_HOMEOWNER,
        403,
    )
    validate_error(
        api.get_period(their_month["id"], intruder),
        E.ERR_NOT_AGREEMENT_HOMEOWNER,
        403,
    )
    validate_error(
        api.create_roof_work_order(
            F.roof_work_order_payload(theirs["id"], "2026-08-10", "2026-09-05"),
            intruder,
        ),
        E.ERR_NOT_AGREEMENT_HOMEOWNER,
        403,
    )

    _, orders = validate_paginated(api.list_roof_work_orders(U.admin_headers()))
    assert orders["total_count"] == 0

    own = validate_success(api.get_agreement(mine["id"], intruder), 200)
    assert own["id"] == mine["id"]
    assert own["homeowner_id"] == first["id"]
    validate_success(api.savings_projection(mine["id"], intruder), 200)

    # The same two reads by an operator role are not scoped at all.
    validate_success(api.get_agreement(theirs["id"], U.agent_headers()), 200)
    validate_success(api.get_period(their_month["id"], U.agent_headers()), 200)


def test_the_shared_agreement_read_is_open_to_six_roles_and_the_projection_to_three(api):
    """The allowed set is per endpoint: six on the row, three on the projection.

    §4: "The `Authorized Role(s)` column is exhaustive: a caller presenting any
    other role in `X-User-Role` receives `ERR_UNAUTHORIZED`". §4: "| GET |
    `/servicing/agreements/{agreement_id}` | Reads one agreement, including all
    three state dimensions and the credit counters. | PortfolioAdmin,
    ServicingAgent, CreditUnderwriter, TitleAgent, FieldOpsCoordinator, Homeowner
    |" §4: "| GET | `/servicing/agreements/{agreement_id}/savings-projection` |
    Computes the twelve-month utility-versus-solar savings projection without
    mutating anything. | PortfolioAdmin, ServicingAgent, Homeowner |"

    Design: Corner/rbac/shared_read_of_one_agreement_succeeds_for_every_role_that_declares_it
    """
    owner, agreement = _one_active_ppa(api)
    version = agreement["version"]

    readers = [
        U.agent_headers(),
        U.underwriter_headers(),
        U.title_headers(),
        U.ops_headers(),
        U.admin_headers(),
        U.homeowner_headers(owner["id"]),
    ]
    views = [
        validate_success(api.get_agreement(agreement["id"], headers), 200)
        for headers in readers
    ]
    for view in views:
        assert view == views[0]
        assert view["version"] == version

    for headers in (U.admin_headers(), U.agent_headers(), U.homeowner_headers(owner["id"])):
        projection = validate_success(
            api.savings_projection(agreement["id"], headers), 200
        )
        assert projection["agreement_id"] == agreement["id"]

    for headers in (U.underwriter_headers(), U.title_headers(), U.ops_headers()):
        validate_error(
            api.savings_projection(agreement["id"], headers),
            E.ERR_UNAUTHORIZED,
            403,
        )

    assert read_agreement(api, agreement["id"])["version"] == version


DETECTED_AT = "2026-07-31T09:00:00Z"
WINDOW_START = "2026-08-01T08:00:00Z"
WINDOW_END = "2026-08-01T12:00:00Z"
MANUFACTURER_LABOR_CENTS = 52000


def _scheduled_visit(api):
    """A SCHEDULED dispatch created by the first coordinator on a live alarm."""
    _, agreement = _one_active_ppa(api)
    event = triage(api, open_outage(api, agreement["id"], DETECTED_AT)["id"])
    roll = dispatch(
        api, event, WINDOW_START, WINDOW_END, U.ops_headers(U.OPS_1)
    )
    assert roll["status"] == C.ROLL_SCHEDULED
    assert roll["dispatched_by_user_id"] == U.OPS_1
    assert roll["diagnosed_by_user_id"] is None
    assert roll["billable_to"] is None
    assert roll["labor_cost_cents"] == 0
    return agreement, event, roll


def test_the_dispatcher_may_not_close_out_the_visit_they_created(api):
    """Two-person control inside one role: the same body fails then succeeds.

    §3.6: "Closing out a dispatch is exclusive to the `FieldOpsCoordinator`, and
    it may not be done by the same `X-User-ID` that created the dispatch — the user
    recorded in `dispatched_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`,
    and that refusal precedes any state check." §3.6: "`INVERTER_FAULT` and
    `MODULE_DEFECT` both set `billable_to` to `PENDING_MANUFACTURER` with
    `labor_cost_cents` of 52000 and leave the outage unexcused".

    Design: Corner/rbac/the_dispatching_user_cannot_close_out_their_own_truck_roll
    """
    _, event, roll = _scheduled_visit(api)
    body = F.complete_payload(
        C.DISPOSITION_SERVICE_COMPLETE, C.CAUSE_INVERTER_FAULT
    )

    validate_error(
        api.complete_truck_roll(roll["id"], body, U.ops_headers(U.OPS_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    blocked = validate_success(api.get_truck_roll(roll["id"], U.ops_headers()), 200)
    assert blocked["status"] == C.ROLL_SCHEDULED
    assert blocked["billable_to"] is None
    assert blocked["labor_cost_cents"] == 0
    assert blocked["version"] == roll["version"]

    completed = validate_success(
        api.complete_truck_roll(roll["id"], body, U.ops_headers(U.OPS_2)), 200
    )
    assert completed["status"] == C.ROLL_COMPLETED
    assert completed["diagnosed_by_user_id"] == U.OPS_2
    assert completed["dispatched_by_user_id"] == U.OPS_1
    assert completed["root_cause"] == C.CAUSE_INVERTER_FAULT
    assert completed["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER
    assert completed["labor_cost_cents"] == MANUFACTURER_LABOR_CENTS

    resolved = validate_success(
        api.get_outage_event(event["id"], U.ops_headers()), 200
    )
    assert resolved["status"] == C.OUTAGE_RESOLVED
    assert resolved["excused"] is False


def _submitted_claim(api):
    """A SUBMITTED inverter claim on a completed visit, submitted by OPS_1."""
    _, _, roll = _scheduled_visit(api)
    completed = validate_success(
        api.complete_truck_roll(
            roll["id"],
            F.complete_payload(
                C.DISPOSITION_SERVICE_COMPLETE, C.CAUSE_INVERTER_FAULT
            ),
            U.ops_headers(U.OPS_2),
        ),
        200,
    )
    assert completed["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER

    claim = make_claim(
        api,
        roll["id"],
        component_install_date="2020-06-01",
        claim_amount_cents=MANUFACTURER_LABOR_CENTS,
    )
    assert claim["status"] == C.CLAIM_DRAFT
    assert claim["warranty_term_years"] == 10
    assert claim["warranty_expires_on"] == "2030-05-31"
    assert claim["revision_count"] == 0

    submitted = submit_claim(api, claim["id"], U.ops_headers(U.OPS_1))
    assert submitted["status"] == C.CLAIM_SUBMITTED
    assert submitted["submitted_by_user_id"] == U.OPS_1
    return roll, submitted


def test_the_submitter_may_ask_for_information_but_may_never_decide(api):
    """Approve and deny are barred; request-info is not on the two-person list.

    §3.6: "Decisions are open to the same two roles, and both are guarded against
    the submitting user: the `X-User-ID` recorded in `submitted_by_user_id` may not
    decide the claim, and an attempt yields `ERR_SEGREGATION_OF_DUTIES`." §2.10 rung
    7: "**Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES`, HTTP 403, on the
    five two-person operations listed in §2.1 — voiding a true-up, closing out a
    truck roll, recording a subordination, and approving or denying a warranty
    claim." §3.6: "A claim that came back with questions moves `INFO_REQUESTED →
    SUBMITTED`, incrementing `revision_count` by one, re-stamping
    `submitted_by_user_id`, and clearing `info_request_note` back to null."

    Design: Corner/rbac/the_submitting_user_cannot_decide_their_own_warranty_claim
    """
    roll, submitted = _submitted_claim(api)
    approval = F.approval_payload(MANUFACTURER_LABOR_CENTS)

    validate_error(
        api.approve_warranty_claim(submitted["id"], approval, U.ops_headers(U.OPS_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.deny_warranty_claim(submitted["id"], U.ops_headers(U.OPS_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    still_open = validate_success(
        api.get_warranty_claim(submitted["id"], U.ops_headers()), 200
    )
    assert still_open["status"] == C.CLAIM_SUBMITTED
    assert still_open["decided_by_user_id"] is None
    assert still_open["approved_amount_cents"] is None

    returned = validate_success(
        api.request_claim_info(
            submitted["id"], F.info_request_payload(), U.ops_headers(U.OPS_1)
        ),
        200,
    )
    assert returned["status"] == C.CLAIM_INFO_REQUESTED

    again = submit_claim(api, submitted["id"], U.ops_headers(U.OPS_1))
    assert again["status"] == C.CLAIM_SUBMITTED
    assert again["revision_count"] == 1
    assert again["submitted_by_user_id"] == U.OPS_1
    assert again["info_request_note"] is None

    assert (
        validate_success(api.get_truck_roll(roll["id"], U.ops_headers()), 200)[
            "billable_to"
        ]
        == C.BILLABLE_PENDING_MANUFACTURER
    )

    approved = validate_success(
        api.approve_warranty_claim(submitted["id"], approval, U.ops_headers(U.OPS_2)),
        200,
    )
    assert approved["status"] == C.CLAIM_APPROVED
    assert approved["decided_by_user_id"] == U.OPS_2
    assert approved["approved_amount_cents"] == MANUFACTURER_LABOR_CENTS
    assert (
        validate_success(api.get_truck_roll(roll["id"], U.ops_headers()), 200)[
            "billable_to"
        ]
        == C.BILLABLE_WARRANTY
    )


def test_each_collection_answers_an_unknown_path_id_with_its_own_code(api):
    """Twelve collections, twelve distinct 404 codes, and no generic fallback.

    §2.4: "Where an endpoint's path carries an identifier — `{homeowner_id}`,
    `{tariff_id}`, `{agreement_id}`, `{period_id}`, `{true_up_id}`,
    `{outage_event_id}`, `{truck_roll_id}`, `{roof_work_order_id}`,
    `{transfer_case_id}`, `{ucc_filing_id}`, `{election_id}` or
    `{warranty_claim_id}` — that identifier must name an existing row of the
    corresponding collection, or the request fails with that collection's
    not-found code: `ERR_HOMEOWNER_NOT_FOUND`, `ERR_TARIFF_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_TRUE_UP_NOT_FOUND`,
    `ERR_OUTAGE_EVENT_NOT_FOUND`, `ERR_TRUCK_ROLL_NOT_FOUND`,
    `ERR_ROOF_WORK_ORDER_NOT_FOUND`, `ERR_TRANSFER_CASE_NOT_FOUND`,
    `ERR_UCC_FILING_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND` or
    `ERR_WARRANTY_CLAIM_NOT_FOUND`, each with HTTP 404." §2.10 rung 4: "**Path
    resource existence.** HTTP 404 with the not-found code of the collection named
    by the path segment, as listed in §2.4." §2.2: "The `error_id` is a unique,
    machine-readable string that identifies the specific error." §2.2: "The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
    """
    set_clock(api, CLOCK)
    missing = NON_EXISTENT_UUID

    reads = [
        (api.get_homeowner(missing, U.agent_headers()), E.ERR_HOMEOWNER_NOT_FOUND),
        (api.get_tariff(missing, U.agent_headers()), E.ERR_TARIFF_NOT_FOUND),
        (api.get_agreement(missing, U.agent_headers()), E.ERR_AGREEMENT_NOT_FOUND),
        (api.get_period(missing, U.agent_headers()), E.ERR_PERIOD_NOT_FOUND),
        (api.get_true_up(missing, U.agent_headers()), E.ERR_TRUE_UP_NOT_FOUND),
        (api.get_outage_event(missing, U.ops_headers()), E.ERR_OUTAGE_EVENT_NOT_FOUND),
        (api.get_truck_roll(missing, U.ops_headers()), E.ERR_TRUCK_ROLL_NOT_FOUND),
        (
            api.get_roof_work_order(missing, U.agent_headers()),
            E.ERR_ROOF_WORK_ORDER_NOT_FOUND,
        ),
        (
            api.get_transfer_case(missing, U.agent_headers()),
            E.ERR_TRANSFER_CASE_NOT_FOUND,
        ),
        (api.get_ucc_filing(missing, U.title_headers()), E.ERR_UCC_FILING_NOT_FOUND),
        (api.get_election(missing, U.agent_headers()), E.ERR_ELECTION_NOT_FOUND),
        (
            api.get_warranty_claim(missing, U.ops_headers()),
            E.ERR_WARRANTY_CLAIM_NOT_FOUND,
        ),
    ]
    for response, expected in reads:
        body = validate_error(response, expected, 404)
        assert body["error_id"] == expected
        assert body["message"].strip() != ""

    # The same unknown id on an action endpoint answers on the same rung.
    validate_error(
        api.reconcile_period(missing, None, U.agent_headers()),
        E.ERR_PERIOD_NOT_FOUND,
        404,
    )
    validate_error(
        api.accept_election(missing, U.agent_headers()),
        E.ERR_ELECTION_NOT_FOUND,
        404,
    )


def test_an_unknown_body_reference_outranks_every_business_rule(api):
    """Five bodies name a missing parent, and none of them reaches its own rule.

    §2.4: "A body reference that is syntactically acceptable but names no
    existing row produces the same not-found code for the referenced collection —
    an unresolvable `homeowner_id` or `buyer_homeowner_id` yields
    `ERR_HOMEOWNER_NOT_FOUND`, an unresolvable `tariff_id` yields
    `ERR_TARIFF_NOT_FOUND`, an unresolvable `agreement_id` yields
    `ERR_AGREEMENT_NOT_FOUND`, an unresolvable `outage_event_id` yields
    `ERR_OUTAGE_EVENT_NOT_FOUND`, and an unresolvable `truck_roll_id` yields
    `ERR_TRUCK_ROLL_NOT_FOUND`." §2.10 rung 5: "**Body reference existence.** HTTP
    404 with the not-found code of the collection named by the unresolvable foreign
    key in the body, evaluated only after every path identifier has resolved and in
    the endpoint's declared input order."

    Design: Corner/errors/unknown_body_reference_ids_return_not_found_before_any_business_rule
    """
    set_clock(api, CLOCK)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = _active_ppa(api, owner["id"], schedule["id"])
    event = triage(api, open_outage(api, agreement["id"], DETECTED_AT)["id"])
    missing = NON_EXISTENT_UUID

    validate_error(
        api.create_agreement(
            F.ppa_agreement_payload(missing, schedule["id"]), U.agent_headers()
        ),
        E.ERR_HOMEOWNER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_agreement(
            F.ppa_agreement_payload(owner["id"], missing), U.agent_headers()
        ),
        E.ERR_TARIFF_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_period(F.period_payload(missing, 2026, 6, 950), U.agent_headers()),
        E.ERR_AGREEMENT_NOT_FOUND,
        404,
    )

    # A real version number belonging to a different event: still 404, not 412.
    stale_dispatch = api.create_truck_roll(
        F.truck_roll_payload(missing, WINDOW_START, WINDOW_END, event["version"]),
        U.ops_headers(),
    )
    validate_error(stale_dispatch, E.ERR_OUTAGE_EVENT_NOT_FOUND, 404)
    assert stale_dispatch.status_code != 412

    # The claim would also have failed the claimability rule of §3.6.
    validate_error(
        api.create_warranty_claim(
            F.warranty_claim_payload(missing), U.ops_headers()
        ),
        E.ERR_TRUCK_ROLL_NOT_FOUND,
        404,
    )

    _, agreements = validate_paginated(api.list_agreements(U.admin_headers()))
    assert agreements["total_count"] == 1
    _, periods = validate_paginated(api.list_periods(U.admin_headers()))
    assert periods["total_count"] == 0
    _, rolls = validate_paginated(api.list_truck_rolls(U.ops_headers()))
    assert rolls["total_count"] == 0
    _, claims = validate_paginated(api.list_warranty_claims(U.ops_headers()))
    assert claims["total_count"] == 0


def test_five_shapes_of_malformed_payload_all_answer_with_one_code(api):
    """A missing field, a bad enum, a date where an instant belongs, a negative
    reading and an oversized page are one and the same rejection.

    §2.10 rung 3: "**Payload shape and domain.** `ERR_INVALID_REQUEST`, HTTP 400,
    on every endpoint that accepts a body or query parameters. This rung covers a
    required input field that is missing or null; a field supplied by the client
    that the endpoint computes or the system owns; a value of the wrong JSON type;
    an enumeration value outside its declared set; a string outside its declared
    length; a numeric value outside its declared range — including negative money, a
    `fico_score` outside 300 through 850, a `dti_ratio` outside 0 through 1, a
    `guarantee_band_pct` outside 0 through 0.2, an `escalator_pct` outside 0 through
    0.05, a `period_month` outside 1 through 12, and a `term_years` that is not 10,
    15, 20 or 25; a date or instant that is not valid ISO 8601; and a `limit`
    outside 1 through 100 or a negative `offset`." §3.3: "the inverter-reported
    `metered_kwh` for the month, which must be a whole number of kilowatt-hours and
    may not be negative." §3.5: "an `outage_type` of `INVERTER_FAULT`, `COMMS_LOSS`
    or `PRODUCTION_ANOMALY`, and the `detected_at` instant at which monitoring first
    saw the fault."

    Design: Corner/errors/malformed_or_out_of_range_payloads_return_invalid_request
    """
    _, agreement = _one_active_ppa(api)

    validate_error(
        api.create_period(
            {"agreement_id": agreement["id"], "period_year": 2026, "metered_kwh": 950},
            U.agent_headers(),
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_outage_event(
            F.outage_event_payload(
                agreement["id"], "2026-07-30T00:00:00Z", outage_type="SQUIRREL_DAMAGE"
            ),
            U.ops_headers(),
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_outage_event(
            F.outage_event_payload(
                agreement["id"], "2026-07-30", outage_type=C.OUTAGE_TYPE_COMMS_LOSS
            ),
            U.ops_headers(),
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 6, -1), U.agent_headers()
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    for bad_page in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
        validate_error(
            api.list_periods(U.agent_headers(), bad_page),
            E.ERR_INVALID_REQUEST,
            400,
        )

    _, meta = validate_paginated(api.list_periods(U.agent_headers(), {"limit": 100}))
    assert meta["limit"] == 100
    assert meta["total_count"] == 0
    _, events = validate_paginated(api.list_outage_events(U.ops_headers()))
    assert events["total_count"] == 0


def test_every_child_write_against_a_drafted_agreement_is_not_active(api):
    """The specific 409 covers five children, and outranks the election window.

    §2.10 rung 8: "and `ERR_AGREEMENT_NOT_ACTIVE` when a child record is written
    against an agreement whose `lifecycle_state` is `DRAFT`, `PREPAID_CLOSED` or
    `PURCHASED_CLOSED`." §3.7: "As with every other child record, an agreement in
    `DRAFT`, `PREPAID_CLOSED` or `PURCHASED_CLOSED` reports
    `ERR_AGREEMENT_NOT_ACTIVE`". §2.10 rung 11 places `ERR_ELECTION_WINDOW_CLOSED`
    below it, and §2.10: "Evaluation stops at the first violated rung."

    Design: Corner/errors/every_child_write_against_a_draft_agreement_is_rejected_as_not_active
    """
    set_clock(api, CLOCK)
    owner = make_homeowner(api)
    buyer = make_buyer(api)
    schedule = make_tariff(api)
    drafted = _draft_ppa(api, owner["id"], schedule["id"])
    assert drafted["lifecycle_state"] == C.LIFECYCLE_DRAFT

    validate_error(
        api.create_period(
            F.period_payload(drafted["id"], 2026, 6, 950), U.agent_headers()
        ),
        E.ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.create_outage_event(
            F.outage_event_payload(drafted["id"], DETECTED_AT), U.ops_headers()
        ),
        E.ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.create_roof_work_order(
            F.roof_work_order_payload(drafted["id"], "2026-08-10", "2026-09-05"),
            U.agent_headers(),
        ),
        E.ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.create_transfer_case(
            F.assumption_payload(drafted["id"], "2026-09-15", buyer["id"]),
            U.agent_headers(),
        ),
        E.ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    # 2026-08-01 is also far outside the window of a 2025-01-01 twenty-year deal.
    election = api.create_election(
        F.election_payload(drafted["id"], C.ELECTION_PURCHASE), U.agent_headers()
    )
    validate_error(election, E.ERR_AGREEMENT_NOT_ACTIVE, 409)
    assert election.status_code != 422

    activated = validate_success(
        api.activate_agreement(drafted["id"], U.agent_headers()), 200
    )
    assert activated["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    replay = api.activate_agreement(drafted["id"], U.agent_headers())
    validate_error(replay, E.ERR_INVALID_STATE_TRANSITION, 409)

    _, periods = validate_paginated(
        api.list_periods(U.agent_headers(), {"agreement_id": drafted["id"]})
    )
    assert periods["total_count"] == 0
    _, cases = validate_paginated(api.list_transfer_cases(U.agent_headers()))
    assert cases["total_count"] == 0
    _, elections = validate_paginated(api.list_elections(U.agent_headers()))
    assert elections["total_count"] == 0
