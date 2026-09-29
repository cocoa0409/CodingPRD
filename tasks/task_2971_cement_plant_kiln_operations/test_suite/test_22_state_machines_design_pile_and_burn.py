"""Breadth coverage of the raw mix design lifecycle, the blending bed's seal gate and the
two divergent branches of trial-burn adjudication.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals, assert_oxide
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LAB_HEADERS,
    QUALITY_HEADERS,
)


def _d1_components(materials):
    return [
        f.component(materials["limestone"]["id"], 80.00),
        f.component(materials["clay"]["id"], 16.00),
        f.component(materials["iron_ore"]["id"], 4.00),
    ]


# ---------------------------------------------------------------------------
# valid_transition: the design's three-hop happy path
# ---------------------------------------------------------------------------
def test_a_design_walks_draft_to_submitted_to_approved(api):
    """Each hop is one mutation, so the version reads 1, 2 and 3, and the approval stamps
    the second person's identity and the logical clock onto the row.

    PRD: "Approval by a `QualityManager` moves the design `SUBMITTED → APPROVED`, records
    the approver in `approved_by_user_id` and the logical clock instant in `approved_at`."

    Design: Corner/state_machines/design_walks_draft_to_submitted_to_approved
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)

    drafted = validate_success(
        api.create_design(
            f.design_payload(
                plant["id"],
                _d1_components(materials),
                code="D1",
                target_lsf=97.00,
                target_sm=1.50,
                target_am=0.80,
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["revision_count"] == 0
    assert drafted["created_by_user_id"] == ENGINEER_HEADERS["X-User-ID"]
    assert drafted["approved_by_user_id"] is None
    assert drafted["approved_at"] is None
    assert drafted["superseded_by_design_id"] is None
    assert drafted["version"] == 1

    submitted = validate_success(api.submit_design(drafted["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == 2
    assert submitted["approved_by_user_id"] is None

    approved = validate_success(api.approve_design(drafted["id"], QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["version"] == 3
    assert approved["approved_by_user_id"] == QUALITY_HEADERS["X-User-ID"]
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00Z", "approved_at")
    assert approved["superseded_by_design_id"] is None


def test_submission_re_derives_the_oxides_and_the_modules(api):
    """The chemistry is recomputed on the submit hop rather than deferred to approval, so
    the SUBMITTED read already carries 41.8000 / 12.7200 / 3.7600 / 4.7200 and an LSF of
    96.94 that sits 0.06 from the 97.00 target.

    PRD: "Submission re-derives the four oxides and the three modules before it checks
    anything, then applies two substantive gates."

    Design: Corner/state_machines/design_walks_draft_to_submitted_to_approved
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    drafted = fx.create_draft_design(
        api,
        plant["id"],
        materials,
        components=_d1_components(materials),
        code="D1",
        target_lsf=97.00,
        target_sm=1.50,
        target_am=0.80,
    )

    submitted = validate_success(api.submit_design(drafted["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    assert_oxide(submitted["as_designed_cao_pct"], 41.8000, "as_designed_cao_pct")
    assert_oxide(submitted["as_designed_sio2_pct"], 12.7200, "as_designed_sio2_pct")
    assert_oxide(submitted["as_designed_al2o3_pct"], 3.7600, "as_designed_al2o3_pct")
    assert_oxide(submitted["as_designed_fe2o3_pct"], 4.7200, "as_designed_fe2o3_pct")
    assert_amount(submitted["as_designed_lsf"], 96.94, "as_designed_lsf")
    assert_amount(submitted["as_designed_sm"], 1.50, "as_designed_sm")
    assert_amount(submitted["as_designed_am"], 0.80, "as_designed_am")


# ---------------------------------------------------------------------------
# side_effect_execution: approval supersedes the plant's previous recipe
# ---------------------------------------------------------------------------
def test_approving_a_second_design_supersedes_the_first(api):
    """The new design's own response says nothing about the cascade, but the older design
    has moved to SUPERSEDED with a back-pointer and a fifth version, only one design of the
    plant is left APPROVED, and the pile already on the ground is untouched.

    PRD: "Approval carries one cascade hop: the plant's previously `APPROVED` design, if one
    exists, moves `APPROVED → SUPERSEDED`, has its `superseded_by_design_id` set to the
    newly approved design's identifier, and has its `version` incremented."

    Design: Corner/state_machines/approving_a_second_design_supersedes_the_first
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    d2 = fx.create_approved_design(api, plant["id"], materials)
    pile = fx.create_open_pile(api, plant["id"], d2["id"])
    blended = fx.add_reference_additions(api, pile["id"], materials)
    assert_amount(blended["as_blended_lsf"], 96.98, "as_blended_lsf")

    before = validate_success(api.get_design(d2["id"], ENGINEER_HEADERS))
    assert before["status"] == "APPROVED"
    assert before["active_pile_count"] == 1
    assert before["version"] == 4

    d1 = fx.create_draft_design(
        api,
        plant["id"],
        materials,
        components=_d1_components(materials),
        code="D1",
        target_lsf=97.00,
        target_sm=1.50,
        target_am=0.80,
    )
    validate_success(api.submit_design(d1["id"], ENGINEER_HEADERS))
    approved = validate_success(api.approve_design(d1["id"], QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["superseded_by_design_id"] is None

    superseded = validate_success(api.get_design(d2["id"], ENGINEER_HEADERS))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_design_id"] == d1["id"]
    assert superseded["version"] == 5

    rows, meta = validate_paginated(
        api.list_designs(
            ENGINEER_HEADERS, params={"plant_id": plant["id"], "status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [d1["id"]]

    # The physical material is already on the ground, so the pile survives.
    untouched = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert untouched["status"] == "OPEN"
    assert_amount(untouched["as_blended_lsf"], 96.98, "as_blended_lsf")

    # A new pile against the superseded recipe is refused.
    validate_error(
        api.create_pile(
            f.pile_payload(plant["id"], d2["id"], superseded["version"], "PB"),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_DESIGN_NOT_APPROVED.value,
        409,
    )


# ---------------------------------------------------------------------------
# precondition_enforcement: the emptiness gate precedes the chemistry gate
# ---------------------------------------------------------------------------
def test_an_empty_pile_cannot_be_sealed(api):
    """With no additions the LSF deviation is undefined, so the emptiness gate answers with
    ERR_PILE_EMPTY rather than a chemistry complaint, and the bed is sealable as soon as
    material is actually on it.

    PRD: "Four conditions guard it: the pile must be `OPEN`, else `ERR_INVALID_PILE_STATE`;
    the pile must have at least one addition, since an empty bed cannot be fed to a kiln,
    else `ERR_PILE_EMPTY`; the design must still be `APPROVED`, else
    `ERR_DESIGN_NOT_APPROVED`; and `lsf_deviation` must be no greater than the design's
    `pile_lsf_tolerance`, with equality accepted, else `ERR_PILE_LSF_OFF_TARGET`."

    Design: Corner/state_machines/pile_cannot_be_sealed_while_it_has_no_additions
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    design = fx.create_approved_design(api, plant["id"], materials)
    pile = fx.create_open_pile(api, plant["id"], design["id"])

    validate_error(
        api.seal_pile(pile["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_PILE_EMPTY.value,
        409,
    )

    unsealed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert unsealed["status"] == "OPEN"
    assert unsealed["sealed_at"] is None
    assert_amount(unsealed["dry_tonnes"], 0.00, "dry_tonnes")
    assert unsealed["lsf_deviation"] is None

    fx.add_reference_additions(api, pile["id"], materials)
    sealed = validate_success(api.seal_pile(pile["id"], ENGINEER_HEADERS))
    assert sealed["status"] == "SEALED"
    assert_amount(sealed["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(sealed["lsf_deviation"], 0.02, "lsf_deviation")


# ---------------------------------------------------------------------------
# valid_transition: the AUTHORIZED branch mints a bounded window
# ---------------------------------------------------------------------------
def test_the_authorized_branch_mints_a_bounded_validity_window(api):
    """A thirty-day authorisation opened at the epoch runs from 2026-08-01T00:00:00Z to
    exactly 2026-08-31T00:00:00Z, and the four hops leave the row at version 4 with the
    technician and the officer recorded separately.

    PRD: "A decision of `AUTHORIZED` moves the trial burn `RESULT_RECORDED → AUTHORIZED` and
    mints an authorisation: the supplied `authorized_max_tsr_pct` is stored, `valid_from` is
    stamped with the logical clock, `valid_until` is set to `valid_from` advanced by
    `valid_days` days, and `adjudicated_by_user_id` records the officer."

    Design: Corner/state_machines/burn_test_authorized_branch_mints_a_bounded_validity_window
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    fuels = fx.create_fuels(api)

    requested = validate_success(
        api.create_burn_test(
            f.burn_test_payload(plant["id"], fuels["rdf"]["id"], 25.00, 30),
            ENV_HEADERS,
        ),
        201,
    )
    assert requested["status"] == "REQUESTED"
    assert_amount(requested["authorized_max_tsr_pct"], 0.00, "authorized_max_tsr_pct")
    assert requested["valid_from"] is None
    assert requested["valid_until"] is None
    assert requested["version"] == 1

    started = validate_success(api.start_burn_test(requested["id"], LAB_HEADERS))
    assert started["status"] == "IN_PROGRESS"
    assert started["version"] == 2

    recorded = validate_success(
        api.record_burn_test_result(
            requested["id"], f.burn_result_payload(), LAB_HEADERS
        )
    )
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["result_recorded_by_user_id"] == LAB_HEADERS["X-User-ID"]
    assert recorded["version"] == 3

    authorized = validate_success(
        api.adjudicate_burn_test(
            requested["id"], f.adjudication_payload("AUTHORIZED", 25.00), ENV_HEADERS
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert_amount(authorized["authorized_max_tsr_pct"], 25.00, "authorized_max_tsr_pct")
    assert_instant_equals(
        authorized["valid_from"], "2026-08-01T00:00:00Z", "valid_from"
    )
    assert_instant_equals(
        authorized["valid_until"], "2026-08-31T00:00:00Z", "valid_until"
    )
    assert authorized["adjudicated_by_user_id"] == ENV_HEADERS["X-User-ID"]
    assert authorized["version"] == 4


def test_an_officer_cannot_grant_more_substitution_than_was_requested(api):
    """40.00 percent exceeds both the 25.00 asked for and the plant's 35.00 permit ceiling,
    so the adjudication is refused and the trial burn stays at RESULT_RECORDED.

    PRD: "Two conditions bound this branch: `stack_compliant` must be true, and the
    `authorized_max_tsr_pct` granted must be no greater than the `requested_max_tsr_pct`
    asked for and no greater than the plant's `permit_max_tsr_pct` — an officer cannot grant
    more than was requested, nor more than the permit itself allows."

    Design: Corner/state_machines/burn_test_authorized_branch_mints_a_bounded_validity_window
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    fuels = fx.create_fuels(api)

    burn = validate_success(
        api.create_burn_test(
            f.burn_test_payload(plant["id"], fuels["rdf"]["id"], 25.00, 30),
            ENV_HEADERS,
        ),
        201,
    )
    validate_success(api.start_burn_test(burn["id"], LAB_HEADERS))
    validate_success(
        api.record_burn_test_result(burn["id"], f.burn_result_payload(), LAB_HEADERS)
    )

    validate_error(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 40.00), ENV_HEADERS
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    unchanged = validate_success(api.get_burn_test(burn["id"], ENV_HEADERS))
    assert unchanged["status"] == "RESULT_RECORDED"
    assert_amount(unchanged["authorized_max_tsr_pct"], 0.00, "authorized_max_tsr_pct")
    assert unchanged["valid_from"] is None
    assert unchanged["valid_until"] is None
    assert unchanged["version"] == 3


# ---------------------------------------------------------------------------
# side_effect_execution: the REJECTED branch mints nothing
# ---------------------------------------------------------------------------
def test_the_rejected_branch_mints_no_window_at_all(api):
    """The reason is stored while the ceiling stays at zero and both window ends stay null,
    and the terminal state refuses a second adjudication.

    PRD: "A decision of `REJECTED` moves the trial burn `RESULT_RECORDED → REJECTED` and
    mints nothing at all: the `decision_reason` is stored, `authorized_max_tsr_pct` stays at
    0, and both `valid_from` and `valid_until` stay null."

    Design: Corner/state_machines/burn_test_rejected_branch_mints_no_window_at_all
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    fuels = fx.create_fuels(api)

    burn = validate_success(
        api.create_burn_test(
            f.burn_test_payload(plant["id"], fuels["tdf"]["id"], 10.00, 30),
            LAB_HEADERS,
        ),
        201,
    )
    validate_success(api.start_burn_test(burn["id"], LAB_HEADERS))
    validate_success(
        api.record_burn_test_result(
            burn["id"],
            f.burn_result_payload(
                measured_chlorine_pct=0.10,
                measured_nox_kg_per_gj=0.40,
                stack_compliant=False,
            ),
            LAB_HEADERS,
        )
    )

    rejected = validate_success(
        api.adjudicate_burn_test(
            burn["id"],
            f.adjudication_payload(
                "REJECTED", None, decision_reason="STACK_NON_COMPLIANT"
            ),
            ENV_HEADERS,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decision_reason"] == "STACK_NON_COMPLIANT"
    assert_amount(rejected["authorized_max_tsr_pct"], 0.00, "authorized_max_tsr_pct")
    assert rejected["valid_from"] is None
    assert rejected["valid_until"] is None
    assert rejected["version"] == 4

    rows, meta = validate_paginated(
        api.list_burn_tests(
            ENV_HEADERS, params={"plant_id": plant["id"], "status": "AUTHORIZED"}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    validate_error(
        api.adjudicate_burn_test(
            burn["id"],
            f.adjudication_payload("AUTHORIZED", 10.00),
            ENV_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_BURN_TEST_STATE.value,
        409,
    )

    still_rejected = validate_success(api.get_burn_test(burn["id"], ENV_HEADERS))
    assert still_rejected["status"] == "REJECTED"
    assert still_rejected["version"] == 4
