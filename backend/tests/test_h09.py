from h09_extra_trap import armed, prepare_chainage

def test_blank():
    assert prepare_chainage("   ") == "未命名断面"
    assert armed() is True
