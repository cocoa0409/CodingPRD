"""Light structural aliases for the entities the PRD defines.

These are documentation-grade aliases, not runtime validators: the response
bodies are plain JSON dictionaries and the tests assert against them directly.
"""

from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]

Institution = Json
SpeciesProgram = Json
Veterinarian = Json
Animal = Json
PopulationRecommendation = Json
TransferAgreement = Json
ComplianceDocument = Json
PreShipmentTest = Json
QuarantineOccupancy = Json
ShipmentBooking = Json
IntroductionProtocol = Json
StudbookSubmission = Json

Headers = Dict[str, str]
PageResult = Tuple[List[Json], Json]

# Entities carrying the full system-field set: id, created_at, updated_at, version.
VERSIONED_ENTITIES = (
    "Institution",
    "SpeciesProgram",
    "Veterinarian",
    "Animal",
    "PopulationRecommendation",
    "TransferAgreement",
    "ComplianceDocument",
    "QuarantineOccupancy",
    "ShipmentBooking",
    "IntroductionProtocol",
    "StudbookSubmission",
)

# The one immutable entity: it carries only id and created_at.
IMMUTABLE_ENTITIES = ("PreShipmentTest",)
