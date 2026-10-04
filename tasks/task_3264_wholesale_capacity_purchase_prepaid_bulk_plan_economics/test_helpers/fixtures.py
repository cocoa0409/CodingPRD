"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API; the
runner restarts the server before each test, so no state carries over.
"""
from .api_client import api_client as api
from .factories import (
    create_activation_payload,
    create_addon_payload,
    create_agreement_payload,
    create_case_payload,
    create_inventory_payload,
    create_partner_payload,
    create_plan_payload,
    create_subscriber_payload,
    quote_term_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

CLOCK_START = "2026-10-01T00:00:00Z"
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

_MSISDN_SEQ = iter(range(100, 90000))


def next_msisdn():
    return "130" + str(next(_MSISDN_SEQ)).zfill(8)


class Setup(dict):
    """Attribute access over the rows a composite setup produced."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer aid
            raise AttributeError(item) from exc


# ---------------------------------------------------------------------------
# Primitive calls
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_START):
    resp = api.set_clock(TEST_USERS["admin_headers"], current_utc)
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: set clock -> {resp.status_code} {body}"
    return body["data"]


def create_agreement(**overrides):
    resp = api.create_agreement(
        create_agreement_payload(**overrides), TEST_USERS["planner_headers"]
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create agreement -> {resp.status_code} {body}"
    return body["data"]


def create_plan(agreement_id, **overrides):
    resp = api.create_plan(
        create_plan_payload(agreement_id, **overrides), TEST_USERS["planner_headers"]
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create plan -> {resp.status_code} {body}"
    return body["data"]


def offer_plan(plan_id, agreement_version=None):
    payload = {}
    if agreement_version is not None:
        payload["expected_CapacityAgreement_version"] = agreement_version
    resp = api.offer_plan(plan_id, TEST_USERS["planner_headers"], payload)
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: offer plan -> {resp.status_code} {body}"
    return body["data"]


def activate_agreement(agreement_id, agreement_version=None):
    """Drive the DRAFT -> ACTIVE transition explicitly.

    Returns the live agreement row, not the stale input dict, so callers can use its
    `version` as an optimistic-concurrency expectation.
    """
    payload = {}
    if agreement_version is not None:
        payload["expected_CapacityAgreement_version"] = agreement_version
    resp = api.activate_agreement(agreement_id, TEST_USERS["planner_headers"], payload)
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: activate agreement -> {resp.status_code} {body}"
    return body["data"]


def create_subscriber(**overrides):
    resp = api.create_subscriber(
        create_subscriber_payload(**overrides), TEST_USERS["planner_headers"]
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create subscriber -> {resp.status_code} {body}"
    return body["data"]


def create_inventory(**overrides):
    resp = api.create_inventory(
        create_inventory_payload(**overrides), TEST_USERS["planner_headers"]
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create inventory -> {resp.status_code} {body}"
    return body["data"]


def create_partner(**overrides):
    resp = api.create_partner(
        create_partner_payload(**overrides), TEST_USERS["planner_headers"]
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create partner -> {resp.status_code} {body}"
    return body["data"]


def quote_term(subscriber_id, plan_id, agreement_version):
    resp = api.create_term(
        quote_term_payload(subscriber_id, plan_id, agreement_version),
        make_subscriber_headers(subscriber_id),
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: quote term -> {resp.status_code} {body}"
    return body["data"]


def purchase_term(term_id, subscriber_id):
    resp = api.purchase_term(term_id, make_subscriber_headers(subscriber_id))
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: purchase term -> {resp.status_code} {body}"
    return body["data"]


def request_activation(subscriber_id, term_id, **overrides):
    resp = api.create_activation(
        create_activation_payload(subscriber_id, term_id, **overrides),
        make_subscriber_headers(subscriber_id),
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: request activation -> {resp.status_code} {body}"
    return body["data"]


def provision_activation(activation_id):
    resp = api.provision_activation(activation_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: provision -> {resp.status_code} {body}"
    return body["data"]


def complete_activation(activation_id, subscriber_id):
    resp = api.complete_activation(activation_id, make_subscriber_headers(subscriber_id))
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: complete -> {resp.status_code} {body}"
    return body["data"]


def fail_activation(activation_id, reason="SIM_MEDIA_FAULT"):
    resp = api.fail_activation(
        activation_id, TEST_USERS["agent_headers"], {"failure_reason": reason}
    )
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: fail activation -> {resp.status_code} {body}"
    return body["data"]


def submit_port(activation_id, subscriber_id, msisdn, carrier="Cascade Wireless", last4="4471"):
    payload = {
        "porting_msisdn": msisdn,
        "losing_carrier": carrier,
        "account_number_last4": last4,
    }
    resp = api.submit_port(activation_id, make_subscriber_headers(subscriber_id), payload)
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: submit port -> {resp.status_code} {body}"
    return body["data"]


def reject_port(activation_id, rejection_code="E0403"):
    resp = api.reject_port(
        activation_id, TEST_USERS["agent_headers"], {"rejection_code": rejection_code}
    )
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: reject port -> {resp.status_code} {body}"
    return body["data"]


def cancel_port(activation_id, subscriber_id):
    resp = api.cancel_port(activation_id, make_subscriber_headers(subscriber_id))
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: cancel port -> {resp.status_code} {body}"
    return body["data"]


def consume_data(subscriber_id, data_mb):
    resp = api.consume_data(
        subscriber_id, TEST_USERS["planner_headers"], {"data_mb": data_mb}
    )
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: consume_data -> {resp.status_code} {body}"
    return body["data"]


def run_cycle(subscriber_id):
    resp = api.run_cycle(subscriber_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: run_cycle -> {resp.status_code} {body}"
    return body["data"]


def create_case(subscriber_id, topic_code="PORT_STATUS"):
    resp = api.create_case(
        create_case_payload(subscriber_id, topic_code=topic_code),
        make_subscriber_headers(subscriber_id),
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create case -> {resp.status_code} {body}"
    return body["data"]


def create_addon(subscriber_id, **overrides):
    resp = api.create_addon(
        create_addon_payload(subscriber_id, **overrides),
        make_subscriber_headers(subscriber_id),
    )
    body = resp.json()
    assert resp.status_code == 201, f"Setup failed: create add-on -> {resp.status_code} {body}"
    return body["data"]


def activate_addon(addon_id):
    resp = api.activate_addon(addon_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: activate add-on -> {resp.status_code} {body}"
    return body["data"]


def get_summary(agreement_id):
    resp = api.get_usage_summary(agreement_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: usage summary -> {resp.status_code} {body}"
    return body["data"]


def get_subscriber(subscriber_id):
    resp = api.get_subscriber(subscriber_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get subscriber -> {resp.status_code} {body}"
    return body["data"]


def get_activation(activation_id):
    resp = api.get_activation(activation_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get activation -> {resp.status_code} {body}"
    return body["data"]


def get_term(term_id):
    resp = api.get_term(term_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get term -> {resp.status_code} {body}"
    return body["data"]


def get_plan(plan_id):
    resp = api.get_plan(plan_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get plan -> {resp.status_code} {body}"
    return body["data"]


def get_agreement(agreement_id):
    resp = api.get_agreement(agreement_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get agreement -> {resp.status_code} {body}"
    return body["data"]


def get_inventory(inventory_id):
    resp = api.get_inventory(inventory_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get inventory -> {resp.status_code} {body}"
    return body["data"]


def get_case(case_id):
    resp = api.get_case(case_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get case -> {resp.status_code} {body}"
    return body["data"]


def get_addon(addon_id):
    resp = api.get_addon(addon_id, TEST_USERS["planner_headers"])
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: get add-on -> {resp.status_code} {body}"
    return body["data"]


def list_cycles(prepaid_term_id, cycle_status=None):
    params = {"prepaid_term_id": prepaid_term_id}
    if cycle_status is not None:
        params["cycle_status"] = cycle_status
    resp = api.list_cycles(TEST_USERS["planner_headers"], params)
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed: list cycles -> {resp.status_code} {body}"
    return body["data"]


def current_agreement_version(agreement_id):
    return get_agreement(agreement_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

SEED_PLAN_CODE = "SEEDPLAN"
SEED_PLAN_ALLOTMENT_MB = 1


def setup_active_agreement(committed_data_mb=16000, **overrides):
    """Walk an agreement from DRAFT to ACTIVE and return the live row.

    PRD 3.1 admits the DRAFT -> ACTIVE transition "only when the three committed
    volumes are each at least 1 and at least one plan on the agreement is already in
    status `OFFERED`". A bare agreement therefore cannot be activated at all, so the
    helper first registers and offers a throwaway one-megabyte plan. Its distinctive
    plan_code keeps it clear of the plan codes the tests register themselves, and a
    single unsold megabyte leaves the agreement balance untouched.
    """
    agreement = create_agreement(committed_data_mb=committed_data_mb, **overrides)
    seed = create_plan(
        agreement["id"],
        plan_code=SEED_PLAN_CODE,
        data_allotment_mb=SEED_PLAN_ALLOTMENT_MB,
    )
    offer_plan(seed["id"], current_agreement_version(agreement["id"]))
    return activate_agreement(agreement["id"])


def setup_offered_plan(agreement_id, agreement_version=None, **overrides):
    """Create a plan on the agreement and offer it.

    Offering carries an optimistic-concurrency expectation on the parent agreement
    (PRD 2.7), and `create_plan` has just bumped that row's version, so the
    expectation must be read *after* the plan is registered — a version sampled before
    it is already stale and the offer is refused with ERR_STALE_VERSION.
    """
    plan = create_plan(agreement_id, **overrides)
    return offer_plan(plan["id"], current_agreement_version(agreement_id))


def setup_agreement_with_offered_plan(
    committed_data_mb=16000, state_code="CA", **plan_overrides
):
    """Active agreement + one offered plan. Returns (agreement, plan)."""
    agreement = setup_active_agreement(
        committed_data_mb=committed_data_mb, state_code=state_code
    )
    plan = setup_offered_plan(agreement["id"], **plan_overrides)
    # Registering and offering the plan bumped the agreement row, so hand back the
    # live row: callers use the returned dict's `version` as an OCC expectation.
    return get_agreement(agreement["id"]), plan


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_subscriber_with_quoted_term(state_code="CA", **plan_overrides):
    """Active agreement + offered plan + subscriber + QUOTED term."""
    agreement, plan = setup_agreement_with_offered_plan(
        state_code=state_code, **plan_overrides
    )
    subscriber = create_subscriber(state_code=state_code)
    term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
    return agreement, plan, subscriber, term


def setup_subscriber_with_purchased_term(
    state_code="CA", inventory_units=40, **plan_overrides
):
    """... through the purchase transition; the term is PURCHASED."""
    agreement, plan, subscriber, term = setup_subscriber_with_quoted_term(
        state_code=state_code, **plan_overrides
    )
    purchase_term(term["id"], subscriber["id"])
    if inventory_units is not None:
        create_inventory(state_code=state_code, unit_count=inventory_units)
    return agreement, plan, subscriber, get_term(term["id"])


def setup_awaiting_activation(state_code="CA", inventory_units=40, **plan_overrides):
    """... plus an activation in REQUESTED state (term AWAITING_ACTIVATION)."""
    agreement, plan, subscriber, term = setup_subscriber_with_purchased_term(
        state_code=state_code, inventory_units=inventory_units, **plan_overrides
    )
    activation = request_activation(subscriber["id"], term["id"])
    return agreement, plan, subscriber, term, activation


def setup_provisioned_activation(state_code="CA", inventory_units=40, **plan_overrides):
    """... plus a PROVISIONED activation; the subscriber holds HELD capacity."""
    agreement, plan, subscriber, term, activation = setup_awaiting_activation(
        state_code=state_code, inventory_units=inventory_units, **plan_overrides
    )
    provision_activation(activation["id"])
    inventory = api.list_inventories(
        TEST_USERS["planner_headers"], {"state_code": state_code}
    ).json()["data"][0]
    return agreement, plan, subscriber, term, activation, inventory


def setup_activated_subscriber(
    state_code="CA",
    inventory_units=10,
    data_allotment_mb=3000,
    term_months=3,
    intro_price_cents=1999,
    renewal_price_cents=3042,
    committed_data_mb=16000,
    partner_id=None,
    activation_channel="DIGITAL",
    msisdn=None,
):
    """Full happy path: agreement, plan, subscriber, term ACTIVE, cycle 1 open."""
    agreement = setup_active_agreement(
        committed_data_mb=committed_data_mb, state_code=state_code
    )
    if partner_id is None:
        inventory = create_inventory(state_code=state_code, unit_count=inventory_units)
    else:
        inventory = create_inventory(
            state_code=state_code,
            unit_count=inventory_units,
            retail_partner_id=partner_id,
        )
    plan = setup_offered_plan(
        agreement["id"],
        agreement["version"],
        plan_code="H3",
        term_months=term_months,
        intro_price_cents=intro_price_cents,
        renewal_price_cents=renewal_price_cents,
        data_allotment_mb=data_allotment_mb,
    )
    subscriber = create_subscriber(state_code=state_code, **({"msisdn": msisdn} if msisdn else {}))
    term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
    purchase_term(term["id"], subscriber["id"])
    activation_kwargs = {}
    if partner_id is not None:
        activation_kwargs = {
            "activation_channel": activation_channel,
            "retail_partner_id": partner_id,
        }
    activation = request_activation(subscriber["id"], term["id"], **activation_kwargs)
    provision_activation(activation["id"])
    complete_activation(activation["id"], subscriber["id"])
    return Setup(
        agreement=agreement,
        plan=plan,
        subscriber=get_subscriber(subscriber["id"]),
        term=get_term(term["id"]),
        activation=get_activation(activation["id"]),
        inventory=get_inventory(inventory["id"]),
    )


def setup_two_activated_subscribers(state_code="CA", **plan_overrides):
    """Two subscribers activated on the same plan of one agreement."""
    agreement = setup_active_agreement(state_code=state_code)
    create_inventory(state_code=state_code, unit_count=10)
    plan = setup_offered_plan(
        agreement["id"], agreement["version"], **plan_overrides
    )
    created = []
    for _ in range(2):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code=state_code)
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        activation = request_activation(subscriber["id"], term["id"])
        provision_activation(activation["id"])
        complete_activation(activation["id"], subscriber["id"])
        created.append((subscriber, get_term(term["id"]), get_activation(activation["id"])))
    first, second = created
    return Setup(
        agreement=agreement,
        plan=plan,
        subscriber=first[0],
        term=first[1],
        activation=first[2],
        second_subscriber=second[0],
        second_term=second[1],
        second_activation=second[2],
    )


def setup_subscribers_purchased(count=2, plan=None, agreement=None, state_code="CA"):
    """`count` subscribers each holding a purchased (unactivated) term on one plan."""
    agreement = agreement or setup_active_agreement(state_code=state_code)
    create_inventory(state_code=state_code, unit_count=count + 1)
    plan = plan or setup_offered_plan(agreement["id"], agreement["version"])
    holders = []
    for _ in range(count):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code=state_code)
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        holders.append((subscriber, get_term(term["id"])))
    return Setup(agreement=agreement, plan=plan, holders=holders)


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_renewal_due_term(term_months=3, **plan_overrides):
    """An activated term whose every cycle has rolled, landing in RENEWAL_DUE."""
    setup = setup_activated_subscriber(term_months=term_months, **plan_overrides)
    for _ in range(term_months):
        run_cycle(setup["subscriber"]["id"])
    setup["subscriber"] = get_subscriber(setup["subscriber"]["id"])
    setup["term"] = get_term(setup["term"]["id"])
    return setup


def setup_churned_subscriber(state_code="CA", addon=False, cases=(), msisdn=None, **sub_overrides):
    """An activated subscriber who is then churned through its own cancel."""
    setup = setup_activated_subscriber(
        state_code=state_code,
        **({"msisdn": msisdn} if msisdn else {}),
        **sub_overrides,
    )
    addon_row = None
    if addon:
        addon_row = create_addon(
            setup["subscriber"]["id"],
            addon_type="ROAMING",
            addon_days=30,
            per_day_allotment_mb=500,
        )
        activate_addon(addon_row["id"])
    case_rows = []
    for topic, assigned in cases:
        case_row = create_case(setup["subscriber"]["id"], topic_code=topic)
        if assigned:
            api.assign_case(case_row["id"], TEST_USERS["agent_headers"])
        case_rows.append(case_row)
    current = get_subscriber(setup["subscriber"]["id"])
    resp = api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    assert resp.status_code == 200, f"Setup failed: cancel subscriber -> {resp.status_code}"
    setup["addon"] = addon_row
    setup["cases"] = case_rows
    setup["subscriber"] = resp.json()["data"]
    return setup


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_subscriber_with_usage(data_mb, allotment=3000, msisdn=None):
    """Activated subscriber whose open cycle already holds `data_mb` of usage.

    PRD 3.4 arms deprioritization only when the consumption threshold is reached *and*
    the serving agreement's `congestion_active` is true, and PRD 3.1 makes that flag
    true "the moment the index reaches the congestion trigger index". Committing the
    agreement at exactly the sold allotment puts the index at 100 percent, so the
    threshold road is armed and the fixtures exercise the real conjunction.
    """
    setup = setup_activated_subscriber(
        data_allotment_mb=allotment,
        # The sold allotment fills the pipe exactly, putting the congestion index at
        # 100 percent: past any plausible trigger, and still inside the 120 percent
        # oversale ceiling so the sale itself is admissible.
        committed_data_mb=allotment,
        **({"msisdn": msisdn} if msisdn else {}),
    )
    if data_mb:
        consume_data(setup["subscriber"]["id"], data_mb)
    setup["subscriber"] = get_subscriber(setup["subscriber"]["id"])
    return setup


def setup_subscribers_at_oversale_ceiling(committed_data_mb=100000, allotment=3000):
    """Agreement holding exactly the 120 percent oversale ceiling of sold allotment."""
    agreement = setup_active_agreement(committed_data_mb=committed_data_mb)
    create_inventory(state_code="CA", unit_count=200)
    plan = setup_offered_plan(
        agreement["id"], agreement["version"], plan_code="S3", data_allotment_mb=allotment
    )
    holders = []
    for _ in range(40):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        holders.append((subscriber, get_term(term["id"])))
    return Setup(agreement=agreement, plan=plan, holders=holders)


# ---------------------------------------------------------------------------
# Tier 5 — terminal state
# ---------------------------------------------------------------------------

def setup_term_with_rolled_cycles(cycles=1, term_months=3, **plan_overrides):
    """Activated term with `cycles` cycles already rolled and the next one open."""
    setup = setup_activated_subscriber(term_months=term_months, **plan_overrides)
    for _ in range(cycles):
        run_cycle(setup["subscriber"]["id"])
    setup["subscriber"] = get_subscriber(setup["subscriber"]["id"])
    setup["term"] = get_term(setup["term"]["id"])
    return setup


def setup_grace_subscriber(state_code="CA"):
    """Subscriber parked in GRACE by a failed activation; the term is back to PURCHASED.

    PRD 3.7 gives the PROVISIONED failure path its own precondition — the block must
    have reached SHIPPED or DELIVERED and its shipment_sla_days window must have
    elapsed — so the block is returned (which fails the activation through the
    shipped-media path of 3.8) rather than failing a freshly reserved block.
    """
    agreement, plan, subscriber, term, activation = setup_awaiting_activation(
        state_code=state_code
    )
    provision_activation(activation["id"])
    # Returning the reserved media is the reachable failure path: PRD 3.8 has it set
    # the activation to FAILED, "which cascades its subscriber into GRACE and its term
    # back to PURCHASED, exactly as the failure path of 3.7 does."
    block = api.list_inventories(
        TEST_USERS["planner_headers"], {"state_code": state_code}
    ).json()["data"][0]
    resp = api.return_inventory(block["id"], TEST_USERS["fulfillment_headers"])
    assert resp.status_code == 200, (
        f"Setup failed: return the reserved media -> {resp.status_code} {resp.json()}"
    )
    assert get_activation(activation["id"])["activation_status"] == "FAILED"
    return Setup(
        agreement=agreement,
        plan=plan,
        subscriber=get_subscriber(subscriber["id"]),
        term=get_term(term["id"]),
        activation=get_activation(activation["id"]),
    )


def setup_expired_term_with_breakage(state_code="CA", **plan_overrides):
    """A started term that churned and now sits EXPIRED with breakage recognised."""
    setup = setup_activated_subscriber(state_code=state_code, **plan_overrides)
    run_cycle(setup["subscriber"]["id"])
    current = get_subscriber(setup["subscriber"]["id"])
    resp = api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    assert resp.status_code == 200, f"Setup failed: churn -> {resp.status_code}"
    setup["subscriber"] = resp.json()["data"]
    setup["term"] = get_term(setup["term"]["id"])
    return setup