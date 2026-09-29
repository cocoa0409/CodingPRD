"""Cascades that run from a child write all the way out to the owner of record."""

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_score_equals,
    assert_status,
)
from test_helpers.fixtures import (
    caprock_qualified_parcel,
    clear_curative,
    grant_consent,
    publish_setback_rule,
    raise_curative,
    read_consent,
    read_curative,
    read_landowner,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
    rescreen,
)
from test_helpers.test_users import TITLE_COUNSEL_USER_ID_2


def _trinity_draw_parcel():
    """An owner whose county imposes one waivable and one non-waivable ordinance."""
    landowner = register_landowner(
        legal_name="Trinity Draw Family Trust", entity_type="TRUST"
    )
    waivable = publish_setback_rule(
        jurisdiction_code="48375",
        rule_type="PROPERTY_LINE",
        setback_feet=200,
        encumbrance_rate_per_acre=0.2000,
        consent_waivable=True,
    )
    publish_setback_rule(
        jurisdiction_code="48375",
        rule_type="OCCUPIED_DWELLING",
        setback_feet=600,
        encumbrance_rate_per_acre=0.1500,
        consent_waivable=False,
    )
    parcel = register_parcel(
        landowner["id"],
        apn="R-2375-901",
        county_fips="48375",
        gross_acres=100.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    return landowner, waivable, parcel


def _caprock_blocking_chain():
    """A field-verified parcel carrying a two-link blocking curative chain."""
    setup = caprock_qualified_parcel()
    parcel_id = setup["parcel"]["id"]
    rescreen(parcel_id, "FIELD_VERIFIED")
    predecessor = raise_curative(
        parcel_id,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=450000,
    )
    successor = raise_curative(
        parcel_id,
        item_type="MORTGAGE_SUBORDINATION",
        severity="BLOCKING",
        curative_cost_cents=275000,
        blocks_item_id=predecessor["id"],
    )
    return setup, predecessor, successor


def test_a_granted_consent_buys_back_four_fifths_of_its_rules_encumbrance():
    """
    The waivable ordinance encumbers twenty acres of a hundred-acre tract; the
    neighbour's signature releases sixteen of them, and the release lands on the
    consent as well as on the parcel.

    PRD: "Each such consent releases the parcel's `gross_acres` multiplied by
    that rule's `encumbrance_rate_per_acre` multiplied by four fifths — a granted
    consent buys back eighty percent of the rule's encumbrance, not all of it —
    with that product rounded half up to two decimals."

    Design: Difficulty/transitive_cascade/consent_grant_cascade_to_landowner_posture
    """
    _landowner, waivable, parcel = _trinity_draw_parcel()
    assert_acres_equals(parcel["raw_setback_acres"], 35.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 65.00, "buildable_acres")
    consent = request_consent(
        parcel["id"], waivable["id"], neighbor_name="H. Alvarado", consent_expiry_days=60
    )
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")

    granted = grant_consent(consent["id"])

    assert_status(granted, "GRANTED", "consent")
    assert_acres_equals(granted["released_acres"], 16.00, "released_acres")
    assert_instant_equals(granted["granted_at"], "2026-08-01T00:00:00Z", "granted_at")
    assert_acres_equals(
        read_consent(consent["id"])["released_acres"], 16.00, "released_acres"
    )


def test_the_consent_cascade_reaches_the_owners_relationship_posture():
    """
    The acreage release lifts the parcel over the qualification floor, which
    promotes the parcel, which in turn advances the owner from prospect to
    engaged — four hops from a single grant.

    PRD: "Hop three, if that promotion happened, resynchronises the owner's
    posture, which may advance them `PROSPECT → ENGAGED`."

    Design: Difficulty/transitive_cascade/consent_grant_cascade_to_landowner_posture
    """
    landowner, waivable, parcel = _trinity_draw_parcel()
    assert_status(parcel, "SCREENING", "parcel")
    assert_status(read_landowner(landowner["id"]), "PROSPECT", "landowner")
    consent = request_consent(parcel["id"], waivable["id"], neighbor_name="H. Alvarado")

    grant_consent(consent["id"])

    after = read_parcel(parcel["id"])
    assert_acres_equals(after["consent_released_acres"], 16.00, "consent_released_acres")
    assert_acres_equals(
        after["setback_encumbered_acres"], 19.00, "setback_encumbered_acres"
    )
    assert_acres_equals(after["buildable_acres"], 81.00, "buildable_acres")
    assert_status(after, "QUALIFIED", "parcel")
    assert_status(read_landowner(landowner["id"]), "ENGAGED", "landowner")


def test_the_raw_setback_and_the_score_are_untouched_by_a_release():
    """
    A release is booked against the encumbrance, never against the ordinance
    accumulation itself, and it feeds no term of the screening blend.

    PRD: "Hop one re-derives the parcel's acreage: `consent_released_acres` rises
    by this consent's own rounded release term, which is also written onto the
    consent's `released_acres`, `setback_encumbered_acres` falls by the same
    amount, and `buildable_acres` rises."

    Design: Difficulty/transitive_cascade/consent_grant_cascade_to_landowner_posture
    """
    _landowner, waivable, parcel = _trinity_draw_parcel()
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY"
    consent = request_consent(parcel["id"], waivable["id"], neighbor_name="H. Alvarado")

    grant_consent(consent["id"])

    after = read_parcel(parcel["id"])
    assert_acres_equals(after["raw_setback_acres"], 35.00, "raw_setback_acres")
    assert_score_equals(after["screening_score"], 82.15, "screening_score")
    assert after["screening_tier"] == "PRIORITY"


def test_clearing_a_predecessor_promotes_its_blocked_successor():
    """
    The second defect opens blocked behind the first. Clearing the first releases
    it into the open queue, which lowers the parcel's open count and re-scores it
    one rung up the title ladder.

    PRD: "Hop two promotes successors: every item whose `blocks_item_id` is this
    item and whose status is `BLOCKED` moves `BLOCKED → OPEN`, processed in
    `created_at` ascending order."

    Design: Difficulty/transitive_cascade/curative_clear_releases_successor_and_rescores
    """
    setup, predecessor, successor = _caprock_blocking_chain()
    parcel_id = setup["parcel"]["id"]
    assert_status(read_curative(predecessor["id"]), "OPEN", "predecessor")
    assert_status(read_curative(successor["id"]), "BLOCKED", "successor")
    blocked_parcel = read_parcel(parcel_id)
    assert blocked_parcel["blocking_curative_open_count"] == 2
    assert_score_equals(blocked_parcel["screening_score"], 67.15, "screening_score")

    cleared = clear_curative(predecessor["id"])

    assert_status(cleared, "CLEARED", "predecessor")
    assert cleared["cleared_by_user_id"] == TITLE_COUNSEL_USER_ID_2
    assert_instant_equals(cleared["cleared_at"], "2026-08-01T00:00:00Z", "cleared_at")
    assert_status(read_curative(successor["id"]), "OPEN", "successor")
    after = read_parcel(parcel_id)
    assert after["blocking_curative_open_count"] == 1
    assert_score_equals(after["screening_score"], 75.90, "screening_score")
    assert after["screening_tier"] == "STANDARD"


def test_clearing_capitalises_its_own_cost_and_nothing_else():
    """
    Only the cleared item's budget is capitalised onto the parcel; the successor's
    budget waits until its own work is done, and no waiver has been used.

    PRD: "On success, hop one moves the item `OPEN → CLEARED`, stamps
    `cleared_at` from the logical clock and `cleared_by_user_id` from the acting
    identifier, and **adds this item's `curative_cost_cents` to the parcel's
    `curative_cost_cents`**."

    Design: Difficulty/transitive_cascade/curative_clear_releases_successor_and_rescores
    """
    setup, predecessor, _successor = _caprock_blocking_chain()
    parcel_id = setup["parcel"]["id"]

    clear_curative(predecessor["id"])

    after = read_parcel(parcel_id)
    assert_cents_equals(after["curative_cost_cents"], 450000, "curative_cost_cents")
    assert after["waived_blocking_count"] == 0
    assert_acres_equals(after["buildable_acres"], 100.00, "buildable_acres")
    assert_status(after, "SCREENING", "parcel")
    assert_status(read_landowner(setup["landowner"]["id"]), "PROSPECT", "landowner")


def test_a_successor_opens_blocked_behind_an_unresolved_predecessor():
    """
    A defect that names an unresolved predecessor is not workable yet, and both
    links count against the parcel while they sit unresolved.

    PRD: "The item's `created_by_user_id` is stamped from the acting `X-User-ID`,
    and its status opens as `BLOCKED` when the predecessor named by
    `blocks_item_id` is still in `BLOCKED` or `OPEN`, and as `OPEN` otherwise."

    Design: Difficulty/transitive_cascade/curative_clear_releases_successor_and_rescores
    """
    setup, predecessor, successor = _caprock_blocking_chain()

    assert successor["blocks_item_id"] == predecessor["id"]
    assert_status(successor, "BLOCKED", "successor")
    assert_status(predecessor, "OPEN", "predecessor")
    assert read_parcel(setup["parcel"]["id"])["blocking_curative_open_count"] == 2
