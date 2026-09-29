"""Type aliases for the resource shapes the CCR contract returns.

These are documentation-grade aliases rather than validation machinery: the
suite asserts on values with the helpers in ``assertions``, and uses these
names so that a helper signature says which resource family it hands back.
"""

from typing import Any, Dict, List, Tuple

# A decoded JSON object as it arrives in the envelope's ``data`` field.
Json = Dict[str, Any]

# Resource families of the contract.
DisposalUnit = Json
ComplianceSummary = Json
QualifiedProfessional = Json
StabilityAssessment = Json
MonitoringWell = Json
MonitoringProgram = Json
SamplingEvent = Json
AnalyticalResult = Json
StatisticalEvaluation = Json
ClosurePlan = Json
ClosureExtensionRequest = Json
BeneficialReuseAgreement = Json
ReuseShipment = Json
CapInspection = Json
PublicPosting = Json

# A request body, and a header pair declaring the acting identity.
Payload = Dict[str, Any]
Headers = Dict[str, str]

# A page of a list endpoint: the rows and the pagination meta block.
Page = Tuple[List[Json], Json]

# The dict a fixture helper returns once it has built a world through the API.
World = Dict[str, Any]
