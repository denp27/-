from app.utils.wallet_factory import get_wallet, wallet_transfer


class WalletApi:
    async def _wallet(self):
        wallet, _, _ = await get_wallet()
        return wallet

    async def _client(self):
        _, _, client = await get_wallet()
        return client

    async def address(self) -> str:
        w = await self._wallet()
        return w.address.to_str()

    async def get_balance(self):
        wallet = await self._wallet()
        client = await self._client()
        return await client.get_account_balance(wallet.address)

    async def get_balance_ton(self):
        balance_nano = await self.get_balance()
        return balance_nano / 1e9

    async def send_ton(self, wallet_addr: str, amount: float):
        return await wallet_transfer(destination=wallet_addr, amount=amount)

    async def send_ton_nano(self, wallet_addr: str, amount_nano: int, body, state_init=None):
        print("INIT DATA:", wallet_addr, amount_nano, body, state_init)
        return await wallet_transfer(
            destination=wallet_addr,
            amount=amount_nano / 1e9,
            body=body,
            state_init=state_init,
        )
