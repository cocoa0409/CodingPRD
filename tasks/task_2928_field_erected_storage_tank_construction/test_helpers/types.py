"""Lightweight type aliases for the fourteen resource families.

The API returns plain JSON objects, so these are documentation-grade aliases
rather than runtime validators.
"""

from typing import Any, Dict, List

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]

Tank = Json
FoundationPackage = Json
SettlementSurvey = Json
PlateLot = Json
ShellCourse = Json
Welder = Json
WeldSeam = Json
NdeReport = Json
WaterSource = Json
HydrotestPlan = Json
WaterWithdrawal = Json
CoatingApplication = Json
Appurtenance = Json
CommissioningPackage = Json

# A point reading inside a settlement survey's point_readings array:
# {"point_index": int, "elevation_in": float}
PointReading = Json

# One spot inside a coating application's spot_readings array: exactly three
# numeric gauge readings in mils.
SpotReading = List[float]
