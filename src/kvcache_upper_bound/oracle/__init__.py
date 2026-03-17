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
from .prefix_trie import PrefixTrie, PrefixTrieNode

__all__ = [
    "CapacityAnalysisResult",
    "CapacityRequestMetric",
    "CapacitySummary",
    "ContentAnalysisResult",
    "ContentRequestMetric",
    "ContentSummary",
    "PrefixTrie",
    "PrefixTrieNode",
    "analyze_capacity_upper_bound",
    "analyze_content_upper_bound",
]
