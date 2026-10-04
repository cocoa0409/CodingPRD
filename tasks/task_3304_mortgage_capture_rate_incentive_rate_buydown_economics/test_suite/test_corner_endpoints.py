"""Corner coverage - action endpoints, computed reads and nested creation."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def test_reserving_an_available_home_moves_it_under_contract(api):
    """The reserve action performs the transition directly, with no contract involved.

    PRD §3.2: "When a sales counselor reserves an available inventory home, it moves to
    `UNDER_CONTRACT` and the owning community's `forward_units_committed` is recomputed."
    PRD §2.4: "Any operation that mutates a derived field — the community's
    `capture_rate_bps` or `incentive_spend_cents`, the home site's `home_site_status`, the
    contract's `deposit_held_cents` — is a mutation of that row and therefore refreshes its
    `updated_at` and increments its `version`, exactly as a client-supplied change to a
    stored input field would."
    Design: Corner/endpoints/reserve_endpoint_moves_home_site_under_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})

    reserved = get_success_data(
        api.reserve_home_site(world["cm1"], world["hs1"], SALES_HEADERS)
    )
    assert reserved["home_site_status"] == "UNDER_CONTRACT", reserved["home_site_status"]
    assert reserved["version"] == site["version"] + 1, (
        f"the posture change is a mutation, so the version advances, "
        f"got {reserved['version']} from {site['version']}"
    )


def test_reserving_a_home_writes_no_contract_against_it(api):
    """The action endpoint is a reservation, not a sale, so the contract list stays empty.

    PRD §3.2: "The reverse move, back to `AVAILABLE`, happens automatically when the
    contract written against that home is cancelled, and the move to the terminal `SOLD`
    posture happens when that contract closes."
    PRD §3.4: "A `SalesCounselor` writes a purchase contract against an available
    inventory home, naming the `buyer_id`".
    Design: Corner/endpoints/reserve_endpoint_moves_home_site_under_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})
    get_success_data(api.reserve_home_site(world["cm1"], world["hs1"], SALES_HEADERS))

    contracts, _ = fixtures.rows(
        api.list_home_site_contracts(world["hs1"], world["sales_headers"])
    )
    assert contracts == [], f"reserving alone writes no contract, got {contracts}"


def disclosed_contract_world(api):
    """A contract with one acknowledged disclosure and one still-issued disclosure."""
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    first = fixtures.deliver_disclosure(api, world["ct1"])
    world["d1"] = first["id"]
    fixtures.acknowledge(api, world["d1"], world["b1"])

    second = fixtures.deliver_disclosure(
        api, world["ct1"], disclosure_type="STEERING_PROHIBITION"
    )
    world["d2"] = second["id"]
    world["d2_deadline"] = second["cure_deadline_iso"]
    return world


def test_the_disclosure_read_returns_every_form_delivered_for_the_contract(api):
    """The listing is a computed read whose members carry their own cure deadlines.

    PRD §3.9: "A contract's disclosures and their earliest open cure deadline are listed
    together on the contract's disclosure read, and a single form is readable by any role
    including the buyer."
    PRD §3.9: "Delivery stamps `delivery_iso` with the current logical clock and computes
    `cure_deadline_iso` as that day's midnight plus three calendar days".
    Design: Corner/endpoints/computed_read_of_contract_disclosures_returns_the_earliest_open_cure_deadline
    """
    world = disclosed_contract_world(api)

    rows, _ = fixtures.rows(
        api.list_contract_disclosures(world["ct1"], COMPLIANCE_HEADERS)
    )
    assert len(rows) == 2, f"both forms are listed, got {len(rows)}"

    by_id = {row["id"]: row for row in rows}
    assert by_id[world["d1"]]["disclosure_status"] == "ACKNOWLEDGED", (
        f"the first form was acknowledged, got {by_id[world['d1']]['disclosure_status']}"
    )
    assert by_id[world["d2"]]["disclosure_status"] == "ISSUED", (
        f"the second form has not been touched, got {by_id[world['d2']]['disclosure_status']}"
    )
    assert by_id[world["d2"]]["cure_deadline_iso"].startswith("2026-09-04T00:00:00"), (
        f"a form delivered on 2026-09-01 closes its window three days later, "
        f"got {by_id[world['d2']]['cure_deadline_iso']}"
    )


def test_the_acknowledged_form_drops_out_of_the_open_cure_candidate_set(api):
    """Only the still-issued form remains open, so the earliest open deadline is its own.

    PRD §2.8: "Disclosures already in `ACKNOWLEDGED` or `WAIVED` status are excluded from
    the candidate set entirely, so an acknowledged disclosure can never resurrect an
    expired cure window."
    PRD §2.8: "A contract additionally exposes a single `aba_cure_deadline_iso` value,
    computed by the disclosure-cure-deadline rule as the earliest `cure_deadline_iso`
    among the contract's disclosures that are still in `ISSUED` or `CURING` status."
    Design: Corner/endpoints/computed_read_of_contract_disclosures_returns_the_earliest_open_cure_deadline
    """
    world = disclosed_contract_world(api)

    rows, _ = fixtures.rows(
        api.list_contract_disclosures(world["ct1"], COMPLIANCE_HEADERS)
    )
    open_rows = [row for row in rows if row["disclosure_status"] in ("ISSUED", "CURING")]
    assert len(open_rows) == 1, (
        f"the acknowledged form is excluded from the open set, got {len(open_rows)}"
    )
    earliest_open = min(row["cure_deadline_iso"] for row in open_rows)
    assert earliest_open.startswith("2026-09-04T00:00:00"), (
        f"the earliest still-open deadline is the issued form's, got {earliest_open}"
    )
    assert open_rows[0]["id"] == world["d2"], open_rows[0]["id"]


def test_filing_an_application_under_a_contract_records_the_lender_choice(api):
    """The nested create is the application path, and it flips the buyer's lender flag.

    PRD §3.3: "Underwriting begins when a `MortgageBanker` or `SalesCounselor` files a
    loan application against a contract, choosing the `lender_entity_code`".
    PRD §3.3: "Filing with the affiliated lender flips the buyer's
    `affiliated_lender_selected` to true."
    Design: Corner/endpoints/nested_application_creation_under_a_contract_records_the_lender_choice
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    created = api.create_loan_application(
        world["ct1"], f.loan_application_payload(), BANKER_HEADERS
    )
    application = validate_success(created, expected_status=201)
    assert application["application_status"] == "SUBMITTED", application["application_status"]

    buyer = fixtures.read_buyer(api, world["b1"])
    assert buyer["affiliated_lender_selected"] is True, (
        f"the affiliated filing is what sets the flag, got {buyer['affiliated_lender_selected']}"
    )


def test_the_contract_application_listing_shows_the_single_filed_application(api):
    """The nested read reports exactly the row the create just wrote.

    PRD §3.3: "The new application opens in `application_status` `SUBMITTED` with
    `lock_waiver_status` `NOT_REQUESTED`".
    PRD §2.12: "Requests that address a nested resource carry the full ancestry in the
    path, and the server validates those identifiers strictly left to right".
    Design: Corner/endpoints/nested_application_creation_under_a_contract_records_the_lender_choice
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})
    application = fixtures.create_application(api, world["ct1"])

    rows, meta = fixtures.rows(
        api.list_contract_loan_applications(world["ct1"], world["banker_headers"])
    )
    assert len(rows) == 1, f"exactly one application was filed, got {len(rows)}"
    assert rows[0]["id"] == application["id"], rows[0]["id"]