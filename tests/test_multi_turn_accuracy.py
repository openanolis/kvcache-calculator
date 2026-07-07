from kvcache_upper_bound.heuristic.multi_agent import (
    MultiAgentHeuristicConfig,
    CurveShapeConfig,
    PolicyEfficiency,
)


def test_per_turn_reusable_private_tokens():
    config = MultiAgentHeuristicConfig(
        concurrent_agents=100,
        shared_prefix_tokens=4096,
        avg_new_tokens_per_turn=2048,
        avg_turns_per_session=8,
        private_window_tokens=32768,
    )
    per_turn = config.per_turn_reusable_private_tokens()
    assert len(per_turn) == 8
    assert per_turn[0] == 0
    assert per_turn[1] == 2048
    assert per_turn[7] == min(32768, 7 * 2048)


def test_per_turn_content_hit_rates():
    config = MultiAgentHeuristicConfig(
        concurrent_agents=100,
        shared_prefix_tokens=4096,
        avg_new_tokens_per_turn=2048,
        avg_turns_per_session=8,
        private_window_tokens=32768,
    )
    rates = config.per_turn_content_hit_rates()
    assert len(rates) == 8
    assert rates[0] < rates[7]
    # Turn 0: hit=4096, req=4096+2048+0=6144, rate=4096/6144=0.667
    assert abs(rates[0] - 4096 / 6144) < 0.001


def test_per_turn_working_set():
    config = MultiAgentHeuristicConfig(
        concurrent_agents=100,
        shared_prefix_tokens=4096,
        avg_new_tokens_per_turn=2048,
        avg_turns_per_session=4,
        private_window_tokens=32768,
    )
    wst = config.per_turn_working_set_tokens()
    assert len(wst) == 4
    assert wst[0] == 4096 + 0 + 2048  # shared + 0 private + new
    assert wst[1] == 4096 + 2048 + 2048
