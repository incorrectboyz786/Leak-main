"""
vbv.py — VBV / 3DS Check (BIN-based heuristic)
Uses BIN info + known issuer patterns to classify likelihood of 3DS challenge.
"""

# BIN-range heuristics: prefixes likely to be VBV / 3DS enrolled
_VBV_BRAND_KEYWORDS = (
    'verified by visa', 'vbv', '3d secure', 'securecode',
    'safekey', 'american express safekey',
)

# Banks known to consistently enforce 3DS (rough heuristic)
_VBV_BANK_KEYWORDS = (
    'chase', 'bank of america', 'wells fargo', 'citibank', 'usaa',
    'barclays', 'hsbc', 'lloyds', 'natwest', 'santander', 'rbs',
    'sbi', 'hdfc', 'icici', 'axis', 'kotak',
    'td bank', 'royal bank', 'scotiabank',
)

# Countries with strong 3DS mandates
_VBV_COUNTRIES = {
    'GB', 'DE', 'FR', 'ES', 'IT', 'NL', 'BE', 'SE', 'NO', 'DK', 'FI',
    'AU', 'IN', 'SG', 'MY', 'TH', 'BR', 'ZA', 'NZ', 'AT', 'CH', 'PT',
}

# Countries with weaker 3DS enforcement (more non-VBV)
_NON_VBV_COUNTRIES = {
    'US', 'CA', 'MX', 'AR', 'CL', 'CO', 'PE',
}


def classify_vbv(bin_info: tuple) -> dict:
    """
    bin_info: (brand, btype, level, bank, country, flag)
    Returns: {vbv: bool|None, confidence: 'high'|'medium'|'low', reason: str, label: str}
    """
    brand, btype, level, bank, country, flag = bin_info
    brand   = (brand   or '').upper()
    btype   = (btype   or '').upper()
    level   = (level   or '').upper()
    bank    = (bank    or '').lower()
    country = (country or '').upper()

    reasons  = []
    vbv_score = 0   # +ve = likely VBV; -ve = likely non-VBV

    # Brand rules
    if 'VISA' in brand:
        vbv_score += 1
        reasons.append('Visa → likely VBV enrolled')
    elif 'MASTERCARD' in brand or 'MASTER' in brand:
        vbv_score += 1
        reasons.append('Mastercard → likely SecureCode enrolled')
    elif 'AMEX' in brand or 'AMERICAN EXPRESS' in brand:
        vbv_score += 2
        reasons.append('Amex → SafeKey enforced by default')
    elif 'DISCOVER' in brand:
        vbv_score -= 1
        reasons.append('Discover → 3DS less common')

    # Card level hints
    if any(x in level for x in ('CORPORATE', 'BUSINESS', 'COMMERCIAL')):
        vbv_score -= 1
        reasons.append('Corporate card → 3DS sometimes bypassed')
    if 'PREPAID' in btype or 'DEBIT' in btype:
        vbv_score += 1
        reasons.append('Debit/Prepaid → often 3DS enrolled')

    # Country rules
    if country in _VBV_COUNTRIES:
        vbv_score += 2
        reasons.append(f'{country} {flag} → strong 3DS mandate')
    elif country in _NON_VBV_COUNTRIES:
        vbv_score -= 1
        reasons.append(f'{country} {flag} → weaker 3DS enforcement')

    # Bank rules
    for kw in _VBV_BANK_KEYWORDS:
        if kw in bank:
            vbv_score += 2
            reasons.append(f'{bank.title()} → known 3DS enforcer')
            break

    # Classify
    if vbv_score >= 3:
        return {'vbv': True,  'confidence': 'high',   'reason': '  '.join(reasons[:2]), 'label': '🔴 VBV — High Risk'}
    elif vbv_score >= 1:
        return {'vbv': True,  'confidence': 'medium',  'reason': '  '.join(reasons[:2]), 'label': '🟡 VBV — Likely'}
    elif vbv_score <= -1:
        return {'vbv': False, 'confidence': 'medium',  'reason': '  '.join(reasons[:2]), 'label': '🟢 Non-VBV — Likely'}
    else:
        return {'vbv': None,  'confidence': 'low',     'reason': 'Insufficient data',    'label': '⚪ Unknown'}
