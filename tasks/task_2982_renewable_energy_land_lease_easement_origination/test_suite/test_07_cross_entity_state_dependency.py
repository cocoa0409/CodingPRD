"""Gates whose governing state lives on a different entity from the one written."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CORRIDOR_NOT_PERMITTED,
    ERR_TITLE_CURATIVE_BLOCKING,
    ERR_W9_MISSING,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_null,
    assert_status,
)
from test_helpers.factories import exercise_payload, record_memo_payload
from test_helpers.fixtures import (
    advance_option_to_executed,
    amend_landowner,
    caprock_executed_option,
    caprock_qualified_parcel,
    clear_curative,
    client,
    draft_option,
    exercise_option,
    grant_crossing,
    leases_for_option,
    permit_corridor,
    plan_corridor,
    post_full_security,
    propose_crossing,
    publish_caprock_setback_rules,
    raise_curative,
    read_corridor,
    read_crossing,
    read_curative,
    read_landowner,
    read_lease,
    read_option,
    read_parcel,
    register_landowner,
    register_parcel,
    submit_memo,
)
from test_helpers.test_users import PORTFOLIO_MANAGER, PORTFOLIO_MANAGER_2


def _executed_option_with_a_blocking_defect():
    """A binding option whose parcel picked up a blocking defect after execution."""
    setup = caprock_executed_option(option_term_days=365, extension_count_allowed=0)
    item = raise_curative(
        setup["parcel"]["id"],
        item_type="ACCESS_EASEMENT_GAP",
        severity="BLOCKING",
        curative_cost_cents=310000,
    )
    return setup, item


def _crossing_on_an_unpermitted_corridor():
    """A proposed crossing whose corridor has not yet cleared its route permit."""
    parcel_setup = caprock_qualified_parcel()
    corridor = plan_corridor()
    assert_status(corridor, "PLANNED", "corridor")
    assert corridor["granted_crossing_count"] == 0
    crossing = propose_crossing(corridor["id"], parcel_setup["parcel"]["id"])
    return corridor, crossing


def _lease_awaiting_a_w9():
    """A submitted memorandum whose only remaining objection is a missing W-9."""
    landowner = register_landowner(
        legal_name="Guadalupe Flats Ranch LP",
        entity_type="PARTNERSHIP",
        w9_on_file=False,
    )
    landowner_id = landowner["id"]
    assert landowner["w9_on_file"] is False
    publish_caprock_setback_rules()
    parcel = register_parcel(landowner_id)
    option = draft_option(
        parcel["id"], landowner_id, option_term_days=365, extension_count_allowed=0
    )
    advance_option_to_executed(option["id"], landowner_id)
    lease = exercise_option(option["id"], "NOL-2982-0007")
    posted = post_full_security(lease["id"])
    assert_cents_equals(posted["security_posted_cents"], 5225000, "security_posted_cents")
    submitted = submit_memo(lease["id"])
    assert submitted["recording_status"] == "MEMO_SUBMITTED"
    return landowner_id, parcel["id"], lease["id"]


def test_an_open_blocking_defect_two_hops_away_refuses_the_exercise():
    """
    The gate is written on the agreement but the governing state sits on a title
    curative item reached through the parcel's counter. With the item open the
    conversion is refused and the instrument is untouched.

    PRD: "The parcel's `blocking_curative_open_count` must be zero, or the attempt
    is refused with `ERR_TITLE_CURATIVE_BLOCKING` (422) — the company does not take
    a thirty-five-year interest in defective title."

    Design: Difficulty/cross_entity_state_dependency/exercise_blocked_by_open_blocking_curative_item
    """
    setup, item = _executed_option_with_a_blocking_defect()
    option_id = setup["option"]["id"]
    assert read_parcel(setup["parcel"]["id"])["blocking_curative_open_count"] == 1
    assert_status(read_curative(item["id"]), "OPEN", "curative item")

    response = client().exercise_option(
        option_id, exercise_payload("NOL-2982-0006"), PORTFOLIO_MANAGER_2
    )

    validate_error(response, ERR_TITLE_CURATIVE_BLOCKING, 422)
    option = read_option(option_id)
    assert_status(option, "EXECUTED", "option")
    assert_null(option["exercised_at"], "exercised_at")
    assert leases_for_option(option_id) == [], "a refused exercise minted a lease"


def test_clearing_that_defect_lets_the_byte_identical_exercise_through():
    """
    Nothing about the request changes; only the far entity's state does. The same
    exercise then converts the option and mints exactly one lease.

    PRD: "On success the agreement moves `EXECUTED → EXERCISED` with `exercised_at`
    stamped from the logical clock, and a lease agreement is created and returned."

    Design: Difficulty/cross_entity_state_dependency/exercise_blocked_by_open_blocking_curative_item
    """
    setup, item = _executed_option_with_a_blocking_defect()
    option_id = setup["option"]["id"]
    parcel_id = setup["parcel"]["id"]
    refused = client().exercise_option(
        option_id, exercise_payload("NOL-2982-0006"), PORTFOLIO_MANAGER_2
    )
    validate_error(refused, ERR_TITLE_CURATIVE_BLOCKING, 422)

    clear_curative(item["id"])
    assert read_parcel(parcel_id)["blocking_curative_open_count"] == 0
    lease = exercise_option(option_id, "NOL-2982-0006")

    assert_status(read_option(option_id), "EXERCISED", "option")
    assert_acres_equals(lease["acre_basis_at_exercise"], 100.00, "acre_basis_at_exercise")
    assert_cents_equals(
        lease["total_security_required_cents"], 5225000, "total_security_required_cents"
    )
    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 310000, "curative_cost_cents"
    )
    leases = leases_for_option(option_id)
    assert [row["id"] for row in leases] == [lease["id"]], (
        f"expected exactly one lease, got {[row['id'] for row in leases]}"
    )


def test_the_optioned_parcel_is_never_requalified_so_it_is_not_the_blocker():
    """
    Raising the defect would have demoted a merely qualified parcel; an optioned
    one is left alone, which is what makes the refusal attributable to the title
    item rather than to the parcel's own status.

    PRD: "The procedure never fires at all when the parcel's `status` is
    `DISQUALIFIED`, `OPTIONED` or `LEASED` — those three statuses are moved only by
    the explicit transitions described in §3."

    Design: Difficulty/cross_entity_state_dependency/exercise_blocked_by_open_blocking_curative_item
    """
    setup, item = _executed_option_with_a_blocking_defect()
    parcel_id = setup["parcel"]["id"]
    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")

    clear_curative(item["id"])

    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")


def test_a_crossing_cannot_be_granted_while_its_corridor_is_only_planned():
    """
    The governing state is one hop up, on the crossing's own parent route. An
    unpermitted corridor refuses the grant and its derived counter does not move.

    PRD: "The crossing must be in `PROPOSED`, and the corridor must have reached
    `PERMITTED` — a crossing on a still-`PLANNED` corridor is refused with
    `ERR_CORRIDOR_NOT_PERMITTED` (422)."

    Design: Difficulty/cross_entity_state_dependency/crossing_grant_requires_permitted_corridor
    """
    corridor, crossing = _crossing_on_an_unpermitted_corridor()
    assert crossing["occupied_m"] == 500
    assert crossing["duration_days"] == 30
    assert crossing["long_occupancy_surcharge_bps"] == 0
    assert_cents_equals(crossing["compensation_cents"], 900000, "compensation_cents")

    response = client().grant_crossing_agreement(crossing["id"], {}, PORTFOLIO_MANAGER)

    validate_error(response, ERR_CORRIDOR_NOT_PERMITTED, 422)
    after = read_crossing(crossing["id"])
    assert_status(after, "PROPOSED", "crossing")
    assert_null(after["granted_at"], "granted_at")
    assert read_corridor(corridor["id"])["granted_crossing_count"] == 0


def test_permitting_the_corridor_reconciles_the_parents_granted_counter():
    """
    Once the route is permitted the identical grant succeeds, and the parent's
    derived count reconciles on the successful branch only. The crossing's price is
    fixed at proposal and the grant does not restate it.

    PRD: "On success the crossing moves `PROPOSED → GRANTED`, `granted_at` is
    stamped from the logical clock, and the corridor's `granted_crossing_count` is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/crossing_grant_requires_permitted_corridor
    """
    corridor, crossing = _crossing_on_an_unpermitted_corridor()
    refused = client().grant_crossing_agreement(crossing["id"], {}, PORTFOLIO_MANAGER)
    validate_error(refused, ERR_CORRIDOR_NOT_PERMITTED, 422)

    permitted = permit_corridor(corridor["id"])
    assert_status(permitted, "PERMITTED", "corridor")
    assert_instant_equals(
        permitted["permitted_at"], "2026-08-01T00:00:00Z", "permitted_at"
    )

    granted = grant_crossing(crossing["id"])

    assert_status(granted, "GRANTED", "crossing")
    assert_instant_equals(granted["granted_at"], "2026-08-01T00:00:00Z", "granted_at")
    assert read_corridor(corridor["id"])["granted_crossing_count"] == 1
    assert_cents_equals(
        read_crossing(crossing["id"])["compensation_cents"], 900000, "compensation_cents"
    )


def test_a_missing_w9_on_the_owner_refuses_the_recording():
    """
    The dependency here is a plain administrative flag on the root owner rather
    than another entity's lifecycle state, and it stops the county filing dead.

    PRD: "It has one cross-entity gate: the landowner's `w9_on_file` must be true,
    because no instrument may be recorded for a payee the developer cannot report
    to the tax authorities, and a missing W-9 is refused with `ERR_W9_MISSING`
    (422)."

    Design: Difficulty/cross_entity_state_dependency/record_memo_requires_landowner_w9_on_file
    """
    _landowner_id, parcel_id, lease_id = _lease_awaiting_a_w9()

    response = client().record_memo(
        lease_id,
        record_memo_payload(recording_instrument_no="2026-0044823"),
        PORTFOLIO_MANAGER_2,
    )

    validate_error(response, ERR_W9_MISSING, 422)
    lease = read_lease(lease_id)
    assert lease["recording_status"] == "MEMO_SUBMITTED"
    assert_null(lease["recorded_at"], "recorded_at")
    assert_null(lease["recording_instrument_no"], "recording_instrument_no")
    assert_status(read_parcel(parcel_id), "OPTIONED", "parcel")


def test_filing_the_w9_unblocks_recording_and_fires_the_three_hop_cascade():
    """
    A patch by the payments desk — not a state transition — clears the objection.
    The identical recording then drives the parcel to its terminal status and the
    owner to their terminal posture, without touching the money already paid.

    PRD: "Recording then cascades in three hops: the recording dimension reaches
    the terminal `RECORDED`, the parcel finally moves `OPTIONED → LEASED` — its own
    terminal status — and the owner's posture advances `UNDER_OPTION → UNDER_LEASE`."

    Design: Difficulty/cross_entity_state_dependency/record_memo_requires_landowner_w9_on_file
    """
    landowner_id, parcel_id, lease_id = _lease_awaiting_a_w9()
    refused = client().record_memo(
        lease_id,
        record_memo_payload(recording_instrument_no="2026-0044823"),
        PORTFOLIO_MANAGER_2,
    )
    validate_error(refused, ERR_W9_MISSING, 422)

    amended = amend_landowner(landowner_id, w9_on_file=True)
    assert amended["w9_on_file"] is True

    recorded = client().record_memo(
        lease_id,
        record_memo_payload(recording_instrument_no="2026-0044823"),
        PORTFOLIO_MANAGER_2,
    )
    lease = read_lease(lease_id)

    assert recorded.status_code == 200, recorded.text
    assert lease["recording_status"] == "RECORDED"
    assert_instant_equals(lease["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")
    assert lease["recording_instrument_no"] == "2026-0044823"
    assert_status(read_parcel(parcel_id), "LEASED", "parcel")
    landowner = read_landowner(landowner_id)
    assert_status(landowner, "UNDER_LEASE", "landowner")
    assert_cents_equals(landowner["total_paid_cents"], 312500, "total_paid_cents")
