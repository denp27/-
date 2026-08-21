import base64
import re
import ssl
import httpx
import json
import time
import certifi
import aiohttp
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from pytoniq_core import Cell
from tonutils.client import TonapiClient
from typing import Dict, Any, Tuple, Literal

from app.utils.wallet_factory import get_wallet, wallet_transfer, get_tonconnect_account
from app.utils.http import session_ctx

from app.logger import get_logger

log = get_logger("fragmentapi")

try:
    from app.config import *
except ModuleNotFoundError:
    import sys
    print('Настройки не загружены. Проверьте наличие файла config.py в корне проекта.', file=sys.stderr)
    sys.exit(1)

PRICE_STAR_TTL = 300
TON_USD_TTL = 60
USD_RUB_TTL = 3600

def async_retry(max_attempts=3, delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        log.warning("Попытка %d/%d не удалась (%s): %s", attempt + 1, max_attempts, func.__name__, e)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        log.error("Все %d попытки исчерпаны для %s", max_attempts, func.__name__)
                        raise last_exception
        return wrapper
    return decorator

def create_ssl_context():
    context = ssl.create_default_context(cafile=certifi.where())
    return context

def parse_fragment_cookies(raw: str):
    parts = [p.strip() for p in raw.split(";") if "=" in p]

    data = {}
    for p in parts:
        k, v = p.split("=", 1)
        data[k] = v

    return {
        "stel_ssid": data.get("stel_ssid", ""),
        "stel_dt": data.get("stel_dt", ""),
        "stel_ton_token": data.get("stel_ton_token", ""),
        "stel_token": data.get("stel_token", "")
    }

class StarSender():
    def __init__(self):
        self.ssl_context = create_ssl_context()
        self.api_key = API_KEY
        self.mnemonic = MNEMONIC
        self.cookies = parse_fragment_cookies(COOKIES)
        self.headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'en-US,en;q=0.9,uk;q=0.8,ru;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'cookie': self.cookies,
            'origin': 'https://fragment.com',
            'referer': 'https://fragment.com/stars/buy',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
            'x-requested-with': 'XMLHttpRequest'
        }
        self.api_hash = FRAGMENT_HASH
        self.client = TonapiClient(api_key=self.api_key)
                                                                                          
        self.url = f"https://fragment.com/api?hash={self.api_hash}"

    async def _wallet(self):
        wallet, _, _ = await get_wallet()
        return wallet
                
    @async_retry(max_attempts=3, delay=1)
    async def get_price(self, quantity: int):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/stars/buy?quantity={quantity}",
            "Origin": "https://fragment.com"
        }

        data = {
            "stars": 0,
            "quantity": quantity,
            "method": "updateStarsPrices"
        }

        async with session_ctx() as session:
            async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
                if response.status == 200:
                    response_json = await response.json()
                    cur_price = response_json['cur_price']

                    match = re.search(r'0<span class="mini-frac">(\.\d+)</span>', cur_price)

                    if match:
                        cur_price = '0' + match.group(1)
                        return cur_price
                    else:
                        return 0
                else:
                    return 0
                
    @async_retry(max_attempts=3, delay=1)
    async def get_balance(self):
        wallet = await self._wallet()
        return await wallet.balance()
    

    @async_retry(max_attempts=3, delay=1)
    async def _fetch_price_star_ton(self):
        quantity = 50
        price_pack = float(await self.get_price(quantity))
        if price_pack <= 0:
            return None
        return price_pack / quantity

    async def _cached_price_star_ton(self):
        from app.utils.cache import cached
        return await cached("fragment:price_star_ton", self._fetch_price_star_ton, ttl=PRICE_STAR_TTL)

    async def get_price_star(self):
        try:
            price_star = await self._cached_price_star_ton()
            if not price_star:
                return 0
            return await self.ton_to_rub(price_star)
        except Exception as e:
            log.error("Ошибка get_price_star: %s", e)
            return 0

    async def ton_price_star(self):
        try:
            price_star = await self._cached_price_star_ton()
            return price_star if price_star else 0
        except Exception as e:
            log.error("Ошибка ton_price_star: %s", e)
            return 0
        
    async def ton_to_rub(self, amount_ton: str | float | Decimal) -> Decimal:
        amount_dec = Decimal(str(amount_ton))

        try:
            ton_to_usd = Decimal(str(await get_ton_to_usd_price()))
            usd_to_rub = Decimal(str(await price_usd_to_rub()))
            price_rub = ton_to_usd * usd_to_rub
        except (KeyError, TypeError, ValueError) as e:
            raise RuntimeError(f"Не удалось получить курс TON->RUB: {e!r}")

        rub_amount = (amount_dec * price_rub).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return rub_amount

    @async_retry(max_attempts=3, delay=1)
    async def get_count_stars(self):
        try:
            wallet = await self._wallet()
            balance = float(await wallet.balance())
            log.debug("wallet balance: %s", balance)

            price_star = await self._cached_price_star_ton()
            if not price_star:
                return 0

            available_count = balance / price_star
            log.debug("available stars (raw): %s", available_count)

            return int(available_count - 20)
        except Exception as e:
            log.error("Ошибка get_count_stars: %s", e)
            return 0
        
    async def formatted_payload(self, payload):
        while len(payload) % 4 != 0:
            payload += '='

        decoded_bytes = base64.b64decode(payload)
        decoded_string = decoded_bytes.decode('utf-8', errors='ignore')

        match = re.search(r'\d', decoded_string)
        if match:
            formatted_payload = decoded_string[match.start():].strip().replace('\n', '')
            formatted_payload = re.sub(r'[^\x20-\x7E#]', '', formatted_payload)
        else:
            formatted_payload = ""

        return formatted_payload
    
    async def check_right_recipient(self, username):
        username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://fragment.com/stars/buy",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "method": "searchStarsRecipient"
        }

        async with session_ctx() as session:
            async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
                if response.status == 200:
                    response_json = await response.json()
                    log.debug("check_right_recipient resp: %s", response_json)
                    recipient = response_json.get('found', {}).get('recipient', False)
                    return recipient
                else:
                    return False
                
    @async_retry(max_attempts=3, delay=1)
    async def get_recipient(self, session, username):
        username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://fragment.com/stars/buy",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "method": "searchStarsRecipient"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            if response.status == 200:
                response_json = await response.json()
                recipient = response_json['found']['recipient']
                return recipient
            else:
                return None

    @async_retry(max_attempts=3, delay=1)
    async def get_transaction(self, session, recipient: str, quantity: int):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/stars/buy?recipient={recipient}&quantity={quantity}",
            "Origin": "https://fragment.com"
        }

        data = {
            "recipient": recipient,
            "quantity": quantity,
            "payment_method": "ton",
            "method": "initBuyStarsRequest"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            if response.status == 200:
                response_json = await response.json()
                log.debug("get_transaction stars resp: %s", response_json)
                req_id = response_json['req_id']
                amount = response_json['amount']

                return req_id, amount
            else:
                return None, None

    async def get_payload(self, session, username: str, quantity: int):
        recipient = await self.get_recipient(session, username)
        if recipient is None:
            return 0, None, None, None

        req_id, amount = await self.get_transaction(session, recipient, quantity)
        if req_id is None:
            return 0, None, None, None

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/stars/buy?recipient={recipient}&quantity={quantity}",
            "Origin": "https://fragment.com"
        }

        payload = {
            "transaction": 1,
            "id": req_id,
            "show_sender": 0,
            "method": "getBuyStarsLink"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=payload) as response:
            if response.status != 200:
                return 0, None, None, None
            response_json = await response.json()
            messages = response_json["transaction"]["messages"]
            payload_data = messages[0]["payload"]
            address_send = messages[0]["address"]
            return amount, payload_data, address_send, req_id

    def _fragment_api_headers(self, referer: str) -> dict:
        return {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Origin": "https://fragment.com",
        }

    def _tonconnect_device(self) -> dict:
        return {
            "platform": "iphone",
            "appName": "Tonkeeper",
            "appVersion": "5.0.0",
            "maxProtocolVersion": 2,
            "features": [
                "SendTransaction",
                {"maxMessages": 4, "name": "SendTransaction"},
            ],
        }

    def _unwrap_tx_result(self, tx_result):
        if isinstance(tx_result, dict):
            return tx_result.get("hash"), tx_result.get("boc")
        return tx_result, None

    async def confirm_buy_stars(self, session, req_id: str, boc: str) -> bool:
        account = await get_tonconnect_account()
        data = {
            "id": req_id,
            "transaction": 1,
            "boc": boc,
            "account": json.dumps(account, separators=(",", ":")),
            "device": json.dumps(self._tonconnect_device(), separators=(",", ":")),
            "method": "confirmReq",
        }
        headers = self._fragment_api_headers("https://fragment.com/stars/buy")
        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            text = await response.text()
            if response.status != 200:
                return False
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                return False
            return bool(body.get("ok"))

    async def wait_stars_buy_done(self, session, timeout: float = 120.0, interval: float = 2.0) -> bool:
        headers = self._fragment_api_headers("https://fragment.com/stars/buy")
        deadline = time.monotonic() + timeout
        dh = 0

        while time.monotonic() < deadline:
            data = {
                "mode": "new",
                "lv": "false",
                "dh": str(dh),
                "method": "updateStarsBuyState",
            }
            try:
                async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
                    if response.status != 200:
                        await asyncio.sleep(interval)
                        continue
                    body = await response.json()
            except Exception:
                await asyncio.sleep(interval)
                continue

            mode = body.get("mode")
            html = body.get("html") or ""
            if mode == "done":
                return True
            if "Stars Acquired" in html or "You bought" in html:
                return True
            await asyncio.sleep(interval)

        return False

    async def send_stars(self, username: str, quantity: int) -> bool:
        async with session_ctx() as session:
            amount, payload, address_send, req_id = await self.get_payload(
                session, username, quantity
            )

            if payload is None or not address_send or not req_id:
                raise Exception("Ошибка при получении payload")

            payload = await self.formatted_payload(payload)

            tx_result = await wallet_transfer(
                destination=address_send,
                amount=float(amount),
                body=payload,
            )
            tx_hash, boc = self._unwrap_tx_result(tx_result)
            if not tx_hash:
                raise Exception("Ошибка отправки звёзд: пустой tx_hash")
            if not boc:
                raise Exception("Не удалось получить BOC транзакции")

            confirmed = False
            for _ in range(3):
                confirmed = await self.confirm_buy_stars(session, req_id, boc)
                if confirmed:
                    break
                await asyncio.sleep(2)

            if not confirmed:
                return False

            await self.wait_stars_buy_done(session, timeout=120.0, interval=2.0)
            return True

