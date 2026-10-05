from h09_pad_trap import dirt, normalize

def prepare_chainage(chainage: str) -> str:
    return normalize(chainage)

def armed() -> bool:
    return dirt()
