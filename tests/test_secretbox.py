"""Custom-server Kodi passwords are encrypted at rest in preferences.json."""
import json

import pytest

from kodi_np.secretbox import PREFIX, decrypt_secret, encrypt_secret, is_encrypted_secret


@pytest.fixture
def prefs_on_disk(app_module, tmp_path):
    from kodi_np import preferences as prefs_mod

    app_module.PREFERENCES_DIR = tmp_path
    app_module.PREFERENCES_FILE = tmp_path / "preferences.json"
    prefs_mod.invalidate_preferences_cache()
    return tmp_path


def test_encrypt_roundtrip_is_not_plaintext():
    blob = encrypt_secret("hunter2")
    assert blob.startswith(PREFIX)
    assert "hunter2" not in blob
    assert decrypt_secret(blob) == "hunter2"
    assert is_encrypted_secret(blob) is True


def test_empty_secret_stays_empty():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""
    assert is_encrypted_secret("") is False


def test_legacy_plaintext_is_still_readable():
    assert decrypt_secret("hunter2") == "hunter2"
    assert is_encrypted_secret("hunter2") is False


def test_garbage_ciphertext_returns_empty():
    assert decrypt_secret(PREFIX + "not-a-fernet-token") == ""


def test_create_server_writes_encrypted_password(client, prefs_on_disk, app_module):
    app_module.KODI_SERVERS = {
        1: {
            "id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1",
            "label": "Living Room", "auth": None, "username": "", "password": "",
            "source": "env",
        },
    }
    created = client.post("/api/servers", json={
        "host": "http://10.0.0.56:8080",
        "username": "kodi",
        "password": "hunter2",
        "label": "Attic",
    })
    assert created.status_code == 200
    on_disk = json.loads((prefs_on_disk / "preferences.json").read_text(encoding="utf-8"))
    stored = on_disk["custom_servers"][0]
    assert "password" not in stored
    assert stored["password_enc"].startswith(PREFIX)
    assert "hunter2" not in json.dumps(on_disk)

    listed = client.get("/api/servers").get_data(as_text=True)
    assert "hunter2" not in listed

    prefs = client.get("/api/preferences").get_json()
    servers = prefs.get("custom_servers") or []
    assert servers
    assert "password" not in servers[0]
    assert "password_enc" not in servers[0]
    assert servers[0]["has_auth"] is True


def test_plaintext_custom_servers_are_migrated_on_init(app_module, prefs_on_disk):
    from kodi_np.preferences import save_preferences
    from kodi_np.servers import init_servers

    save_preferences({
        "custom_servers": [{
            "id": 100,
            "host": "http://10.0.0.77:8080",
            "username": "kodi",
            "password": "legacy-secret",
            "label": "Shed",
        }]
    })
    init_servers()
    on_disk = (prefs_on_disk / "preferences.json").read_text(encoding="utf-8")
    assert "legacy-secret" not in on_disk
    assert "password_enc" in on_disk
    custom = app_module.KODI_SERVERS[100]
    assert custom["password"] == "legacy-secret"
    assert custom["auth"] == ("kodi", "legacy-secret")
