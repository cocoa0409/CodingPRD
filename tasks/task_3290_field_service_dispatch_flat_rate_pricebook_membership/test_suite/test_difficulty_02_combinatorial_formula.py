"""Depth tests for the combinatorial formulas: the eligibility selector's
multi-input ranking and the incentive statement's pinned rounding order.
"""
from test_helpers import TEST_USERS, fixtures as F, validate_success

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


SHIFT = [{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-20T18:00:00Z"}]


def _dispatch_returns_technician_id(postal_a, postal_b, appointment_postal="78701"):
    """Two otherwise identical technicians; dispatch a one-hour HVAC job on the branch."""
    branch = F.create_branch()
    first = F.hire_technician(
        branch["id"], name="Dana", postal_code=postal_a, shift_segments=SHIFT,
        daily_capacity_hours=8,
    )
    second = F.hire_technician(
        branch["id"], name="Eli", postal_code=postal_b, shift_segments=SHIFT,
        daily_capacity_hours=8,
    )
    F.create_task(code="HVAC-TUNE", estimated_hours=1.0, flat_rate_cents=5000)
    appointment = F.book_appointment(
        branch["id"],
        postal_code=appointment_postal,
        window_start_utc="2026-09-10T12:00:00Z",
        window_end_utc="2026-09-10T14:00:00Z",
    )
    F.add_line(appointment["id"], code="HVAC-TUNE", status="SOLD")
    dispatched = F.dispatch(appointment["id"])
    return first, second, dispatched


# =====================================================================
# technician_eligibility_filter_multi_input_selector
# =====================================================================
def test_eligibility_ranks_equally_booked_candidates_by_postal_code(api):
    """PRD §3.5: "Among the eligible technicians the selection is deterministic, and the
    ordering is by the technician's current `scheduled_hours` ascending, then their
    `dispatched_hours` ascending, then their `postal_code` ascending, then their creation
    order ascending; the first in that order is selected."

    Design: Difficulty/combinatorial_formula/technician_eligibility_filter_multi_input_selector
    """
    # Both candidates are equally booked and equally available, so the ranking falls
    # through to the postal-code key.
    first, second, dispatched = _dispatch_returns_technician_id("78705", "78702")

    assert dispatched["technician_id"] == second["id"], (
        "78702 sorts before 78705, so the 78702 technician takes the job; "
        f"selected {dispatched['technician_id']}"
    )
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatch_status"] == "DISPATCHED"


def test_eligibility_location_clause_excludes_a_different_postal_prefix(api):
    """PRD §3.5: "the location clause: the first three characters of the technician's
    `postal_code` must equal the first three characters of the appointment's `postal_code`.
    Matching is by the leading three-character prefix, which is the system's proxy for a
    compatible service territory."

    Design: Difficulty/combinatorial_formula/technician_eligibility_filter_multi_input_selector
    """
    # A 752-prefix technician cannot serve a 787-prefix appointment even though every
    # other clause is satisfied.
    first, second, dispatched = _dispatch_returns_technician_id("78702", "75201")

    assert dispatched["technician_id"] == first["id"], (
        "only the 787-prefix technician satisfies the location clause; "
        f"selected {dispatched['technician_id']}"
    )
    technician = F.get_technician(second["id"])
    assert technician["dispatched_hours"] == 0, (
        "the excluded technician must carry no dispatched hours"
    )


def _dispatch_with_shift_ends(shift_a, shift_b):
    """Two HVAC technicians equal on every clause but their shifts."""
    branch = F.create_branch()
    first = F.hire_technician(
        branch["id"], name="Dana", postal_code="78702", shift_segments=shift_a, daily_capacity_hours=8
    )
    second = F.hire_technician(
        branch["id"], name="Eli", postal_code="78702", shift_segments=shift_b, daily_capacity_hours=8
    )
    F.create_task(code="HVAC-TUNE", estimated_hours=1.0, flat_rate_cents=5000)
    appointment = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-10T12:00:00Z",
        window_end_utc="2026-09-10T14:00:00Z",
    )
    F.add_line(appointment["id"], code="HVAC-TUNE", status="SOLD")
    return first, second, F.dispatch(appointment["id"])


def test_eligibility_shift_clause_is_a_strict_overlap(api):
    """PRD §3.5: "the shift clause: at least one of the technician's `shift_segments` must
    genuinely overlap the appointment window, meaning the segment's end is strictly later
    than `window_start_utc` and the segment's start is strictly before `window_end_utc`.
    The overlap test is strict, so a shift that ends exactly at the appointment's window
    start does not overlap and the technician is ineligible."

    Design: Difficulty/combinatorial_formula/technician_eligibility_filter_multi_input_selector
    """
    first, second, dispatched = _dispatch_with_shift_ends(
        [{"start_utc": "2026-09-10T09:00:00Z", "end_utc": "2026-09-10T12:00:00Z"}],
        SHIFT,
    )

    assert dispatched["technician_id"] == second["id"], (
        "a shift ending exactly at 12:00 does not overlap a window opening at 12:00, "
        f"selected {dispatched['technician_id']}"
    )


# =====================================================================
# incentive_pay_nested_rounding_order
# =====================================================================
def _complete_jobs(price_cents_list, code_base="HVAC-X"):
    """Complete one appointment per price on a single technician. Returns (tech, branch)."""
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"], shift_segments=SHIFT, daily_capacity_hours=40
    )
    for index, price in enumerate(price_cents_list):
        code = f"{code_base}{index}"
        F.create_task(code=code, estimated_hours=1.0, flat_rate_cents=price)
        appointment = F.book_appointment(
            branch["id"],
            window_start_utc=f"2026-09-1{index + 1}T09:00:00Z",
            window_end_utc=f"2026-09-1{index + 1}T11:00:00Z",
        )
        F.add_line(appointment["id"], code=code, status="SOLD")
        F.dispatch_two_calls(appointment["id"])
    return branch, technician