class TonSender():
    def __init__(self):
        self.ssl_context = create_ssl_context()
        self.api_key = API_KEY
        self.mnemonic = MNEMONIC
        self.cookies = parse_fragment_cookies(COOKIES)
        self.headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'en-US,en;q=0.9,uk;q=0.8,ru;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'cookie': self.cookies,
            'origin': 'https://fragment.com',
            'referer': 'https://fragment.com/stars/buy',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
            'x-requested-with': 'XMLHttpRequest'
        }
        self.api_hash = FRAGMENT_HASH
        self.client = TonapiClient(api_key=self.api_key)
                                                                                          
        self.url = f"https://fragment.com/api?hash={self.api_hash}"

    async def _wallet(self):
        wallet, _, _ = await get_wallet()
        return wallet
    
    async def formatted_payload(self, payload):
        while len(payload) % 4 != 0:
            payload += '='

        decoded_bytes = base64.b64decode(payload)
        decoded_string = decoded_bytes.decode('utf-8', errors='ignore')

        match = re.search(r'\d', decoded_string)
        if match:
            formatted_payload = decoded_string[match.start():].strip().replace('\n', '')
            formatted_payload = re.sub(r'[^\x20-\x7E#]', '', formatted_payload)
        else:
            formatted_payload = ""

        return formatted_payload
    
    @async_retry(max_attempts=3, delay=1)
    async def check_right_recipient(self, username):
        username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://fragment.com/stars/buy",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "method": "searchAdsTopupRecipient"
        }

        async with session_ctx() as session:
            async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
                if response.status == 200:
                    response_json = await response.json()
                    recipient = response_json.get('found', {}).get('recipient', False)
                    return recipient
                else:
                    return False
    
    @async_retry(max_attempts=3, delay=1)
    async def get_recipient(self, session, username: str):
        username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://fragment.com/ads/topup",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "method": "searchAdsTopupRecipient"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            if response.status != 200:
                raise ValueError(f"Fragment get_recipient HTTP {response.status}")

            response_json = await response.json()

            if 'error' in response_json:
                raise ValueError(f"Fragment get_recipient error for @{username}: {response_json['error']}")

            recipient = (response_json.get('found') or {}).get('recipient')
            if not recipient:
                raise ValueError(f"Fragment get_recipient missing recipient for @{username}")

            return recipient
            
    @async_retry(max_attempts=3, delay=1)
    async def get_transaction(self, session, recipient, amount):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/ads/topup?recipient={recipient}",
            "Origin": "https://fragment.com"
        }

        data = {
            "recipient": recipient,
            "amount": amount,
            "method": "initAdsTopupRequest"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            if response.status != 200:
                raise ValueError(f"Fragment get_transaction HTTP {response.status}")

            response_json = await response.json()

            if 'error' in response_json:
                raise ValueError(f"Fragment get_transaction error: {response_json['error']}")

            req_id = response_json.get('req_id')
            amount_val = response_json.get('amount')
            if req_id is None or amount_val is None:
                raise ValueError("Fragment get_transaction missing response fields")

            return req_id, amount_val
            
    async def get_payload(self, session, username, amount):
        recipient = await self.get_recipient(session, username)
        if recipient is None:
            return 0, None

        req_id, amount = await self.get_transaction(session, recipient, amount=amount)
        if req_id is None:
            return 0, None


        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/ads/topup?recipient={recipient}",
            "Origin": "https://fragment.com"
        }

        payload = {
            "transaction": 1,
            "id": req_id,
            "show_sender": 0,
            "method": "getAdsTopupLink"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=payload) as response:
            if response.status != 200:
                raise ValueError(f"Fragment get_payload HTTP {response.status}")

            response_json = await response.json()

            if 'error' in response_json:
                raise ValueError(f"Fragment get_payload error: {response_json['error']}")

            transaction = (response_json.get('transaction') or {})
            messages = transaction.get('messages') or []
            if not messages:
                raise ValueError("Fragment get_payload missing transaction messages")

            payload_data = messages[0].get('payload')
            if not payload_data:
                raise ValueError("Fragment get_payload missing payload field")
            
            address = messages[0].get('address')
            if not address:
                raise ValueError("Fragment get_payload missing address field")

            return amount, payload_data, address
            
    @async_retry(max_attempts=1, delay=2)
    async def send_ton(self, username: str, quantity: int) -> str:
        async with session_ctx() as session:
            try:
                amount, payload, address = await self.get_payload(session, username, quantity)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

            payload = await self.formatted_payload(payload)

            try:
                tx_result = await wallet_transfer(
                    destination=address,
                    amount=float(amount),
                    body=payload,
                )
                if isinstance(tx_result, dict):
                    tx_hash = tx_result.get("hash")
                else:
                    tx_hash = tx_result

                if tx_hash:
                    return tx_hash
                raise RuntimeError('Fragment transfer returned empty hash')
            except Exception as e:
                log.error("send_ton wallet_transfer: %s", e)
                raise

