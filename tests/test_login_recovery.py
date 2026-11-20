import json

import pytest

from app.config import ConfigError, parse_auth_json
from notify_feishu import make_card, make_summary
from scripts import login


def test_github_export_round_trips_complete_storage_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {
        "cookies": [{"name": "session", "value": "test-cookie"}],
        "origins": [{"origin": "https://example.test", "localStorage": [
            {"name": "state", "value": "测试" * 15000},
        ]}],
    }
    (tmp_path / "storage-state.json").write_text(json.dumps(state), encoding="utf-8")

    login.export_github_state()

    exported = (tmp_path / "storage-state-github.txt").read_text(encoding="ascii")
    assert len(exported) < 48 * 1024
    assert parse_auth_json(exported, "DOUYIN_STORAGE_STATE") == state
    assert parse_auth_json("storage-state.json", "DOUYIN_STORAGE_STATE") == state


def test_invalid_compressed_state_has_a_safe_error():
    with pytest.raises(ConfigError, match="压缩登录状态无效"):
        parse_auth_json("gzip-base64:invalid!", "DOUYIN_STORAGE_STATE")


def test_feishu_reports_login_abort_without_listing_every_friend(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOUYIN_CONFIG", json.dumps({"targets": [{"name": "测试好友"}]}))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("JOB_STATUS", "failure")
    monkeypatch.setenv("SENDER_OUTCOME", "failure")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    report = {"results": [{
        "target": "登录检查", "status": "failed", "sent": 0,
        "error": "进入抖音私信页面后登录状态失效",
    }]}
    (artifacts / "result.json").write_text(json.dumps(report), encoding="utf-8")

    summary = make_summary()

    assert "登录检查失败" in summary
    assert "登录状态失效" in summary
    assert "本次未发送" in summary
    assert "结果待确认" not in summary
    assert "测试好友" not in summary
    assert make_card(summary)["header"]["template"] == "orange"
