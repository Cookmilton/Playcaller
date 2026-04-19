"""
Validation, session audit, metrics, and optional calibration for recommendation quality.

Does not alter Game → Drive → ActualPlayResult logging; audit rows attach parallel metadata.
"""

from .audit import (
    append_open_audit,
    audit_record_from_recommendation,
    actual_to_audit_dict,
    link_open_audit_to_actual,
    next_review_ordinal,
    supersede_open_audits_for_snap,
    trim_stale_open_audits,
    void_last_closed_audit,
)
from .calibration import CalibrationProfile, load_calibration_profile
from .metrics import (
    EXPLOSIVE_GAIN_YARD_THRESHOLD,
    actual_fields_is_explosive,
    actual_fields_is_turnover,
    evaluate_audit_records,
    summarize_audit_session,
)

__all__ = [
    "append_open_audit",
    "audit_record_from_recommendation",
    "link_open_audit_to_actual",
    "actual_to_audit_dict",
    "next_review_ordinal",
    "supersede_open_audits_for_snap",
    "trim_stale_open_audits",
    "void_last_closed_audit",
    "CalibrationProfile",
    "load_calibration_profile",
    "EXPLOSIVE_GAIN_YARD_THRESHOLD",
    "actual_fields_is_explosive",
    "actual_fields_is_turnover",
    "evaluate_audit_records",
    "summarize_audit_session",
]
