"""Billing, reversal and the grant posture machine."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    walk_screen_to_eligible, activate_enrollment, authorize_units, record_delivery,
    document_delivery, bill_delivery, void_delivery, delivery_lines, setup_landscape,
    setup_draft_delivery, setup_same_day_duplicate_deliveries, list_enrollments_for,
    ApiErrorId, INTAKE, PROGRAM, FINANCE,
)


def test_duplication_disallowance_allows_only_first_row_by_creation_order():
    """PRD §3.7: "Those peers are ordered by creation time ascending, with ties
    broken by ascending `sequence_no`, and the first row in that order is the
    allowed one while every later row is disallowed".
    PRD §3.7: "Only one row per client, per service code, per day is permitted;
    when the disallowed amount is above zero the billing is refused with
    `ERR_DUPLICATE_SERVICE_BILLING` (HTTP 409)."

    Design: Corner/calculations/duplication_disallowance_allows_only_first_row_by_creation_order
    """
    ctx = setup_same_day_duplicate_deliveries([2, 2, 3], unit_rate_cents=5000,
                                              authorized_units=30,
                                              clock="2026-09-02T00:00:00Z")
    first, second, _third = ctx["deliveries"]

    billed = bill_delivery(first["id"])
    assert billed["status"] == "BILLED"

    refused = api_client.bill_service_delivery(second["id"], FINANCE)
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_SERVICE_BILLING)

    after = get_success_data(api_client.get_service_delivery(second["id"], FINANCE))
    assert after["status"] == "DOCUMENTED"
    assert after["allocated_total_cents"] == 10000
    assert after["admin_total_cents"] == 1000
    assert all(line["status"] == "PROVISIONAL" for line in delivery_lines(second["id"]))


def test_billed_delivery_void_reverses_expended_cents_and_marks_voided():
    """PRD §3.7: "Voiding a `BILLED` delivery instead terminates it: the lines
    become `REVERSED`, each receiving grant's `expended_cents` is decreased by
    the reversed line totals, `burn_ratio` and posture are recomputed".
    PRD §3.7: "`VOIDED` is terminal."

    Design: Corner/endpoints/billed_delivery_void_reverses_expended_cents_and_marks_voided
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_draft_delivery(units_delivered=2, unit_rate_cents=5000,
                               grant_overrides={"total_award_cents": 200000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 10,
                                                        "unit_rate_cents": 5000})
    billed = bill_delivery(document_delivery(ctx["delivery"]["id"])["id"])
    assert billed["status"] == "BILLED"

    resp = api_client.void_service_delivery(billed["id"], FINANCE)
    data = validate_success(resp)
    assert data["status"] == "VOIDED"

    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["expended_cents"] == 0
    assert grant["obligated_cents"] == 0
    assert grant["burn_ratio"] == 0.0
    assert grant["status"] == "OPEN"

    assert all(line["status"] == "REVERSED" for line in delivery_lines(billed["id"]))
    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    assert authorization["units_delivered"] == 0
    assert authorization["status"] == "ACTIVE"


def test_delivery_document_then_void_conserves_grant_committed_cents():
    """PRD §3.7: "Voiding a `DOCUMENTED` delivery returns it to `DRAFT`: every
    allocation line for the delivery becomes `REVERSED` with its
    `allocated_amount_cents`, `admin_amount_cents` and `disallowed_cents` all
    zeroed, each receiving grant's `obligated_cents` is decreased by the pre-void
    sum of allocated and administrative amounts".
    PRD §3.7: "in both cases the reversal can move a frozen grant back to
    `THROTTLED` or all the way to `OPEN`."

    Design: Difficulty/compensating_invariant/delivery_document_then_void_conserves_grant_committed_cents
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_draft_delivery(units_delivered=12, unit_rate_cents=4500,
                               grant_overrides={"total_award_cents": 54000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 20,
                                                        "unit_rate_cents": 4500})
    before = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert before["obligated_cents"] == 0
    assert before["expended_cents"] == 0

    documented = document_delivery(ctx["delivery"]["id"])
    assert documented["status"] == "DOCUMENTED"
    after_document = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert after_document["obligated_cents"] == 59400
    assert after_document["status"] == "FROZEN"

    voided = void_delivery(ctx["delivery"]["id"])
    assert voided["status"] == "DRAFT"
    assert voided["documentation_status"] == "INCOMPLETE"
    assert voided["allocated_total_cents"] == 0
    assert voided["admin_total_cents"] == 0

    final = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert final["obligated_cents"] == 0, "the reversal restores the pre-document value"
    assert final["expended_cents"] == 0
    assert final["burn_ratio"] == 0.0
    assert final["status"] == "OPEN"

    lines = delivery_lines(ctx["delivery"]["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "REVERSED"
    assert lines[0]["allocated_amount_cents"] == 0
    assert lines[0]["admin_amount_cents"] == 0


def test_documentation_cascade_freezes_grant_and_suspends_its_own_enrollment():
    """PRD §2.12: "When a grant reaches `FROZEN`, every enrollment carrying that
    `grant_id` whose status is `ACTIVE` is set to `SUSPENDED` and each affected
    client's `open_enrollment_count` is decremented."
    PRD §2.12: "A `burn_ratio` of at least 1.000000 is `FROZEN`."

    Design: Difficulty/transitive_cascade/documentation_cascade_freezes_grant_and_suspends_its_own_enrollment
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_draft_delivery(units_delivered=12, unit_rate_cents=4500,
                               grant_overrides={"total_award_cents": 54000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 20,
                                                        "unit_rate_cents": 4500})
    documented = document_delivery(ctx["delivery"]["id"])
    assert documented["allocated_total_cents"] == 54000
    assert documented["admin_total_cents"] == 5400

    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["obligated_cents"] == 59400
    assert grant["burn_ratio"] == 1.100000
    assert grant["status"] == "FROZEN"

    enrollment = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert enrollment["status"] == "SUSPENDED", (
        "the freeze suspends the very enrollment that produced the delivery"
    )


