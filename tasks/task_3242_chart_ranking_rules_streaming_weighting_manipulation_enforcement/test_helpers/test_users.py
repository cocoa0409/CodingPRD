"""Pre-built role headers for every role in the PRD.

PlatformAdmin, ChartManager, ChartOps and Investigator use opaque operator
ids, so shared constants are canonical for them (a per-instance builder is
still provided so tests can control the exact operator id, e.g. for
segregation-of-duties scenarios). DataProvider is entity-backed by Provider
(X-User-ID is the Provider's id) and LabelRep is entity-backed by
LabelAccount (X-User-ID is the LabelAccount's id) — for those, always use
the per-instance builders with the real entity id whenever the call is
identity- or ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "chart_manager_headers": build_user_headers("chart-manager-1", "ChartManager"),
    "chart_ops_headers": build_user_headers("chart-ops-1", "ChartOps"),
    "investigator_headers": build_user_headers("investigator-1", "Investigator"),
    # Entity-backed roles — fallback constants for non-identity tests ONLY.
    "data_provider_headers": build_user_headers("data-provider-fallback", "DataProvider"),
    "label_rep_headers": build_user_headers("label-rep-fallback", "LabelRep"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin with an explicit opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_chart_manager_headers(user_id: str) -> dict:
    """ChartManager with an explicit opaque operator id."""
    return build_user_headers(user_id, "ChartManager")


def make_chart_ops_headers(user_id: str) -> dict:
    """ChartOps with an explicit opaque operator id (used to control the
    escalating analyst identity for segregation-of-duties checks)."""
    return build_user_headers(user_id, "ChartOps")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator with an explicit opaque operator id (must equal the
    investigation's assigned_to at resolve time)."""
    return build_user_headers(user_id, "Investigator")


def make_data_provider_headers(provider_id: str) -> dict:
    """DataProvider (entity_backed: Provider). Pass the acting Provider's id
    as user_id for report submission."""
    return build_user_headers(provider_id, "DataProvider")


def make_label_rep_headers(label_account_id: str) -> dict:
    """LabelRep (entity_backed: LabelAccount). Pass the acting LabelAccount's
    id as user_id for title registration and dispute filing."""
    return build_user_headers(label_account_id, "LabelRep")
