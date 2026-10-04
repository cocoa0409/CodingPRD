"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is re-launched and the database emptied before
every individual test. Helpers use the lenient validator so a broken setup
surfaces as a clear "setup failed" error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_product_configuration_payload,
    create_jurisdiction_program_payload,
    create_allocation_batch_payload,
    create_carton_payload,
    create_allocation_window_payload,
    create_storage_site_payload,
    create_equipment_verification_payload,
    create_site_order_payload,
    create_dispatch_payload,
    create_shipper_payload,
    create_logger_reading_payload,
    create_excursion_payload,
    create_transfer_payload,
    create_reservation_payload,
    create_carton_family_payload,
    create_reporting_period_payload,
    create_ledger_entry_payload,
)
from .test_users import TEST_USERS, make_site_coordinator_headers

CLOCK_START = "2026-09-01T00:00:00Z"

MFG = TEST_USERS["manufacturing_qa_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]
PLANNER = TEST_USERS["distribution_planner_headers"]
LOGISTICS = TEST_USERS["logistics_operator_headers"]
REVIEWER = TEST_USERS["cold_chain_reviewer_headers"]
MSL = TEST_USERS["medical_science_liaison_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _ok(response):
    data = get_success_data(response)
    assert isinstance(data, dict), f"setup failed: expected object, got {type(data)}"
    return data


def set_clock(instant: str):
    """Advance the logical clock. Returns the clock payload."""
    res = api_client.set_clock({"current_utc": instant}, ADMIN)
    return get_success_data(res)


def _approve_setup(response, label: str):
    if response.status_code >= 400:
        raise AssertionError(
            f"setup failed at {label}: HTTP {response.status_code} {response.text[:300]}"
        )
    return response


def _ok_strict(response, label: str):
    _approve_setup(response, label)
    return get_success_data(response)


# ── Tier 1: single-resource builders ──────────────────────────────────────

def make_product(**overrides):
    """Register a product presentation. Defaults to the PRD's anchored product."""
    res = api_client.create_product_configuration(
        create_product_configuration_payload(**overrides), MFG)
    return _ok_strict(res, "create_product_configuration")


def make_program(**overrides):
    """Register a jurisdiction program."""
    res = api_client.create_jurisdiction_program(
        create_jurisdiction_program_payload(**overrides), RA)
    return _ok_strict(res, "create_jurisdiction_program")


def make_site(program_id, **overrides):
    """Register a storage site."""
    res = api_client.create_storage_site(
        create_storage_site_payload(program_id, **overrides), PLANNER)
    return _ok_strict(res, "create_storage_site")


def certify_site(site_id, **overrides):
    """Record a PASSED equipment verification against a site."""
    res = api_client.create_site_equipment_verification(
        create_equipment_verification_payload(site_id, **overrides), REVIEWER)
    return _ok_strict(res, "create_site_equipment_verification")


def make_batch(product_id, program_id, **overrides):
    """Record a manufacturing batch."""
    res = api_client.create_allocation_batch(
        create_allocation_batch_payload(product_id, program_id, **overrides), MFG)
    return _ok_strict(res, "create_allocation_batch")


def register_carton(batch_id, serial="C-01", vials_per_carton=195):
    res = api_client.register_carton(
        batch_id, create_carton_payload(carton_serial=serial,
                                        vials_per_carton=vials_per_carton), MFG)
    return _ok_strict(res, "register_carton")


def release_batch(batch_id):
    res = api_client.release_batch(batch_id, MFG)
    return _ok_strict(res, "release_batch")


def open_window(batch_id, program_id, **overrides):
    """Announce a window and open it. Returns (window, entitlements)."""
    win = _ok_strict(
        api_client.create_allocation_window(
            create_allocation_window_payload(batch_id, program_id, **overrides), PLANNER),
        "create_allocation_window")
    win = _ok_strict(
        api_client.open_allocation_window(
            win["id"], {"expected_allocation_window_version": win["version"]}, PLANNER),
        "open_allocation_window")
    return win, list_entitlements(win["id"])


def list_entitlements(window_id):
    res = api_client.list_window_entitlements(window_id, PLANNER)
    return get_success_data(res)


def first_entitlement(window_id):
    ents = list_entitlements(window_id)
    assert ents, "setup failed: window produced no entitlement"
    return ents[0]


def submit_order(entitlement_id, site_id, **overrides):
    """Draft and submit an order for a site. Returns the submitted order."""
    order = _ok_strict(
        api_client.create_site_order(
            create_site_order_payload(entitlement_id, site_id, **overrides),
            make_site_coordinator_headers(site_id)),
        "create_site_order")
    order = _ok_strict(
        api_client.submit_site_order(order["id"], make_site_coordinator_headers(site_id)),
        "submit_site_order")
    return order


def accept_order(order_id, window_version, accepted_cartons=2,
                 deliver_at="2026-09-01T06:00:00Z"):
    res = api_client.accept_site_order(
        order_id,
        {"accepted_cartons": accepted_cartons,
         "deliver_at": deliver_at,
         "expected_allocation_window_version": window_version},
        PLANNER)
    return res


# ── Tier 2: entity hierarchies ────────────────────────────────────────────

def setup_program_product_site(**overrides):
    """Program + product + certified site. The reusable top of every hierarchy."""
    product = make_product(**overrides.get("product_overrides", {}))
    program = make_program(**overrides.get("program_overrides", {}))
    site = make_site(program["id"], **overrides.get("site_overrides", {}))
    certify_site(site["id"], **overrides.get("cert_overrides", {}))
    return product, program, site


def setup_entitled_site(**overrides):
    """Program + product + batch + carton + released + open window + entitlement + certified site.

    Returns a dict of the whole anchored hierarchy.
    """
    product = make_product(**overrides.get("product_overrides", {}))
    program = make_program(**overrides.get("program_overrides", {}))

    batch = make_batch(product["id"], program["id"], **overrides.get("batch_overrides", {}))
    carton = register_carton(batch["id"], serial=overrides.get("carton_serial", "C-01"))
    release_batch(batch["id"])

    win, ents = open_window(batch["id"], program["id"], **overrides.get("window_overrides", {}))
    entitlement = ents[0]

    site = make_site(program["id"], **overrides.get("site_overrides", {}))
    certify_site(site["id"], **overrides.get("cert_overrides", {}))

    return {
        "product": product,
        "program": program,
        "batch": batch,
        "carton": carton,
        "window": win,
        "entitlement": entitlement,
        "site": site,
    }


# ── Tier 3: lifecycle shortcuts ───────────────────────────────────────────

def deliver_carton_to_site(ctx, site=None, order_overrides=None, accept_cartons=2,
                           entry_route="DIRECT_ULTRA_COLD", carton=None):
    """Order → submit → accept → dispatch → pack → shipper → seal → dispatch → deliver.

    Returns (order, dispatch, shipper, carton).
    """
    site = site or ctx["site"]
    carton = carton or ctx["carton"]

    order = submit_order(
        ctx["entitlement"]["id"], site["id"], **(order_overrides or {}))
    # The parent window's version is re-read here because it advances on every
    # acceptance recorded against it (PRD §2.6), and the fixture helpers above may
    # already have committed against this window.
    accept = accept_order(order["id"], current_window_version_for_order(order["id"]),
                          accepted_cartons=accept_cartons)
    _approve_setup(accept, "accept_site_order")
    order = get_success_data(accept)

    dispatch = _ok_strict(
        api_client.create_dispatch(
            create_dispatch_payload(order["id"], site["id"], entry_route=entry_route), LOGISTICS),
        "create_dispatch")
    dispatch = _ok_strict(api_client.pack_dispatch(dispatch["id"], LOGISTICS), "pack_dispatch")

    shipper = _ok_strict(
        api_client.create_shipper(
            create_shipper_payload(dispatch["id"], shipper_serial="SH-0001",
                                   logger_serial="LG-0001"), LOGISTICS),
        "create_shipper")
    shipper = _ok_strict(
        api_client.attach_carton_to_shipper(shipper["id"], {"carton_id": carton["id"]}, LOGISTICS),
        "attach_carton")

    _ok_strict(api_client.create_logger_reading(
        create_logger_reading_payload(shipper["id"], recorded_at="2026-09-01T01:00:00Z",
                                      temperature_c=-75), LOGISTICS), "logger_reading_1")
    _ok_strict(api_client.create_logger_reading(
        create_logger_reading_payload(shipper["id"], recorded_at="2026-09-01T06:05:00Z",
                                      temperature_c=-74), LOGISTICS), "logger_reading_2")

    shipper = _ok_strict(api_client.get_shipper(shipper["id"], REVIEWER), "get_shipper")
    shipper = _ok_strict(
        api_client.seal_shipper(shipper["id"],
                                {"expected_shipper_version": shipper["version"]}, LOGISTICS),
        "seal_shipper")
    dispatch = _ok_strict(api_client.send_dispatch(dispatch["id"], LOGISTICS), "dispatch_dispatch")
    dispatch = _ok_strict(
        api_client.deliver_dispatch(dispatch["id"], {"arrived_at": "2026-09-01T06:00:00Z"},
                                    make_site_coordinator_headers(site["id"])),
        "deliver_dispatch")
    carton = _ok_strict(api_client.get_carton(carton["id"], REVIEWER), "get_carton")
    return order, dispatch, shipper, carton


def anchor_delivered_carton(**overrides):
    """The anchored base fixture: one carton delivered ultra-cold back at its site.

    Returns a dict extending ``setup_entitled_site`` with ``order``, ``dispatch``,
    ``shipper`` and the refreshed ``carton``.
    """
    ctx = setup_entitled_site(**overrides)
    order, dispatch, shipper, carton = deliver_carton_to_site(ctx)
    ctx.update({"order": order, "dispatch": dispatch, "shipper": shipper, "carton": carton})
    return ctx


def anchor_thawed_carton(thaw_at="2026-09-01T08:00:00Z", **overrides):
    """The anchored fixture plus the carton taken out of ultra-cold."""
    ctx = anchor_delivered_carton(**overrides)
    set_clock(thaw_at)
    res = api_client.thaw_carton(ctx["carton"]["id"],
                                 make_site_coordinator_headers(ctx["site"]["id"]))
    _approve_setup(res, "thaw_carton")
    ctx["carton"] = get_success_data(res)
    return ctx


def create_excursion(carton_id, site_id, **overrides):
    res = api_client.create_temperature_excursion(
        create_excursion_payload(carton_id, site_id, **overrides),
        make_site_coordinator_headers(site_id))
    return _ok_strict(res, "create_temperature_excursion")


def file_wastage_report(adjudication_id, site_id, **overrides):
    """File a wastage report as the SiteCoordinator acting for ``site_id``."""
    from .factories import create_wastage_report_payload
    res = api_client.create_wastage_report(
        create_wastage_report_payload(adjudication_id, **overrides),
        make_site_coordinator_headers(site_id))
    return _ok_strict(res, "create_wastage_report")


# ── Tier 4: accumulation / threshold targeting ────────────────────────────

def setup_reservation_pair(capacity=10, incumbent_cartons=6, incumbent_start="2026-09-01T09:00:00Z",
                           incumbent_end="2026-09-01T12:00:00Z", **overrides):
    """A certified ultra-cold site with a known capacity and one HELD incumbent reservation.

    Returns (ctx, incumbent_reservation).
    """
    ctx = anchor_delivered_carton(**overrides)
    if capacity != ctx["site"]["ultra_cold_capacity_cartons"]:
        # Re-register a site at the requested capacity and use it for reservations.
        site = make_site(ctx["program"]["id"], ultra_cold_capacity_cartons=capacity,
                         refrigerated_capacity_cartons=capacity)
        certify_site(site["id"])
        ctx["site"] = site
    incumbent = _ok_strict(
        api_client.create_carton_storage_reservation(
            create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                       reserved_capacity_cartons=incumbent_cartons,
                                       start_at=incumbent_start, end_at=incumbent_end,
                                       resolve_method="RESERVATION_BOUNDARY"),
            PLANNER),
        "create_incumbent_reservation")
    return ctx, incumbent


def setup_lapsed_program(program_code="OH", fixed_weekly_cartons=20,
                         window_closes_at="2026-09-02T00:00:00Z",
                         clock_after="2026-09-03T12:00:00Z", **overrides):
    """Drive a program's window to lapse so its lapsed carton rate reaches 1.0.

    A FIXED_QUANTITY program of twenty weekly cartons with a plain half hold-back
    has a rate of twenty and a reservable amount of ten, so `computed_cartons` is
    ten -- the same anchor the rest of the corpus uses (PRD §3.2).  Every carton
    released is then lapsed, so the lapsed carton rate reaches 1.0 and the program
    lands in the top risk tier.

    Returns (product, program, batch, window, entitlement).
    """
    product = make_product(product_code=f"PZ-{program_code}-2026", **overrides.get("product_overrides", {}))
    program = make_program(jurisdiction_code=program_code,
                           fixed_weekly_cartons=fixed_weekly_cartons,
                           weekly_allocation_cap_cartons=fixed_weekly_cartons,
                           **overrides.get("program_overrides", {}))
    batch = make_batch(product["id"], program["id"],
                       batch_code=f"UCV-BATCH-{program_code}-1",
                       released_cartons=fixed_weekly_cartons)
    register_carton(batch["id"], serial=f"C-{program_code}-01")
    release_batch(batch["id"])
    win, ents = open_window(batch["id"], program["id"], closes_at=window_closes_at)
    set_clock(clock_after)
    win = _ok_strict(api_client.close_allocation_window(win["id"], PLANNER), "close_allocation_window")
    return product, program, batch, win, ents[0]


def setup_adjudicated_excursion(ctx, min_temperature_c=-65, outcome="NOT_USABLE",
                                first_breach_at="2026-09-01T09:00:00Z",
                                last_breach_at="2026-09-01T10:00:00Z"):
    """Report → review → adjudicate an excursion on the fixture's thawed carton.

    Returns the adjudicated excursion.
    """
    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"],
                           min_temperature_c=min_temperature_c,
                           first_breach_at=first_breach_at,
                           last_breach_at=last_breach_at,
                           reported_at="2026-09-01T10:05:00Z")
    _ok_strict(api_client.review_temperature_excursion(exc["id"], REVIEWER), "review_excursion")
    res = api_client.adjudicate_temperature_excursion(
        exc["id"], {"outcome": outcome, "rationale": "Fixture adjudication."}, MSL)
    _approve_setup(res, "adjudicate_excursion")
    return get_success_data(res)


