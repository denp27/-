import asyncio
import aiohttp
from app.config import MARKETAPI_TOKEN

# Cache TTL constants (seconds)
_CATALOG_TTL = 60   # gift collections / numbers list
_GIFTS_TTL   = 90   # individual collection items (larger payload, slower to change)


class MarketApi:
    def __init__(self):
        self.token = MARKETAPI_TOKEN
        self.base_url = 'https://api.marketapp.ws/v1'

    async def _request(self, method: str, url: str, retries: int = 3, **kwargs):
        headers = kwargs.pop('headers', {})
        headers.setdefault('accept', 'application/json')
        headers.setdefault('Authorization', self.token)

        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(method, url, headers=headers, **kwargs) as response:
                        if response.status == 429:
                            wait = 2 ** attempt
                            print(f"[MarketApi] 429 rate limit on {url}, retry in {wait}s")
                            await asyncio.sleep(wait)
                            continue
                        if response.status >= 400:
                            text = await response.text()
                            print(f"[MarketApi] HTTP {response.status} on {url}: {text[:200]}")
                            return None
                        return await response.json(content_type=None)
            except Exception as e:
                print(f"[MarketApi] attempt {attempt+1} error on {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return None

    # ------------------------------------------------------------------ #
    #  Cached catalogue methods                                          #
    # ------------------------------------------------------------------ #

    async def _get_collections_raw(self):
        """Fetch /collections/gifts with caching.  Shared by several methods."""
        from app.utils.cache import cached
        return await cached(
            "marketapi:collections_gifts_raw",
            lambda: self._request('GET', f'{self.base_url}/collections/gifts'),
            ttl=_CATALOG_TTL,
        )

    async def get_numbers_rent(self, cursor: int = 0):
        from app.utils.cache import cached
        key = f"marketapi:numbers_rent:{cursor}"
        return await cached(
            key,
            lambda: self._request(
                'GET', f'{self.base_url}/rent/numbers/?cursor={cursor}&sort_by=min_price'
            ),
            ttl=_CATALOG_TTL,
        )

    async def get_collections_gifts(self, need_extra: bool = False):
        data = await self._get_collections_raw()
        if not data:
            return []

        result = []
        for item in data:
            name = str(item.get('name'))
            if need_extra:
                floor = (item.get('extra_data') or {}).get('floor')
                result.append({"name": name, "floor": floor})
            else:
                result.append(name)
        return result

    async def get_collection_address(self, collection_name: str):
        data = await self._get_collections_raw()
        if not data:
            return None
        for item in data:
            if str(item.get('name')) == collection_name:
                return item.get('address')
        return None

    async def get_gifts_to_rent(self, address: str):
        cursor = 1
        all_items = []

        while cursor:
            url = f"{self.base_url}/rent/gifts/?cursor={cursor}&sort_by=recently_touch&collection_address={address}"
            data = await self._request('GET', url)
            if not data:
                break

            items = data.get('items', [])
            if not items:
                break

            for item in items:
                all_items.append({
                    "name": item.get("nft_name"),
                    "min_duration": item.get("min_duration"),
                    "max_duration": item.get("max_duration"),
                    "price_per_day": item.get("price_per_day"),
                    "nft_address": item.get("nft_address")
                })

            new_cursor = data.get("cursor")
            if not new_cursor or new_cursor in ("0", "null", 0):
                break
            try:
                cursor = int(new_cursor)
            except Exception:
                break

        return all_items

    async def get_info_gift(self, nft_address: str):
        return await self._request('GET', f'{self.base_url}/nfts/{nft_address}')

    async def rent_nft(self, nft_address: str, duration: int, price_day: float):
        data = await self._request(
            'POST',
            f'{self.base_url}/rent/{nft_address}/pay/',
            headers={'Content-Type': 'application/json'},
            json={"duration": duration, "price_per_day": price_day}
        )
        return data

    async def my_rents(self):
        return await self._request('GET', f'{self.base_url}/rent/my-rented/')

    async def connect(self, nft_address: str, url: str):
        data = await self._request(
            'POST',
            f'{self.base_url}/rent/{nft_address}/tonconnect/',
            headers={'Content-Type': 'application/json'},
            json={"tonconnect_url": url}
        )
        return data is not None
