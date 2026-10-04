"""Coverage assignments: cross-entity activation gates, closed-interval
exclusivity, cell capacity, supersede, sweep closure, windows and OCC."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
PA = TEST_USERS["pricing_analyst_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]


def test_assignment_activation_requires_active_registration():
    """PRD §3.5: "Activation moves a `PROPOSED` assignment to `ACTIVE` through a battery of gates, in order: the distributor must be `APPROVED` (`ERR_DISTRIBUTOR_NOT_APPROVED`); the current date must lie inside the closed coverage window (`ERR_WINDOW_INVALID`); the line must be `LAUNCHED` (`ERR_LINE_NOT_LAUNCHED`, HTTP 409); when the market's `registration_required` is true, a registration for the assignment's market and line must be `ACTIVE` (`ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409); when the assignment is exclusive, the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409) and its posture not `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409); exclusivity is re-checked against overlapping exclusive `ACTIVE` or `SUSPENDED` assignments on the cell (`ERR_EXCLUSIVE_OVERLAP`); and the cell must currently hold fewer than 3 assignments in `ACTIVE` or `SUSPENDED` — a third coexists, a fourth is refused with `ERR_CELL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_active_registration
    """
    sc = fx.setup_launched_line()
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True)
    reg = fx.create_market_registration_record(
        market["id"], sc["line"]["id"], sc["formulation"]["id"])
    validate_success(api_client.submit_market_registration(reg["id"], RA))

    dist = fx.create_approved_distributor(
        market["id"], legal_name="Deutsche Vertrieb GmbH")
    asg = fx.propose_coverage_assignment(dist["id"], market["id"],
                                         sc["line"]["id"])

    blocked = api_client.activate_coverage_assignment(asg["id"], CM)
    validate_error(blocked, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)

    validate_success(api_client.approve_market_registration(
        reg["id"], "REG-DE-1001", RA))
    activated = api_client.activate_coverage_assignment(asg["id"], CM)
    assert validate_success(activated)["status"] == "ACTIVE"


def test_exclusive_coverage_closed_interval_touch_conflict():
    """PRD §2.9: "Coverage assignments and promotions run on **calendar dates** (`starts_on`, `ends_on`) interpreted as closed intervals: both endpoints are included, so two exclusive assignments whose date ranges merely touch on a single day already overlap."
    PRD §3.5: "If `exclusive` is true, the proposal also conflicts — `ERR_EXCLUSIVE_OVERLAP` (HTTP 409) — with any other assignment on the same market-channel-line **cell** that is itself exclusive, sits in `ACTIVE` or `SUSPENDED`, and overlaps under closed-interval semantics; because the intervals are closed, windows that merely touch on a single date already conflict."
    PRD §3.5: "the new assignment's `supersedes_assignment_id` points at the superseded proposal with the greatest `created_at` — or stays null when nothing was superseded."

    Design: Difficulty/resource_temporal_overlap/exclusive_coverage_closed_interval_touch_conflict
    """
    sc = fx.setup_active_coverage(exclusive=True,
                                  window=("2026-08-01", "2027-02-28"))
    market_id = sc["market"]["id"]
    line_id = sc["line"]["id"]

    d2 = fx.create_approved_distributor(market_id,
                                        legal_name="Second Source Trading",
                                        credit_limit_cents=500000)
    d2_version = d2["version"]

    touching = api_client.create_coverage_assignment(
        d2["id"],
        {"market_id": market_id, "product_line_id": line_id,
         "channel": "HARDWARE", "exclusive": True, "starts_on": "2027-02-28",
         "ends_on": "2027-08-31", "annual_quota_units": 600,
         "expected_distributor_version": d2_version}, CM)
    validate_error(touching, ApiErrorId.ERR_EXCLUSIVE_OVERLAP)

    assert fx.get_distributor_version(d2["id"]) == d2_version, \
        "the rejected proposal did not bump the distributor version"

    next_day = api_client.create_coverage_assignment(
        d2["id"],
        {"market_id": market_id, "product_line_id": line_id,
         "channel": "HARDWARE", "exclusive": True, "starts_on": "2027-03-01",
         "ends_on": "2027-08-31", "annual_quota_units": 600,
         "expected_distributor_version": d2_version}, CM)
    data = validate_success(next_day, 201)
    assert data["status"] == "PROPOSED"
    assert data["supersedes_assignment_id"] is None, \
        "nothing PROPOSED remained on the cell to supersede"


def test_assignment_auto_closes_after_ends_on():
    """PRD §2.4: "Coverage assignments in `ACTIVE` or `SUSPENDED` move to `CLOSED` when the current date passes their `ends_on`."

    Design: Corner/state_machines/assignment_auto_closes_after_ends_on
    """
    sc = fx.setup_active_coverage(window=("2026-08-01", "2026-09-30"))
    assert sc["assignment"]["status"] == "ACTIVE"

    fx.advance_clock("2026-10-01T00:00:00Z")
    after = validate_success(
        api_client.get_coverage_assignment(sc["assignment"]["id"], CM))
    assert after["status"] == "CLOSED"


def test_inverted_windows_rejected_on_assignment_and_promotion():
    """PRD §3.5: "and a sane window — `starts_on` strictly before `ends_on`, and `ends_on` not already past (`ERR_WINDOW_INVALID`, HTTP 422)".
    PRD §3.8: "a closed date window `starts_on` to `ends_on` (`ends_on` may equal `starts_on` but never precede it, and a window entirely past is refused — both faults are `ERR_WINDOW_INVALID`, HTTP 422)".
    PRD §2.6: "Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned — later checks are never reached once an earlier one fails." (temporal arithmetic is rule 10, before referential compatibility at rule 11, so the inverted window is reported even though the line is still in FORMULATION).

    Design: Corner/validations/inverted_windows_rejected_on_assignment_and_promotion
    """
    brand = fx.create_brand()
    line = fx.create_product_line(brand["id"])  # stays FORMULATION
    market = fx.create_market()
    dist = fx.create_approved_distributor(market["id"])

    bad_assignment = api_client.create_coverage_assignment(
        dist["id"],
        {"market_id": market["id"], "product_line_id": line["id"],
         "channel": "HARDWARE", "starts_on": "2027-01-01",
         "ends_on": "2026-01-01", "annual_quota_units": 100,
         "expected_distributor_version": dist["version"]}, CM)
    validate_error(bad_assignment, ApiErrorId.ERR_WINDOW_INVALID)

    bad_promo = api_client.create_promotion(
        {"product_line_id": line["id"], "channel": "HARDWARE",
         "discount_pct": 10.00, "starts_on": "2026-12-01",
         "ends_on": "2026-11-01", "funding_budget_cents": 1000}, PA)
    validate_error(bad_promo, ApiErrorId.ERR_WINDOW_INVALID)


def test_cell_capacity_third_assignment_ok_fourth_fails():
    """PRD §3.5: "and the cell must currently hold fewer than 3 assignments in `ACTIVE` or `SUSPENDED` — a third coexists, a fourth is refused with `ERR_CELL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/errors/cell_capacity_third_assignment_ok_fourth_fails
    """
    sc = fx.setup_launched_line()
    market = fx.create_market()
    # PRD §3.5 supersedes any PROPOSED proposal on the cell at each new create,
    # so the three coexisting occupants must be activated as they are proposed.
    assignments = []
    for i in range(3):
        dist = fx.create_approved_distributor(
            market["id"], legal_name=f"Cell Co {i + 1}")
        asg = fx.create_active_assignment(
            dist["id"], market["id"], sc["line"]["id"], exclusive=False)
        assert asg["status"] == "ACTIVE"
        assignments.append(asg)

    dist4 = fx.create_approved_distributor(market["id"], legal_name="Cell Co 4")
    fourth_asg = fx.propose_coverage_assignment(
        dist4["id"], market["id"], sc["line"]["id"], exclusive=False)

    fourth = api_client.activate_coverage_assignment(fourth_asg["id"], CM)
    validate_error(fourth, ApiErrorId.ERR_CELL_CAPACITY_EXCEEDED)
    stuck = validate_success(
        api_client.get_coverage_assignment(fourth_asg["id"], CM))
    assert stuck["status"] == "PROPOSED"


def test_market_close_blocked_then_succeeds():
    """PRD §3.4: "Closing a market moves it `OPEN` → `CLOSED`; `CLOSED` is terminal, and the close is refused with `ERR_MARKET_IN_USE` (HTTP 409) while either any coverage assignment references it in `PROPOSED`, `ACTIVE` or `SUSPENDED` status, or any registration references it in `DRAFT`, `SUBMITTED`, `ACTIVE` or `RENEWAL_DUE` status."

    Design: Corner/errors/market_close_blocked_then_succeeds
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market()
    dist = fx.create_approved_distributor(market["id"])
    asg = fx.propose_coverage_assignment(dist["id"], market["id"],
                                         sc["line"]["id"])

    blocked = api_client.close_market(market["id"], RA)
    validate_error(blocked, ApiErrorId.ERR_MARKET_IN_USE)

    validate_success(api_client.withdraw_coverage_assignment(asg["id"], CM))
    closed = api_client.close_market(market["id"], RA)
    assert validate_success(closed)["status"] == "CLOSED"