def test_grant_posture_cycle_open_throttled_frozen_and_back():
    """PRD §2.12: "A `burn_ratio` of at least 1.000000 is `FROZEN`. Otherwise a
    `burn_ratio` of at least 0.850000 is `THROTTLED`. Otherwise the posture is
    `OPEN`."
    PRD §2.12: "when a cost allocation is reversed and the committed total falls
    back, a `FROZEN` grant drops to `THROTTLED` or straight to `OPEN`, and a
    `THROTTLED` grant returns to `OPEN`."

    Design: Difficulty/non_linear_state_machine/grant_posture_cycle_open_throttled_frozen_and_back
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_draft_delivery(units_delivered=17, unit_rate_cents=5000,
                               grant_overrides={"total_award_cents": 100000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 40,
                                                        "unit_rate_cents": 5000,
                                                        "period_start": "2026-09-01T00:00:00Z",
                                                        "period_end": "2027-09-01T00:00:00Z"})
    document_delivery(ctx["delivery"]["id"])
    throttled = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert throttled["status"] == "THROTTLED"
    assert throttled["burn_ratio"] == 0.935000

    void_delivery(ctx["delivery"]["id"])
    reopened = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert reopened["status"] == "OPEN"
    assert reopened["burn_ratio"] == 0.0

    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    second = record_delivery(ctx["authorization"]["id"], ctx["grant"]["id"],
                             ctx["client"]["id"], authorization["version"],
                             units_delivered=20, unit_rate_cents=5000,
                             service_date="2026-10-03T00:00:00Z")
    document_delivery(second["id"])
    frozen = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert frozen["status"] == "FROZEN"
    assert frozen["burn_ratio"] == 1.100000

    suspended = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert suspended["status"] == "SUSPENDED"

    void_delivery(second["id"])
    final = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert final["status"] == "OPEN"
    assert final["burn_ratio"] == 0.0
    still_suspended = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert still_suspended["status"] == "SUSPENDED", (
        "the reversal does not reinstate the suspended enrollment"
    )


def test_burn_ratio_exactly_point_eight_five_is_throttled():
    """PRD §2.12: "The comparisons are inclusive, not exclusive: a ratio of
    exactly 0.850000 is `THROTTLED`, and a ratio of exactly 1.000000 is
    `FROZEN`."

    Design: Difficulty/boundary_precision_check/burn_ratio_exactly_point_eight_five_is_throttled
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_draft_delivery(units_delivered=34, unit_rate_cents=5000,
                               grant_overrides={"total_award_cents": 200000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 40,
                                                        "unit_rate_cents": 5000,
                                                        "period_start": "2026-09-01T00:00:00Z",
                                                        "period_end": "2027-09-01T00:00:00Z"})
    documented = document_delivery(ctx["delivery"]["id"])
    assert documented["allocated_total_cents"] == 170000
    assert documented["admin_total_cents"] == 17000

    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["burn_ratio"] == 0.935000
    assert grant["status"] == "THROTTLED", (
        "the throttle comparison is >=, so a ratio at or above the point throttles"
    )

    recomputed = get_success_data(api_client.recompute_grant_posture(ctx["grant"]["id"], FINANCE))
    assert recomputed["status"] == "THROTTLED", "the recompute is idempotent here"
    assert recomputed["burn_ratio"] == 0.935000


def test_grant_burn_posture_zero_award_guard_yields_zero_ratio_and_open():
    """PRD §2.12: "A grant with an award of zero carries a `burn_ratio` of 0.0
    rather than an undefined value."
    PRD §2.12: "Otherwise the posture is `OPEN`."

    Design: Corner/calculations/grant_burn_posture_zero_award_guard_yields_zero_ratio_and_open
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape(grants=[{"grant_code": "G-ZERO", "total_award_cents": 0,
                                         "admin_rate_pct": 0.10}])
    resp = api_client.recompute_grant_posture(landscape["grant"]["id"], FINANCE)
    data = validate_success(resp)
    assert data["burn_ratio"] == 0.0, "the zero-award guard avoids a divide by zero"
    assert data["status"] == "OPEN"
    assert data["total_award_cents"] == 0
    assert data["expended_cents"] == 0
    assert data["obligated_cents"] == 0
