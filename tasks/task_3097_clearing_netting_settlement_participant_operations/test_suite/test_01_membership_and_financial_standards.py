"""Participant registration, admission gates and the financial-standard review."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    assert_participant, assert_participant_financial_standard,
    create_participant_payload, TEST_USERS,
    set_clock, create_participant, create_active_participant, get_deposit,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_participant_registration_defaults_and_opens_deposit_pool():
    """PRD §3.1: "Registration leaves the member in `PENDING` and immediately
    opens a clearing-member deposit pool for it in `PENDING` status; the capital
    floor and financial-standard status are computed at the same moment, so a
    newly registered member already reports `required_min_net_capital_cents` and
    a `financial_standard_status`."

    Design: Corner/entities/participant_create_defaults_and_pending_initial_state
    """
    set_clock()
    res = api_client.create_participant(
        create_participant_payload(legal_name="Corner Clearing LLC",
                                   lei="LEI-CORNER1",
                                   participant_class="BROKER_DEALER",
                                   net_capital_cents=600000000),
        ADMIN)
    participant = validate_success(res, 201)
    assert_participant(participant)
    assert participant["membership_status"] == "PENDING"
    assert participant["is_defaulted"] is False
    assert participant["requires_segregated_custody"] is False
    assert participant["version"] == 1
    assert participant["required_min_net_capital_cents"] == 500000000
    assert participant["financial_standard_status"] == "PASS"

    pools = validate_success(
        api_client.list_participant_deposits(participant["id"], ADMIN), 200)
    assert len(pools) == 1
    assert pools[0]["posted_amount_cents"] == 0


def test_participant_registration_rejects_unknown_field():
    """PRD §2.12: "Structural request validation — a missing required field, a
    mistyped value, or an unknown field, reported as `ERR_INVALID_REQUEST`".

    Design: Corner/entities/participant_create_extra_field_rejected
    """
    set_clock()
    payload = create_participant_payload(legal_name="Strict Co", lei="LEI-STRICT")
    payload["membership_status"] = "ACTIVE"
    validate_error(api_client.create_participant(payload, ADMIN), "ERR_INVALID_REQUEST")

    data, _ = None, None
    res = api_client.list_participants(ADMIN, params={"participant_class": "BANK"})
    data, _ = validate_success(res, 200), None
    assert res.json()["data"] == [] or all(
        p["legal_name"] != "Strict Co" for p in res.json()["data"])


def test_participant_read_unknown_id_returns_resource_not_found():
    """PRD §2.11: "A path-level miss is reported as `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/participant_get_unknown_id_returns_not_found
    """
    set_clock()
    validate_error(api_client.get_participant(NON_EXISTENT_UUID, ADMIN),
                   "ERR_RESOURCE_NOT_FOUND")


def test_participant_list_paginates_over_the_filtered_set():
    """PRD §2.3: "A paginated response carries the four pagination fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/participants_list_paginates_and_reports_total_count
    """
    set_clock()
    for name, lei, klass, cap in (
            ("Page Alpha", "LEI-PG1", "BROKER_DEALER", 600000000),
            ("Page Beta", "LEI-PG2", "BROKER_DEALER", 600000000),
            ("Page Gamma", "LEI-PG3", "BANK", 2000000000)):
        create_participant(name, lei, klass, cap)

    res = api_client.list_participants(
        ADMIN, params={"limit": 2, "offset": 0, "participant_class": "BROKER_DEALER"})
    body = res.json()
    validate_success(res, 200)
    assert len(body["data"]) == 2
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["has_more"] is False

    unfiltered = api_client.list_participants(ADMIN, params={"limit": 2, "offset": 0})
    ubody = unfiltered.json()
    assert len(ubody["data"]) == 2
    assert ubody["meta"]["total_count"] == 3
    assert ubody["meta"]["has_more"] is True


def test_financial_standard_floor_is_greater_of_class_base_and_flat_floor():
    """PRD §2.4: "The capital floor is the greater of a class base and a flat
    house floor of 500,000,000 cents."
    PRD §2.4: "the only class whose base falls below the floor is the
    `BROKER_DEALER`, which is therefore held to 500,000,000 cents rather than to
    its own 250,000,000-cent base."

    Design: Corner/calculations/financial_standard_minimum_class_base_and_flat_floor
    """
    set_clock()
    thin = create_participant("Thin Capital Co", "LEI-THIN1",
                              "BROKER_DEALER", 400000000)
    assert thin["required_min_net_capital_cents"] == 500000000
    assert thin["financial_standard_status"] == "FAIL"
    validate_error(api_client.activate_participant(thin["id"], ADMIN),
                   "ERR_FINANCIAL_STANDARD_NOT_MET")

    rich = create_participant("Rich Capital Co", "LEI-RICH1",
                              "BROKER_DEALER", 600000000)
    assert rich["financial_standard_status"] == "PASS"


def test_financial_standard_not_met_blocks_activation_and_can_be_cured():
    """PRD §3.1: "Its `financial_standard_status` must be `PASS`, or the attempt
    fails with `ERR_FINANCIAL_STANDARD_NOT_MET`."
    PRD §3.1: "The review recomputes the class floor and the pass/fail verdict
    and re-stamps `last_financial_review_at`".

    Design: Corner/errors/low_level_capital_fails_financial_standard_and_blocks_activation
    """
    set_clock()
    thin = create_participant("Thin Margin Co", "LEI-FS2",
                              "BROKER_DEALER", 400000000)
    validate_error(api_client.activate_participant(thin["id"], ADMIN),
                   "ERR_FINANCIAL_STANDARD_NOT_MET")

    refreshed = validate_success(api_client.get_participant(thin["id"], ADMIN), 200)
    assert refreshed["financial_standard_status"] == "FAIL"
    assert refreshed["required_min_net_capital_cents"] == 500000000

    reviewed = validate_success(api_client.financial_review(
        thin["id"], {"net_capital_cents": 600000000}, RISK), 200)
    assert reviewed["financial_standard_status"] == "PASS"

    activated = validate_success(api_client.activate_participant(thin["id"], ADMIN), 200)
    assert activated["membership_status"] == "ACTIVE"


def test_segregated_custody_gate_applies_only_when_flag_is_set():
    """PRD §3.1: "If `requires_segregated_custody` is true, the member must
    already hold at least one custody account whose `account_type` is
    `SEGREGATED`, or the attempt fails with `ERR_SEGREGATED_CUSTODY_REQUIRED`."

    Design: Corner/validations/segregated_custody_required_before_activation
    """
    set_clock()
    gated = create_participant("Segregated Co", "LEI-SG1", "CUSTODIAN_BANK",
                               2000000000, requires_segregated_custody=True)
    validate_error(api_client.activate_participant(gated["id"], ADMIN),
                   "ERR_SEGREGATED_CUSTODY_REQUIRED")
    still = validate_success(api_client.get_participant(gated["id"], ADMIN), 200)
    assert still["membership_status"] == "PENDING"

    validate_success(api_client.create_custody_account(
        gated["id"], {"account_number": "SG1-SEG-1", "account_type": "SEGREGATED"},
        ADMIN), 201)
    activated = validate_success(api_client.activate_participant(gated["id"], ADMIN), 200)
    assert activated["membership_status"] == "ACTIVE"

    ungated = create_participant("Not Segregated Co", "LEI-SG2", "CUSTODIAN_BANK",
                                 2000000000, requires_segregated_custody=False)
    assert validate_success(
        api_client.activate_participant(ungated["id"], ADMIN), 200
    )["membership_status"] == "ACTIVE"


def test_activation_requires_pending_state():
    """PRD §3.1: "The member must still be in `PENDING`, or the attempt fails
    with `ERR_INVALID_STATE`."

    Design: Corner/rbac/risk_officer_cannot_activate_participant
    """
    set_clock()
    participant = create_participant("Rbac Alpha", "LEI-RB1", "BANK", 2000000000)

    validate_error(api_client.activate_participant(participant["id"], RISK),
                   "ERR_UNAUTHORIZED")
    unchanged = validate_success(api_client.get_participant(participant["id"], ADMIN), 200)
    assert unchanged["membership_status"] == "PENDING"

    activated = validate_success(api_client.activate_participant(participant["id"], ADMIN), 200)
    assert activated["membership_status"] == "ACTIVE"

    validate_error(api_client.activate_participant(participant["id"], ADMIN),
                   "ERR_INVALID_STATE")


def test_security_market_fields_round_trip_with_declared_defaults():
    """PRD §3.3: "the instrument clears in the security's settlement `currency`,
    which defaults to USD when a security is registered."
    PRD §2.10: "`id` is a server-minted identifier formatted as a UUID with no
    type prefix."

    Design: Corner/entities/security_get_round_trips_market_fields
    """
    set_clock()
    security = validate_success(api_client.create_security(
        {"ticker": "RTP1", "cusip": "912828XR1", "prev_settlement_price_cents": 1250},
        ADMIN), 201)
    read = validate_success(api_client.get_security(security["id"], ADMIN), 200)
    assert read["ticker"] == "RTP1"
    assert read["cusip"] == "912828XR1"
    assert read["prev_settlement_price_cents"] == 1250
    assert read["currency"] == "USD"
    assert read["current_volatility_bps"] == 0


def test_security_immutable_identity_fields_are_refused_on_update():
    """PRD §2.10: "An update that supplies any of them is refused with
    `ERR_IMMUTABLE_FIELD` (HTTP 422)."

    Design: Corner/entities/security_immutable_ticker_rejected
    """
    set_clock()
    security = validate_success(api_client.create_security(
        {"ticker": "IMM1", "cusip": "912828XR2", "prev_settlement_price_cents": 5000},
        ADMIN), 201)

    validate_error(api_client.update_security(security["id"], {"ticker": "IMM2"}, ADMIN),
                   "ERR_IMMUTABLE_FIELD")
    assert validate_success(api_client.get_security(security["id"], ADMIN), 200)["ticker"] == "IMM1"

    updated = validate_success(api_client.update_security(
        security["id"], {"prev_settlement_price_cents": 6000}, ADMIN), 200)
    assert updated["ticker"] == "IMM1"
    assert updated["prev_settlement_price_cents"] == 6000


def test_missing_role_header_is_refused_before_existence():
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of the declared roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    set_clock()
    res = api_client.get_participant(NON_EXISTENT_UUID, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)