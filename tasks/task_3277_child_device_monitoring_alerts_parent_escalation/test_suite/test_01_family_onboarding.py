"""Family onboarding: creation defaults and the auto-created primary parent."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_family,
    assert_parent_member,
    create_family,
    create_family_payload,
    is_iso8601_timestamp,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_family_creation_defaults_applied(api):
    """PRD §3.1: "Two optional inputs tune the account at creation:
    `subscription_tier`, one of `BASIC`, `STANDARD`, or `PREMIUM` (defaulting to
    `STANDARD` when omitted), and `analysis_variant`, one of `LEXICAL_V1` or
    `CONTEXTUAL_V2` (defaulting to `LEXICAL_V1`), which selects the risk-scoring
    variant applied to all content ingested for the family."
    PRD §3.1: "Creation returns the new `FamilyAccount` with `account_status` set
    to `ACTIVE`, stamps `billing_period_start` at the current logical clock time,
    and sets `billing_period_end` exactly thirty days later."
    PRD §3.3: "`BASIC` allows 2, `STANDARD` allows 5, and `PREMIUM` allows 10,
    and the family's computed `device_limit` always reflects the current tier."

    Design: Corner/entities/family_creation_defaults_applied
    """
    resp = api.create_family(create_family_payload(), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_family(data)
    assert data["subscription_tier"] == "STANDARD"
    assert data["analysis_variant"] == "LEXICAL_V1"
    assert data["device_limit"] == 5
    assert data["account_status"] == "ACTIVE"
    assert data["device_count"] == 0
    assert is_iso8601_timestamp(data["billing_period_start"])
    assert is_iso8601_timestamp(data["billing_period_end"])


def test_family_creation_auto_creates_primary_parent(api):
    """PRD §3.1: "In the same operation the system creates the primary
    `ParentMember` with `is_primary` set to true and `member_status` `ACTIVE`;
    further parent members may be listed for a family through the family's
    parent-members collection, each carrying a `display_name` and `email`."

    Design: Corner/entities/family_creation_auto_creates_primary_parent
    """
    fam, parent = create_family(primary_parent_name="Pat PP")
    assert_parent_member(parent)
    assert parent["is_primary"] is True
    assert parent["display_name"] == "Pat PP"
    assert parent["member_status"] == "ACTIVE"