def test_incentive_rounds_each_appointment_component_before_summing(api):
    """PRD §3.11: "while the base is below 20000 cents the rate is two percent".
    PRD §3.11: "Each appointment's component is rounded individually, before any summation.
    The gross is the sum of those individually rounded components — not the rounding of the
    raw total, which is the whole point of pinning the order".

    Design: Difficulty/combinatorial_formula/incentive_pay_nested_rounding_order
    """
    branch, technician = _complete_jobs([15000, 15000])

    response = api.get_incentive_statement(
        technician["id"], {"period_year": 2026, "period_month": 9}, MANAGER
    )
    statement = validate_success(response)
    assert statement["gross_component_cents"] == 600, (
        "two 15000-cent jobs contribute two individually rounded 300-cent components, "
        f"got {statement['gross_component_cents']}"
    )
    assert statement["clamped_component_cents"] == 600
    assert statement["charge_cents"] == 0
    assert statement["incentive_cents"] == 12, (
        f"600 cents at the two-hundredths rate is 12, got {statement['incentive_cents']}"
    )


def test_incentive_uses_the_six_percent_tier_and_its_pay_rate(api):
    """PRD §3.11: "once the base is 50000 cents or more the rate is six percent".
    PRD §3.11: "a figure of at most 75000 cents yields a rate of three and a half
    hundredths".

    Design: Difficulty/combinatorial_formula/incentive_pay_nested_rounding_order
    """
    branch, technician = _complete_jobs([60000])

    response = api.get_incentive_statement(
        technician["id"], {"period_year": 2026, "period_month": 9}, MANAGER
    )
    statement = validate_success(response)
    assert statement["gross_component_cents"] == 3600, (
        f"60000 cents at six percent is 3600, got {statement['gross_component_cents']}"
    )
    assert statement["clamped_component_cents"] == 3600
    assert statement["incentive_cents"] == 72, (
        # PRD §3.11: "a figure of at most 25000 cents yields a rate of two
        # hundredths".  3600 sits in that band, so the rate is 0.02 and the
        # payout is 3600 * 0.02 = 72; 0.035 only applies above 25000 and at or
        # below 75000.
        f"3600 cents at the two-hundredths rate is 72, "
        f"got {statement['incentive_cents']}"
    )