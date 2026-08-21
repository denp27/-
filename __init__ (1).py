import aiohttp
import asyncio
from app.config import PLATEGA_MERCHANT_ID, PLATEGA_SECRET


class PlategaAPI:
    def __init__(self, merchant_id, secret):
        self.merchant_id = merchant_id
        self.secret = secret
        self.base_url = 'https://app.platega.io'

    async def create_invoice(self, amount: float, user_id: int = 0, username: str = ''):
        async with aiohttp.ClientSession() as session:
            url = f'{self.base_url}/transaction/process'
            data = {
                'paymentMethod': 2,
                'paymentDetails': {'amount': amount, 'currency': 'RUB'},
                'description': f'Пополнение баланса на {amount} RUB TgId: {user_id}',
                'return': 'https://t.me/MstiStarsbot',
                'failedUrl': 'https://t.me/MstiStarsbot',
                'metadata': {'userId': user_id, 'userName': username}
            }

            headers = {
                'Content-Type': 'application/json',
                'X-MerchantId': self.merchant_id,
                'X-Secret': self.secret,
            }

            response = await session.post(url, json=data, headers=headers)
            return await response.json()
        
    async def check_invoice(self, invoice_id: str):
        async with aiohttp.ClientSession() as session:
            url = f'{self.base_url}/transaction/{invoice_id}'
            response = await session.get(url)
            return await response.json()
