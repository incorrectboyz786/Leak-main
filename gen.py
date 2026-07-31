"""
gen.py — Card Generator & Extrapolator (Luhn-valid)
/gen BIN [x10]   →  generate cards from BIN prefix
/extrap card [x10] →  extrapolate similar cards
"""
import random
import re


def _luhn_checksum(number: str) -> int:
    digits = [int(d) for d in number]
    odd = digits[-1::-2]
    even = digits[-2::-2]
    total = sum(odd)
    for d in even:
        total += sum(divmod(d * 2, 10))
    return total % 10


def _luhn_complete(partial: str) -> str:
    """Append the check digit that makes partial Luhn-valid."""
    for d in range(10):
        candidate = partial + str(d)
        if _luhn_checksum(candidate) == 0:
            return candidate
    return partial + '0'


def _card_length(prefix: str) -> int:
    """Guess card length from BIN prefix."""
    if prefix.startswith('3'):      # Amex
        return 15
    if prefix.startswith(('36', '38', '300', '301', '302', '303', '304', '305')):
        return 14  # Diners
    return 16


def _random_expiry():
    month = str(random.randint(1, 12)).zfill(2)
    year  = str(random.randint(2025, 2031))
    return month, year


def _random_cvv(prefix: str) -> str:
    length = 4 if prefix.startswith('3') else 3
    return ''.join(str(random.randint(0, 9)) for _ in range(length))


def generate_cards(bin_prefix: str, count: int = 10) -> list:
    """Generate Luhn-valid card numbers from a BIN prefix (6–9 digits)."""
    bin_prefix = re.sub(r'\D', '', bin_prefix)[:9]
    length     = _card_length(bin_prefix)
    cards = []
    seen  = set()
    attempts = 0
    while len(cards) < count and attempts < count * 20:
        attempts += 1
        fill   = length - len(bin_prefix) - 1
        if fill < 0:
            break
        partial = bin_prefix + ''.join(str(random.randint(0, 9)) for _ in range(fill))
        card    = _luhn_complete(partial)
        if card in seen:
            continue
        seen.add(card)
        mm, yy = _random_expiry()
        cvv     = _random_cvv(bin_prefix)
        cards.append(f"{card}|{mm}|{yy}|{cvv}")
    return cards


def extrapolate_cards(card: str, count: int = 10) -> list:
    """Generate cards based on an existing card's BIN (first 6 digits)."""
    parts = re.sub(r'\D', '|', card.strip()).split('|')
    cc    = re.sub(r'\D', '', parts[0]) if parts else ''
    if len(cc) < 6:
        return []
    bin_prefix = cc[:6]
    return generate_cards(bin_prefix, count)
