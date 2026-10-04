"""Composite setup helpers for multi-step test prerequisites.

Setup helpers use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading: StoreOrganizer is entity-backed (X-User-ID must be a real
Store.id) and Judge is entity-backed (X-User-ID must be a JudgeCertification id).
Every ownership-gated call below therefore builds headers from the entity that
was actually created, never from the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    SET_PRERELEASE_END,
    SET_PRERELEASE_START,
    SET_STREET_DATE,
    TEST_DEFAULTS,
)
from .factories import (
    approve_payload,
    create_allocation_order_payload,
    create_code_redemption_payload,
    create_enforcement_case_payload,
    create_event_application_payload,
    create_format_payload,
    create_judge_payload,
    create_prize_distribution_payload,
    create_prize_report_payload,
    create_product_configuration_payload,
    create_redeem_payload,
    create_set_release_payload,
    create_store_payload,
    transition_payload,
)
from .test_users import TEST_USERS, make_store_organizer_headers


# ─── Low-level plumbing ───────────────────────────────

def set_clock(current_utc: str, headers=None) -> dict:
    """Advance the logical clock (PRD §3.13)."""
    res = api_client.set_current_utc(
        current_utc, headers or TEST_USERS["ops_admin_headers"]
    )
    return get_success_data(res)


def create_store(**overrides) -> dict:
    payload = create_store_payload(**overrides)
    return get_success_data(
        api_client.create_store(payload, TEST_USERS["ops_admin_headers"])
    )


def create_set_release(**overrides) -> dict:
    payload = create_set_release_payload(**overrides)
    return get_success_data(
        api_client.create_set_release(payload, TEST_USERS["ops_admin_headers"])
    )


def create_format(**overrides) -> dict:
    payload = create_format_payload(**overrides)
    return get_success_data(
        api_client.create_format(payload, TEST_USERS["ops_admin_headers"])
    )


def register_judge(**overrides) -> dict:
    payload = create_judge_payload(**overrides)
    return get_success_data(
        api_client.create_judge(payload, TEST_USERS["ops_admin_headers"])
    )


def create_application(store, set_release, fmt, **overrides) -> dict:
    """Submit an event application as the owning StoreOrganizer (PRD §3.2)."""
    payload = create_event_application_payload(
        store["id"], set_release["id"], fmt["id"], **overrides
    )
    res = api_client.create_event_application(
        payload, make_store_organizer_headers(store["id"])
    )
    return get_success_data(res)


def current_store(store_id: str) -> dict:
    """Read a store back through the collection read (PRD §2.3)."""
    data, _meta = _paginated_stores()
    for row in data:
        if row["id"] == store_id:
            return row
    raise AssertionError(f"Store {store_id} not found in store listing")


def current_store_version(store_id: str) -> int:
    """The Store's live version, used to satisfy the OCC guard (PRD §2.10)."""
    return current_store(store_id)["version"]


def _paginated_stores():
    res = api_client.list_stores(
        TEST_USERS["ops_admin_headers"], params={"limit": 100, "offset": 0}
    )
    return get_success_data(res), None


def get_product_configuration(configuration_id: str) -> dict:
    return get_success_data(
        api_client.get_product_configuration(
            configuration_id, TEST_USERS["ops_admin_headers"]
        )
    )


def current_product_configuration(configuration_id: str) -> dict:
    return get_product_configuration(configuration_id)


def get_application(application_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_event_application(
            application_id, headers or TEST_USERS["ops_admin_headers"]
        )
    )


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(
        api_client.get_prize_allocation(
            allocation_id, TEST_USERS["ops_admin_headers"]
        )
    )


def get_distribution(distribution_id: str) -> dict:
    return get_success_data(
        api_client.get_prize_distribution(
            distribution_id, TEST_USERS["ops_admin_headers"]
        )
    )


def get_code(redemption_id: str) -> dict:
    return get_success_data(
        api_client.get_code_redemption(
            redemption_id, TEST_USERS["ops_admin_headers"]
        )
    )


def get_format(format_id: str) -> dict:
    data, _ = _paginated_formats()
    for row in data:
        if row["id"] == format_id:
            return row
    raise AssertionError(f"Format {format_id} not found in listing")


def _paginated_formats():
    res = api_client.list_formats(
        TEST_USERS["ops_admin_headers"], params={"limit": 100, "offset": 0}
    )
    return get_success_data(res), None


def get_set_release(set_release_id: str) -> dict:
    data, _ = _paginated_set_releases()
    for row in data:
        if row["id"] == set_release_id:
            return row
    raise AssertionError(f"SetRelease {set_release_id} not found in listing")


