"""Role authorisation as a flat peer lattice.

The six roles are peers: each one owns an exclusive surface that every other role is
refused on, a handful of surfaces are shared by exactly the roles named on them, and
the read surface is wide even where the write surface is narrow.
"""

import pytest

from test_helpers import (
    BASE_SCORE,
    NETWORK_MANAGER,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    ApiErrorId,
    CategoryStatus,
    FulfillmentStatus,
    InstallerStatus,
    assert_ledger_row,
    assert_score,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    make_installer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Fabricated ids: every probe below is expected to fail on the role gate long before
# any path id is resolved, so these need not exist.
FAKE_PROJECT_ID = "00000000-0000-4000-8000-0000000000b1"
FAKE_INSTALLER_ID = "00000000-0000-4000-8000-0000000000b2"
FAKE_REMOVE_INSTALLER_ID = "00000000-0000-4000-8000-0000000000b3"
FAKE_ASSIGNMENT_ID = "00000000-0000-4000-8000-0000000000b4"
FAKE_DEPOSIT_PROJECT_ID = "00000000-0000-4000-8000-0000000000b5"

WINDOW = ("2026-09-01T08:00:00.000Z", "2026-09-01T16:00:00.000Z")
OCCURRED_AT = "2026-08-01T00:00:00.000Z"


def _catalogue_write(api):
    """The ProgramAdmin-only catalogue registration, offered by a coordinator."""
    return api.create_service_category(f.service_category_payload(),
                                       PROJECT_COORDINATOR)


def _network_write(api):
    """The NetworkManager-only recruitment, offered by a service manager."""
    return api.create_installer(f.installer_payload(legal_name="Rogue Trades LLC",
                                                    contact_email="ops@rogue.example"),
                                SERVICE_MANAGER)


def _assignment_write(api):
    """The ProjectCoordinator-only window hold, offered by a network manager."""
    return api.create_assignment(
        f.assignment_payload(FAKE_PROJECT_ID, FAKE_INSTALLER_ID, 1,
                             window_start=WINDOW[0], window_end=WINDOW[1]),
        NETWORK_MANAGER,
    )


def _removal_write(api):
    """The ServiceManager-only removal, offered by a network manager — and with the
    required `expected_installer_version` left out, so a field check would also fire."""
    return api.remove_installer(FAKE_REMOVE_INSTALLER_ID,
                                {"removal_reason": "Not my call"},
                                NETWORK_MANAGER)


def _start_write(api):
    """The Installer-only on-site start, offered by a coordinator, with an empty body."""
    return api.start_assignment(FAKE_ASSIGNMENT_ID, PROJECT_COORDINATOR, {})


def _deposit_write(api):
    """The Customer-only deposit payment, offered by a coordinator."""
    return api.pay_deposit(FAKE_DEPOSIT_PROJECT_ID, f.deposit_payload(51306),
                           PROJECT_COORDINATOR)


@pytest.mark.parametrize(
    "probe,owning_role",
    [
        (_catalogue_write, "ProgramAdmin"),
        (_network_write, "NetworkManager"),
        (_assignment_write, "ProjectCoordinator"),
        (_removal_write, "ServiceManager"),
        (_start_write, "Installer"),
        (_deposit_write, "Customer"),
    ],
)
def test_each_exclusive_surface_refuses_every_other_role(api, probe, owning_role):
    """Six probes, one per role's exclusive surface, each offered by a role that is not
    listed for it: all six answer `ERR_UNAUTHORIZED_ROLE` with HTTP 403, and they do so
    on an empty store with fabricated ids and, for two of them, an incomplete body.

    PRD 2.8: "2. `X-User-Role` is one of the six declared roles and is listed as
    authorised for the target endpoint — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
    Applies to every endpoint."

    Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_every_other_role
    """
    response = probe(api)
    body = validate_error(response, ApiErrorId.UNAUTHORIZED_ROLE)
    assert isinstance(body["message"], str) and body["message"], (
        f"the {owning_role} surface must explain its refusal"
    )


def test_the_rightful_role_is_unaffected_by_the_six_refusals(api):
    """After all six wrong-role probes the store is still empty, and the ProgramAdmin
    who actually owns the catalogue registers FLOOR-DIRECT as the one and only row.

    PRD 2.1: "`ProgramAdmin` owns the programme configuration — the service catalogue
    and the jurisdiction policy table — and is the retailer-side escalation path for
    permit filings, permit issuance, jurisdiction inspection results, project
    cancellation and reinstatement."

    Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_every_other_role
    """
    for probe in (_catalogue_write, _network_write, _assignment_write,
                  _removal_write, _start_write, _deposit_write):
        validate_error(probe(api), ApiErrorId.UNAUTHORIZED_ROLE)

    # Nothing the six probes touched was created.
    rows, meta = validate_paginated(api.list_service_categories(PROGRAM_ADMIN))
    assert rows == [], "a refused catalogue write must leave no category behind"
    assert meta["total_count"] == 0
    rows, meta = validate_paginated(api.list_installers(NETWORK_MANAGER))
    assert rows == [], "a refused recruitment must leave no installer behind"
    assert meta["total_count"] == 0

    category = get_success_data(
        api.create_service_category(f.service_category_payload(), PROGRAM_ADMIN)
    )
    assert category["code"] == "FLOOR-DIRECT"
    assert category["status"] == CategoryStatus.ACTIVE
    assert_version(category, 1, "the freshly registered category")

    rows, meta = validate_paginated(api.list_service_categories(PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "exactly one ServiceCategory row exists afterwards"
    assert [row["id"] for row in rows] == [category["id"]]


def test_customer_registration_is_open_to_both_roles_named_on_it(api):
    """A `ProgramAdmin` and a `ProjectCoordinator` each register a household against the
    same jurisdiction, and both calls answer 201 with distinct ids.

    PRD 2.1: "It shares customer registration and project creation with
    `ProjectCoordinator`, and may perform every read."

    Design: Corner/rbac/shared_operations_accept_every_role_named_on_them
    """
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())

    first = validate_success(
        api.create_customer(f.customer_payload(jurisdiction["id"]), PROGRAM_ADMIN), 201)
    second = validate_success(
        api.create_customer(f.second_customer_payload(jurisdiction["id"]),
                            PROJECT_COORDINATOR), 201)

    assert first["full_name"] == "Dana Reyes"
    assert second["full_name"] == "Miles Okafor"
    assert first["id"] != second["id"], (
        "the operation is genuinely shared, not admin-only with a coordinator echo"
    )
    assert first["jurisdiction_id"] == jurisdiction["id"]
    assert second["jurisdiction_id"] == jurisdiction["id"]

    rows, meta = validate_paginated(api.list_customers(PROGRAM_ADMIN))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def _fresh_active_firm(api):
    """One ACTIVE firm in METRO-02 with an empty ledger."""
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    network = fx.activated_installer(api, jurisdiction["id"])
    network["jurisdiction"] = jurisdiction
    return network


def test_scorecard_filing_is_open_to_both_roles_named_on_it(api):
    """A coordinator files the customer-satisfaction survey and a service manager files
    the upheld warranty against the same firm; both rows are operator-filed, so both
    carry `source` MANUAL.

    PRD 3.9: "Operator-filed events get `source` `MANUAL`; the events appended by
    assignment completion, no-show release, punch escalation, quality inspection and
    warranty upholding get `source` `SYSTEM`."

    Design: Corner/rbac/shared_operations_accept_every_role_named_on_them
    """
    network = _fresh_active_firm(api)
    installer_id = network["installer"]["id"]
    assert network["installer"]["rolling_event_count"] == 0
    assert_score(network["installer"]["composite_score"], BASE_SCORE,
                 "composite_score before any event")

    survey = validate_success(
        api.create_scorecard_event(installer_id,
                                   f.csat_event_payload(5, OCCURRED_AT),
                                   PROJECT_COORDINATOR), 201)
    upheld = validate_success(
        api.create_scorecard_event(
            installer_id,
            f.scorecard_event_payload("WARRANTY_UPHELD", OCCURRED_AT),
            SERVICE_MANAGER), 201)

    assert survey["event_type"] == "CSAT_SURVEY"
    assert survey["csat_score"] == 5
    assert upheld["event_type"] == "WARRANTY_UPHELD"
    for event, filed_by in ((survey, "the coordinator"), (upheld, "the service manager")):
        assert event["source"] == "MANUAL", f"{filed_by} files a MANUAL row"
        assert event["installer_id"] == installer_id
        assert_ledger_row(event)
    assert survey["id"] != upheld["id"]


def test_the_two_filing_peers_events_land_on_one_ledger(api):
    """The coordinator's row and the service manager's row accumulate against the same
    firm, and the firm itself may read the resulting scorecard.

    PRD 2.1: "`ServiceManager` owns escalation: triaging labour-warranty claims, signing
    off `SAFETY` punch items (it is the only role permitted to do so), releasing an
    install window as a no-show (again, the only role permitted to do so), filing
    scorecard events alongside `ProjectCoordinator`, cancelling a project, and removing
    an installer from the network."

    Design: Corner/rbac/shared_operations_accept_every_role_named_on_them
    """
    network = _fresh_active_firm(api)
    installer_id = network["installer"]["id"]

    get_success_data(
        api.create_scorecard_event(installer_id, f.csat_event_payload(5, OCCURRED_AT),
                                   PROJECT_COORDINATOR))
    get_success_data(
        api.create_scorecard_event(
            installer_id, f.scorecard_event_payload("WARRANTY_UPHELD", OCCURRED_AT),
            SERVICE_MANAGER))

    # The firm reads its own scorecard with its own identity.
    scorecard = get_success_data(
        api.get_scorecard(installer_id, make_installer_headers(installer_id)))
    assert scorecard["rolling_event_count"] == 2, (
        "both peers' events accumulate on the same installer"
    )

    rows, meta = validate_paginated(
        api.list_installer_scorecard_events(installer_id, SERVICE_MANAGER))
    assert meta["total_count"] == 2
    assert [row["source"] for row in rows] == ["MANUAL", "MANUAL"]
    assert fx.read_installer(api, installer_id)["rolling_event_count"] == 2


def _one_row_of_everything(api):
    """A real MEASURED FLOOR-DIRECT project in METRO-02 and one recruited firm, so every
    refused write below targets a row that exists and can only fail on the role gate."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    installer = fx.recruit_installer(api)
    project = fx.sell_project(api, base)
    base["installer"] = installer
    base["project"] = project
    return base


def test_neither_peer_may_write_on_the_others_surface(api):
    """The network manager cannot price a change order, the service manager cannot close
    a project, the household cannot sell one and the crew cannot list customers.

    PRD 2.1: "A `ServiceManager` is emphatically not a super-user: it cannot sell a
    project, book or complete a measurement, price a change order, plan a delivery or
    verify a trade licence."

    Design: Corner/rbac/peer_roles_are_walled_off_on_writes_while_sharing_reads
    """
    ctx = _one_row_of_everything(api)
    project = ctx["project"]
    customer_id = ctx["customer"]["id"]
    installer_id = ctx["installer"]["id"]
    assert project["fulfillment_status"] == FulfillmentStatus.MEASURED

    validate_error(
        api.create_change_order(
            f.change_order_payload(project["id"], project["version"],
                                   [f.primary_line(10.00)]),
            NETWORK_MANAGER),
        ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(api.close_project(project["id"], SERVICE_MANAGER),
                   ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(
        api.create_project(
            f.project_payload(customer_id, ctx["category"]["id"],
                              ctx["jurisdiction"]["id"],
                              site_address="19 Larch Way"),
            make_customer_headers(customer_id)),
        ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(api.list_customers(make_installer_headers(installer_id)),
                   ApiErrorId.UNAUTHORIZED_ROLE)


def test_the_walled_off_writes_change_nothing_at_all(api):
    """After the four refusals no change order exists, the project count is still one,
    and the project's version has not moved.

    PRD 2.1: "`ProjectCoordinator` owns project execution: selling the project, booking
    and completing the in-home measurement, raising and pricing change orders, planning
    material deliveries and advancing their transit status, holding, confirming and
    releasing installer windows, reserving jurisdiction inspection slots, recording the
    quality inspection, escalating punch items and closing the project."

    Design: Corner/rbac/peer_roles_are_walled_off_on_writes_while_sharing_reads
    """
    ctx = _one_row_of_everything(api)
    project = ctx["project"]
    customer_id = ctx["customer"]["id"]
    installer_id = ctx["installer"]["id"]

    validate_error(
        api.create_change_order(
            f.change_order_payload(project["id"], project["version"],
                                   [f.primary_line(10.00)]),
            NETWORK_MANAGER),
        ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(api.close_project(project["id"], SERVICE_MANAGER),
                   ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(
        api.create_project(
            f.project_payload(customer_id, ctx["category"]["id"],
                              ctx["jurisdiction"]["id"],
                              site_address="19 Larch Way"),
            make_customer_headers(customer_id)),
        ApiErrorId.UNAUTHORIZED_ROLE)
    validate_error(api.list_customers(make_installer_headers(installer_id)),
                   ApiErrorId.UNAUTHORIZED_ROLE)

    rows, meta = validate_paginated(api.list_change_orders(PROJECT_COORDINATOR))
    assert rows == [], "the refused change order was never persisted"
    assert meta["total_count"] == 0
    rows, meta = validate_paginated(api.list_projects(PROJECT_COORDINATOR))
    assert meta["total_count"] == 1, "the household's attempted sale created nothing"
    assert [row["id"] for row in rows] == [project["id"]]

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the project after four refusals")
    assert after["fulfillment_status"] == FulfillmentStatus.MEASURED
    assert after["closed_at"] is None


def test_the_two_peers_share_the_installer_read_they_were_refused_writes_on(api):
    """The very installer row the writes were refused around is readable, identically,
    by both the network manager and the project coordinator.

    PRD 2.1: "It reads installers, credentials, scorecards, projects and assignments."

    Design: Corner/rbac/peer_roles_are_walled_off_on_writes_while_sharing_reads
    """
    ctx = _one_row_of_everything(api)
    installer_id = ctx["installer"]["id"]

    by_network = get_success_data(api.get_installer(installer_id, NETWORK_MANAGER))
    by_coordinator = get_success_data(
        api.get_installer(installer_id, PROJECT_COORDINATOR))

    assert by_network["legal_name"] == "Northside Flooring LLC"
    assert by_coordinator["legal_name"] == "Northside Flooring LLC"
    assert by_network["id"] == by_coordinator["id"] == installer_id
    assert by_network["status"] == by_coordinator["status"] == InstallerStatus.APPLIED
    assert_version(by_coordinator, by_network["version"],
                   "the shared installer read")
    # A read carries no side effects, so the two peers see the same committed capacity.
    assert by_network["committed_minutes"] == by_coordinator["committed_minutes"] == 0
