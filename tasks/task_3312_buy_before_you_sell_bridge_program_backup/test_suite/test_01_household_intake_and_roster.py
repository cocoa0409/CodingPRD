"""Household intake, property records and the partner roster (PRD section 3.1)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_homeowner, assert_property, assert_agent,
    create_homeowner_payload, create_property_payload, create_agent_payload,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
    reset_clock, create_homeowner, make_property,
)

COORD = TEST_USERS["coordinator_headers"]


def test_homeowner_create_returns_row_in_initial_lifecycle_state(api):
    """PRD section 3.1: "A newly registered household starts with a `program_status`
    of `NONE` and a `sealed_flag` of false, and it holds no equity until a
    qualification has been approved for it."

    PRD section 2.5: "a newly registered `Homeowner`, a `Property`, a `BackupOffer`, an
    `Agent` and a `Disbursement` alike are addressed by a server-minted UUID `id`, and
    all of them expose `created_at`, `updated_at` and `version`."

    Design: Corner/entities/homeowner_create_returns_full_row
    """
    reset_clock()
    res = api.create_homeowner(
        create_homeowner_payload(full_name="Corner H1", email="c.h1@x.com", credit_score=700),
        COORD,
    )
    h = validate_success(res, 201)
    assert_homeowner(h)
    assert h["credit_score"] == 700
    assert h["program_status"] == "NONE", "a fresh household is NONE, not enrolled"
    assert h["sealed_flag"] is False


def test_homeowner_missing_email_rejected_before_any_row_is_written(api):
    """PRD section 3.1: "A transaction coordinator registers one by supplying the
    principal's `full_name`, a contact `email`, a `credit_score` and an annual
    `household_income_cents`, and may optionally set a `max_dti_bps` tolerance for the
    household's debt-to-income ratio, which defaults to 4300 basis points when not
    supplied."

    PRD section 2.11: "Only then is the payload itself inspected for missing required
    fields and for values outside their declared types and ranges, all of which
    produce `ERR_INVALID_REQUEST`."

    Design: Corner/entities/homeowner_missing_required_field_returns_invalid_request
    """
    payload = create_homeowner_payload(full_name="No Email")
    payload.pop("email")
    res = api.create_homeowner(payload, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_property_omitted_optionals_take_their_declared_defaults(api):
    """PRD section 3.1: "Several fields are optional and carry defaults that an implementer
    must honour rather than treat as absent: `mortgage_payoff_cents` defaults to 0, which is
    the correct value for a home owned free and clear; `purchase_price_cents` defaults to 0
    and is meaningful only for a home of kind `NEW`"

    PRD section 3.1: "Every property begins `UNLISTED` in its `listing_status` and
    `NOT_STARTED` in its `repair_status`, with a `site_visit_count` of zero and a
    `program_inventory_flag` of false"

    Design: Corner/entities/property_defaults_applied_when_omitted
    """
    reset_clock()
    h = create_homeowner(full_name="Corner H2", email="c.h2@x.com")
    res = api.create_property(
        {"homeowner_id": h["id"], "address": "1 Def Way", "kind": "DEPARTING",
         "appraised_value_cents": 50_000_000, "condition_grade": "B"},
        COORD,
    )
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["purchase_price_cents"] == 0, "purchase_price_cents defaults to 0"
    assert prop["mortgage_payoff_cents"] == 0, "mortgage_payoff_cents defaults to 0"
    assert prop["listing_status"] == "UNLISTED"
    assert prop["repair_status"] == "NOT_STARTED"
    assert prop["site_visit_count"] == 0
    assert prop["program_inventory_flag"] is False


def test_property_kind_outside_the_declared_enum_is_refused(api):
    """PRD section 3.1: "Creating a property requires the owning `homeowner_id`, a street
    `address`, a `kind` of either `DEPARTING` or `NEW`, the `appraised_value_cents`, and a
    `condition_grade` of `A`, `B`, `C` or `D`."

    Design: Corner/entities/property_kind_enum_constraint_rejects_invalid_value
    """
    reset_clock()
    h = create_homeowner(full_name="Corner H4", email="c.h4@x.com")
    res = api.create_property(
        create_property_payload(h["id"], address="4 Def Way", kind="OTHER",
                                appraised_value_cents=50_000_000, condition_grade="B"),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_reading_a_missing_property_returns_property_not_found(api):
    """PRD section 2.6: "a missing property yields `ERR_PROPERTY_NOT_FOUND`"

    Design: Corner/entities/property_not_found_returns_404
    """
    res = api.get_property(NON_EXISTENT_UUID, COORD)
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, expected_status=404)


def test_property_list_is_scoped_to_the_named_household(api):
    """PRD section 2.3: "The `limit` is the maximum number of items returned and defaults
    to 10 when omitted; it must be at least 1 and at most 100."

    PRD section 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope described in §2.2."

    Design: Corner/entities/properties_list_filtered_by_homeowner
    """
    reset_clock()
    owner_a = create_homeowner(full_name="Owner A", email="own.a@x.com")
    owner_b = create_homeowner(full_name="Owner B", email="own.b@x.com")
    pa = make_property(owner_a["id"], "DEPARTING", "5 Def Way", appraised_value_cents=50_000_000)
    pb = make_property(owner_b["id"], "DEPARTING", "6 Def Way", appraised_value_cents=50_000_000)

    res = api.list_properties(COORD, params={"homeowner_id": owner_a["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    ids = [p["id"] for p in data]
    assert pa["id"] in ids, "the household's own property is returned"
    assert pb["id"] not in ids, "another household's property is not returned"
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_agent_qualification_transition_increments_version_once(api):
    """PRD section 2.5: "Every entity except one also carries a `version` integer that
    the server increments by one on each mutation".

    PRD section 3.1: "A freshly registered agent is `PENDING` and may not receive
    referrals. A coordinator moves the agent to `QUALIFIED` once its licence has been
    verified; the licence number must be present for that step to succeed."

    Design: Corner/cross_cutting_layers/version_increments_on_agent_qualify
    """
    reset_clock()
    res = api.create_agent(create_agent_payload(full_name="Ver Agent", license_number="LIC-VER"), COORD)
    agent = validate_success(res, 201)
    assert_agent(agent)
    assert agent["qualification_status"] == "PENDING"
    assert agent["version"] == 1, "version starts at 1 on creation"

    qualified = validate_success(api.qualify_agent(agent["id"], COORD), 200)
    assert qualified["qualification_status"] == "QUALIFIED"
    assert qualified["version"] == 2, "one mutation increments version by exactly one"