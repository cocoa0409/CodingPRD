"""Pre-built role headers for the ten roles declared in PRD §2.1.

Shared constants are safe for the opaque, unscoped roles (DutyOfficer,
ManagingDirector, PartyCoordinator, RecorderCustodian, DocketOfficer,
BoardAdmin) and for any test that does not exercise an ownership rule.

Four roles carry an ownership scope (PRD §2.1); for those, ownership-gated
calls MUST go through the per-instance builder with the real scoped identity:
  - IIC actions             -> make_iic_headers(investigation["iic_user_id"])
  - GroupChairman actions   -> make_group_chairman_headers(group["chairman_user_id"])
  - AddresseeContact calls  -> make_addressee_contact_headers(org["id"])
                               (entity-backed: X-User-ID IS the organization's id)
  - BoardMember votes       -> make_board_member_headers(member_id) where
                               member_id is in meeting["sitting_member_ids"]

Two ManagingDirector identities exist so segregation-of-duties setups work:
md-1 is the canonical proposer, md-2 the canonical adopter (PRD §3.2 bars the
proposer from adopting their own decision).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque, unscoped roles — shared constant is the canonical form.
    "duty_officer_headers": build_user_headers("duty-officer-1", "DutyOfficer"),
    "party_coordinator_headers": build_user_headers("pc-1", "PartyCoordinator"),
    "recorder_custodian_headers": build_user_headers("rc-1", "RecorderCustodian"),
    "docket_officer_headers": build_user_headers("do-1", "DocketOfficer"),
    "board_admin_headers": build_user_headers("ba-1", "BoardAdmin"),
    # ManagingDirector — generic plus the SoD proposer/adopter pair.
    "managing_director_headers": build_user_headers("md-1", "ManagingDirector"),
    "md_proposer_headers": build_user_headers("md-1", "ManagingDirector"),
    "md_adopter_headers": build_user_headers("md-2", "ManagingDirector"),
    # Ownership-scoped roles — shared constants are fallbacks for non-ownership
    # tests only (they match the canonical fixture identities iic-1 / gc-1).
    "iic_headers": build_user_headers("iic-1", "IIC"),
    "group_chairman_headers": build_user_headers("gc-1", "GroupChairman"),
    "board_member_headers": build_user_headers("bm-1", "BoardMember"),
    # Entity-backed role (PartyOrganization) — fallback for non-ownership tests;
    # response submission requires make_addressee_contact_headers(org["id"]).
    "addressee_contact_headers": build_user_headers("test-addressee-org-1", "AddresseeContact"),
}


def make_managing_director_headers(user_id: str) -> dict:
    """ManagingDirector with a specific identity (propose/adopt SoD checks)."""
    return build_user_headers(user_id, "ManagingDirector")


def make_iic_headers(user_id: str) -> dict:
    """IIC scoped to an investigation: pass investigation["iic_user_id"] for
    ownership-gated calls (groups, seats, violations, verify, recommendations,
    phase advance/reopen)."""
    return build_user_headers(user_id, "IIC")


def make_group_chairman_headers(user_id: str) -> dict:
    """GroupChairman scoped to a group: pass group["chairman_user_id"] for
    ownership-gated calls (author factual report, complete group)."""
    return build_user_headers(user_id, "GroupChairman")


def make_addressee_contact_headers(org_id: str) -> dict:
    """AddresseeContact is entity-backed by PartyOrganization (PRD §2.1):
    X-User-ID IS the acting organization's id. Pass the addressee org's id —
    recommendation["addressee_org_id"] — for response submission."""
    return build_user_headers(org_id, "AddresseeContact")


def make_board_member_headers(user_id: str) -> dict:
    """BoardMember scoped to a meeting roster: pass an id from
    meeting["sitting_member_ids"] when casting votes."""
    return build_user_headers(user_id, "BoardMember")
