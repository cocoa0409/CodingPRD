"""Serialization. Private bookkeeping keys are prefixed with an underscore and dropped."""

import rollups


def public(record):
    if record is None:
        return None
    return dict((k, v) for k, v in record.items() if not k.startswith("_"))


def certification_summary(project):
    """PRD 3.7 computed read: the project-level certification summary."""
    return {
        "total_link_count": project["total_link_count"],
        "certified_link_count": project["certified_link_count"],
        "failed_link_count": project["failed_link_count"],
        "completeness_pct_strict": project["completeness_pct_strict"],
        "completeness_pct_provisional": project["completeness_pct_provisional"],
        "warranty_status": project["warranty_status"],
        "as_built_cost_cents": project["as_built_cost_cents"],
        "consumed_mac_cents": project["consumed_mac_cents"],
    }


def certification_report(link):
    """PRD 3.7 computed read: one link's evidence, assembled from its latest result."""
    result = rollups.latest_test_result(link["id"])
    report = {
        "link_id": link["id"],
        "identifier": link["identifier"],
        "install_state": link["install_state"],
        "record_state": link["record_state"],
        "test_attempt_count": link["test_attempt_count"],
        "latest_test_outcome": link["latest_test_outcome"],
        "latest_test_standard": None,
        "graded_length_m": None,
        "insertion_loss_budget_db": None,
        "worst_margin_db": None,
        "failure_reason": None,
        "certifier_user_id": link["certifier_user_id"],
    }
    if result is not None:
        report["latest_test_standard"] = result["test_standard"]
        report["graded_length_m"] = result["_graded_length_m"]
        report["insertion_loss_budget_db"] = result["insertion_loss_budget_db"]
        report["worst_margin_db"] = result["worst_margin_db"]
        report["failure_reason"] = result["failure_reason"]
    return report
