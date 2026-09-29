"""Engineered substitutions: the four disposition branches and their reversal.

Covers the APPROVED / APPROVED_AS_NOTED divergence (the money moves, the schedule does
not), the contingency driver's coupling to a disruption event, the bounded
SUBMITTED → REVISION_REQUESTED → SUBMITTED cycle, and the exact conservation the
rescission of an approval must honour.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_disruption_event,
    assert_exposure_band,
    assert_instant_equals,
    assert_material_package,
    assert_package_schedule_invariants,
    assert_rff_risk_band,
    assert_substitution_request,
    assert_supplier,
    build_buyout_scenario,
    build_contingency_substitution_scenario,
    dispose_substitution,
    log_disruption_event,
    open_project,
    raise_substitution,
    read_package,
    read_project,
    register_package,
    register_supplier,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_substitution_request_payload,
    disposition_substitution_payload,
    rescind_substitution_payload,
    resubmit_substitution_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
DESIGN_ENGINEER = TEST_USERS["design_engineer_headers"]

SUBSTITUTE_NAME = "Northline Steel Mills"
PROPOSED_PRODUCT = "Alternate mill-certified plate assembly"
COST_DELTA = 45000.00
SCHEDULE_DELTA_DAYS = 12
ENGINEER_CONDITIONS = (
    "Substitute accepted only if the published fabrication window is held without change"
)
UNKNOWN_ID = "00000000-0000-4000-8000-000000000999"


# ─── private setup helpers (not tests — no Design tag) ────────────────────

def _read_substitution(request_id):
    """GET one substitution request through validate_success."""
    data = validate_success(
        api_client.get_substitution_request(request_id, BUYOUT_MANAGER)
    )
    assert_substitution_request(data)
    return data


def _read_package(package_id):
    """GET one scope package through validate_success, checking its derivations."""
    data = validate_success(api_client.get_material_package(package_id, BUYOUT_MANAGER))
    assert_material_package(data)
    assert_package_schedule_invariants(data)
    assert_rff_risk_band(data["float_days"], data["rff_risk_band"])
    return data


def _read_supplier(supplier_id):
    data = validate_success(api_client.get_supplier(supplier_id, BUYOUT_MANAGER))
    assert_supplier(data)
    assert_exposure_band(data["exposure_score_snapshot"], data["exposure_band_snapshot"])
    return data


def _setup_package_and_substitute(*, scope_code="STRUCT-STEEL-01", project=None):
    """A project, one scope package at the task defaults, and a clean substitute supplier."""
    project = project or open_project()
    package = register_package(project["id"], scope_code=scope_code)
    substitute = register_supplier(
        legal_name=SUBSTITUTE_NAME,
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    return project, package, substitute


def _setup_submitted_substitution(**request_overrides):
    """A SUBMITTED request proposing 45000.00 and 12 days against a fresh package."""
    project, package, substitute = _setup_package_and_substitute()
    overrides = {
        "proposed_product": PROPOSED_PRODUCT,
        "cost_delta": COST_DELTA,
        "schedule_delta_days": SCHEDULE_DELTA_DAYS,
    }
    overrides.update(request_overrides)
    request = raise_substitution(package["id"], substitute["id"], **overrides)
    return {
        "project": project,
        "package": package,
        "substitute": substitute,
        "request": request,
    }


def _setup_twin_packages_with_submitted_substitutions():
    """Two identical packages, one substitute supplier, and one SUBMITTED request on each.

    The two requests carry identical `cost_delta` and `schedule_delta_days`, so any later
    difference between the packages is attributable to the disposition branch alone.
    """
    project = open_project()
    package_a = register_package(project["id"], scope_code="STRUCT-STEEL-01")
    package_b = register_package(project["id"], scope_code="STRUCT-STEEL-02")
    substitute = register_supplier(
        legal_name=SUBSTITUTE_NAME,
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    request_a = raise_substitution(
        package_a["id"],
        substitute["id"],
        proposed_product=PROPOSED_PRODUCT,
        cost_delta=COST_DELTA,
        schedule_delta_days=SCHEDULE_DELTA_DAYS,
    )
    request_b = raise_substitution(
        package_b["id"],
        substitute["id"],
        proposed_product=PROPOSED_PRODUCT,
        cost_delta=COST_DELTA,
        schedule_delta_days=SCHEDULE_DELTA_DAYS,
    )
    return {
        "project": project,
        "package_a": package_a,
        "package_b": package_b,
        "substitute": substitute,
        "request_a": request_a,
        "request_b": request_b,
    }


def _substitution_count_for_package(package_id):
    _rows, meta = validate_paginated(
        api_client.list_substitution_requests(
            BUYOUT_MANAGER, params={"material_package_id": package_id}
        )
    )
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine /
#          substitution_branch_approved_as_noted_diverges_from_approved
# ---------------------------------------------------------------------------

def test_substitution_approved_applies_both_the_cost_and_the_schedule_delta():
    """A clean approval moves the money and lengthens fabrication, re-deriving the schedule.

    PRD §3.8: "On approval both deltas are applied: `applied_cost_delta` is set to
    `cost_delta` and `applied_schedule_delta_days` to `schedule_delta_days`, the package's
    `estimated_cost` is increased by the applied cost delta and its
    `fabrication_duration_days` is increased by the applied schedule delta, and the
    package's `lead_time_days`, `release_for_fabrication_date`, `float_days` and
    `rff_risk_band` are all re-derived from the mutated durations". PRD §3.1:
    "`lead_time_days` is the sum of `submittal_review_days`, `fabrication_duration_days`
    and `delivery_transit_days`." PRD §3.1: "`release_for_fabrication_date` is the
    `required_onsite_date` moved backwards by `lead_time_days` calendar days."

    Design: Difficulty/non_linear_state_machine/substitution_branch_approved_as_noted_diverges_from_approved
    """
    scenario = _setup_submitted_substitution()
    package = scenario["package"]

    baseline = _read_package(package["id"])
    assert baseline["fabrication_duration_days"] == 70
    assert baseline["lead_time_days"] == 111
    assert baseline["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)

    dispositioned = validate_success(
        api_client.disposition_substitution_request(
            scenario["request"]["id"],
            disposition_substitution_payload("APPROVED"),
            DESIGN_ENGINEER,
        )
    )
    assert_substitution_request(dispositioned)
    assert dispositioned["status"] == "APPROVED"
    assert dispositioned["applied_cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert dispositioned["applied_schedule_delta_days"] == SCHEDULE_DELTA_DAYS

    mutated = _read_package(package["id"])
    assert mutated["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert mutated["fabrication_duration_days"] == 82
    assert mutated["lead_time_days"] == 123
    assert_instant_equals(
        mutated["release_for_fabrication_date"], "2026-10-29T00:00:00.000Z"
    )
    assert mutated["float_days"] == 89
    assert mutated["rff_risk_band"] == "ON_TRACK"
    # The baseline snapshots anchor the compensation invariant and never move.
    assert mutated["baseline_estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert mutated["baseline_fabrication_duration_days"] == 70

    project = read_project(scenario["project"]["id"])
    assert project["estimated_total_cost"] == pytest.approx(1245000.00, abs=0.005)


def test_substitution_approved_as_noted_moves_the_money_but_not_the_schedule():
    """On identical inputs, APPROVED_AS_NOTED zeroes the schedule delta while APPROVED keeps it.

    PRD §3.8: "`applied_cost_delta` is set to `cost_delta` exactly as before, but
    `applied_schedule_delta_days` is set to **0** — the engineer's conditions forbid any
    schedule impact — so the package's `estimated_cost` is increased by the applied cost
    delta while its `fabrication_duration_days` is left completely untouched, and the
    release-for-fabrication schedule consequently shifts only insofar as nothing about it
    changed." PRD §3.8: "This is the single most commonly mis-implemented branch in the
    workflow: the money moves, the schedule does not." PRD §3.8: "On approval both deltas
    are applied: `applied_cost_delta` is set to `cost_delta` and
    `applied_schedule_delta_days` to `schedule_delta_days`".

    Design: Difficulty/non_linear_state_machine/substitution_branch_approved_as_noted_diverges_from_approved
    """
    scenario = _setup_twin_packages_with_submitted_substitutions()

    approved = dispose_substitution(scenario["request_a"]["id"], "APPROVED")
    assert approved["status"] == "APPROVED"

    as_noted = validate_success(
        api_client.disposition_substitution_request(
            scenario["request_b"]["id"],
            disposition_substitution_payload(
                "APPROVED_AS_NOTED", engineer_conditions=ENGINEER_CONDITIONS
            ),
            DESIGN_ENGINEER,
        )
    )
    assert_substitution_request(as_noted)
    assert as_noted["status"] == "APPROVED_AS_NOTED"
    assert as_noted["engineer_conditions"] == ENGINEER_CONDITIONS
    assert as_noted["cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert as_noted["schedule_delta_days"] == SCHEDULE_DELTA_DAYS
    assert as_noted["applied_cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert as_noted["applied_schedule_delta_days"] == 0

    package_a = _read_package(scenario["package_a"]["id"])
    package_b = _read_package(scenario["package_b"]["id"])

    # The money moves identically on both branches.
    assert package_a["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert package_b["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)

    # The schedule diverges: only the clean approval lengthens fabrication.
    assert package_a["fabrication_duration_days"] == 82
    assert package_b["fabrication_duration_days"] == 70
    assert package_a["lead_time_days"] == 123
    assert package_b["lead_time_days"] == 111
    assert_instant_equals(
        package_a["release_for_fabrication_date"], "2026-10-29T00:00:00.000Z"
    )
    assert_instant_equals(
        package_b["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert package_a["float_days"] == 89
    assert package_b["float_days"] == 101
    assert package_a["rff_risk_band"] == "ON_TRACK"
    assert package_b["rff_risk_band"] == "ON_TRACK"
    assert package_b["baseline_fabrication_duration_days"] == 70

    project = read_project(scenario["project"]["id"])
    assert project["estimated_total_cost"] == pytest.approx(2490000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade /
#          contingency_substitution_approval_mitigates_event_and_reshapes_schedule
# ---------------------------------------------------------------------------

def _setup_contingency_substitution():
    """A SUBMITTED DISRUPTION_CONTINGENCY request against an OPEN 25 percent tariff event."""
    return build_contingency_substitution_scenario(
        event_overrides={
            "event_type": "TARIFF_IMPOSED",
            "effective_date": "2026-07-01T00:00:00.000Z",
            "tariff_rate_pct": 25.00,
        },
        substitute_overrides={
            "legal_name": SUBSTITUTE_NAME,
            "country_of_origin": "US",
            "declared_tariff_rate_pct": 0.00,
        },
        request_overrides={
            "proposed_product": PROPOSED_PRODUCT,
            "cost_delta": COST_DELTA,
            "schedule_delta_days": SCHEDULE_DELTA_DAYS,
        },
    )


def test_substitution_contingency_approval_reshapes_the_package_schedule():
    """Approving the contingency applies both deltas and re-derives the release schedule.

    PRD §3.8: "On approval both deltas are applied: `applied_cost_delta` is set to
    `cost_delta` and `applied_schedule_delta_days` to `schedule_delta_days`, the package's
    `estimated_cost` is increased by the applied cost delta and its
    `fabrication_duration_days` is increased by the applied schedule delta, and the
    package's `lead_time_days`, `release_for_fabrication_date`, `float_days` and
    `rff_risk_band` are all re-derived from the mutated durations". PRD §3.1: "`float_days`
    measures how much room is left before the release date arrives: it is the number of
    whole days from the current logical clock forward to `release_for_fabrication_date`".
    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less, `AT_RISK`
    when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or more."

    Design: Difficulty/transitive_cascade/contingency_substitution_approval_mitigates_event_and_reshapes_schedule
    """
    scenario = _setup_contingency_substitution()
    request = scenario["request"]
    assert request["driver"] == "DISRUPTION_CONTINGENCY"
    assert request["disruption_event_id"] == scenario["event"]["id"]

    approved = validate_success(
        api_client.disposition_substitution_request(
            request["id"],
            disposition_substitution_payload("APPROVED"),
            DESIGN_ENGINEER,
        )
    )
    assert_substitution_request(approved)
    assert approved["status"] == "APPROVED"
    assert approved["applied_cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert approved["applied_schedule_delta_days"] == SCHEDULE_DELTA_DAYS

    package = _read_package(scenario["package"]["id"])
    assert package["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert package["fabrication_duration_days"] == 82
    assert package["lead_time_days"] == 123
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-10-29T00:00:00.000Z"
    )
    assert package["float_days"] == 89
    assert package["rff_risk_band"] == "ON_TRACK"

    project = read_project(scenario["project"]["id"])
    assert project["estimated_total_cost"] == pytest.approx(1245000.00, abs=0.005)


def test_substitution_contingency_approval_mitigates_the_event_and_clears_exposure():
    """The same approval closes the disruption and drops the incumbent from HIGH to LOW.

    PRD §3.8: "When the `driver` is `DISRUPTION_CONTINGENCY` and the disposition is either
    `APPROVED` or `APPROVED_AS_NOTED`, the referenced disruption event moves from `OPEN` to
    `MITIGATED` and its `mitigated_at` is stamped with the current logical clock." PRD §3.8:
    "Because only `OPEN` events feed either exposure reading, that single transition lowers
    the offending supplier's `open_disruption_count` and both exposure figures on the next
    read of that supplier". PRD §3.2: "That effective rate is multiplied by 1.6, and the
    product is capped at 40 points." PRD §3.2: "The **event component** is the count of
    in-scope `OPEN` events of any type, whatever their kind, multiplied by 20 points, also
    capped at 40". PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US`". PRD §3.2: "The band is then `HIGH` when the score is at
    least 60, `ELEVATED` when it is at least 30 but below 60, and `LOW` below 30". PRD §3.2:
    "Only `OPEN` events participate in either component — a `MITIGATED` event is excluded
    entirely, not down-weighted".

    Design: Difficulty/transitive_cascade/contingency_substitution_approval_mitigates_event_and_reshapes_schedule
    """
    scenario = _setup_contingency_substitution()
    incumbent_id = scenario["incumbent"]["id"]

    # 25.00 x 1.6 capped at 40, plus one open event worth 20, plus 0 for a US origin.
    before = _read_supplier(incumbent_id)
    assert before["open_disruption_count"] == 1
    assert before["exposure_score_snapshot"] == pytest.approx(60.00, abs=0.005)
    assert before["exposure_band_snapshot"] == "HIGH"

    validate_success(
        api_client.disposition_substitution_request(
            scenario["request"]["id"],
            disposition_substitution_payload("APPROVED"),
            DESIGN_ENGINEER,
        )
    )

    events, meta = validate_paginated(
        api_client.list_disruption_events(incumbent_id, BUYOUT_MANAGER)
    )
    assert meta["total_count"] == 1
    event = events[0]
    assert_disruption_event(event)
    assert event["id"] == scenario["event"]["id"]
    assert event["status"] == "MITIGATED"
    assert_instant_equals(event["mitigated_at"], "2026-08-01T00:00:00.000Z")

    after = _read_supplier(incumbent_id)
    assert after["open_disruption_count"] == 0
    assert after["exposure_score_snapshot"] == pytest.approx(0.00, abs=0.005)
    assert after["exposure_band_snapshot"] == "LOW"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant /
#          rescind_restores_package_schedule_days_and_estimate_exactly
# ---------------------------------------------------------------------------

def test_substitution_rescinding_an_approval_restores_cost_and_duration_exactly():
    """Rescission returns the package to the cent and the day it stood at before approval.

    PRD §3.8: "Rescinding an `APPROVED` request reverses both applications exactly: the
    package's `estimated_cost` is reduced by `applied_cost_delta` and its
    `fabrication_duration_days` is reduced by `applied_schedule_delta_days`, the
    release-for-fabrication schedule is re-derived, and both applied deltas are reset to 0."
    PRD §3.8: "The conservation requirement is strict — after the rescission the package's
    cost and duration must equal exactly what they were before the approval, to the cent and
    to the day." PRD §3.8: "`RESCINDED` is terminal, and a rescission does not reopen the
    disruption event it mitigated."

    Design: Difficulty/compensating_invariant/rescind_restores_package_schedule_days_and_estimate_exactly
    """
    scenario = _setup_submitted_substitution()
    package_id = scenario["package"]["id"]

    before = _read_package(package_id)
    approved = dispose_substitution(scenario["request"]["id"], "APPROVED")
    assert approved["status"] == "APPROVED"
    mutated = _read_package(package_id)
    assert mutated["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert mutated["fabrication_duration_days"] == 82

    rescinded = validate_success(
        api_client.rescind_substitution_request(
            scenario["request"]["id"],
            rescind_substitution_payload(
                rescission_reason="Engineer of record withdrew the alternate approval"
            ),
            BUYOUT_MANAGER,
        )
    )
    assert_substitution_request(rescinded)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert rescinded["applied_schedule_delta_days"] == 0
    # The proposal itself is retained; only the applications are reversed.
    assert rescinded["cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert rescinded["schedule_delta_days"] == SCHEDULE_DELTA_DAYS

    restored = _read_package(package_id)
    assert restored["estimated_cost"] == pytest.approx(
        before["estimated_cost"], abs=0.005
    )
    assert restored["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert restored["fabrication_duration_days"] == before["fabrication_duration_days"]
    assert restored["fabrication_duration_days"] == 70
    assert restored["estimated_cost"] == pytest.approx(
        restored["baseline_estimated_cost"], abs=0.005
    )
    assert (
        restored["fabrication_duration_days"]
        == restored["baseline_fabrication_duration_days"]
    )
    assert restored["lead_time_days"] == 111
    assert_instant_equals(
        restored["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert restored["float_days"] == 101
    assert restored["rff_risk_band"] == "ON_TRACK"

    project = read_project(scenario["project"]["id"])
    assert project["estimated_total_cost"] == pytest.approx(1200000.00, abs=0.005)


def test_substitution_rescinding_an_approval_as_noted_reverses_only_the_money():
    """An APPROVED_AS_NOTED rescission gives back the cost; there is no duration to restore.

    PRD §3.8: "Rescinding an `APPROVED_AS_NOTED` request reduces `estimated_cost` by
    `applied_cost_delta` and resets `applied_cost_delta` to 0; there is no duration to
    restore, because `applied_schedule_delta_days` was already 0." PRD §3.8:
    "`applied_cost_delta` is set to `cost_delta` exactly as before, but
    `applied_schedule_delta_days` is set to **0** — the engineer's conditions forbid any
    schedule impact — so the package's `estimated_cost` is increased by the applied cost
    delta while its `fabrication_duration_days` is left completely untouched".

    Design: Difficulty/compensating_invariant/rescind_restores_package_schedule_days_and_estimate_exactly
    """
    scenario = _setup_submitted_substitution()
    package_id = scenario["package"]["id"]

    dispose_substitution(
        scenario["request"]["id"],
        "APPROVED_AS_NOTED",
        engineer_conditions=ENGINEER_CONDITIONS,
    )
    mutated = _read_package(package_id)
    assert mutated["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert mutated["fabrication_duration_days"] == 70

    rescinded = validate_success(
        api_client.rescind_substitution_request(
            scenario["request"]["id"],
            rescind_substitution_payload(
                rescission_reason="Owner declined to fund the conditioned alternate"
            ),
            BUYOUT_MANAGER,
        )
    )
    assert_substitution_request(rescinded)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert rescinded["applied_schedule_delta_days"] == 0

    restored = _read_package(package_id)
    assert restored["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert restored["fabrication_duration_days"] == 70
    assert restored["lead_time_days"] == 111
    assert_instant_equals(
        restored["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert restored["float_days"] == 101

    project = read_project(scenario["project"]["id"])
    assert project["estimated_total_cost"] == pytest.approx(1200000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: entities /
#          not_found_get_substitution_request_falls_back_to_the_generic_record_code
# ---------------------------------------------------------------------------

def test_substitution_get_unknown_request_uses_the_generic_record_not_found_code():
    """A substitution request has no bespoke 404 code of its own.

    PRD §2.8: "The remaining record types — storage arrangements, storage documents,
    substitution requests, change order requests and disruption events — share the generic
    `ERR_RECORD_NOT_FOUND`. All six of these codes are HTTP 404."

    Design: Corner/entities/not_found_get_substitution_request_falls_back_to_the_generic_record_code
    """
    response = api_client.get_substitution_request(UNKNOWN_ID, BUYOUT_MANAGER)
    validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND.value, 404)


# ---------------------------------------------------------------------------
# Queue B: entities /
#          foreign_key_references_validated_unknown_proposed_supplier_id_not_found
# ---------------------------------------------------------------------------

def test_substitution_unknown_proposed_supplier_id_is_a_supplier_not_found():
    """An unresolvable `proposed_supplier_id` is attributed to the supplier, not the record.

    PRD §2.8: "The same mapping applies to body foreign keys." PRD §2.8: "a `supplier_id` or
    a `proposed_supplier_id` that names no supplier is `ERR_SUPPLIER_NOT_FOUND`". PRD §2.8:
    "All six of these codes are HTTP 404."

    Design: Corner/entities/foreign_key_references_validated_unknown_proposed_supplier_id_not_found
    """
    project = open_project()
    package = register_package(project["id"])

    response = api_client.create_substitution_request(
        create_substitution_request_payload(
            material_package_id=package["id"],
            proposed_supplier_id=UNKNOWN_ID,
            driver="VALUE_ENGINEERING",
            proposed_product=PROPOSED_PRODUCT,
            cost_delta=COST_DELTA,
            schedule_delta_days=SCHEDULE_DELTA_DAYS,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_FOUND.value, 404)

    assert _substitution_count_for_package(package["id"]) == 0
    unchanged = _read_package(package["id"])
    assert unchanged["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert unchanged["fabrication_duration_days"] == 70


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          valid_transition_revision_requested_then_resubmit_returns_to_submitted
# ---------------------------------------------------------------------------

def test_substitution_revision_requested_then_resubmit_returns_to_submitted():
    """The rework cycle bumps `revision_round` exactly once and overwrites the proposal.

    PRD §3.8: "A **`REVISION_REQUESTED`** disposition sends the request back for rework and
    is permitted only while `revision_round` is still below 2; a third revision request is
    refused with `ERR_INVALID_STATE_TRANSITION`. It records `engineer_conditions` when
    supplied and mutates nothing on the package." PRD §3.8: "A `BuyoutManager` then
    resubmits, supplying a fresh `proposed_product`, `cost_delta` and `schedule_delta_days`,
    which overwrite the stored values along with `submitted_by_user_id`; `revision_round`
    increments by exactly 1 and the request returns to `SUBMITTED`."

    Design: Corner/state_machines/valid_transition_revision_requested_then_resubmit_returns_to_submitted
    """
    scenario = _setup_submitted_substitution()
    package_id = scenario["package"]["id"]
    assert scenario["request"]["revision_round"] == 0

    sent_back = validate_success(
        api_client.disposition_substitution_request(
            scenario["request"]["id"],
            disposition_substitution_payload(
                "REVISION_REQUESTED",
                engineer_conditions="Provide mill certificates and a revised erection sequence",
            ),
            DESIGN_ENGINEER,
        )
    )
    assert_substitution_request(sent_back)
    assert sent_back["status"] == "REVISION_REQUESTED"
    # The disposition itself does not increment the counter; the resubmission does.
    assert sent_back["revision_round"] == 0
    assert (
        sent_back["engineer_conditions"]
        == "Provide mill certificates and a revised erection sequence"
    )
    assert sent_back["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert sent_back["applied_schedule_delta_days"] == 0

    untouched = _read_package(package_id)
    assert untouched["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert untouched["fabrication_duration_days"] == 70

    resubmitted = validate_success(
        api_client.resubmit_substitution_request(
            scenario["request"]["id"],
            resubmit_substitution_payload(
                proposed_product="Revised alternate plate assembly with mill certification",
                cost_delta=30000.00,
                schedule_delta_days=8,
            ),
            BUYOUT_MANAGER,
        )
    )
    assert_substitution_request(resubmitted)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert (
        resubmitted["proposed_product"]
        == "Revised alternate plate assembly with mill certification"
    )
    assert resubmitted["cost_delta"] == pytest.approx(30000.00, abs=0.005)
    assert resubmitted["schedule_delta_days"] == 8
    assert resubmitted["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert resubmitted["applied_schedule_delta_days"] == 0

    still_untouched = _read_package(package_id)
    assert still_untouched["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert still_untouched["fabrication_duration_days"] == 70
    assert still_untouched["lead_time_days"] == 111


# ---------------------------------------------------------------------------
# Queue B: validations /
#          conditional_validation_approved_as_noted_requires_non_blank_engineer_conditions
# ---------------------------------------------------------------------------

def test_substitution_approved_as_noted_requires_non_blank_engineer_conditions():
    """APPROVED_AS_NOTED is refused without conditions, and accepted with them.

    PRD §3.8: "An **`APPROVED_AS_NOTED`** disposition carries the same package-not-`CLOSED`
    and forward-exposure preconditions, and adds one of its own: `engineer_conditions` must
    be supplied and non-blank, otherwise `ERR_ENGINEER_CONDITIONS_REQUIRED`." PRD §3.8:
    "`applied_cost_delta` is set to `cost_delta` exactly as before, but
    `applied_schedule_delta_days` is set to **0** — the engineer's conditions forbid any
    schedule impact — so the package's `estimated_cost` is increased by the applied cost
    delta while its `fabrication_duration_days` is left completely untouched".

    Design: Corner/validations/conditional_validation_approved_as_noted_requires_non_blank_engineer_conditions
    """
    scenario = _setup_submitted_substitution()
    package_id = scenario["package"]["id"]
    request_id = scenario["request"]["id"]

    missing = api_client.disposition_substitution_request(
        request_id,
        disposition_substitution_payload("APPROVED_AS_NOTED"),
        DESIGN_ENGINEER,
    )
    validate_error(missing, ApiErrorId.ERR_ENGINEER_CONDITIONS_REQUIRED.value, 422)

    blank = api_client.disposition_substitution_request(
        request_id,
        disposition_substitution_payload("APPROVED_AS_NOTED", engineer_conditions="   "),
        DESIGN_ENGINEER,
    )
    validate_error(blank, ApiErrorId.ERR_ENGINEER_CONDITIONS_REQUIRED.value, 422)

    still_submitted = _read_substitution(request_id)
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert still_submitted["applied_schedule_delta_days"] == 0
    untouched = _read_package(package_id)
    assert untouched["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert untouched["fabrication_duration_days"] == 70

    accepted = validate_success(
        api_client.disposition_substitution_request(
            request_id,
            disposition_substitution_payload(
                "APPROVED_AS_NOTED", engineer_conditions=ENGINEER_CONDITIONS
            ),
            DESIGN_ENGINEER,
        )
    )
    assert_substitution_request(accepted)
    assert accepted["status"] == "APPROVED_AS_NOTED"
    assert accepted["engineer_conditions"] == ENGINEER_CONDITIONS
    assert accepted["applied_cost_delta"] == pytest.approx(COST_DELTA, abs=0.005)
    assert accepted["applied_schedule_delta_days"] == 0

    mutated = _read_package(package_id)
    assert mutated["estimated_cost"] == pytest.approx(1245000.00, abs=0.005)
    assert mutated["fabrication_duration_days"] == 70
    assert mutated["lead_time_days"] == 111
    assert_instant_equals(
        mutated["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )


# ---------------------------------------------------------------------------
# Queue B: validations /
#          conditional_validation_a_disruption_event_id_pairs_only_with_the_contingency_driver
# ---------------------------------------------------------------------------

def test_substitution_disruption_event_id_pairs_only_with_the_contingency_driver():
    """The event reference is required by the contingency driver and forbidden to the others.

    PRD §3.8: "Second, the `disruption_event_id` is conditional on the driver: when the
    `driver` is `DISRUPTION_CONTINGENCY` it is **required**, and the event it names must
    belong to the supplier the package is currently quoted or committed against — that is
    what makes the substitution genuinely a contingency response rather than an unrelated
    swap. With any other driver, `disruption_event_id` must be omitted." PRD §3.8: "Two
    coherence rules bind the request to the world it claims to describe, and both are
    reported as `ERR_INVALID_REQUEST`." PRD §3.2: "Events start `OPEN`, with `mitigated_at`
    null".

    Design: Corner/validations/conditional_validation_a_disruption_event_id_pairs_only_with_the_contingency_driver
    """
    project = open_project()
    package = register_package(project["id"])
    incumbent = register_supplier()
    # The event must belong to the supplier the package is quoted against.
    submit_quote(package["id"], incumbent["id"])
    event = log_disruption_event(
        incumbent["id"],
        event_type="PORT_CONGESTION",
        effective_date="2026-07-20T00:00:00.000Z",
        description="Berth congestion at the discharge port delaying mill shipments",
        tariff_rate_pct=0.00,
    )
    substitute = register_supplier(
        legal_name=SUBSTITUTE_NAME,
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )

    # A non-contingency driver may not carry the reference.
    with_reference = api_client.create_substitution_request(
        create_substitution_request_payload(
            material_package_id=package["id"],
            proposed_supplier_id=substitute["id"],
            driver="VALUE_ENGINEERING",
            proposed_product=PROPOSED_PRODUCT,
            cost_delta=COST_DELTA,
            schedule_delta_days=SCHEDULE_DELTA_DAYS,
            disruption_event_id=event["id"],
        ),
        BUYOUT_MANAGER,
    )
    validate_error(with_reference, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # The contingency driver may not omit it.
    without_reference = api_client.create_substitution_request(
        create_substitution_request_payload(
            material_package_id=package["id"],
            proposed_supplier_id=substitute["id"],
            driver="DISRUPTION_CONTINGENCY",
            proposed_product=PROPOSED_PRODUCT,
            cost_delta=COST_DELTA,
            schedule_delta_days=SCHEDULE_DELTA_DAYS,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(without_reference, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    assert _substitution_count_for_package(package["id"]) == 0

    # The matched pair is accepted.
    created = validate_success(
        api_client.create_substitution_request(
            create_substitution_request_payload(
                material_package_id=package["id"],
                proposed_supplier_id=substitute["id"],
                driver="DISRUPTION_CONTINGENCY",
                proposed_product=PROPOSED_PRODUCT,
                cost_delta=COST_DELTA,
                schedule_delta_days=SCHEDULE_DELTA_DAYS,
                disruption_event_id=event["id"],
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_substitution_request(created)
    assert created["status"] == "SUBMITTED"
    assert created["driver"] == "DISRUPTION_CONTINGENCY"
    assert created["disruption_event_id"] == event["id"]
    assert created["revision_round"] == 0
    assert created["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert created["applied_schedule_delta_days"] == 0
    assert _substitution_count_for_package(package["id"]) == 1

    events, meta = validate_paginated(
        api_client.list_disruption_events(incumbent["id"], BUYOUT_MANAGER)
    )
    assert meta["total_count"] == 1
    assert_disruption_event(events[0])
    assert events[0]["status"] == "OPEN"
    assert events[0]["mitigated_at"] is None


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_a_substitution_may_not_propose_the_supplier_already_committed
# ---------------------------------------------------------------------------

def test_substitution_may_not_propose_the_supplier_already_committed():
    """The incumbent behind a COMMITTED order cannot be proposed as its own substitute.

    PRD §3.8: "First, a substitution may not propose the supplier the package is already
    committed to: the `proposed_supplier_id` must not equal the supplier behind any
    commitment on that package whose `commitment_status` is `PENDING` or `COMMITTED`."
    PRD §3.8: "Two coherence rules bind the request to the world it claims to describe, and
    both are reported as `ERR_INVALID_REQUEST`."

    Design: Corner/validations/violation_error_a_substitution_may_not_propose_the_supplier_already_committed
    """
    scenario = build_buyout_scenario()
    package = scenario["package"]
    incumbent = scenario["supplier"]
    assert scenario["commitment"]["commitment_status"] == "COMMITTED"

    refused = api_client.create_substitution_request(
        create_substitution_request_payload(
            material_package_id=package["id"],
            proposed_supplier_id=incumbent["id"],
            driver="VALUE_ENGINEERING",
            proposed_product=PROPOSED_PRODUCT,
            cost_delta=COST_DELTA,
            schedule_delta_days=SCHEDULE_DELTA_DAYS,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    assert _substitution_count_for_package(package["id"]) == 0

    substitute = register_supplier(
        legal_name=SUBSTITUTE_NAME,
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    created = validate_success(
        api_client.create_substitution_request(
            create_substitution_request_payload(
                material_package_id=package["id"],
                proposed_supplier_id=substitute["id"],
                driver="VALUE_ENGINEERING",
                proposed_product=PROPOSED_PRODUCT,
                cost_delta=COST_DELTA,
                schedule_delta_days=SCHEDULE_DELTA_DAYS,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_substitution_request(created)
    assert created["status"] == "SUBMITTED"
    assert created["proposed_supplier_id"] == substitute["id"]
    assert _substitution_count_for_package(package["id"]) == 1

    unchanged = read_package(package["id"])
    assert unchanged["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)
    assert unchanged["fabrication_duration_days"] == 70
