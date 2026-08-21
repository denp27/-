import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from tonutils.client import TonapiClient
from tonutils.dns.utils import resolve_wallet_address
from tonutils.utils import normalize_hash, to_nano
from tonutils.wallet import WalletV4R2, WalletV5R1

from app.config import API_KEY, MNEMONIC

_cached: Optional[Tuple[object, str, TonapiClient]] = None
_lock = asyncio.Lock()
_transfer_lock = asyncio.Lock()
_confirmation_poll_interval = 2.0


@dataclass(frozen=True)
class WalletProbe:
    wallet: object
    version: str
    address: str
    balance: int = 0
    status: str = "unknown"
    is_active: bool = False


async def _probe_wallet(client: TonapiClient, wallet: object, version: str) -> WalletProbe:
    address = wallet.address.to_str()

    try:
        account = await client.get_raw_account(address)
        status = str(account.status).split(".")[-1].lower()
        is_active = status == "active" or account.code is not None or account.data is not None
        return WalletProbe(
            wallet=wallet,
            version=version,
            address=address,
            balance=int(account.balance),
            status=status,
            is_active=is_active,
        )
    except Exception as exc:
        print(f"[WalletFactory] raw account probe failed for {version} {address}: {exc}")

    try:
        balance = await client.get_account_balance(address)
        balance_int = int(balance)
        return WalletProbe(
            wallet=wallet,
            version=version,
            address=address,
            balance=balance_int,
            status="balance-only",
            is_active=balance_int > 0,
        )
    except Exception as exc:
        print(f"[WalletFactory] balance probe failed for {version} {address}: {exc}")

    return WalletProbe(wallet=wallet, version=version, address=address)


def _choose_wallet(v4: WalletProbe, v5: WalletProbe) -> WalletProbe:
    active = [probe for probe in (v4, v5) if probe.is_active]
    if active:
        return max(active, key=lambda probe: probe.balance)

    funded = [probe for probe in (v4, v5) if probe.balance > 0]
    if funded:
        return max(funded, key=lambda probe: probe.balance)

    return v5


async def get_wallet() -> Tuple[object, str, TonapiClient]:
    global _cached
    if _cached is not None:
        return _cached

    async with _lock:
        if _cached is not None:
            return _cached

        client = TonapiClient(api_key=API_KEY)
        mnemonic = MNEMONIC.split() if isinstance(MNEMONIC, str) else MNEMONIC

        wallet_v4, _, _, _ = WalletV4R2.from_mnemonic(client=client, mnemonic=mnemonic)
        wallet_v5, _, _, _ = WalletV5R1.from_mnemonic(client=client, mnemonic=mnemonic)

        v4 = await _probe_wallet(client, wallet_v4, "v4r2")
        v5 = await _probe_wallet(client, wallet_v5, "v5r1")

        for probe in (v4, v5):
            print(
                "[WalletFactory] "
                f"{probe.version} addr={probe.address} "
                f"status={probe.status} active={probe.is_active} "
                f"balance_nano={probe.balance}"
            )

        chosen = _choose_wallet(v4, v5)
        if not chosen.is_active and chosen.balance <= 0:
            print("[WalletFactory] No active wallet detected, defaulting to v5r1")

        print(f"[WalletFactory] Using {chosen.version}: {chosen.address}")
        _cached = (chosen.wallet, chosen.version, client)
        return _cached


async def get_tonconnect_account() -> Dict[str, str]:
    wallet, _, _ = await get_wallet()
    state_init_b64 = base64.b64encode(
        wallet.state_init.serialize().to_boc()
    ).decode("ascii")
    return {
        "address": wallet.address.to_str(is_user_friendly=False),
        "chain": "-239",
        "walletStateInit": state_init_b64,
    }


async def _wait_for_seqno(wallet, client, initial_seqno: Optional[int]) -> None:
    if initial_seqno is None:
        return
    while True:
        await asyncio.sleep(_confirmation_poll_interval)
        try:
            current = await wallet.get_seqno(client, wallet.address)
        except Exception:
            continue
        if current is not None and current > initial_seqno:
            return


async def wallet_transfer(
    destination: str,
    amount: float = 0,
    body: Any = None,
    state_init=None,
    **kwargs,
) -> Dict[str, str]:
    async with _transfer_lock:
        wallet, _, client = await get_wallet()

        try:
            initial_seqno = await wallet.get_seqno(client, wallet.address)
        except Exception:
            initial_seqno = None

        dest = await resolve_wallet_address(client, destination)
        seqno = initial_seqno if initial_seqno is not None else 0

        wallet_message = wallet.create_wallet_internal_message(
            destination=dest,
            value=to_nano(amount),
            body=body,
            state_init=state_init,
        )
        transfer_body = wallet.raw_create_transfer_msg(
            private_key=wallet.private_key,
            messages=[wallet_message],
            seqno=seqno,
        )
        external_state_init = wallet.state_init if seqno == 0 else None
        message = wallet.create_external_msg(
            dest=wallet.address,
            body=transfer_body,
            state_init=external_state_init,
        )
        message_boc = message.serialize().to_boc()
        await client.send_message(message_boc.hex())

        tx_hash = normalize_hash(message).hex()
        boc_b64 = base64.b64encode(message_boc).decode("ascii")
        await _wait_for_seqno(wallet, client, initial_seqno)
        return {"hash": tx_hash, "boc": boc_b64}


async def get_wallet_only():
    wallet, _, _ = await get_wallet()
    return wallet


async def get_client():
    _, _, client = await get_wallet()
    return client


async def get_address() -> str:
    wallet, _, _ = await get_wallet()
    return wallet.address.to_str()
