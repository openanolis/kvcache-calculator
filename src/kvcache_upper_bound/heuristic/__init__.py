"""Trace-free heuristic estimators for KVCache planning."""

from .calibration import (
    CalibrationGrid,
    CalibrationResult,
    CalibrationTierComparison,
    CalibrationTierTarget,
    CalibrationTraceTarget,
    CalibrationTrial,
    build_calibration_grid_from_ranges,
    build_default_calibration_grid,
    build_trace_calibration_target,
    calibrate_multi_agent_parameters,
    write_calibration_outputs,
)
from .config_loader import load_multi_agent_heuristic_config
from .multi_agent import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicAnalysisResult,
    HeuristicCapacityTier,
    HeuristicDeploymentConfig,
    HeuristicScenarioSummary,
    HeuristicTierRow,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    analyze_multi_agent_heuristic,
)
from .output import (
    HeuristicInputSummary,
    HeuristicTierInputSummary,
    build_multi_agent_input_summaries,
    write_multi_agent_outputs,
)
from .report import HeuristicReportContext, write_multi_agent_report_outputs
from .structure import (
    TraceStructureHints,
    TraceStructureRecommendation,
    build_trace_structure_recommendation,
    estimate_multi_agent_structure_from_trace,
)

__all__ = [
    "CalibrationGrid",
    "CalibrationResult",
    "CalibrationTierComparison",
    "CalibrationTierTarget",
    "CalibrationTraceTarget",
    "CalibrationTrial",
    "CurveShapeConfig",
    "HeuristicAnalysisConfig",
    "HeuristicAnalysisResult",
    "HeuristicCapacityTier",
    "HeuristicDeploymentConfig",
    "HeuristicInputSummary",
    "HeuristicScenarioSummary",
    "HeuristicTierInputSummary",
    "HeuristicTierRow",
    "MultiAgentHeuristicConfig",
    "PolicyEfficiency",
    "TraceStructureHints",
    "TraceStructureRecommendation",
    "analyze_multi_agent_heuristic",
    "build_multi_agent_input_summaries",
    "build_trace_structure_recommendation",
    "build_default_calibration_grid",
    "build_calibration_grid_from_ranges",
    "build_trace_calibration_target",
    "calibrate_multi_agent_parameters",
    "estimate_multi_agent_structure_from_trace",
    "load_multi_agent_heuristic_config",
    "HeuristicReportContext",
    "write_calibration_outputs",
    "write_multi_agent_outputs",
    "write_multi_agent_report_outputs",
]
