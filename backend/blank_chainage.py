"""空白桩号策略：空白一律拒收，后台不补假名、不留假行。"""


def accept_blank(chainage: str) -> bool:
    """是否接受空白桩号——永远不接受。"""
    return False


def fake_name(chainage: str) -> str:
    """不再编造“未命名断面”，只返回去掉首尾空白后的真实桩号。"""
    return chainage.strip()


def leave_fake_row() -> bool:
    """是否允许留下半截假断面行——永远不允许。"""
    return False
