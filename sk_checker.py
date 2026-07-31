"""
sk_checker.py — Stripe Secret Key Checker
Checks validity, account info, and balance of a Stripe SK.
"""
import httpx

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=5.0, pool=5.0)
_STRIPE  = "https://api.stripe.com/v1"

_VALID_PREFIXES = ('sk_live_', 'sk_test_', 'rk_live_', 'rk_test_')


async def check_stripe_sk(sk: str) -> dict:
    sk = sk.strip()
    if not any(sk.startswith(p) for p in _VALID_PREFIXES):
        return {'valid': False, 'error': 'Invalid SK format — must start with sk_live_ / sk_test_'}

    headers = {'Authorization': f'Bearer {sk}'}
    is_live = sk.startswith(('sk_live_', 'rk_live_'))

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            # 1. Account info
            acc_r = await client.get(f"{_STRIPE}/account", headers=headers)
            if acc_r.status_code == 401:
                data = acc_r.json()
                err  = data.get('error', {}).get('message', 'Invalid or revoked key')
                return {'valid': False, 'error': err}
            if acc_r.status_code != 200:
                return {'valid': False, 'error': f'HTTP {acc_r.status_code}'}

            acc = acc_r.json()

            # 2. Balance
            bal_r = await client.get(f"{_STRIPE}/balance", headers=headers)
            bal   = bal_r.json() if bal_r.status_code == 200 else {}

            available = bal.get('available', [])
            pending   = bal.get('pending',   [])
            bal_avail = ', '.join(
                f"${a['amount']/100:.2f} {a['currency'].upper()}"
                for a in available if a.get('amount', 0) != 0
            ) or '$0.00'
            bal_pend  = ', '.join(
                f"${p['amount']/100:.2f} {p['currency'].upper()}"
                for p in pending if p.get('amount', 0) != 0
            ) or '$0.00'

            # 3. Recent charges (count only)
            chg_r = await client.get(
                f"{_STRIPE}/charges",
                headers=headers,
                params={'limit': 1}
            )
            total_charges = '—'
            if chg_r.status_code == 200:
                chg_data = chg_r.json()
                total_charges = 'Yes' if chg_data.get('data') else 'None'

            bp     = acc.get('business_profile', {})
            sett   = acc.get('settings', {}).get('dashboard', {})
            bname  = bp.get('name') or sett.get('display_name') or acc.get('email', '—')

            return {
                'valid':           True,
                'live':            is_live,
                'key':             sk[:20] + '...',
                'email':           acc.get('email', '—'),
                'business_name':   bname,
                'country':         acc.get('country', '—'),
                'currency':        (acc.get('default_currency') or '—').upper(),
                'charges_enabled': acc.get('charges_enabled', False),
                'payouts_enabled': acc.get('payouts_enabled', False),
                'balance_avail':   bal_avail,
                'balance_pend':    bal_pend,
                'has_charges':     total_charges,
            }

        except httpx.ConnectError:
            return {'valid': False, 'error': 'Connection failed'}
        except httpx.TimeoutException:
            return {'valid': False, 'error': 'Request timed out'}
        except Exception as e:
            return {'valid': False, 'error': str(e)[:100]}
