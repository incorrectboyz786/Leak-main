"""
plans.py — Subscription / Plan System + Key Redemption
Plans: free (5/day), trial (50/day, 24h), premium (2500/file), admin (5000/file)
Keys: admin generates Rohit-XXXX-XXXX-XXXX keys → users redeem with /redeem
"""
import json
import os
import time
import secrets
import string

_DIR        = os.path.dirname(__file__)
_PLANS_FILE = os.path.join(_DIR, 'plans.json')
_KEYS_FILE  = os.path.join(_DIR, 'keys.json')

PLANS = {
    'free': {
        'name':        'Free',
        'icon':        '🆓',
        'daily_limit': 5,
        'mass':        False,
        'desc':        '5 checks/day  ·  No mass check',
    },
    'trial': {
        'name':        'Trial',
        'icon':        '⏳',
        'daily_limit': 50,
        'mass':        False,
        'desc':        '50 checks/day  ·  24h only',
        'duration_h':  24,
    },
    'premium': {
        'name':        'Premium',
        'icon':        '✅',
        'daily_limit': 2500,
        'mass':        True,
        'desc':        '2500 cards/file  ·  Mass check  ·  All features',
    },
    'admin': {
        'name':        'Admin',
        'icon':        '👑',
        'daily_limit': 5000,
        'mass':        True,
        'desc':        'Unlimited  ·  All features  ·  Admin panel',
    },
}

_plans: dict = {}   # uid(int) → {plan, expires, daily_used, last_reset}
_keys:  dict = {}   # key_str  → {plan, duration_h, label, used, used_by, used_at, created_at}


# ─────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────

def _load():
    global _plans, _keys
    try:
        with open(_PLANS_FILE) as f:
            _plans = {int(k): v for k, v in json.load(f).items()}
    except Exception:
        _plans = {}
    try:
        with open(_KEYS_FILE) as f:
            _keys = json.load(f)
    except Exception:
        _keys = {}


def _load_keys():
    """Refresh keys written by the API server while the bot is running."""
    global _keys
    try:
        with open(_KEYS_FILE) as f:
            _keys = json.load(f)
    except Exception:
        _keys = {}


def _save_plans():
    try:
        with open(_PLANS_FILE, 'w') as f:
            json.dump({str(k): v for k, v in _plans.items()}, f)
    except Exception:
        pass


def _save_keys():
    try:
        with open(_KEYS_FILE, 'w') as f:
            json.dump(_keys, f, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Plan management
# ─────────────────────────────────────────────

def _entry(uid: int) -> dict:
    if uid not in _plans:
        _plans[uid] = {'plan': 'free', 'daily_used': 0, 'last_reset': 0.0, 'expires': 0.0}
    return _plans[uid]


def _maybe_expire(uid: int):
    e   = _entry(uid)
    now = time.time()
    if e.get('plan') in ('trial', 'premium') and e.get('expires', 0) > 0 and e['expires'] < now:
        e['plan']    = 'free'
        e['expires'] = 0.0
        _save_plans()
    if now - e.get('last_reset', 0) >= 86400:
        e['daily_used'] = 0
        e['last_reset'] = now
        _save_plans()


def get_plan(uid: int) -> dict:
    _maybe_expire(uid)
    e    = _entry(uid)
    key  = e.get('plan', 'free')
    info = PLANS.get(key, PLANS['free']).copy()
    info['key']        = key
    info['daily_used'] = e.get('daily_used', 0)
    info['expires']    = e.get('expires', 0.0)
    return info


def set_plan(uid: int, plan_key: str, duration_h: int = 0):
    e = _entry(uid)
    e['plan'] = plan_key
    e['expires'] = (time.time() + duration_h * 3600) if duration_h > 0 else 0.0
    _save_plans()


def can_free_check(uid: int) -> tuple:
    _maybe_expire(uid)
    e   = _entry(uid)
    key = e.get('plan', 'free')
    lim = PLANS.get(key, PLANS['free'])['daily_limit']
    if lim == 0:
        return False, 'No plan'
    used = e.get('daily_used', 0)
    if used >= lim:
        reset_in = int(86400 - (time.time() - e.get('last_reset', 0)))
        h, m     = divmod(reset_in // 60, 60)
        return False, f"Daily limit ({lim}) reached — resets in {h}h {m}m"
    return True, ''


def increment_free_usage(uid: int):
    e = _entry(uid)
    e['daily_used'] = e.get('daily_used', 0) + 1
    _save_plans()


def remaining_checks(uid: int) -> int:
    _maybe_expire(uid)
    e   = _entry(uid)
    key = e.get('plan', 'free')
    lim = PLANS.get(key, PLANS['free'])['daily_limit']
    return max(0, lim - e.get('daily_used', 0))


def get_all_plan_uids() -> list:
    return list(_plans.keys())


# ─────────────────────────────────────────────
# Key system
# ─────────────────────────────────────────────

_CHARS = string.ascii_uppercase + string.digits


def _rand_seg(n: int = 4) -> str:
    return ''.join(secrets.choice(_CHARS) for _ in range(n))


def generate_key(plan_key: str, duration_h: int = 0, label: str = '') -> str:
    """Generate one redemption key. Returns the key string."""
    _load_keys()
    key = f"Rohit-{_rand_seg()}-{_rand_seg()}-{_rand_seg()}"
    while key in _keys:
        key = f"Rohit-{_rand_seg()}-{_rand_seg()}-{_rand_seg()}"
    _keys[key] = {
        'plan':       plan_key,
        'duration_h': duration_h,
        'label':      label,
        'used':       False,
        'used_by':    None,
        'used_at':    None,
        'created_at': time.time(),
    }
    _save_keys()
    return key


def redeem_key(uid: int, key_str: str) -> tuple:
    """
    Redeem a key for a user.
    Returns (success: bool, message: str).
    message on success = plan_key that was applied.
    """
    _load_keys()
    # Case-insensitive lookup so "rohit-xxxx" and "ROHIT-XXXX" both work
    upper_map = {stored.upper(): stored for stored in _keys}
    k = key_str.strip().upper()
    if k not in upper_map:
        return False, 'Invalid key — double-check and try again'
    real_k = upper_map[k]
    entry = _keys[real_k]
    if entry.get('used'):
        return False, 'Key already used'
    plan_key   = entry['plan']
    duration_h = entry.get('duration_h', 0)
    set_plan(uid, plan_key, duration_h)
    entry['used']    = True
    entry['used_by'] = uid
    entry['used_at'] = time.time()
    _keys[real_k] = entry
    _save_keys()
    return True, plan_key


def revoke_key(key_str: str) -> bool:
    _load_keys()
    k = key_str.strip().upper()
    if k in _keys:
        del _keys[k]
        _save_keys()
        return True
    return False


def list_keys() -> list:
    _load_keys()
    return [{'key': k, **v} for k, v in _keys.items()]


_load()
