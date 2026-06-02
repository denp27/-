import asyncio

from aiogram import Bot, Dispatcher

from app.database import init_db, add_collection_address, db_get_collection_address
from app.queue_manager import purchase_queue
from app.config import TOKEN
from app.utils.martketapi import MarketApi
from app.franchise_runner import start_all_franchises
from app.helpers import install_edit_text_fallback

from app.handlers import (
    start_router, stars_router, ton_router, premium_router,
    profile_router, nft_router, numbers_router, deposit_router, admin_router,
    franchise_router, checks_router, history_router
)
from app.middleware import BanMiddleware

marketapp = MarketApi()

BANNER = r"""
 ____  _                  ____        _   
/ ___|| |_ __ _ _ __ ___ | __ )  ___ | |_ 
\___ \| __/ _` | '__/ __||  _ \ / _ \| __|
 ___) | || (_| | |  \__ \| |_) | (_) | |_ 
|____/ \__\__,_|_|  |___/|____/ \___/ \__|
                                    v2.2
         Developer: @kalipsom
"""


async def on_startup():
    all_gifts = await marketapp.get_collections_gifts()
    new_collections = 0
    existing_collections = 0

    for gift in all_gifts:
        existing_address = await db_get_collection_address(gift)
        if existing_address:
            existing_collections += 1
        else:
            try:
                address = await marketapp.get_collection_address(gift)
                if address:
                    await add_collection_address(gift, address)
                    new_collections += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[!] Error getting address for {gift}: {e}")
                continue


async def main():
    print(BANNER)

    install_edit_text_fallback()

    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp["franchise_id"] = 0

    dp.update.middleware(BanMiddleware())

    dp.include_router(start_router)
    dp.include_router(stars_router)
    dp.include_router(ton_router)
    dp.include_router(premium_router)
    dp.include_router(profile_router)
    dp.include_router(nft_router)
    dp.include_router(numbers_router)
    dp.include_router(deposit_router)
    dp.include_router(admin_router)
    dp.include_router(franchise_router)
    dp.include_router(checks_router)
    dp.include_router(history_router)

    await init_db()
    purchase_queue.start()
    asyncio.create_task(on_startup())
    asyncio.create_task(start_all_franchises())

    await dp.start_polling(bot)
