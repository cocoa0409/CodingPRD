"""The consistency model: every derived field is final in the response that wrote it.

Nothing in this programme is eventually correct. The creation response already carries
the frozen quote, the deposit requirement and the permit determination, and a scorecard
event's recomputation is on the installer row by the time the next request is served.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    FinancialStatus,
    FulfillmentStatus,
    PermitResponsibleParty,
    PermitStatus,
    assert_money,
    assert_project_dimensions,
    assert_same_fields,
    assert_score,
    assert_units,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_success,
)

QUOTED = 196673
DEPOSIT = 59002
CLOCK = "2026-08-01T00:00:00.000Z"

DERIVED_PROJECT_FIELDS = (
    "quoted_labor_cents",
    "deposit_required_cents",
    "effective_units",
    "permit_responsibility",
    "permit_status",
    "total_due_cents",
    "fulfillment_status",
    "financial_status",
    "version",
)


def test_the_creation_response_already_carries_every_derived_field(api):
    """The sale's 201 body pins the frozen quote, the deposit requirement, the units and
    the permit determination, and an immediate read returns the same figures field for
    field with no second write and no polling.

    PRD 3.3: "It runs the labour calculation in its provisional variant and freezes the
    result into `quoted_labor_cents`, which is **never** recomputed afterwards, not by a
    measurement, not by an accepted change order, and not by a later amendment to the
    category's rate."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_writing_response_itself
    """
    base = fx.program_baseline(api, f.quick_category_payload(),
                              f.jurisdiction_payload())
    written = validate_success(
        api.create_project(
            f.project_payload(base["customer"]["id"], base["category"]["id"],
                              base["jurisdiction"]["id"], estimated_units=420.00,
                              site_address="22 Larch Way"),
            PROJECT_COORDINATOR),
        201)

    assert_money(written["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    assert_money(written["deposit_required_cents"], DEPOSIT, "deposit_required_cents")
    assert_units(written["effective_units"], 420.00, "effective_units")
    assert written["permit_responsibility"] == PermitResponsibleParty.RETAILER
    assert written["permit_status"] == PermitStatus.PENDING_APPLICATION
    # No labour has been finalised, so nothing is yet due.
    assert_money(written["total_due_cents"], 0, "total_due_cents")
    assert_project_dimensions(written, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED)

    read_back = fx.read_project(api, written["id"])
    assert_same_fields(written, read_back, DERIVED_PROJECT_FIELDS)


def test_a_scorecard_event_is_recomputed_before_the_next_request_is_served(api):
    """The event row freezes its own three deltas, and the installer's satisfaction and
    composite scores are already rewritten by the time the next read arrives.

    PRD 3.9: "These three numbers are written onto the ledger row when it is created and
    are **never** rewritten afterwards, even if the tariff itself were to change."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_writing_response_itself
    """
    jurisdiction = fx.create_jurisdiction(api, f.jurisdiction_payload())
    installer = fx.activated_installer(api, jurisdiction["id"])["installer"]
    assert_score(installer["satisfaction_score"], 85.00,
                 "satisfaction_score at activation")

    event = validate_success(
        api.create_scorecard_event(installer["id"], f.csat_event_payload(1, CLOCK),
                                   SERVICE_MANAGER),
        201)
    # A rating of 1 is two steps below neutral: (1 - 3) * 5.00.
    assert_score(event["quality_delta"], 0.00, "quality_delta")
    assert_score(event["timeliness_delta"], 0.00, "timeliness_delta")
    assert_score(event["satisfaction_delta"], -10.00, "satisfaction_delta")

    after = fx.read_installer(api, installer["id"])
    assert_score(after["satisfaction_score"], 75.00, "satisfaction_score")
    # 85.00 * 0.45 + 85.00 * 0.30 + 75.00 * 0.25 = 38.25 + 25.50 + 18.75 = 82.50.
    assert_score(after["composite_score"], 82.50, "composite_score")
    assert after["rolling_event_count"] == 1

    # The recomputation is observable on the computed read as well, unchanged.
    scorecard = get_success_data(api.get_scorecard(installer["id"], SERVICE_MANAGER))
    assert_score(scorecard["rolling_satisfaction_score"], 75.00,
                 "rolling_satisfaction_score")
    assert_score(scorecard["rolling_composite_score"], 82.50,
                 "rolling_composite_score")
    assert scorecard["rolling_event_count"] == 1
