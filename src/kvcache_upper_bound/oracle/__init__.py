"""Oracle layers for KVCache upper bound analysis."""

from .capacity import (
    CapacityAnalysisResult,
    CapacityRequestMetric,
    CapacitySummary,
    analyze_capacity_upper_bound,
)
from .content import (
    ContentAnalysisResult,
    ContentRequestMetric,
    ContentSummary,
    analyze_content_upper_bound,
)
from .lfu import LFUSimulationResult, analyze_lfu_baseline
from .lru import LRUSimulationResult, analyze_lru_baseline
from .prefix_aware import PrefixAwareSimulationResult, analyze_prefix_aware
from .prefix_trie import PrefixTrie, PrefixTrieNode
from .strict_prefix import (
    StrictPrefixAnalysisResult,
    StrictPrefixRequestMetric,
    StrictPrefixSummary,
    analyze_strict_prefix_capacity_upper_bound,
)

__all__ = [
    "CapacityAnalysisResult",
    "CapacityRequestMetric",
    "CapacitySummary",
    "ContentAnalysisResult",
    "ContentRequestMetric",
    "ContentSummary",
    "LFUSimulationResult",
    "LRUSimulationResult",
    "PrefixAwareSimulationResult",
    "PrefixTrie",
    "PrefixTrieNode",
    "StrictPrefixAnalysisResult",
    "StrictPrefixRequestMetric",
    "StrictPrefixSummary",
    "analyze_capacity_upper_bound",
    "analyze_content_upper_bound",
    "analyze_lfu_baseline",
    "analyze_lru_baseline",
    "analyze_prefix_aware",
    "analyze_strict_prefix_capacity_upper_bound",
]
