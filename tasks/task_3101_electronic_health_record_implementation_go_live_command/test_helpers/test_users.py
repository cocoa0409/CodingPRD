"""Pre-built role headers for every role in the PRD.

Thirteen roles are ``opaque`` identities whose ``X-User-ID`` is a free operator
identifier; their shared constants are the canonical form.  ``CredentialedTrainer``
is ``entity_backed`` — its ``X-User-ID`` must be the ``id`` of the acting trainer
row itself, so ownership-gated calls must go through
``make_credentialed_trainer_headers(trainer_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "implementation_director_headers": build_user_headers("test-director-1", "ImplementationDirector"),
    "implementation_analyst_headers": build_user_headers("test-analyst-1", "ImplementationAnalyst"),
    "build_analyst_headers": build_user_headers("test-build-analyst-1", "BuildAnalyst"),
    "test_lead_headers": build_user_headers("test-test-lead-1", "TestLead"),
    "training_coordinator_headers": build_user_headers("test-training-coord-1", "TrainingCoordinator"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "credentialed_trainer_headers": build_user_headers("test-trainer-1", "CredentialedTrainer"),
    "conversion_analyst_headers": build_user_headers("test-conversion-analyst-1", "ConversionAnalyst"),
    "order_reconciler_headers": build_user_headers("test-order-reconciler-1", "OrderReconciler"),
    "revenue_cycle_analyst_headers": build_user_headers("test-revenue-cycle-1", "RevenueCycleAnalyst"),
    "interface_engineer_headers": build_user_headers("test-interface-engineer-1", "InterfaceEngineer"),
    "cutover_lead_headers": build_user_headers("test-cutover-lead-1", "CutoverLead"),
    "command_center_lead_headers": build_user_headers("test-command-center-lead-1", "CommandCenterLead"),
    "triage_commander_headers": build_user_headers("test-triage-commander-1", "TriageCommander"),
    "optimization_lead_headers": build_user_headers("test-optimization-lead-1", "OptimizationLead"),
}


def make_credentialed_trainer_headers(trainer_id: str) -> dict:
    """For CredentialedTrainer (entity_backed:CredentialedTrainer).

    Pass the actual CredentialedTrainer row's id as user_id whenever the call is
    ownership-gated: the credential check compares the exam's proctor of record
    against ``X-User-ID``.
    """
    return build_user_headers(trainer_id, "CredentialedTrainer")


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role with an explicit operator id.

    Used where a test needs two distinct principals acting under the same role
    (for example, the segregation-of-duties pair).
    """
    return build_user_headers(user_id, role)