def _paginated_set_releases():
    res = api_client.list_set_releases(
        TEST_USERS["ops_admin_headers"], params={"limit": 100, "offset": 0}
    )
    return get_success_data(res), None


def get_case(case_id: str) -> dict:
    return get_success_data(
        api_client.get_enforcement_case(case_id, TEST_USERS["ops_admin_headers"])
    )


def get_judge(judge_ref: str) -> dict:
    return get_success_data(
        api_client.get_judge(judge_ref, TEST_USERS["ops_admin_headers"])
    )


def get_reprint_plan(plan_id: str) -> dict:
    return get_success_data(
        api_client.get_reprint_plan(plan_id, TEST_USERS["ops_admin_headers"])
    )


def get_order(order_id: str) -> dict:
    return get_success_data(
        api_client.get_allocation_order(order_id, TEST_USERS["ops_admin_headers"])
    )


# ─── Code cards (PRD §3.11) ───────────────────────────

def mint_code(application_id: str, **overrides) -> dict:
    payload = create_code_redemption_payload(application_id, **overrides)
    return get_success_data(
        api_client.create_code_redemption(payload, TEST_USERS["ops_admin_headers"])
    )


def redeem_code(application_id: str, redemption_code: str, store_id: str,
                **overrides) -> dict:
    payload = create_redeem_payload(redemption_code, **overrides)
    res = api_client.redeem_code(
        application_id, payload, make_store_organizer_headers(store_id)
    )
    return get_success_data(res)


def mint_and_redeem_digital_members(application_id: str, store_id: str,
                                    count: int, prefix: str = "POD") -> list:
    """Mint `count` DIGITAL cards bound to the application and redeem each one."""
    redeemed = []
    for index in range(count):
        code = f"{prefix}-{index}"
        card = mint_code(
            application_id, redemption_code=code, code_kind="DIGITAL"
        )
        redeem_code(application_id, code, store_id)
        redeemed.append(card)
    return redeemed


# ─── Transitions (PRD §3.3, §3.4, §3.5, §3.6) ─────────

def approve_application(application_id: str, store_id: str,
                        pool_mode: str = "BUNDLED",
                        **overrides) -> dict:
    """Approve with the Store's current version, so the OCC guard passes and the
    approval's state/business rules are the only gates in play (PRD §2.10)."""
    payload = approve_payload(
        expected_store_version=current_store_version(store_id),
        pool_mode=pool_mode,
        pool_variant=pool_mode,
        **overrides,
    )
    res = api_client.transition_event_application(
        application_id, payload, TEST_USERS["ops_admin_headers"]
    )
    return get_success_data(res)


def approve_application_raw(application_id: str, expected_store_version,
                            pool_mode: str = "BUNDLED", **overrides):
    """Approve with an explicit caller-supplied version; returns the raw response."""
    payload = approve_payload(
        expected_store_version=expected_store_version,
        pool_mode=pool_mode,
        pool_variant=pool_mode,
        **overrides,
    )
    return api_client.transition_event_application(
        application_id, payload, TEST_USERS["ops_admin_headers"]
    )


def transition_application(application_id: str, action: str, store_id=None,
                           headers=None, **overrides):
    """Raw transition call; uses the owning organizer unless told otherwise."""
    caller = headers or (
        make_store_organizer_headers(store_id) if store_id
        else TEST_USERS["ops_admin_headers"]
    )
    return api_client.transition_event_application(
        application_id, transition_payload(action, **overrides), caller
    )


def complete_application(application_id: str, store_id: str) -> dict:
    """APPROVED -> COMPLETED (needs the clock at least street_date + 7 days)."""
    res = transition_application(application_id, "COMPLETE", store_id=store_id)
    return get_success_data(res)


def propose_distribution(allocation_id: str, store_id: str, **overrides) -> dict:
    payload = create_prize_distribution_payload(allocation_id, **overrides)
    res = api_client.create_prize_distribution(
        payload, make_store_organizer_headers(store_id)
    )
    return get_success_data(res)


def pass_distribution(distribution_id: str) -> dict:
    res = api_client.transition_prize_distribution(
        distribution_id, transition_payload("PASS"),
        TEST_USERS["ops_admin_headers"],
    )
    return get_success_data(res)


def void_distribution(distribution_id: str) -> dict:
    res = api_client.transition_prize_distribution(
        distribution_id, transition_payload("VOID"),
        TEST_USERS["ops_admin_headers"],
    )
    return get_success_data(res)


