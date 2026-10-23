"""Tests for the unified bead economy (word / sentence / discrim), v2 100×100 baseline.

新版基线（2026-08-26）：
* 三个正式训练项目平权，标准档统一 600；字词 5/10 分钟 = 600/1200，
  句子 10/15 句 = 600/900，辨音 50/100/150 词 = 300/600/900。
* 完成不足 20% 不发拼点（不算有效训练）；≥20% 按真实完成比例结算（浮点余量）。
* 正确率不影响拼点、答错不扣拼点；无辨音轮次递减、无首轮全对彩蛋。
* 今日三练（三类各完整完成一次）= +100/天；今日复习清空 = +100/天。
* Streak 不发拼点；无每日硬上限。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pth_corpus.achievement import (
    AchievementConfig,
    compute_activity_reward,
    compute_review_reward,
)
from pth_corpus.prototype_app import create_app

CONFIG_DIR = Path(__file__).resolve().parents[1] / "src" / "pth_corpus" / "prototype_data"


def _shipped_config() -> AchievementConfig:
    data = json.loads(
        (CONFIG_DIR / "achievement_config_v2.json").read_text(encoding="utf-8")
    )
    return AchievementConfig.from_dict(data)


def test_shipped_config_pins_new_baseline() -> None:
    """锁死 100×100 基线数值：600/1200、600/900、300/600/900、三练 100、复习 100。"""
    config = _shipped_config()
    assert config.tiers == {
        "word": {3: 360.0, 5: 600.0, 10: 1200.0},
        "sentence": {5: 300.0, 10: 600.0, 15: 900.0},
        "discrim": {50: 300.0, 100: 600.0, 150: 900.0},
    }
    assert config.minimum_completion_ratio == 0.2
    assert config.trio_bonus == 100
    assert config.review_reward == 100
    # 旧规则全部移除
    assert not hasattr(config, "daily_bead_cap")
    assert not hasattr(config, "streak_bonus")
    assert not hasattr(config, "completion_bonus")


def test_full_completion_pays_the_full_tier() -> None:
    config = _shipped_config()
    assert compute_activity_reward(config, "word", 5, 1.0).total_beads == 600
    assert compute_activity_reward(config, "word", 10, 1.0).total_beads == 1200
    assert compute_activity_reward(config, "sentence", 10, 1.0).total_beads == 600
    assert compute_activity_reward(config, "sentence", 15, 1.0).total_beads == 900
    assert compute_activity_reward(config, "discrim", 50, 1.0).total_beads == 300
    assert compute_activity_reward(config, "discrim", 100, 1.0).total_beads == 600
    assert compute_activity_reward(config, "discrim", 150, 1.0).total_beads == 900


def test_partial_completion_scales_by_real_ratio() -> None:
    config = _shipped_config()
    # 规则文档示例：标准档满额 600，完成 60% → 约 360
    sixty = compute_activity_reward(config, "sentence", 10, 6 / 10)
    assert sixty.total_beads == 360
    # 浮点余额允许存在（不四舍五入，防套利）
    third = compute_activity_reward(config, "sentence", 15, 5 / 15)
    assert third.total_beads == pytest.approx(300.0)
    discrim_half = compute_activity_reward(config, "discrim", 100, 0.5)
    assert discrim_half.total_beads == 300
    word_half = compute_activity_reward(config, "word", 10, 0.5)
    assert word_half.total_beads == 600


def test_below_threshold_earns_nothing_and_is_not_valid() -> None:
    config = _shipped_config()
    tiny = compute_activity_reward(config, "word", 10, 0.1)
    assert not tiny.eligible and tiny.total_beads == 0
    assert tiny.completed_today is False
    edge = compute_activity_reward(config, "word", 10, 0.199)
    assert not edge.eligible
    ok = compute_activity_reward(config, "word", 10, 0.2)
    assert ok.eligible


def test_correctness_does_not_affect_points() -> None:
    """答对答错不影响拼点：辨音按「完成判断数 / 目标判断数」结算。"""
    config = _shipped_config()
    wrong_heavy = compute_activity_reward(config, "discrim", 50, 1.0)
    assert wrong_heavy.total_beads == 300  # 全对与全错按投入同样结算
    partial = compute_activity_reward(config, "discrim", 50, 30 / 50)
    assert partial.total_beads == 180


def test_trio_bonus_once_per_day() -> None:
    config = _shipped_config()
    triggered = compute_activity_reward(
        config, "sentence", 10, 1.0, trio_eligible=True
    )
    assert triggered.trio_bonus == 100 and triggered.total_beads == 700
    awarded = compute_activity_reward(
        config, "sentence", 10, 1.0, trio_eligible=True, trio_awarded_today=True
    )
    assert awarded.trio_bonus == 0 and awarded.total_beads == 600
    # 未达成三练 → 0；部分完成不触发三练加成
    not_ready = compute_activity_reward(config, "word", 5, 1.0)
    assert not_ready.trio_bonus == 0
    partial_trio = compute_activity_reward(
        config, "word", 5, 0.5, trio_eligible=True
    )
    assert partial_trio.trio_bonus == 0 and partial_trio.total_beads == 300


def test_streak_is_display_only() -> None:
    config = _shipped_config()
    reward = compute_activity_reward(
        config, "word", 10, 1.0, streak_days=30
    )
    assert reward.streak_bonus == 0
    assert reward.streak_days == 30
    assert reward.total_beads == 1200  # 连续 30 天不加拼点


def test_review_reward_is_fixed_and_flat() -> None:
    config = _shipped_config()
    reward = compute_review_reward(config)
    assert reward.eligible and reward.total_beads == 100
    assert reward.trio_bonus == 0 and reward.streak_bonus == 0


def test_unknown_tier_is_rejected() -> None:
    config = _shipped_config()
    with pytest.raises(ValueError):
        compute_activity_reward(config, "word", 15, 1.0)
    with pytest.raises(ValueError):
        compute_activity_reward(config, "sentence", 6, 1.0)
    with pytest.raises(ValueError):
        compute_activity_reward(config, "discrim", 200, 1.0)


def test_config_validation_rejects_bad_tiers() -> None:
    base = {"version": "x", "tiers": {}}
    with pytest.raises(ValueError):
        AchievementConfig.from_dict(base)
    with pytest.raises(ValueError):
        AchievementConfig.from_dict(
            {**base, "tiers": {"word": {"0": 100}}}
        )
    with pytest.raises(ValueError):
        AchievementConfig.from_dict(
            {**base, "tiers": {"word": {"5": -1}}}
        )


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(data_root=tmp_path)
    return TestClient(app)


def test_settle_endpoint_word(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        full = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 10, "completion_ratio": 1.0},
        ).json()
        assert full["total_beads"] == 1200 and full["completed_today"] is True
        partial = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 5, "completion_ratio": 0.6},
        ).json()
        assert partial["total_beads"] == 360
        below = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 10, "completion_ratio": 0.1},
        ).json()
        assert below["eligible"] is False and below["total_beads"] == 0
        # 旧 15/20 分钟档已删除 → 400
        assert (
            client.post(
                "/api/achievement/settle",
                json={"planned_duration_minutes": 15, "completion_ratio": 1.0},
            ).status_code
            == 400
        )
        # 旧字段（streak 加成 / 日上限）不再接受
        old = client.post(
            "/api/achievement/settle",
            json={
                "planned_duration_minutes": 10,
                "completion_ratio": 1.0,
                "beads_earned_today": 999,
                "first_completion_today": True,
            },
        )
        assert old.status_code in (400, 422)


def test_settle_endpoint_sentence(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        full = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 10,
            },
        ).json()
        assert full["total_beads"] == 600
        full15 = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 15,
                "completed_sentence_count": 15,
            },
        ).json()
        assert full15["total_beads"] == 900
        partial = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 6,
            },
        ).json()
        assert partial["total_beads"] == 360
        below = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 1,
            },
        ).json()
        assert below["eligible"] is False


def test_settle_endpoint_discrim_uses_completed_points(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        full = client.post(
            "/api/achievement/settle",
            json={
                "activity": "discrim",
                "completed_points": 100,
                "total_points": 100,
            },
        ).json()
        assert full["total_beads"] == 600
        # 答错不影响：完成 100 判断点即使全错也按完成结算
        wrong_all = client.post(
            "/api/achievement/settle",
            json={
                "activity": "discrim",
                "completed_points": 100,
                "total_points": 100,
            },
        ).json()
        assert wrong_all["total_beads"] == 600
        partial = client.post(
            "/api/achievement/settle",
            json={
                "activity": "discrim",
                "completed_points": 25,
                "total_points": 50,
            },
        ).json()
        assert partial["total_beads"] == 150
        # 旧的正确率/轮次字段不再接受
        old = client.post(
            "/api/achievement/settle",
            json={
                "activity": "discrim",
                "correct_points": 10,
                "total_points": 11,
                "round_completed": True,
                "discrim_round_today": 1,
            },
        )
        assert old.status_code in (400, 422)


def test_settle_endpoint_trio_and_review(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        triggered = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 10,
                "word_completed_today": True,
                "discrim_completed_today": True,
            },
        ).json()
        assert triggered["trio_bonus"] == 100
        assert triggered["total_beads"] == 700
        awarded = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 10,
                "word_completed_today": True,
                "discrim_completed_today": True,
                "trio_awarded_today": True,
            },
        ).json()
        assert awarded["trio_bonus"] == 0 and awarded["total_beads"] == 600
        review = client.post(
            "/api/achievement/settle", json={"activity": "review"}
        ).json()
        assert review["total_beads"] == 100


def test_settle_endpoint_streak_is_display_only(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        body = client.post(
            "/api/achievement/settle",
            json={
                "activity": "sentence",
                "sentence_count": 10,
                "completed_sentence_count": 10,
                "streak_days": 30,
            },
        ).json()
        assert body["streak_days"] == 30
        assert body["streak_bonus"] == 0
        assert body["total_beads"] == 600


def test_settle_endpoint_validation(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert (
            client.post(
                "/api/achievement/settle", json={"activity": "bogus"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/achievement/settle",
                json={"activity": "sentence", "sentence_count": 10},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/achievement/settle",
                json={
                    "activity": "discrim",
                    "completed_points": 12,
                    "total_points": 11,
                },
            ).status_code
            == 400
        )
