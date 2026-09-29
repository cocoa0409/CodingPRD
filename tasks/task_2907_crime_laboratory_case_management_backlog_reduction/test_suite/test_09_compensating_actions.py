"""Paired debits and credits that must net exactly: handing a request to another examiner, and
withdrawing an award that had already been shipped.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_two_decimal_value,
    assert_workload,
)
from test_helpers.factories import assignment_payload, engagement_cancellation_payload
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    award_engagement,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    set_clock,
    ship_engagement,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
)


def _six_hour_trace_request_handed_from_one_examiner_to_another(api):
    """A six-hour fibre comparison first placed with one trace examiner and then reassigned to a
    colleague, the reassignment quoting the version the first assignment left behind.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    outgoing = register_analyst(
        api,
        full_name="Marta Villareal",
        disciplines=["TRACE"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    incoming = register_analyst(
        api,
        full_name="Devon Achebe",
        disciplines=["TRACE"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="FTIR Fibre and Paint Comparison",
        discipline="TRACE",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=False,
        accreditation_scope_code="TR-FTIR-01",
        validation_study_item_count=20,
        precision_cv_pct=5.00,
    )
    case = submit_case(
        api,
        agency_case_number="P-2026-1818",
        submitting_agency="COUNTY SO",
        offense_category="PROPERTY_CRIME",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="TRACE_MEDIA", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=3)
    first = assign_request(
        api, request["id"], outgoing["id"], expected_version=request["version"]
    )
    current_version = read_request(api, request["id"])["version"]
    second = validate_success(
        api.create_assignment(
            request["id"],
            assignment_payload(incoming["id"], current_version, assignment_reason="MANUAL"),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    return outgoing, incoming, request, first, second


def test_reassignment_supersedes_the_first_row_and_points_it_at_the_second(api):
    """The displaced row is closed rather than deleted, keeps the six hours it snapshotted, and
    names the row that replaced it, so both holders remain walkable from the request.

    PRD §3.4: "On success the incumbent's `ACTIVE` assignment moves to `SUPERSEDED` with
    `closed_at_utc` stamped and `superseded_by_assignment_id` pointing at the newly created row, and
    the outgoing examiner's `assigned_casework_hours` is decreased by exactly that superseded
    assignment's snapshotted `estimated_hours` — not by the request's current estimate."

    Design: Difficulty/compensating_invariant/reassignment_conserves_total_committed_casework_hours
    """
    _outgoing, incoming, request, first, second = _six_hour_trace_request_handed_from_one_examiner_to_another(
        api
    )

    displaced = validate_success(api.get_assignment(first["id"], CASE_MANAGER_HEADERS))
    assert_fields(
        displaced,
        status="SUPERSEDED",
        estimated_hours=6.00,
        superseded_by_assignment_id=second["id"],
    )
    assert_instant_equals(
        displaced["closed_at_utc"], "2026-08-01T00:00:00Z", "closed_at_utc"
    )

    holder = validate_success(api.get_assignment(second["id"], CASE_MANAGER_HEADERS))
    assert_fields(holder, status="ACTIVE", estimated_hours=6.00)
    assert holder["superseded_by_assignment_id"] is None, (
        "The current holder's row is not itself superseded"
    )

    reread = read_request(api, request["id"])
    assert_fields(
        reread,
        status="ASSIGNED",
        assigned_analyst_id=incoming["id"],
        estimated_hours=6.00,
    )

    _rows, meta = validate_paginated(
        api.list_assignments(
            CASE_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=2)


def test_the_committed_hours_ledger_nets_to_the_same_six_hours(api):
    """The debit and the credit are equal and opposite: the outgoing examiner is back to nothing
    encumbered, the incoming one carries the whole six hours, and the pair still totals exactly the
    request's estimate.

    PRD §2.11: "The **committed casework hours** invariant fixes each examiner's
    `assigned_casework_hours` at the sum of the snapshotted `estimated_hours` of that examiner's
    assignments whose `status` is `ACTIVE`, rounded half up to 2 decimal places."

    Design: Difficulty/compensating_invariant/reassignment_conserves_total_committed_casework_hours
    """
    outgoing, incoming, _request, _first, _second = _six_hour_trace_request_handed_from_one_examiner_to_another(
        api
    )

    outgoing_row = validate_success(
        api.get_analyst(outgoing["id"], QUALITY_MANAGER_HEADERS)
    )
    incoming_row = validate_success(
        api.get_analyst(incoming["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_two_decimal_value(
        outgoing_row["assigned_casework_hours"], 0.00, "assigned_casework_hours"
    )
    assert_two_decimal_value(
        incoming_row["assigned_casework_hours"], 6.00, "assigned_casework_hours"
    )
    assert_two_decimal_value(
        float(outgoing_row["assigned_casework_hours"])
        + float(incoming_row["assigned_casework_hours"]),
        6.00,
        "laboratory-wide committed casework hours",
    )

    assert_workload(
        validate_success(api.get_analyst_workload(outgoing["id"], CASE_MANAGER_HEADERS)),
        projected_load_hours=0.00,
        projected_utilization_pct=0.00,
        active_assignment_count=0,
    )
    assert_workload(
        validate_success(api.get_analyst_workload(incoming["id"], CASE_MANAGER_HEADERS)),
        projected_load_hours=6.00,
        projected_utilization_pct=18.75,
        active_assignment_count=1,
    )


def _rush_award_shipped_then_withdrawn(api):
    """A five-item rush award priced at 238050 cents, shipped to the vendor, and then cancelled while
    the property was still out of the building.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Northgate Forensic Labs",
        accredited_disciplines=["CHEMISTRY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=2,
        unit_price_cents=45000,
        rush_surcharge_pct=0.15,
        contract_ceiling_cents=10000000,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-1919",
        submitting_agency="STATE PATROL",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=5)
    engagement = award_engagement(
        api,
        request["id"],
        vendor["id"],
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-15T00:00:00Z",
        rush_flag=True,
    )
    encumbered_before_cancel = validate_success(
        api.get_vendor(vendor["id"], CASE_MANAGER_HEADERS)
    )
    ship_engagement(api, engagement["id"])
    validate_success(
        api.cancel_vendor_engagement(
            engagement["id"],
            engagement_cancellation_payload(
                "Vendor withdrew capacity before analysis began."
            ),
            CASE_MANAGER_HEADERS,
        )
    )
    return vendor, case, item, request, engagement, encumbered_before_cancel


def test_cancelling_the_award_returns_the_encumbrance_to_zero_with_no_residue(api):
    """The award encumbered 238050 cents; withdrawing it takes exactly that figure back off, leaving
    nothing encumbered and nothing spent, while the engagement row keeps its historical pricing for
    the audit trail.

    PRD §3.7: "The engagement moves to the terminal `CANCELLED`, the vendor's `encumbered_cents`
    decreases by exactly `award_amount_cents` — restoring the pre-award value with zero residue — and
    `spent_cents` is not touched at all."

    Design: Difficulty/compensating_invariant/vendor_engagement_cancel_restores_encumbrance_with_zero_residue
    """
    vendor, _case, _item, _request, engagement, before = _rush_award_shipped_then_withdrawn(api)

    assert_fields(engagement, award_amount_cents=238050)
    assert_fields(before, encumbered_cents=238050, spent_cents=0)

    reread = validate_success(
        api.get_vendor_engagement(engagement["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(
        reread,
        status="CANCELLED",
        award_amount_cents=238050,
        rush_surcharge_cents=33750,
        discount_amount_cents=20700,
    )

    ledger = validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS))
    assert_fields(ledger, encumbered_cents=0, spent_cents=0)

    _rows, meta = validate_paginated(
        api.list_vendor_engagements(
            CASE_MANAGER_HEADERS, {"vendor_id": vendor["id"], "status": "CANCELLED"}
        )
    )
    assert_list_meta(meta, expected_total=1)


def test_the_property_comes_home_but_the_checkout_it_made_is_not_erased(api):
    """The custody axis is only partly reversed: the exhibit is back in the vault and the request is
    queued again, yet the checkout the shipment genuinely performed still stands at one.

    PRD §3.7: "The request returns `OUTSOURCED` → `QUEUED` and the case rollup runs; cancelling an
    engagement that was already `AT_VENDOR` additionally brings the property home, `IN_ANALYSIS` →
    `IN_VAULT`."

    Design: Difficulty/compensating_invariant/vendor_engagement_cancel_restores_encumbrance_with_zero_residue
    """
    _vendor, case, item, request, _engagement, _before = _rush_award_shipped_then_withdrawn(api)

    reread_item = validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS))
    assert_fields(reread_item, custody_status="IN_VAULT", checkout_count=1)

    reread_request = read_request(api, request["id"])
    assert_fields(reread_request, status="QUEUED")
    assert reread_request["assigned_analyst_id"] is None, (
        "A cancelled outsourcing leaves the request unheld"
    )

    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        workflow_status="AWAITING_ASSIGNMENT",
    )
