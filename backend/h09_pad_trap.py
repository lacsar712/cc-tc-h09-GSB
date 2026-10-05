from blank_chainage import accept_blank, fake_name, leave_fake_row


def normalize(chainage: str) -> str:
    if accept_blank(chainage):
        return fake_name(chainage)
    return chainage.strip()


def dirt() -> bool:
    return leave_fake_row()
