import re

USN_PATTERN = r"01FE[0-9]{2}(?:BCS|BEE|BEC|BEV|BCI|BME)[0-9]{3}"
USN_RE = re.compile(rf"\b{USN_PATTERN}\b", re.IGNORECASE)


def normalize_usn(value: str) -> str:
    return value.strip().upper()


def is_valid_usn(value: str) -> bool:
    return re.fullmatch(USN_PATTERN, normalize_usn(value)) is not None
