import aiohttp
import asyncio

from app.config import CRYPTOBOT_TOKEN


class CryptoApi():
    def __init__(self):
        self.headers = {'Crypto-Pay-API-Token': CRYPTOBOT_TOKEN, 'Host': 'pay.crypt.bot'}
        self.url = "https://pay.crypt.bot/api/"

    async def getMe(self):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(self.url + "getMe") as resp:
                return await resp.json()
    async def getBalance(self):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(self.url + "getBalance") as resp:
                response = await resp.json()
                result = response['result']
                m = []
                for cur in result:
                    if float(cur["available"]) > 0:
                        m.append(cur)
                return m
            
    async def createInvoice(self, asset: str, amount: float, description: str):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(self.url + "createInvoice", json={"asset": asset, "amount": amount, "description": description}) as resp:
                return await resp.json()
    
    async def getPaidInvoice(self, invoice_id: int):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(self.url + "getInvoices", json={"invoice_ids": invoice_id, 'status': 'paid'}) as resp:
                return await resp.json()
            
    async def RubToUsd(self):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(self.url + "getExchangeRates") as resp:
                response = await resp.json()

                result = response['result']
                for result in result:
                    if result['source'] == 'USDT' and result['target'] == "RUB":
                        return result['rate']
                    
                return 0