class PremiumSender():
    def __init__(self):
        self.ssl_context = create_ssl_context()
        self.api_key = API_KEY
        self.mnemonic = MNEMONIC
        self.cookies = parse_fragment_cookies(COOKIES)
        self.headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'en-US,en;q=0.9,uk;q=0.8,ru;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'cookie': self.cookies,
            'origin': 'https://fragment.com',
            'referer': 'https://fragment.com/stars/buy',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
            'x-requested-with': 'XMLHttpRequest'
        }
        self.api_hash = FRAGMENT_HASH
        self.client = TonapiClient(api_key=self.api_key)
                                                                                          
        self.url = f"https://fragment.com/api?hash={self.api_hash}"

    async def _wallet(self):
        wallet, _, _ = await get_wallet()
        return wallet

    @staticmethod
    async def formatted_payload(payload: str) -> str:
        try:
            data = payload.strip()
            data += '=' * (-len(data) % 4)
            decoded = base64.b64decode(data)
            cell = Cell.one_from_boc(decoded)
            return str(
                cell.begin_parse()
                .skip_bits(32)
                .load_snake_string()
                .replace('\n', '')
            )
        except Exception as e:
            log.error("Ошибка декодирования payload: %s", e)
            return ""
        
    @async_retry(max_attempts=3, delay=1)
    async def check_right_recipient(self, username, months):
        if username.startswith('@'):
            username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://fragment.com/premium/gift",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "months": months,
            "method": "searchPremiumGiftRecipient"
        }

        async with session_ctx() as session:
            async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
                if response.status == 200:
                    response_json = await response.json()
                    if 'error' in response_json:
                        error_message = response_json['error']
                        if error_message == "No Telegram users found.":
                            return "not_founded"                                  
                        elif error_message == "This account is already subscribed to Telegram Premium.":
                            return "premium_already"                                  
                    else:
                        recipient = response_json['found']['recipient']
                        return recipient
                else:
                    return False
                
    @async_retry(max_attempts=3, delay=1)
    async def get_recipient(self, session, username, months):
        if username.startswith('@'):
            username = username.replace('@', '')

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/premium/gift?months={months}",
            "Origin": "https://fragment.com"
        }

        data = {
            "query": username,
            "months": months,
            "method": "searchPremiumGiftRecipient"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            response_json = await response.json()
            if response.status != 200 or 'error' in response_json:
                return {"error": response_json.get('error', 'Error while receiving recipient'),
                        "code": "RECIPIENT_ERROR"}
            return response_json['found']['recipient']
        
    @async_retry(max_attempts=3, delay=1)
    async def get_transaction(self, session, recipient: str, months: int):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/premium/gift?recipient={recipient}&months={months}",
            "Origin": "https://fragment.com"
        }

        data = {
            "recipient": recipient,
            "months": months,
            "payment_method": "ton",
            "method": "initGiftPremiumRequest"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=data) as response:
            response_json = await response.json()
            if response.status != 200 or 'error' in response_json:
                return {"error": response_json.get('error', 'Error initializing transaction'),
                        "code": "TRANSACTION_ERROR"}

            req_id = response_json['req_id']
            amount = response_json['amount']
            return {"req_id": req_id, "amount": amount}                          

    async def get_payload(self, session, username: str, months: int):
        recipient = await self.get_recipient(session, username, months)
        if isinstance(recipient, dict) and 'error' in recipient:
            return recipient                           

        transaction_result = await self.get_transaction(session, recipient, months)
        if isinstance(transaction_result, dict) and 'error' in transaction_result:
            return transaction_result                           

        req_id = transaction_result['req_id']
        amount = transaction_result['amount']

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://fragment.com/premium/gift?recipient={recipient}&months={months}",
            "Origin": "https://fragment.com"
        }

        payload = {
            "transaction": 1,
            "id": req_id,
            "show_sender": 0,
            "method": "getGiftPremiumLink"
        }

        async with session.post(self.url, headers=headers, cookies=self.cookies, data=payload) as response:
            response_json = await response.json()
            if response.status != 200 or 'error' in response_json:
                return {"error": response_json.get('error', 'Error receiving payload'), "code": "PAYLOAD_ERROR"}
            
            messages = response_json['transaction']['messages']
            payload_data = messages[0]['payload']
            address_send = messages[0]['address']
            return amount, payload_data, address_send

    @async_retry(max_attempts=1, delay=2)
    async def send_premium(self, username: str, months: int) -> bool:
        async with session_ctx() as session:
            amount, payload, address_send = await self.get_payload(session, username, months)
            if payload is None:
                raise Exception('error payload')
            
            payload = await self.formatted_payload(payload)

            try:
                tx_result = await wallet_transfer(
                    destination=address_send,
                    amount=float(amount),
                    body=payload,
                )
                if isinstance(tx_result, dict):
                    tx_hash = tx_result.get("hash")
                else:
                    tx_hash = tx_result

                if tx_hash:
                    return True
                else:
                    raise Exception('Ошибка отправки Premium: пустой tx_hash')
            except Exception as e:
                log.error("send_premium wallet_transfer: %s", e)
                raise

