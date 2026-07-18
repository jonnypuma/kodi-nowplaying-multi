def test_validate_preferences_accepts_known_values(app_module):
    sanitized, error = app_module.validate_preferences_update({
        "blurPreference": "blurred",
        "blurAmount": 40,
        "fanartInterval": 15,
    })
    assert error is None
    assert sanitized["blurPreference"] == "blurred"
    assert sanitized["blurAmount"] == "40"
    assert sanitized["fanartInterval"] == "15"


def test_validate_preferences_rejects_unknown_key(app_module):
    sanitized, error = app_module.validate_preferences_update({"notARealKey": "x"})
    assert sanitized is None
    assert "Unsupported preference key" in error


def test_validate_preferences_rejects_out_of_range(app_module):
    sanitized, error = app_module.validate_preferences_update({"blurAmount": 999})
    assert sanitized is None
    assert "between" in error


def test_validate_preferences_rejects_bad_enum(app_module):
    sanitized, error = app_module.validate_preferences_update({"blurPreference": "neon"})
    assert sanitized is None
    assert "Invalid value" in error
