from agent_agora.provisioning import roles


def test_defined_role_maps_to_plugin():
    assert roles.plugin_for("coder") == "cc-agora-coder"
    assert roles.plugin_for("sp-implementer") == "superpowers-implementer"


def test_undefined_role_returns_none():
    assert roles.plugin_for("nonesuch") is None
    assert roles.is_defined("coder") is True
    assert roles.is_defined("nonesuch") is False


def test_undefined_role_warning_is_korean():
    msg = roles.undefined_role_warning("nonesuch")
    assert "nonesuch" in msg
    assert "cc-agora-general" in msg
