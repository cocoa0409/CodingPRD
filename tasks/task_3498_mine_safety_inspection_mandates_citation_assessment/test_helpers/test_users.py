"""Pre-built role headers for every role in the PRD (§2.1).

Identity model (PRD §2.1, verbatim rules):

- Role ``Inspector``: ``X-User-ID`` IS the ``id`` of the acting Inspector
  entity. Ownership checks on an assigned inspection, an issued citation, or
  an imminent-danger order compare the resource's inspector foreign key to
  ``X-User-ID``.  => ALWAYS build headers with ``make_inspector_headers(
  inspector["id"])`` once the entity exists.
- Role ``OperatorRep``: ``X-User-ID`` IS the ``id`` of the acting Operator
  entity; ownership checks compare it to the ``operator_id`` of the target
  mine (or of the mine owning the target citation/contest).
  => ALWAYS build headers with ``make_operator_rep_headers(operator["id"])``
  once the entity exists.
- Roles ``MSHAAdmin``, ``DistrictManager``, ``CommissionJudge``,
  ``PublicReader``: ``X-User-ID`` is an opaque identifier not tied to any
  persisted entity; the shared constants below are canonical.

The shared ``TEST_USERS`` entries for the two entity-backed roles are
fallbacks ONLY for tests whose outcome cannot depend on ownership
(400-shape probes, 404 probes, authorization probes). Using them on an
ownership-gated call makes every such call fail with
ERR_OPERATOR_MISMATCH / ERR_INSPECTOR_MISMATCH.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — canonical for the four opaque roles; fallback-only for
# the two entity-backed roles (see module docstring).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", UserRole.MSHA_ADMIN.value),
    "district_manager_headers": build_user_headers(
        "test-district-manager-1", UserRole.DISTRICT_MANAGER.value
    ),
    "commission_judge_headers": build_user_headers(
        "test-commission-judge-1", UserRole.COMMISSION_JUDGE.value
    ),
    "public_reader_headers": build_user_headers(
        "test-public-reader-1", UserRole.PUBLIC_READER.value
    ),
    # entity_backed roles — fallback for non-ownership tests only:
    "inspector_headers": build_user_headers(
        "test-inspector-fallback", UserRole.INSPECTOR.value
    ),
    "operator_rep_headers": build_user_headers(
        "test-operator-rep-fallback", UserRole.OPERATOR_REP.value
    ),
}


# ─── Per-instance builders (mandatory for entity-backed roles) ────────────────

def make_inspector_headers(inspector_id: str) -> dict:
    """Inspector headers whose X-User-ID is the acting Inspector entity's id.
    Required for file-review/start/complete, citation issuance, IDO issuance,
    confirm-withdrawal, and verify-abatement (segregation-of-duties tests
    depend on two DISTINCT inspector entity ids)."""
    return build_user_headers(inspector_id, UserRole.INSPECTOR.value)


def make_operator_rep_headers(operator_id: str) -> dict:
    """OperatorRep headers whose X-User-ID is the acting Operator entity's id.
    Required for accident reports, plan submission, abate/extend-abatement,
    and contest file/withdraw (all ownership-gated against mine.operator_id)."""
    return build_user_headers(operator_id, UserRole.OPERATOR_REP.value)


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """MSHAAdmin headers (opaque identity)."""
    return build_user_headers(user_id, UserRole.MSHA_ADMIN.value)


def make_district_manager_headers(user_id: str = "test-district-manager-1") -> dict:
    """DistrictManager headers (opaque identity)."""
    return build_user_headers(user_id, UserRole.DISTRICT_MANAGER.value)


def make_commission_judge_headers(user_id: str = "test-commission-judge-1") -> dict:
    """CommissionJudge headers (opaque identity)."""
    return build_user_headers(user_id, UserRole.COMMISSION_JUDGE.value)


def make_public_reader_headers(user_id: str = "test-public-reader-1") -> dict:
    """PublicReader headers (opaque identity)."""
    return build_user_headers(user_id, UserRole.PUBLIC_READER.value)
