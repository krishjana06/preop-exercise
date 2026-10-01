"""Cadence policy, effective January 1, 2026. No external clinical criteria."""

H_AND_P_MAX_AGE_DAYS = 30
LAB_REQUIREMENTS = {
    "LOW": {"CBC": 30},
    "MODERATE": {"CBC": 30},
    "HIGH": {"CBC": 14, "CMP": 14},
}
MAX_SYSTOLIC_BP = 180
MAX_DIASTOLIC_BP = 110
MAX_TEMPERATURE_F = 100.4
ISSUE_ORDER = {
    category: index
    for index, category in enumerate(
        (
            "MISSING_REQUIRED_DATA",
            "REQUIRED_DOCUMENTATION",
            "REQUIRED_TESTING",
            "ANTICOAGULATION_MANAGEMENT",
            "ACUTE_SAFETY_EXCLUSION",
        )
    )
}