def file_report(application_id: str, allocation_id: str, store_id: str,
                **overrides) -> dict:
    payload = create_prize_report_payload(allocation_id, **overrides)
    res = api_client.create_prize_report(
        application_id, payload, make_store_organizer_headers(store_id)
    )
    return get_success_data(res)


def file_report_raw(application_id: str, store_id: str, payload):
    return api_client.create_prize_report(
        application_id, payload, make_store_organizer_headers(store_id)
    )


def increase_print_run(configuration_id: str, additional_units: int):
    return api_client.transition_product_configuration(
        configuration_id,
        transition_payload("INCREASE_REPRINT_RUN", additional_units=additional_units),
        TEST_USERS["ops_admin_headers"],
    )


def add_pool_points(allocation_id: str, additional_tp: int):
    return api_client.transition_prize_allocation(
        allocation_id,
        transition_payload("INCREASE_REPRINT_RUN", additional_tp=additional_tp),
        TEST_USERS["ops_admin_headers"],
    )


def disburse_code(redemption_id: str):
    return api_client.transition_code_redemption(
        redemption_id, transition_payload("DISBURSE"),
        TEST_USERS["ops_admin_headers"],
    )


def suspend_store(store_id: str, reason: str = "Report-handling audit failure"):
    return api_client.transition_store(
        store_id, transition_payload("SUSPEND", reason=reason),
        TEST_USERS["ops_admin_headers"],
    )


def reinstate_store(store_id: str):
    return api_client.transition_store(
        store_id, transition_payload("REINSTATE"), TEST_USERS["ops_admin_headers"]
    )


# ─── Tier 1/2: release context and applications ───────

def setup_release_context(daily_event_capacity: int = None,
                          event_space_capacity: int = None,
                          store_overrides: dict = None,
                          set_overrides: dict = None,
                          format_overrides: dict = None,
                          format_code: str = "STD",
                          settle: bool = True,
                          release_clock: str = SET_STREET_DATE):
    """Clock at the street date; one store, one set release, one FIXED format.

    With settle=True the clock is advanced to the street date so the release
    settles to RELEASED and events on it may be approved (PRD §3.7).
    Returns (store, set_release, format).
    """
    set_clock(CLOCK_START)

    store_kwargs = {
        "daily_event_capacity": (
            daily_event_capacity if daily_event_capacity is not None
            else TEST_DEFAULTS["DAILY_EVENT_CAPACITY"]
        ),
        "event_space_capacity": (
            event_space_capacity if event_space_capacity is not None
            else TEST_DEFAULTS["EVENT_SPACE_CAPACITY"]
        ),
    }
    store_kwargs.update(store_overrides or {})
    store = create_store(**store_kwargs)

    set_kwargs = {
        "prerelease_start_date": SET_PRERELEASE_START,
        "prerelease_end_date": SET_PRERELEASE_END,
        "street_date": release_clock,
    }
    set_kwargs.update(set_overrides or {})
    set_release = create_set_release(**set_kwargs)

    format_kwargs = {"format_code": format_code}
    format_kwargs.update(format_overrides or {})
    fmt = create_format(**format_kwargs)

    if settle:
        set_clock(release_clock)

    return store, set_release, fmt