def test_new_proposal_supersedes_proposed_assignment_on_same_cell():
    """PRD §3.5: "Creation has one more side effect: any `PROPOSED` proposals already sitting on the same cell are moved to `SUPERSEDED`, and the new assignment's `supersedes_assignment_id` points at the superseded proposal with the greatest `created_at` — or stays null when nothing was superseded."

    Design: Corner/state_machines/new_proposal_supersedes_proposed_assignment_on_same_cell
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market()
    d1 = fx.create_approved_distributor(market["id"], legal_name="Ace Distribution")
    p1 = fx.propose_coverage_assignment(d1["id"], market["id"], sc["line"]["id"])

    d2 = fx.create_approved_distributor(market["id"], legal_name="Rival Distribution")
    p2 = fx.propose_coverage_assignment(d2["id"], market["id"], sc["line"]["id"],
                                        starts_on="2026-09-01",
                                        ends_on="2027-08-31",
                                        annual_quota_units=200)
    assert p2["supersedes_assignment_id"] == p1["id"]

    old = validate_success(api_client.get_coverage_assignment(p1["id"], CM))
    assert old["status"] == "SUPERSEDED"


def test_occ_stale_version_on_assignment_create():
    """PRD §2.7: "Creating a coverage assignment requires the request to carry `expected_distributor_version`, holding the caller's last observed `version` of the parent distributor. If the distributor's version has advanced since — for example because another writer just created an assignment that superseded a pending proposal on the same cell — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a distributor record it has not observed."
    PRD §2.7: "Both creates themselves mutate the parent's bookkeeping: a successful coverage-assignment creation increments the distributor's `version` by one, and a successful price-list creation increments the pack format's `version` by one."

    Design: Corner/complexity_layers/occ_stale_version_on_assignment_create
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market()
    dist = fx.create_approved_distributor(market["id"])
    observed = dist["version"]

    first = api_client.create_coverage_assignment(
        dist["id"],
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "channel": "HARDWARE", "starts_on": "2026-08-01",
         "ends_on": "2027-07-31", "annual_quota_units": 100,
         "expected_distributor_version": observed}, CM)
    validate_success(first, 201)
    assert fx.get_distributor_version(dist["id"]) == observed + 1, \
        "the successful create incremented the distributor version by one"

    stale = api_client.create_coverage_assignment(
        dist["id"],
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "channel": "HARDWARE", "starts_on": "2026-08-01",
         "ends_on": "2027-07-31", "annual_quota_units": 100,
         "expected_distributor_version": observed}, CM)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    current = fx.get_distributor_version(dist["id"])
    assert current == observed + 1, "the rejected replay did not mutate"

    retry = api_client.create_coverage_assignment(
        dist["id"],
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "channel": "HARDWARE", "starts_on": "2026-08-01",
         "ends_on": "2027-07-31", "annual_quota_units": 100,
         "expected_distributor_version": current}, CM)
    validate_success(retry, 201)
