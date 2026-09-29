"""Endpoint-surface probes: the reverse paths from a parent to its children, the declared query
filters, and the two action endpoints whose answer depends on what the target already holds.

The suite shares one database, so a global collection's total_count is never asserted directly:
a single-dimension filter is checked by what the returned page carries and by which planted row
can never appear in it, while every total_count assertion is narrowed to a freshly created parent.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    authored_decision,
    bill_of_type,
    create_allotment,
    create_aoi,
    create_base_property,
    create_closure_order,
    create_pasture,
    create_permit,
    create_permittee,
    create_project,
    create_trespass_incident,
    get_allotment,
    get_aoi,
    get_bill,
    get_permit,
    get_permittee,
    issue_aoi,
    issue_permit,
    lift_closure_order,
    void_bill,
)


def _listed(response):
    """The items of a paginated list response together with its filtered total_count."""
    items, meta = validate_paginated(response)
    return items, meta["total_count"]


def _ids(items):
    return [item["id"] for item in items]


def test_the_nested_closure_order_path_shows_lifted_orders_and_pages_the_collection():
    """The only reverse path from an allotment to its closure orders reports the LIFTED order beside
    the ACTIVE one, narrows to exactly one under each order_status, answers an order_type that was
    never issued with an empty 200 page rather than a 404, and keeps total_count at the size of the
    filtered collection while limit and offset cut a one-row page out of it. Only the surviving
    ACTIVE order feeds the posture, so the allotment reads 0.2000 and 800 rather than 0.3000.

    PRD 4: "| GET | `/allotments/{allotmentId}/closure-orders` | List the closure orders issued over
    one allotment. | All four operational roles |"
    PRD 3.10: "Closure orders are fetched individually and listed either across all allotments or
    narrowed by `allotment_id`, `order_status` and `order_type`."
    PRD 3.10: "The order moves `ACTIVE → LIFTED` and the identical five-hop cascade re-runs over the
    **remaining** sources, so a lift recomputes rather than subtracts: lifting a 0.40 drought order
    while a 0.30 effective stocking adjustment survives leaves the allotment at 0.30 and
    `RESTRICTED`, not at 0.0 and `OPEN`."
    PRD 3.10: "Orders in `order_status` `LIFTED` or `EXPIRED` contribute nothing, and decisions in
    `decision_status` `DRAFT`, `PROPOSED`, `FINAL`, `STAYED` or `VACATED` contribute nothing."
    PRD 3.10: "The `effective_capacity_aums` becomes the `carrying_capacity_aums` multiplied by one
    minus `stocking_adjustment_pct`, floored to a whole AUM — so a 0.40 reduction on a carrying
    capacity of 1,000 AUMs yields 600, and a total closure yields 0."
    PRD 2.3: "The `meta` object of a listing response additionally carries `limit` (the effective
    page size), `offset` (the effective starting position), `total_count` (the number of records
    matching the filters before pagination is applied) and `has_more` (true exactly when records
    matching the filters remain beyond the current page)."
    PRD 2.3: "Every listing operation is paginated by the same two query parameters. `limit`
    controls page size: it defaults to `10` when omitted, may be no smaller than `1`, and may be no
    larger than `100`. `offset` controls the starting position: it defaults to `0` and may be no
    smaller than `0`."

    Design: Corner/endpoints/corner_allotment_closure_order_listing_filters_and_paginates
    """
    allotment = create_allotment(name="Closure Listing Allotment", admin_unit_code="QB-159",
                                 acres=30000, total_permitted_aums=1000,
                                 required_pasture_rotation_count=1)
    lifted = create_closure_order(
        allotment["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-05", effective_end_date="2026-08-31",
        justification="August precipitation 42 percent of normal on the upper pastures.")
    assert lift_closure_order(lifted["id"])["order_status"] == "LIFTED"
    # A lifted order constrains nothing, so its own interval may be immediately re-covered.
    active = create_closure_order(
        allotment["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.20,
        effective_start_date="2026-09-08", effective_end_date="2026-10-31",
        justification="Renewed drying trend recorded at the Sec 12 monitoring plot.")

    both, total = _listed(api_client.list_allotment_closure_orders(
        allotment["id"], make_specialist_headers()))
    assert total == 2, "the nested path exposes the lifted order beside the active one"
    assert set(_ids(both)) == {lifted["id"], active["id"]}

    still_active, total = _listed(api_client.list_allotment_closure_orders(
        allotment["id"], make_specialist_headers(), {"order_status": "ACTIVE"}))
    assert total == 1 and _ids(still_active) == [active["id"]]
    assert still_active[0]["order_status"] == "ACTIVE"
    assert_pct(still_active[0]["reduction_pct"], 0.20)

    withdrawn, total = _listed(api_client.list_allotment_closure_orders(
        allotment["id"], make_specialist_headers(), {"order_status": "LIFTED"}))
    assert total == 1 and _ids(withdrawn) == [lifted["id"]]
    assert withdrawn[0]["order_status"] == "LIFTED"

    never_issued, total = _listed(api_client.list_allotment_closure_orders(
        allotment["id"], make_specialist_headers(), {"order_type": "FULL_CLOSURE"}))
    assert total == 0 and never_issued == [], "an empty filtered page is a 200, never a 404"

    page, meta = validate_paginated(api_client.list_allotment_closure_orders(
        allotment["id"], make_specialist_headers(), {"limit": 1, "offset": 1}))
    assert len(page) == 1, "the page holds one row"
    assert meta["total_count"] == 2, "total_count counts the collection, not the page"
    assert meta["limit"] == 1 and meta["offset"] == 1
    assert meta["has_more"] is False, "one row before the offset and one on the page exhausts two"

    posture = get_allotment(allotment["id"])
    assert_pct(posture["stocking_adjustment_pct"], 0.20)
    assert posture["effective_capacity_aums"] == 800  # floor(1000 x 0.80)
    assert posture["allotment_status"] == "RESTRICTED"


def test_a_transfer_returns_the_successor_and_a_replay_answers_on_the_sources_state():
    """The transfer endpoint answers 201 with the SUCCESSOR rather than the source, and the successor
    is born already ISSUED carrying the SOURCE's permitted_aums, livestock_kind and term dates — the
    term dates supplied in the request are not the ones stored — while the source moves to
    TRANSFERRED. Replaying the identical call breaks priority 8 (the source is no longer ISSUED) and
    priority 15 (it already has a successor) at once, and the lower number wins: HTTP 409
    ERR_PERMIT_STATE_INVALID, never ERR_PREDECESSOR_PERMIT_INVALID, with no second successor born.

    PRD 3.3: "And unlike renewal, transfer does not let the transferor's year run on: the source
    permit moves to `permit_status` `TRANSFERRED`, a successor is created for
    `transferee_permittee_id` with `predecessor_permit_id` set to the source permit, `permit_status`
    `ISSUED`, `account_status` `CURRENT` and the source permit's `permitted_aums`, `livestock_kind`,
    `term_start_date` and `term_end_date`, and **every** operating instruction of the transferor in
    `aoi_status` `DRAFT` or `ISSUED` is voided."
    PRD 3.3: "The base property must belong to the **transferee**, so reusing the transferor's
    property is `ERR_BASE_PROPERTY_NOT_OWNED`, and its `qualified_aums` must be at least the permit's
    `permitted_aums`."
    PRD 3.3: "A permit is listed and filtered by `allotment_id`, `permittee_id`, `base_property_id`,
    `predecessor_permit_id`, `permit_status` and `account_status`, and a single read exposes both
    dimensions along with `suspension_reason` and `consecutive_nonuse_years`."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 2.6: "The subject record must be in a state from which the requested transition is declared,
    and every same-entity precondition of that transition must hold."
    PRD 2.6: "**Preference chain** — `ERR_PREDECESSOR_PERMIT_INVALID`, HTTP 422, on permit renewal
    and permit transfer."
    PRD 2.9: "The second line is **allocation**: `allocated_aums` is the sum, over every annual
    operating instruction whose permit belongs to this allotment, whose `grazing_year` equals the
    allotment's `current_grazing_year`, and whose `aoi_status` is one of `ISSUED`, `USE_REPORTED`,
    `BILLED` or `CLOSED`, of that instruction's `authorized_aums` less its `nonuse_aums`."

    Design: Corner/endpoints/corner_permit_transfer_creates_a_linked_successor
    """
    allotment = create_allotment(name="Transfer Chain Allotment", admin_unit_code="QB-160",
                                 acres=15000, total_permitted_aums=500,
                                 required_pasture_rotation_count=1)
    transferor = create_permittee(name="Transferor Ranch", contact_email="transferor@example.com")
    transferor_land = create_base_property(transferor["id"], base_property_type="LAND",
                                           carrying_capacity_aums=200,
                                           legal_description="T58N R79E Sec 04 all",
                                           controlled_since_date="1991-03-03")
    source = issue_permit(create_permit(
        allotment["id"], transferor["id"], transferor_land["id"], requested_aums=150,
        term_start_date="2026-01-01", term_end_date="2030-12-31",
        livestock_kind="CATTLE")["id"])
    assert source["permit_status"] == "ISSUED"

    transferee = create_permittee(name="Transferee Ranch", contact_email="transferee@example.com")
    transferee_land = create_base_property(transferee["id"], base_property_type="LAND",
                                          carrying_capacity_aums=200,
                                          legal_description="T58N R79E Sec 05 all",
                                          controlled_since_date="2004-05-05")
    assert transferee_land["qualified_aums"] == 200, "at least the permit's 150 permitted AUMs"

    handover = f.transfer_payload(transferee["id"], transferee_land["id"], requested_aums=150,
                                 term_start_date="2026-09-01", term_end_date="2031-08-31")
    successor = get_success_data(api_client.transfer_permit(
        source["id"], handover, make_officer_headers()), 201)
    assert successor["id"] != source["id"], "the body is the successor, not the source"
    assert successor["permittee_id"] == transferee["id"]
    assert successor["base_property_id"] == transferee_land["id"]
    assert successor["allotment_id"] == allotment["id"]
    assert successor["predecessor_permit_id"] == source["id"]
    assert successor["permit_status"] == "ISSUED"
    assert successor["account_status"] == "CURRENT"
    assert successor["suspension_reason"] is None
    assert successor["permitted_aums"] == 150
    assert successor["livestock_kind"] == "CATTLE"
    assert successor["term_start_date"] == "2026-01-01", "the source's term, not the supplied one"
    assert successor["term_end_date"] == "2030-12-31", "the source's term, not the supplied one"

    assert get_permit(source["id"])["permit_status"] == "TRANSFERRED"
    chain, total = _listed(api_client.list_permits(
        make_specialist_headers(), {"predecessor_permit_id": source["id"]}))
    assert total == 1 and _ids(chain) == [successor["id"]]

    ledger = get_allotment(allotment["id"])
    assert ledger["allocated_aums"] == 0, "no instruction of either permit holds the year"
    assert ledger["open_aums"] == 500

    validate_error(api_client.transfer_permit(source["id"], handover, make_officer_headers()),
                   ApiErrorId.ERR_PERMIT_STATE_INVALID, 409)
    _, total = _listed(api_client.list_permits(
        make_specialist_headers(), {"predecessor_permit_id": source["id"]}))
    assert total == 1, "the refused replay bore no second successor"


def test_each_declared_list_filter_narrows_independently_and_combines_conjunctively():
    """One permittee holds two permits on one allotment, one ISSUED and one still PENDING_REVIEW, and
    the ISSUED one carries an ISSUED 2026 instruction with two use records beside a DRAFT 2027 one.
    permit_status separates the two permits of the same permittee, grazing_year separates the two
    instructions of the same permit, and pasture_id separates the two records of the same
    instruction; in each pair the total_count is the size of the filtered set, not of the parent.

    PRD 4: "| GET | `/grazing-permits` | List permits by allotment, permittee, `permit_status` or
    `account_status`. | All four operational roles |"
    PRD 4: "| GET | `/annual-operating-instructions` | List instructions by permit, allotment,
    `grazing_year` or `aoi_status`. | All four operational roles |"
    PRD 4: "| GET | `/pasture-use-records` | List use records by instruction, pasture or
    `record_status`. | All four operational roles |"
    PRD 3.3: "A permit is listed and filtered by `allotment_id`, `permittee_id`, `base_property_id`,
    `predecessor_permit_id`, `permit_status` and `account_status`, and a single read exposes both
    dimensions along with `suspension_reason` and `consecutive_nonuse_years`."
    PRD 3.3: "The application lands in `permit_status` `PENDING_REVIEW` and `account_status`
    `CURRENT`, with `suspension_reason` null, `consecutive_nonuse_years` 0, `predecessor_permit_id`
    null — that self-reference is populated only on a permit born of a renewal or a transfer — and
    `preference_priority` at its default of 2."
    PRD 3.4: "Each grazing year on each permit is governed by one **annual operating instruction**,
    and its `aoi_status` runs through `DRAFT`, `ISSUED`, `USE_REPORTED`, `BILLED` and `CLOSED`, with
    `VOIDED` available as an alternative ending; `CLOSED` and `VOIDED` are terminal."
    PRD 2.3: "The `meta` object of a listing response additionally carries `limit` (the effective
    page size), `offset` (the effective starting position), `total_count` (the number of records
    matching the filters before pagination is applied) and `has_more` (true exactly when records
    matching the filters remain beyond the current page)."

    Design: Corner/endpoints/corner_list_endpoints_honour_their_declared_filters
    """
    allotment = create_allotment(name="Filter Sweep Allotment", admin_unit_code="QB-161",
                                 acres=18000, total_permitted_aums=600,
                                 required_pasture_rotation_count=1)
    first_pasture = create_pasture(allotment["id"], name="Filter Pasture One",
                                   pasture_aum_capacity=300, sequence_order=1, rest_required=False)
    second_pasture = create_pasture(allotment["id"], name="Filter Pasture Two",
                                    pasture_aum_capacity=300, sequence_order=2, rest_required=False)
    holder = create_permittee(name="Filter Sweep Ranch", contact_email="filters@example.com")
    land = create_base_property(holder["id"], base_property_type="LAND",
                                carrying_capacity_aums=200,
                                legal_description="T59N R80E Sec 08 all",
                                controlled_since_date="1993-06-06")
    issued_permit = issue_permit(create_permit(
        allotment["id"], holder["id"], land["id"], requested_aums=100,
        term_start_date="2026-01-01", term_end_date="2030-12-31",
        livestock_kind="CATTLE")["id"])
    pending_permit = create_permit(
        allotment["id"], holder["id"], land["id"], requested_aums=100,
        term_start_date="2027-01-01", term_end_date="2031-12-31", livestock_kind="SHEEP")
    assert pending_permit["permit_status"] == "PENDING_REVIEW"

    year_2026 = create_aoi(issued_permit["id"], grazing_year=2026, authorized_aums=100,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")
    leg_one = add_use_record(year_2026["id"], first_pasture["id"], planned_head_count=30,
                             livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                             planned_exit_date="2026-05-31")
    leg_two = add_use_record(year_2026["id"], second_pasture["id"], planned_head_count=30,
                             livestock_kind="CATTLE", planned_entry_date="2026-06-01",
                             planned_exit_date="2026-07-01")
    # Drafted before the 2026 instruction is issued: issuance raises a preliminary bill and the debt
    # gate of priority 28 would then forbid drafting any further instruction for this permittee.
    year_2027 = create_aoi(issued_permit["id"], grazing_year=2027, authorized_aums=100,
                           season_start_date="2027-01-01", season_end_date="2027-12-31")
    assert issue_aoi(year_2026["id"])["aoi_status"] == "ISSUED"

    both_permits, total = _listed(api_client.list_permits(
        make_specialist_headers(), {"allotment_id": allotment["id"]}))
    assert total == 2 and set(_ids(both_permits)) == {issued_permit["id"], pending_permit["id"]}

    only_issued, total = _listed(api_client.list_permits(
        make_specialist_headers(),
        {"permittee_id": holder["id"], "permit_status": "ISSUED"}))
    assert total == 1 and _ids(only_issued) == [issued_permit["id"]]
    assert only_issued[0]["permit_status"] == "ISSUED"
    assert pending_permit["id"] not in _ids(only_issued), "PENDING_REVIEW is excluded"

    both_years, total = _listed(api_client.list_aois(
        make_specialist_headers(), {"permit_id": issued_permit["id"]}))
    assert total == 2 and set(_ids(both_years)) == {year_2026["id"], year_2027["id"]}

    only_2027, total = _listed(api_client.list_aois(
        make_specialist_headers(),
        {"permit_id": issued_permit["id"], "grazing_year": 2027}))
    assert total == 1 and _ids(only_2027) == [year_2027["id"]]
    assert only_2027[0]["grazing_year"] == 2027
    assert only_2027[0]["aoi_status"] == "DRAFT", "issuing the 2026 year left 2027 where it was"

    both_legs, total = _listed(api_client.list_use_records(
        make_specialist_headers(), {"aoi_id": year_2026["id"]}))
    assert total == 2 and set(_ids(both_legs)) == {leg_one["id"], leg_two["id"]}

    only_second, total = _listed(api_client.list_use_records(
        make_specialist_headers(),
        {"aoi_id": year_2026["id"], "pasture_id": second_pasture["id"]}))
    assert total == 1 and _ids(only_second) == [leg_two["id"]]
    assert only_second[0]["pasture_id"] == second_pasture["id"]


def test_voidability_is_decided_by_the_money_received_and_not_by_the_bill_status():
    """Two bills sit in exactly the same bill_status ISSUED for exactly the same 17,200 cents, and the
    one that has received a single cent is refused with HTTP 409 ERR_BILL_STATE_INVALID while its
    untouched twin voids cleanly and returns its permittee's balance to zero. Voiding the VOIDED bill
    is refused with the same code, and neither void touches the instruction that raised the bill or
    the allotment's allocation, which still stands at the 200 AUMs the two issued instructions hold.

    PRD 3.6: "Voiding a bill is reserved to an `AuthorizedOfficer`, who may optionally record a
    `void_reason`, and it is permitted only while the bill's `amount_paid_cents` is exactly 0 — a bill
    that has received any money at all, or that is already `PAID` or `VOIDED`, yields
    `ERR_BILL_STATE_INVALID`."
    PRD 3.6: "Either way the bill's `bill_status` becomes `VOIDED`, the permittee's
    `outstanding_balance_cents` is recomputed so that it returns to exactly the figure it held before
    the bill was raised, and two conditional effects follow: when the voided bill was an
    `UNAUTHORIZED_USE` bill, its linked trespass incident cycles `BILLED → DETECTED`; and when the
    void leaves the permittee with no `DELINQUENT` bill, every permit of that permittee whose
    `permit_status` is `PENDING_REVIEW`, `ISSUED` or `SUSPENDED` moves `account_status` `DELINQUENT →
    CURRENT`."
    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that permittee's
    bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's `total_amount_cents` less
    its `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute nothing, and an
    `ADJUSTMENT_CREDIT` bill contributes its negative total and so reduces the balance."
    PRD 2.6: "The subject record must be in a state from which the requested transition is declared,
    and every same-entity precondition of that transition must hold."
    PRD 2.9: "The compensation invariant: if an allotment's `allocated_aums` is A before an operating
    instruction is issued, then after issuance it is A plus that instruction's `billable_aums`, and
    after that same instruction is voided it is A again — exactly A, with no drift — while
    `open_aums` returns to `effective_capacity_aums` less A."

    Design: Corner/endpoints/corner_bill_void_conditional_on_nothing_paid
    """
    allotment = create_allotment(name="Void Condition Allotment", admin_unit_code="QB-162",
                                 acres=18000, total_permitted_aums=600,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Void Condition Pasture",
                             pasture_aum_capacity=300, sequence_order=1, rest_required=False)

    def issued_year(name, email, description, entry, exit_date):
        permittee = create_permittee(name=name, contact_email=email)
        land = create_base_property(permittee["id"], base_property_type="LAND",
                                    carrying_capacity_aums=150, legal_description=description,
                                    controlled_since_date="1995-05-15")
        permit = issue_permit(create_permit(
            allotment["id"], permittee["id"], land["id"], requested_aums=100,
            term_start_date="2026-01-01", term_end_date="2030-12-31",
            livestock_kind="CATTLE")["id"])
        aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                         season_start_date="2026-01-01", season_end_date="2026-12-31")
        add_use_record(aoi["id"], pasture["id"], planned_head_count=30, livestock_kind="CATTLE",
                       planned_entry_date=entry, planned_exit_date=exit_date)
        issue_aoi(aoi["id"])
        bill = bill_of_type("PRELIMINARY_USE", aoi_id=aoi["id"])
        assert bill["total_amount_cents"] == 17200  # 100 AUMs x 172 cents, no admin fee under 50,000
        assert bill["bill_status"] == "ISSUED"
        return permittee, aoi, bill

    ranch_a, aoi_a, bill_a = issued_year("Void Ranch A", "voida@example.com",
                                         "T60N R81E Sec 11 all", "2026-05-01", "2026-05-31")
    ranch_b, aoi_b, bill_b = issued_year("Void Ranch B", "voidb@example.com",
                                         "T60N R81E Sec 12 all", "2026-06-01", "2026-07-01")

    part_paid = get_success_data(api_client.record_payment(
        bill_a["id"], f.payment_payload(1), make_permittee_headers(ranch_a["id"])), 201)
    assert part_paid["amount_paid_cents"] == 1
    assert part_paid["bill_status"] == "ISSUED", "one cent of 17,200 does not settle the bill"

    validate_error(api_client.void_bill(bill_a["id"], f.void_payload(
        void_reason="Raised against the wrong operating instructions."), make_officer_headers()),
        ApiErrorId.ERR_BILL_STATE_INVALID, 409)
    assert get_bill(bill_a["id"])["bill_status"] == "ISSUED", "the refused void changed nothing"
    assert get_permittee(ranch_a["id"])["outstanding_balance_cents"] == 17199

    voided = void_bill(bill_b["id"],
                       void_reason="Raised against the wrong operating instructions.")
    assert voided["bill_status"] == "VOIDED"
    assert get_permittee(ranch_b["id"])["outstanding_balance_cents"] == 0

    validate_error(api_client.void_bill(bill_b["id"], f.void_payload(
        void_reason="Duplicate void attempt."), make_officer_headers()),
        ApiErrorId.ERR_BILL_STATE_INVALID, 409)

    assert get_aoi(aoi_a["id"])["aoi_status"] == "ISSUED"
    assert get_aoi(aoi_b["id"])["aoi_status"] == "ISSUED", "voiding the bill did not void the year"
    ledger = get_allotment(allotment["id"])
    assert ledger["allocated_aums"] == 200, "both instructions still hold their 100 AUMs"
    assert ledger["open_aums"] == 400


def test_pastures_and_base_properties_agree_across_all_three_read_paths():
    """A pasture is reachable beneath its allotment, by its own id and from the global inventory
    narrowed by allotment_id, and all three report the same row; the nested path comes back in
    sequence_order ascending, and rest_required is honoured as a filter in both directions, so
    rest_required=false selects the working pasture rather than being dropped as an absent parameter.
    A base property behaves the same way, and the LIVESTOCK property's floored 75 qualified AUMs read
    identically beneath the permittee, from the register and on the by-id read.

    PRD 4: "| GET | `/allotments/{allotmentId}/pastures` | List an allotment's pastures in
    `sequence_order` ascending. | All four operational roles |"
    PRD 3.1: "Pastures are listed either beneath their allotment in rotation order or across the whole
    inventory, narrowed by `allotment_id` or by `rest_required`."
    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`; the
    figure is carried to 2 decimal places and starts at 0."
    PRD 3.2: "The property's `qualified_aums` is its `carrying_capacity_aums` multiplied by that
    factor, floored to a whole AUM."
    PRD 3.2: "A `LAND` property producing 400 AUMs therefore qualifies 400; a `LIVESTOCK` property
    producing the same 400 qualifies 300, and one producing 401 qualifies 300 as well, because the
    product 300.75 is floored rather than rounded."
    PRD 3.2: "Base properties are listed beneath their permittee or across the register, narrowed by
    `permittee_id` or by `base_property_type`."
    PRD 4: "Throughout the table, "all four operational roles" means `Permittee`, `RangeSpecialist`,
    `AuthorizedOfficer` and `AppealsAdjudicator`; `SystemAdmin` holds no domain authority and may call
    only the clock endpoint."

    Design: Corner/endpoints/corner_pasture_and_base_property_reverse_paths_and_filters
    """
    home = create_allotment(name="Pasture Reverse Path Allotment", admin_unit_code="QB-163",
                            acres=30000, total_permitted_aums=1000,
                            required_pasture_rotation_count=2)
    away = create_allotment(name="Single Pasture Allotment", admin_unit_code="QB-164",
                            acres=9000, total_permitted_aums=500,
                            required_pasture_rotation_count=1)
    north = create_pasture(home["id"], name="North Fork", pasture_aum_capacity=400,
                           sequence_order=1, rest_required=False)
    south = create_pasture(home["id"], name="South Fork", pasture_aum_capacity=300,
                           sequence_order=2, rest_required=True)
    cedar = create_pasture(away["id"], name="Cedar Flat", pasture_aum_capacity=200,
                           sequence_order=1, rest_required=False)

    nested, total = _listed(api_client.list_allotment_pastures(
        home["id"], make_specialist_headers()))
    assert total == 2 and _ids(nested) == [north["id"], south["id"]], "sequence_order ascending"
    assert nested[0]["sequence_order"] == 1 and nested[0]["rest_required"] is False
    assert nested[1]["sequence_order"] == 2 and nested[1]["rest_required"] is True
    for item in nested:
        assert item["allotment_id"] == home["id"]
        assert_aums(item["scheduled_aums"], 0.0)

    by_id = get_success_data(api_client.get_pasture(south["id"], make_specialist_headers()), 200)
    assert by_id["id"] == south["id"]
    assert by_id["allotment_id"] == home["id"]
    assert by_id["name"] == "South Fork"
    assert by_id["pasture_aum_capacity"] == 300
    assert by_id["sequence_order"] == 2
    assert by_id["rest_required"] is True
    assert_aums(by_id["scheduled_aums"], 0.0)

    other_allotment, total = _listed(api_client.list_pastures(
        make_specialist_headers(), {"allotment_id": away["id"]}))
    assert total == 1 and _ids(other_allotment) == [cedar["id"]], "the FK narrows the inventory"

    working, total = _listed(api_client.list_pastures(
        make_specialist_headers(), {"allotment_id": home["id"], "rest_required": "false"}))
    assert total == 1 and _ids(working) == [north["id"]], "false is a filter value, not an absence"

    two_property = create_permittee(name="Two Property Ranch", contact_email="twoprop@example.com")

    # Booleans travel as the lowercase JSON spellings a client would put on the wire.
    resting, _meta = validate_paginated(api_client.list_pastures(
        make_permittee_headers(two_property["id"]), {"rest_required": "true", "limit": 100}))
    assert all(item["rest_required"] is True for item in resting), "a Permittee may read the filter"
    assert north["id"] not in _ids(resting) and cedar["id"] not in _ids(resting)
    assert south["id"] in _ids(resting), "the one resting pasture planted here is on the page"

    deeded = create_base_property(two_property["id"], base_property_type="LAND",
                                  carrying_capacity_aums=200,
                                  legal_description="T61N R82E Sec 07 all",
                                  controlled_since_date="1988-04-04")
    controlled = create_base_property(
        two_property["id"], base_property_type="LIVESTOCK", carrying_capacity_aums=100,
        legal_description="Brand NV-4471, 100 head controlled under lease",
        controlled_since_date="2011-06-06")
    one_property = create_permittee(name="One Property Ranch", contact_email="oneprop@example.com")
    only_deeded = create_base_property(one_property["id"], base_property_type="LAND",
                                       carrying_capacity_aums=300,
                                       legal_description="T61N R82E Sec 08 all",
                                       controlled_since_date="1996-02-02")

    held, total = _listed(api_client.list_permittee_base_properties(
        two_property["id"], make_officer_headers()))
    assert total == 2 and set(_ids(held)) == {deeded["id"], controlled["id"]}
    by_property_id = {item["id"]: item for item in held}
    assert by_property_id[deeded["id"]]["base_property_type"] == "LAND"
    assert by_property_id[deeded["id"]]["carrying_capacity_aums"] == 200
    assert by_property_id[deeded["id"]]["qualified_aums"] == 200  # factor 1.0
    assert by_property_id[controlled["id"]]["base_property_type"] == "LIVESTOCK"
    assert by_property_id[controlled["id"]]["carrying_capacity_aums"] == 100
    assert by_property_id[controlled["id"]]["qualified_aums"] == 75  # floor(100 x 0.75)

    livestock_only, total = _listed(api_client.list_permittee_base_properties(
        two_property["id"], make_officer_headers(), {"base_property_type": "LIVESTOCK"}))
    assert total == 1 and _ids(livestock_only) == [controlled["id"]]
    assert livestock_only[0]["qualified_aums"] == 75

    read_by_id = get_success_data(api_client.get_base_property(
        controlled["id"], make_adjudicator_headers()), 200)
    assert read_by_id["id"] == controlled["id"]
    assert read_by_id["permittee_id"] == two_property["id"]
    assert read_by_id["qualified_aums"] == 75, "the by-id read floors exactly as the lists do"

    register, total = _listed(api_client.list_base_properties(
        make_specialist_headers(), {"permittee_id": one_property["id"]}))
    assert total == 1 and _ids(register) == [only_deeded["id"]]
    assert register[0]["qualified_aums"] == 300

    deeded_rows, _meta = validate_paginated(api_client.list_base_properties(
        make_specialist_headers(), {"base_property_type": "LAND", "limit": 100}))
    assert all(item["base_property_type"] == "LAND" for item in deeded_rows)
    assert controlled["id"] not in _ids(deeded_rows), "the LIVESTOCK row can never appear here"

    for owner, expected in ((two_property["id"], deeded["id"]),
                            (one_property["id"], only_deeded["id"])):
        narrowed, total = _listed(api_client.list_base_properties(
            make_specialist_headers(),
            {"permittee_id": owner, "base_property_type": "LAND"}))
        assert total == 1 and _ids(narrowed) == [expected], "the two filters are conjunctive"


def test_the_global_registries_span_allotments_and_narrow_conjunctively():
    """One row of each registry kind is planted on each of two allotments, and every filter dimension
    picks out exactly the row that carries it while allotment_id combined with a second filter is
    conjunctive. A filter matching nothing is an empty 200 page with total_count 0, never a 404. The
    wildfire order's reduction_pct was never sent and the server records 1.0 anyway, closing the west
    allotment outright, while the east allotment carries only its 0.30 drought cut and its version has
    moved by exactly 2 — once for the decision authorship and once for the whole closure cascade.

    PRD 3.10: "Closure orders are fetched individually and listed either across all allotments or
    narrowed by `allotment_id`, `order_status` and `order_type`."
    PRD 3.10: "A `WILDFIRE_CLOSURE` order and a `FULL_CLOSURE` order are total: `reduction_pct` should
    be omitted, or sent as exactly 1.0, and the server records 1.0 in either case."
    PRD 3.10: "The `allotment_status` becomes `CLOSED` when `stocking_adjustment_pct` is exactly 1.0,
    `RESTRICTED` when it is strictly between 0 and 1, and `OPEN` when it is exactly 0."
    PRD 3.11: "Incidents are fetched individually with their `unauthorized_aums`, `billed_aums` and
    `prior_billed_incident_count` visible, and listed with filters on `allotment_id`, `permittee_id`,
    `willfulness` and `incident_status`."
    PRD 3.11: "The `unauthorized_aums` is computed immediately as `head_count` multiplied by the
    animal-unit equivalent of `livestock_kind` — 1.0 for `CATTLE`, 0.2 for `SHEEP`, 1.25 for `HORSES`
    — multiplied by `unauthorized_days` and divided by 30 days per AUM, rounded half-up to 2 decimal
    places."
    PRD 3.12: "Projects are fetched individually with their `permittee_share_cents` and
    `allocated_share_cents` visible, and listed with filters on `allotment_id`, `project_type`,
    `maintenance_responsibility` and `project_status`."
    PRD 3.7: "Assessments are listed with filters on `allotment_id`, `assessment_year`,
    `monitoring_method`, `assessment_status` and `determination`."
    PRD 3.7: "Submitting for field review is the transition `DRAFT → FIELD_REVIEW`, and only the
    authoring specialist may perform it: the acting `X-User-ID` must equal `author_user_id`, and anyone
    else is `ERR_UNAUTHORIZED`."
    PRD 3.8: "Decisions are fetched individually with their `nepa_status`, `adjustment_pct`,
    `pre_decision_adjustment_pct` and both officer identifiers visible, and listed with filters on
    `allotment_id`, `permit_id`, `assessment_id`, `decision_type`, `decision_status` and
    `nepa_status`."
    PRD 3.8: "The new decision lands in `decision_status` `DRAFT` with `nepa_status` `PENDING`,
    `nepa_findings_summary` null, `pre_decision_adjustment_pct` null, `deciding_officer_id` null and
    `effective_date` null unless supplied, and its `authoring_officer_id` is stamped with the
    authoring specialist's `X-User-ID`."
    PRD 3.8: "Authorship itself bumps the allotment's `version`, which means two decisions authored
    back to back against the same allotment cannot both quote the same `expected_allotment_version`;
    the second author must re-read the allotment first."
    PRD 3.10: "The allotment's `version` is bumped once for the whole cascade."

    Design: Corner/endpoints/corner_global_registries_list_across_allotments_with_conjunctive_filters
    """
    east = create_allotment(name="Registry Allotment East", admin_unit_code="QB-165",
                            acres=24000, total_permitted_aums=1000,
                            required_pasture_rotation_count=1)
    west = create_allotment(name="Registry Allotment West", admin_unit_code="QB-166",
                            acres=12000, total_permitted_aums=600,
                            required_pasture_rotation_count=1)
    ranch = create_permittee(name="Registry Ranch", contact_email="registry@example.com")
    land = create_base_property(ranch["id"], base_property_type="LAND",
                                carrying_capacity_aums=200,
                                legal_description="T62N R83E Sec 11 all",
                                controlled_since_date="1993-05-05")
    permit = issue_permit(create_permit(
        east["id"], ranch["id"], land["id"], requested_aums=150,
        term_start_date="2026-01-01", term_end_date="2030-12-31",
        livestock_kind="CATTLE")["id"])

    drafted_assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(east["id"], assessment_year=2026,
                             monitoring_method="INDICATOR_ASSESSMENT"),
        make_specialist_headers()), 201)
    mapped_assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(west["id"], assessment_year=2026,
                             monitoring_method="UTILIZATION_MAPPING", upland_score=60,
                             riparian_score=55, water_quality_score=70,
                             observed_utilization_pct=65),
        make_specialist_headers()), 201)
    submitted = get_success_data(api_client.submit_assessment(
        mapped_assessment["id"], make_specialist_headers()), 200)
    assert submitted["assessment_status"] == "FIELD_REVIEW"

    fence = create_project(east["id"], project_type="FENCE", total_cost_cents=1000000,
                           agency_share_pct=0.6, permittee_share_pct=0.4,
                           maintenance_responsibility="PERMITTEE")
    water = create_project(west["id"], project_type="WATER_DEVELOPMENT", total_cost_cents=500000,
                           agency_share_pct=0.5, permittee_share_pct=0.5,
                           maintenance_responsibility="SHARED")

    willful = create_trespass_incident(east["id"], ranch["id"],
                                       detected_at="2026-07-20T09:00:00Z", head_count=20,
                                       livestock_kind="CATTLE", unauthorized_days=15,
                                       willfulness="WILLFUL")
    unwilful = create_trespass_incident(west["id"], ranch["id"],
                                        detected_at="2026-07-21T09:00:00Z", head_count=10,
                                        livestock_kind="CATTLE", unauthorized_days=6,
                                        willfulness="NON_WILLFUL")

    version_before = get_allotment(east["id"])["version"]
    suspension = authored_decision(east["id"], decision_type="SUSPENSION",
                                   expected_allotment_version=version_before,
                                   permit_id=permit["id"], nepa_level="CX")
    drought = create_closure_order(
        east["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-05", effective_end_date="2026-08-31",
        justification="Upper pasture forage production 38 percent of the ten-year average.")
    total_closure = f.closure_order_payload(
        west["id"], order_type="WILDFIRE_CLOSURE", effective_start_date="2026-08-05",
        effective_end_date="2027-08-04",
        justification="Burned area emergency rehabilitation closure after the Cedar Draw fire.")
    del total_closure["reduction_pct"]
    wildfire = get_success_data(api_client.create_closure_order(
        total_closure, make_officer_headers()), 201)
    # reduction_pct was never sent: the server records 1.0 for a total closure either way.
    assert_pct(wildfire["reduction_pct"], 1.0)

    spanning, _meta = validate_paginated(api_client.list_closure_orders(
        make_specialist_headers(), {"limit": 100}))
    spanning_ids = _ids(spanning)
    assert drought["id"] in spanning_ids and wildfire["id"] in spanning_ids, "one registry, two units"

    east_active, total = _listed(api_client.list_closure_orders(
        make_specialist_headers(),
        {"allotment_id": east["id"], "order_status": "ACTIVE"}))
    assert total == 1 and _ids(east_active) == [drought["id"]]
    assert east_active[0]["order_type"] == "DROUGHT_REDUCTION"
    assert east_active[0]["allotment_id"] == east["id"]
    assert_pct(east_active[0]["reduction_pct"], 0.30)

    burned, _meta = validate_paginated(api_client.list_closure_orders(
        make_permittee_headers(ranch["id"]),
        {"order_type": "WILDFIRE_CLOSURE", "limit": 100}))
    assert all(item["order_type"] == "WILDFIRE_CLOSURE" for item in burned)
    assert drought["id"] not in _ids(burned), "a drought order can never appear here"
    burned_west, total = _listed(api_client.list_closure_orders(
        make_permittee_headers(ranch["id"]),
        {"allotment_id": west["id"], "order_type": "WILDFIRE_CLOSURE"}))
    assert total == 1 and _ids(burned_west) == [wildfire["id"]], "a Permittee may read the registry"

    deliberate, total = _listed(api_client.list_trespass_incidents(
        make_specialist_headers(),
        {"permittee_id": ranch["id"], "willfulness": "WILLFUL"}))
    assert total == 1 and _ids(deliberate) == [willful["id"]]
    assert deliberate[0]["allotment_id"] == east["id"]
    assert_aums(deliberate[0]["unauthorized_aums"], 10.00)  # 20 head x 1.0 x 15 days / 30
    assert deliberate[0]["billed_aums"] == 0
    assert deliberate[0]["incident_status"] == "DETECTED"

    west_incidents, total = _listed(api_client.list_trespass_incidents(
        make_officer_headers(),
        {"allotment_id": west["id"], "permittee_id": ranch["id"]}))
    assert total == 1 and _ids(west_incidents) == [unwilful["id"]]
    assert west_incidents[0]["willfulness"] == "NON_WILLFUL"
    assert_aums(west_incidents[0]["unauthorized_aums"], 2.00)  # 10 head x 1.0 x 6 days / 30

    settled, total = _listed(api_client.list_trespass_incidents(
        make_specialist_headers(),
        {"permittee_id": ranch["id"], "incident_status": "RESOLVED"}))
    assert total == 0 and settled == [], "no incident of this permittee has ever been resolved"

    shared, _meta = validate_paginated(api_client.list_projects(
        make_specialist_headers(), {"maintenance_responsibility": "SHARED", "limit": 100}))
    assert all(item["maintenance_responsibility"] == "SHARED" for item in shared)
    assert fence["id"] not in _ids(shared), "the PERMITTEE-maintained fence can never appear here"
    shared_west, total = _listed(api_client.list_projects(
        make_specialist_headers(),
        {"allotment_id": west["id"], "maintenance_responsibility": "SHARED"}))
    assert total == 1 and _ids(shared_west) == [water["id"]]
    assert shared_west[0]["project_type"] == "WATER_DEVELOPMENT"
    assert shared_west[0]["project_status"] == "PROPOSED"
    assert shared_west[0]["allocated_share_cents"] == 0

    fences, total = _listed(api_client.list_projects(
        make_specialist_headers(),
        {"allotment_id": east["id"], "project_type": "FENCE"}))
    assert total == 1 and _ids(fences) == [fence["id"]]
    assert fences[0]["total_cost_cents"] == 1000000
    assert_pct(fences[0]["permittee_share_pct"], 0.4)
    assert fences[0]["project_status"] == "PROPOSED"

    under_review, total = _listed(api_client.list_assessments(
        make_officer_headers(),
        {"allotment_id": west["id"], "assessment_status": "FIELD_REVIEW"}))
    assert total == 1 and _ids(under_review) == [mapped_assessment["id"]]
    assert under_review[0]["monitoring_method"] == "UTILIZATION_MAPPING"
    assert under_review[0]["allotment_id"] == west["id"]

    still_drafted, total = _listed(api_client.list_assessments(
        make_specialist_headers(),
        {"allotment_id": east["id"], "assessment_year": 2026,
         "monitoring_method": "INDICATOR_ASSESSMENT"}))
    assert total == 1 and _ids(still_drafted) == [drafted_assessment["id"]]
    assert still_drafted[0]["assessment_status"] == "DRAFT", "submitting one did not move the other"
    assert still_drafted[0]["author_user_id"] == "u_spec_1"

    suspensions, total = _listed(api_client.list_decisions(
        make_adjudicator_headers(),
        {"allotment_id": east["id"], "decision_type": "SUSPENSION"}))
    assert total == 1 and _ids(suspensions) == [suspension["id"]]
    assert suspensions[0]["decision_status"] == "DRAFT"
    assert suspensions[0]["nepa_status"] == "PENDING"
    assert suspensions[0]["nepa_findings_summary"] is None
    assert suspensions[0]["adjustment_pct"] is None
    assert suspensions[0]["assessment_id"] is None
    assert suspensions[0]["permit_id"] == permit["id"]
    assert suspensions[0]["authoring_officer_id"] == "u_spec_1"

    reviewed, total = _listed(api_client.list_decisions(
        make_adjudicator_headers(),
        {"allotment_id": east["id"], "nepa_status": "COMPLETE"}))
    assert total == 0 and reviewed == [], "the only decision here is still PENDING review"

    by_permit, total = _listed(api_client.list_decisions(
        make_specialist_headers(), {"permit_id": permit["id"]}))
    assert total == 1 and _ids(by_permit) == [suspension["id"]]

    east_after = get_allotment(east["id"])
    assert east_after["version"] == version_before + 2, "authorship once, the cascade once"
    assert_pct(east_after["stocking_adjustment_pct"], 0.30)
    assert east_after["effective_capacity_aums"] == 700  # floor(1000 x 0.70)
    assert east_after["allotment_status"] == "RESTRICTED"

    west_after = get_allotment(west["id"])
    assert_pct(west_after["stocking_adjustment_pct"], 1.0)
    assert west_after["effective_capacity_aums"] == 0
    assert west_after["allotment_status"] == "CLOSED"