# ── Stragglers used by a single family of tests ───────────────────────────

def make_delivered_second_site(ctx, site_code="MI-RIV-05", capability="REFRIGERATED",
                               expected_weekly_doses=1200, equipment_type="THERMAL_SHIPPER"):
    """Register and certify a second site in the fixture's program."""
    site = make_site(ctx["program"]["id"], site_code=site_code,
                     site_name=f"Site {site_code}", storage_capability=capability,
                     ultra_cold_capacity_cartons=0 if capability != "ULTRA_COLD" else 4,
                     refrigerated_capacity_cartons=12,
                     cold_chain_equipment_type=equipment_type,
                     expected_weekly_doses=expected_weekly_doses)
    certify_site(site["id"], equipment_type=equipment_type,
                 certificate_number=f"CERT-{site_code}")
    return site


def make_family(site_id, member_site_id):
    res = api_client.create_carton_family(
        create_carton_family_payload(site_id, member_site_id), REVIEWER)
    return _ok_strict(res, "create_carton_family")


def add_ledger_entry(carton_id, entry_type, quantity_doses, occurred_at,
                     as_headers=None, reverses_entry_id=None):
    payload = create_ledger_entry_payload(carton_id, entry_type, quantity_doses,
                                          occurred_at=occurred_at)
    if reverses_entry_id is not None:
        payload["reverses_entry_id"] = reverses_entry_id
    res = api_client.create_dose_ledger_entry(payload, as_headers or PLANNER)
    return _ok_strict(res, f"create_dose_ledger_entry({entry_type})")