def setup_application(tier: str = "LOCAL",
                      members: int = 0,
                      invitation: bool = False,
                      pool_mode: str = "BUNDLED",
                      approve: bool = True,
                      extra_tp: int = 0,
                      scheduled_date: str = "2026-09-26T18:00:00Z",
                      expected_headcount: int = None,
                      daily_event_capacity: int = None,
                      event_space_capacity: int = None,
                      store_overrides: dict = None,
                      set_overrides: dict = None,
                      format_overrides: dict = None,
                      format_code: str = "STD",
                      release_clock: str = SET_STREET_DATE,
                      code_prefix: str = "POD",
                      advance_clock_to: str = None):
    """Full pre-approval (and optionally post-approval) scenario.

    Creates store + set release + format + application, mints and redeems
    `members` DIGITAL code cards, optionally mints one AVAILABLE DIGITAL
    invitation, then approves with the Store's current version.

    Returns (store, set_release, format, application, allocation_or_None).
    The allocation is None when approve=False.
    """
    store, set_release, fmt = setup_release_context(
        daily_event_capacity=daily_event_capacity,
        event_space_capacity=event_space_capacity,
        store_overrides=store_overrides,
        set_overrides=set_overrides,
        format_overrides=format_overrides,
        format_code=format_code,
        release_clock=release_clock,
    )

    headcount = expected_headcount
    if headcount is None:
        headcount = {"LOCAL": 12, "QUALIFIER": 30, "CHAMPIONSHIP": 60}[tier]

    application = create_application(
        store, set_release, fmt,
        tier=tier,
        scheduled_date=scheduled_date,
        expected_headcount=headcount,
    )

    if members:
        mint_and_redeem_digital_members(
            application["id"], store["id"], members, prefix=code_prefix
        )
    if invitation:
        mint_code(
            application["id"],
            redemption_code=f"{code_prefix}-INVITE",
            code_kind="DIGITAL",
        )

    allocation = None
    if approve:
        approved = approve_application(
            application["id"], store["id"], pool_mode=pool_mode
        )
        allocation_id = approved["prize_allocation_id"]
        # Re-read the application so callers see it in its post-approval form
        # (status APPROVED, prize_allocation_id set, reporting window opened for
        # a competitive tier). approve_application returns the transition
        # response, whose id is populated even though the fixture's own
        # `application` row predates the approval.
        application = get_application(application["id"])
        allocation = get_allocation(allocation_id)

        if extra_tp:
            add_pool_points(allocation_id, extra_tp)
            allocation = get_allocation(allocation_id)

    if advance_clock_to:
        set_clock(advance_clock_to)

    return store, set_release, fmt, application, allocation


def setup_completed_application(tier: str = "LOCAL",
                                members: int = 0,
                                extra_tp: int = 0,
                                scheduled_date: str = "2026-09-26T18:00:00Z",
                                completion_clock: str = "2026-09-26T00:00:00Z",
                                **setup_kwargs):
    """As setup_application, then walk COMPLETED (PRD §3.4).

    The completion clock defaults to a reading at least seven days past the
    street date. Returns (store, set_release, format, application, allocation).
    """
    store, set_release, fmt, application, allocation = setup_application(
        tier=tier, members=members, extra_tp=extra_tp,
        scheduled_date=scheduled_date, **setup_kwargs
    )
    set_clock(completion_clock)
    complete_application(application["id"], store["id"])
    application = get_application(application["id"])
    return store, set_release, fmt, application, allocation


def setup_reported_application(tier: str = "QUALIFIER",
                               unclaimed_tp: int = 0,
                               reported_headcount: int = 30,
                               scheduled_date: str = "2026-09-26T18:00:00Z",
                               completion_clock: str = "2026-09-26T00:00:00Z",
                               **setup_kwargs):
    """As setup_completed_application, then file the prize report."""
    store, set_release, fmt, application, allocation = setup_completed_application(
        tier=tier, scheduled_date=scheduled_date,
        completion_clock=completion_clock, **setup_kwargs
    )
    report = file_report(
        application["id"], allocation["id"], store["id"],
        unclaimed_tp=unclaimed_tp, reported_headcount=reported_headcount,
    )
    return store, set_release, fmt, get_application(application["id"]), allocation, report


# ─── Tier 4: threshold / accumulation targeting ───────

def setup_pool_with_physical_grants(grant_count: int = 3,
                                    extra_tp: int = 150,
                                    tier: str = "LOCAL",
                                    code_prefix: str = "PHY",
                                    completion_clock: str = "2026-09-26T00:00:00Z"):
    """A completed application whose pool holds `grant_count` RESERVED physical
    grants, ready to be disbursed (PRD §3.11).

    Returns (store, set_release, format, application, allocation, [card rows]).
    """
    store, set_release, fmt, application, allocation = setup_application(
        tier=tier, extra_tp=extra_tp, code_prefix="GRANT"
    )

    cards = []
    for index in range(grant_count):
        code = f"{code_prefix}-{index}"
        card = mint_code(
            application["id"], redemption_code=code, code_kind="PHYSICAL"
        )
        # A physical card is redeemed while the application is still APPROVED;
        # disbursement is what later requires COMPLETED (PRD §3.11).
        redeem_code(
            application["id"], code, store["id"], code_kind="PHYSICAL"
        )
        cards.append(card)

    set_clock(completion_clock)
    complete_application(application["id"], store["id"])
    application = get_application(application["id"])

    return store, set_release, fmt, application, allocation, cards


