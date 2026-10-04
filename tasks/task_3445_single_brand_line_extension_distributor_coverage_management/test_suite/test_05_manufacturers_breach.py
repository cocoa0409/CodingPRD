"""Contract manufacturers: the for-cause revocation cascade, requalification
recency gate, and grantor/revoker segregation of duties."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, make_compliance_auditor_headers,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
TSO = TEST_USERS["trade_secret_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


def test_breach_revocation_cascade_manufacturer_grants_formulation():
    """PRD §3.3: "When the revocation is for cause and the manufacturer is `QUALIFIED`, the full **for-cause cascade** fires: the manufacturer drops to `SUSPENDED` with `suspended_at` stamped at the current logical time; every *other* grant of that manufacturer in `REQUESTED`, `GRANTED` or `ACTIVE` is itself revoked with `revoked_for_cause` true and `revoked_at` set to now; each formulation touched by those revocations re-evaluates its coverage and may regress from `COMPARTMENTALIZED` to `SEALED`; and the `protection_posture` of every brand owning an affected formulation's line is recomputed."
    PRD §3.1: "The posture is `CRITICAL` when at least two such breaches exist, or any single open case has `severity` 5, or the open-case severities sum to at least 10."

    Design: Difficulty/transitive_cascade/breach_revocation_cascade_manufacturer_grants_formulation
    """
    sc = fx.setup_line_with_sealed_formulation()
    form_id = sc["formulation"]["id"]
    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    mfr2 = fx.create_qualified_manufacturer(legal_name="Beta Filling Inc",
                                            capabilities=["AEROSOL_FILL"])
    g1a = fx.create_active_grant(mfr1["id"], form_id, component_scope=["C1"])
    g1b = fx.create_active_grant(mfr1["id"], form_id, component_scope=["C2"])
    g2 = fx.create_active_grant(mfr2["id"], form_id, component_scope=["C3", "C4"])
    assert validate_success(api_client.get_formulation(form_id, TSO))["status"] \
        == "COMPARTMENTALIZED"

    revoked = api_client.revoke_confidentiality_grant(g1a["id"], True, CA)
    revoked_data = validate_success(revoked)
    assert revoked_data["status"] == "REVOKED"
    assert revoked_data["revoked_for_cause"] is True

    mfr1_after = validate_success(
        api_client.get_contract_manufacturer(mfr1["id"], TSO))
    assert mfr1_after["status"] == "SUSPENDED", "cascade link 1"
    assert mfr1_after["disclosed_component_count"] == 0

    g1b_after = validate_success(api_client.get_confidentiality_grant(g1b["id"], TSO))
    assert g1b_after["status"] == "REVOKED", \
        "cascade link 2 revoked the manufacturer's other grant untouched by the call"
    assert g1b_after["revoked_for_cause"] is True

    g2_after = validate_success(api_client.get_confidentiality_grant(g2["id"], TSO))
    assert g2_after["status"] == "ACTIVE", "the other manufacturer is untouched"

    form_after = validate_success(api_client.get_formulation(form_id, TSO))
    assert form_after["status"] == "SEALED", \
        "cascade link 3: coverage of C1 and C2 was lost"

    brand = validate_success(api_client.get_brand(sc["brand"]["id"], BM))
    assert brand["protection_posture"] == "CRITICAL", \
        "two for-cause revocations within 180 days reach the CRITICAL breach count"


def test_manufacturer_requalify_blocked_for_ninety_days_then_allowed():
    """PRD §3.3: "Requalification from `SUSPENDED` back to `QUALIFIED` clears `suspended_at`, but it is refused with `ERR_RECENT_BREACH` (HTTP 409) while any grant of this manufacturer shows `revoked_for_cause` true with a `revoked_at` inside the trailing 90 days."

    Design: Corner/state_machines/manufacturer_requalify_blocked_for_ninety_days_then_allowed
    """
    sc = fx.setup_line_with_sealed_formulation()
    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    g1 = fx.create_active_grant(mfr1["id"], sc["formulation"]["id"],
                                component_scope=["C1", "C2"])
    validate_success(api_client.revoke_confidentiality_grant(g1["id"], True, CA))
    suspended = validate_success(
        api_client.get_contract_manufacturer(mfr1["id"], TSO))
    assert suspended["status"] == "SUSPENDED", "the for-cause revoke cascaded"

    blocked = api_client.qualify_contract_manufacturer(mfr1["id"], TSO)
    validate_error(blocked, ApiErrorId.ERR_RECENT_BREACH)

    fx.advance_clock("2026-12-01T00:00:00Z")  # 91 days after the 2026-09-01 revoke
    requalified = api_client.qualify_contract_manufacturer(mfr1["id"], TSO)
    data = validate_success(requalified)
    assert data["status"] == "QUALIFIED"
    assert data["suspended_at"] is None


def test_for_cause_revocation_by_grantor_is_auditor_conflict():
    """PRD §3.3: "Segregation of duties applies when `for_cause` is true and a `granted_by_user_id` has been recorded: the revoking caller's `X-User-ID` must differ from it, failing `ERR_AUDITOR_CONFLICT` (HTTP 409)."
    PRD §3.3: "Every revocation stamps `revoked_at` with the current logical time and copies the flag into `revoked_for_cause`."

    Design: Corner/validations/for_cause_revocation_by_grantor_is_auditor_conflict
    """
    sc = fx.setup_line_with_sealed_formulation()
    mfr1 = fx.create_qualified_manufacturer()
    grant = fx.create_granted_grant(mfr1["id"], sc["formulation"]["id"])
    assert grant["granted_by_user_id"] == "tso-1"

    conflict = api_client.revoke_confidentiality_grant(
        grant["id"], True, make_compliance_auditor_headers("tso-1"))
    validate_error(conflict, ApiErrorId.ERR_AUDITOR_CONFLICT)

    revoked = api_client.revoke_confidentiality_grant(grant["id"], False, CA)
    data = validate_success(revoked)
    assert data["status"] == "REVOKED"
    assert data["revoked_for_cause"] is False

    mfr = validate_success(api_client.get_contract_manufacturer(mfr1["id"], TSO))
    assert mfr["status"] == "QUALIFIED", \
        "a non-cause revocation fires no manufacturer cascade"