def make_reporting_period(program_id, **overrides):
    res = api_client.create_reporting_period(
        create_reporting_period_payload(program_id, **overrides), RA)
    return _ok_strict(res, "create_reporting_period")


def add_lapsed_periods(program_id, count=5, period_end="2026-08-08T00:00:00Z"):
    """Register ``count`` unsubmitted reporting periods that have already closed.

    PRD §3.9: "it counts lapsed periods in `lapsed_period_count`, being reporting
    periods whose `period_end` is at or before `as_of` while their status is not
    `SUBMITTED`", and the weighted score is five points per lapsed period.  Five
    unsubmitted periods is therefore the cheapest PRD-faithful way to drive a
    program past the "at most twenty" tier-zero boundary.
    """
    rows = []
    for _ in range(count):
        rows.append(make_reporting_period(
            program_id, period_start="2026-08-01T00:00:00Z", period_end=period_end))
    return rows


def usable_doses(site_id, headers=None):
    res = api_client.get_site_usable_doses(site_id, headers or PLANNER)
    return get_success_data(res)


def get_program(program_id):
    return get_success_data(api_client.get_jurisdiction_program(program_id, RA))


def get_site(site_id):
    return get_success_data(api_client.get_storage_site(site_id, PLANNER))


def get_entitlement(ent_id):
    return get_success_data(api_client.get_allocation_entitlement(ent_id, PLANNER))


def get_carton(carton_id, headers=None):
    return get_success_data(api_client.get_carton(carton_id, headers or REVIEWER))


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_site_order(order_id, headers or PLANNER))


def get_shipper(shipper_id):
    return get_success_data(api_client.get_shipper(shipper_id, REVIEWER))


def get_excursion(exc_id):
    return get_success_data(api_client.get_temperature_excursion(exc_id, REVIEWER))


def current_window_version_for_order(order_id):
    """The parent AllocationWindow's current version (PRD §2.6).

    PRD §2.6: "Planners must recompute their view before retrying, because the
    window's version advances on every acceptance, rejection, and release recorded
    against it".
    """
    order = get_order(order_id)
    ent = get_entitlement(order["allocation_entitlement_id"])
    win = get_success_data(api_client.get_allocation_window(
        ent["allocation_window_id"], PLANNER))
    return win["version"]


def get_site_reservations(site_id):
    return get_success_data(api_client.list_site_storage_reservations(site_id, PLANNER))