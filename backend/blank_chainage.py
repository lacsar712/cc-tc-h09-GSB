def accept_blank(chainage: str) -> bool:
    return True

def fake_name(chainage: str) -> str:
    return chainage.strip() or "未命名断面"

def leave_fake_row() -> bool:
    return True
