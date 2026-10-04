"""Rights-holder registration and ledger reads."""
from test_helpers import TEST_USERS
from test_helpers.fixtures import ADMIN, create_licensor, set_clock
from test_helpers import (
    assert_licensor,
    assert_licensor_invariants,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


def test_licensor_registration_writes_zero_ledger_and_default_currency(api):
    """PRD §2.4: "The `currency` field carries the ISO currency code and defaults
    to `USD` when the caller does not supply one. At registration the ledger
    triple is written to zero: `accrued_royalty_cents`,
    `guarantee_recovery_block_cents` and `accrued_unsettled_cents` all begin at
    0."

    Design: Corner/entities/licensor_create_defaults_and_ledger_zeros
    """
    set_clock(api)
    resp = api.create_licensor(
        {
            "name": "National Basketball League",
            "league_code": "NBL",
            "royalty_rate_pct": 0.125,
            "minimum_guarantee_cents": 2000000,
        },
        ADMIN,
    )
    licensor = validate_success(resp, expected_status=201)

    assert licensor["name"] == "National Basketball League"
    assert licensor["league_code"] == "NBL"
    assert licensor["royalty_rate_pct"] == 0.125
    assert licensor["minimum_guarantee_cents"] == 2000000

    assert licensor["accrued_royalty_cents"] == 0
    assert licensor["guarantee_recovery_block_cents"] == 0
    assert licensor["accrued_unsettled_cents"] == 0

    assert licensor["currency"] == "USD"
    assert is_valid_uuid(licensor["id"]), "id must be a server-minted bare UUID"
    assert is_iso8601_timestamp(licensor["created_at"])
    assert is_iso8601_timestamp(licensor["updated_at"])
    assert isinstance(licensor["version"], int)
    assert_licensor(licensor)


def test_licensor_read_exposes_the_whole_ledger_to_an_auditor(api):
    """PRD §2.4: "The licensor's ledger is governed by one invariant, checked at
    every observable point: `accrued_unsettled_cents` equals the greater of zero
    and the difference between `accrued_royalty_cents` and
    `guarantee_recovery_block_cents`."

    Design: Corner/endpoints/licensor_get_returns_full_ledger_for_audit
    """
    set_clock(api)
    licensor = create_licensor(
        api, name="Licensor V", royalty_rate_pct=0.1,
        minimum_guarantee_cents=100000,
    )

    read = validate_success(
        api.get_licensor(licensor["id"], TEST_USERS["audit_only_headers"]),
        expected_status=200,
    )

    assert read["accrued_royalty_cents"] == 0
    assert read["guarantee_recovery_block_cents"] == 0
    assert read["accrued_unsettled_cents"] == 0
    assert read["minimum_guarantee_cents"] == 100000
    assert read["royalty_rate_pct"] == 0.1
    assert read["id"] == licensor["id"]
    assert_licensor_invariants(read)


def test_licensor_read_is_available_to_the_read_only_role(api):
    """PRD §2.1: "`LicensingOps` is the one entity-backed role." and "`AuditOnly`
    holds no exclusive operation whatsoever and can serve no request that
    mutates state."

    Design: Corner/endpoints/licensor_get_returns_full_ledger_for_audit
    """
    from test_helpers import TEST_USERS

    set_clock(api)
    licensor = create_licensor(api, name="Licensor V2")

    read = validate_success(
        api.get_licensor(licensor["id"], TEST_USERS["audit_only_headers"]),
        expected_status=200,
    )
    assert read["id"] == licensor["id"]
    assert_licensor_invariants(read)