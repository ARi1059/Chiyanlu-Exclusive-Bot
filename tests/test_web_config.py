"""WEB_* 配置（P0·T6）。

核心保证：默认不启用 web —— 接入 main.py 对现有生产零影响。同时验证可经 env 开启。
用 Config.from_env() 重新解析（module 级 config 单例已在 import 时固化）。
"""
from __future__ import annotations

from bot.config import Config


def test_web_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WEB_ENABLED", raising=False)
    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.delenv("WEB_PORT", raising=False)
    cfg = Config.from_env()
    assert cfg.web_enabled is False
    assert cfg.web_host == "127.0.0.1"
    assert cfg.web_port == 8080


def test_web_enabled_via_env(monkeypatch):
    monkeypatch.setenv("WEB_ENABLED", "true")
    monkeypatch.setenv("WEB_PORT", "9000")
    cfg = Config.from_env()
    assert cfg.web_enabled is True
    assert cfg.web_port == 9000


def test_web_enabled_accepts_common_truthy(monkeypatch):
    for val in ("1", "TRUE", "Yes", "on"):
        monkeypatch.setenv("WEB_ENABLED", val)
        assert Config.from_env().web_enabled is True
    for val in ("0", "false", "no", ""):
        monkeypatch.setenv("WEB_ENABLED", val)
        assert Config.from_env().web_enabled is False
