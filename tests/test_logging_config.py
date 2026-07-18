import json
import logging
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "kodi-np-multi"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from logging_config import JsonFormatter, configure_logging


def test_configure_logging_default_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert root.handlers
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_json_format(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    formatter = logging.getLogger().handlers[0].formatter
    assert isinstance(formatter, JsonFormatter)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["logger"] == "test"