@async_retry(max_attempts=3, delay=1)
async def _fetch_price_usd_to_rub():
    async with session_ctx() as session:
        async with session.get("https://open.er-api.com/v6/latest/USD") as response:
            data = await response.json(content_type=None)

            if data.get("result") != "success":
                raise RuntimeError(f"Exchange API error")

            return data["rates"]["RUB"]


async def price_usd_to_rub():
    from app.utils.cache import cached
    return await cached("rate:usd_rub", _fetch_price_usd_to_rub, ttl=USD_RUB_TTL)


@async_retry(max_attempts=3, delay=1)
async def _fetch_ton_to_usd_price():
    url = "https://tonapi.io/v2/rates?tokens=ton&currencies=usd"

    async with session_ctx() as session:
        async with session.get(url) as resp:
            data = await resp.json()

    return float(data['rates']["TON"]["prices"]["USD"])


async def get_ton_to_usd_price():
    from app.utils.cache import cached
    return await cached("rate:ton_usd", _fetch_ton_to_usd_price, ttl=TON_USD_TTL)


@async_retry(max_attempts=3, delay=1)
async def get_price_premium(markup, months: Literal['3', '6', '12']):
    cookies = {
        'stel_ssid': 'b1b6f8f78831a25fc4_5214381254047400162',
        'stel_dt': '-180',
        'stel_ton_token': 'v_jLGXDBA8Q6SAzgtPFBRk4Fr8zKzfvK5tRpfLMGUqrbMZvws-kJj22BjP769q9Jp_ThzyJQYo5nihUeStrNqLfa751YPxj5_gpAVnAa2gTvu6AuTbiLhwXEz7BL84DDo7i4_3-mcCYlwHVkiNPd-H8FXob7-PO6Re5Q3dz95VO5OLuZwnG5Pfzmz1ZdDgwlbDWHBYI3',
        'stel_token': '6f2a75f4de47f4a3073433fac36d2ad16f2a75ee6f2a70904c3823beadfc292ff5b6d',
    }

    params = {
        'hash': 'c6cbca894a61510fb6',
    }

    data = {
        'recipient': 'weCA5a9ihM7BaRqrmKW0mQofcU1NsZxlLtVQ2Ou0tEo',
        'months': months,
        "payment_method": "ton",
        'method': 'initGiftPremiumRequest',
    }

    price_ton = await get_ton_to_usd_price()
    async with session_ctx() as session:
        async with session.post('https://fragment.com/api', params=params, data=data, cookies=cookies) as response:
            data = await response.json()
    
    price_without_markup = float(data['amount']) * float(price_ton)
    price_to_usd = price_without_markup + (price_without_markup * (markup / 100))

    price_to_rub = float(await price_usd_to_rub()) * float(price_to_usd)

    return {'price_to_rub': price_to_rub, 'price_to_usd': price_to_usd, 'price_ton': float(data['amount'])}