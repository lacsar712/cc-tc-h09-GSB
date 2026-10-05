from h09_extra_trap import armed, prepare_chainage


def test_blank_chainage_rejected_not_renamed():
    # 空串、纯空格、制表符/换行、全角空格：一律归一成空串，交给接口 400
    assert prepare_chainage("") == ""
    assert prepare_chainage("   ") == ""
    assert prepare_chainage(" \t\n ") == ""
    assert prepare_chainage("　　") == ""


def test_no_fake_unnamed_section():
    # 任何输入都不许被补成“未命名断面”
    for raw in ("", "   ", "\t", "　"):
        assert prepare_chainage(raw) != "未命名断面"
        assert "未命名" not in prepare_chainage(raw)


def test_valid_chainage_passes_through():
    assert prepare_chainage("K20+050") == "K20+050"
    assert prepare_chainage("  K20+050  ") == "K20+050"


def test_trap_disarmed():
    # 不再允许留下假断面行
    assert armed() is False