def setup_two_qualifier_applications(first_headcount: int = 30,
                                     second_headcount: int = 30,
                                     first_unclaimed: int = 0,
                                     second_unclaimed: int = 0,
                                     first_scheduled: str = "2026-09-26T18:00:00Z",
                                     second_scheduled: str = "2026-10-03T18:00:00Z",
                                     first_completion_clock: str = "2026-09-26T00:00:00Z",
                                     second_completion_clock: str = "2026-10-03T00:00:00Z"):
    """Two approved QUALIFIER applications on one store, on different days,
    each with an OPEN pool. Returns a dict of both scenarios."""
    store, set_release, fmt = setup_release_context()

    first = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date=first_scheduled, expected_headcount=first_headcount,
    )
    first_approved = approve_application(first["id"], store["id"])
    first_alloc = get_allocation(first_approved["prize_allocation_id"])

    second = create_application(
        store, set_release, fmt, tier="QUALIFIER",
        scheduled_date=second_scheduled, expected_headcount=second_headcount,
    )
    second_approved = approve_application(second["id"], store["id"])
    second_alloc = get_allocation(second_approved["prize_allocation_id"])

    set_clock(first_completion_clock)
    complete_application(first["id"], store["id"])

    set_clock(second_completion_clock)
    complete_application(second["id"], store["id"])

    return {
        "store": store,
        "set_release": set_release,
        "format": fmt,
        "first": get_application(first["id"]),
        "second": get_application(second["id"]),
        "first_allocation": first_alloc,
        "second_allocation": second_alloc,
        "first_headcount": first_headcount,
        "second_headcount": second_headcount,
        "first_unclaimed": first_unclaimed,
        "second_unclaimed": second_unclaimed,
    }


# ─── Tier 3: distribution-queue shortcuts (PRD §3.12) ─

def setup_product_configuration(print_run_units: int = 50,
                                configuration_kind: str = "COLLECTOR_BOOSTER",
                                pack_count: int = 12,
                                order_quantities: list = None,
                                set_overrides: dict = None):
    """One store + set release + configuration, plus any pending orders.

    Returns (store, set_release, configuration, [order rows]).
    """
    set_clock(CLOCK_START)
    store = create_store()
    set_release = create_set_release(**(set_overrides or {}))

    configuration = get_success_data(api_client.create_product_configuration(
        create_product_configuration_payload(
            set_release["id"],
            configuration_kind=configuration_kind,
            pack_count=pack_count,
            print_run_units=print_run_units,
        ),
        TEST_USERS["ops_admin_headers"],
    ))

    orders = []
    for quantity in (order_quantities or []):
        orders.append(get_success_data(api_client.create_allocation_order(
            create_allocation_order_payload(
                configuration["id"], quantity=quantity,
            ),
            TEST_USERS["distributor_headers"],
        )))

    return store, set_release, configuration, orders


def approve_allocation_order(order_id: str, expected_version=None):
    """APPROVE an allocation order, defaulting the OCC guard to the live version."""
    res = api_client.transition_allocation_order(
        order_id,
        transition_payload(
            "APPROVE", expected_product_configuration_version=expected_version
        ),
        TEST_USERS["ops_admin_headers"],
    )
    return get_success_data(res)


def transition_allocation_order_raw(order_id: str, action: str,
                                    expected_version=None, **overrides):
    payload = transition_payload(
        action,
        expected_product_configuration_version=expected_version,
        **overrides,
    )
    return api_client.transition_allocation_order(
        order_id, payload, TEST_USERS["ops_admin_headers"]
    )


# ─── Tier 5: enforcement / judge scenario (PRD §3.10) ─

def setup_judge_with_case(level: str = "LEVEL_2",
                          offense_class: str = "SEVERE",
                          rules_enforcement_level: str = "PROFESSIONAL",
                          repeated_offense: bool = None,
                          judge_ref: str = "JUDGE-ALPHA"):
    """Store + set release + format + LOCAL application + judge + one FILED case.

    Returns (store, set_release, format, application, judge, case).
    """
    store, set_release, fmt, application, _ = setup_application(
        tier="LOCAL", approve=False
    )
    judge = register_judge(judge_ref=judge_ref, level=level)

    case_kwargs = {
        "judge_ref": judge["judge_ref"],
        "offense_class": offense_class,
        "rules_enforcement_level": rules_enforcement_level,
    }
    if repeated_offense is not None:
        case_kwargs["repeated_offense"] = repeated_offense

    case = get_success_data(api_client.create_enforcement_case(
        create_enforcement_case_payload(application["id"], **case_kwargs),
        build_judge_headers(judge),
    ))
    return store, set_release, fmt, application, judge, case


def build_judge_headers(judge: dict) -> dict:
    """Judge is entity-backed; thread the certification's own id (PRD §2.1)."""
    from .test_users import make_judge_headers
    return make_judge_headers(judge["id"])