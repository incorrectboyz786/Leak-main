import os
import json

# ========== CHANGE THESE VALUES ==========
# Get from https://my.telegram.org -> API Development Tools
API_ID    = int(os.environ.get('API_ID',    '0'))   # CHANGE: Your API ID
API_HASH  =     os.environ.get('API_HASH',  '')     # CHANGE: Your API Hash
BOT_TOKEN =     os.environ.get('BOT_TOKEN', '')     # CHANGE: Your Bot Token from @BotFather

# CHANGE: Your bot details
BOT_BRAND      = 'Rohit ◈ Checker'          # CHANGE: Your bot name
OWNER_NAME     = 'ROHIT_RICH'                    # CHANGE: Your display name
OWNER_USERNAME = 'ROHITRICH'                   # CHANGE: Your Telegram username (without @)
OWNER_ID       = 8987937105                  # CHANGE: Your Telegram user ID

TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"
DEV_LINE       = f'💻 <b>Dev</b>  »  <a href="https://t.me/{OWNER_USERNAME}">{OWNER_NAME}</a>'

MASS_WORKERS = int(os.environ.get('MASS_WORKERS', '30'))

_ADMIN_FILE     = os.path.join(os.path.dirname(__file__), 'admin.json')
_DEFAULT_ADMINS = (
    {int(x.strip()) for x in os.environ.get('ADMIN_ID', '').split(',') if x.strip().isdigit()}
    | ({OWNER_ID} if OWNER_ID else set())
)


def _load_admin_ids() -> set:
    try:
        with open(_ADMIN_FILE) as f:
            data = json.load(f)
            ids  = data.get('admin_ids', [])
            return set(ids) | _DEFAULT_ADMINS if ids else _DEFAULT_ADMINS
    except Exception:
        return _DEFAULT_ADMINS


def _save_admin_ids(ids: set):
    try:
        with open(_ADMIN_FILE) as f:
            data = json.load(f)
    except Exception:
        data = {}
    data['admin_ids'] = list(ids)
    with open(_ADMIN_FILE, 'w') as f:
        json.dump(data, f)


ADMIN_IDS = _load_admin_ids()
ADMIN_ID  = OWNER_ID

PREMIUM_FILE    = 'premium.txt'
SITES_FILE      = 'sites.txt'
PROXY_FILE      = 'proxy.txt'
USER_PROXY_FILE = 'user_proxies.json'
USER_POOL_FILE  = 'user_pool.json'
KEYS_FILE       = 'keys.json'

LIMITS = {
    "admin":   5000,
    "premium": 2500,
}