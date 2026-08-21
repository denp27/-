import asyncio
import importlib.util
import types
import traceback
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import TelegramObject

from app.database import get_all_franchises, register_franchise_user
from app.middleware import BanMiddleware

_running: Dict[str, asyncio.Task] = {}

_HANDLER_MODULES = (
    "app.handlers.start",
    "app.handlers.stars",
    "app.handlers.ton",
    "app.handlers.premium",
    "app.handlers.profile",
    "app.handlers.nft",
    "app.handlers.numbers",
    "app.handlers.deposit",
    "app.handlers.franchise",
    "app.handlers.gifts",
)


class _FranchiseUserMiddleware(BaseMiddleware):
    def __init__(self, franchise_id: int):
        self._franchise_id = franchise_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            await register_franchise_user(self._franchise_id, user.id)
        return await handler(event, data)


def _load_module_isolated(mod_name: str) -> types.ModuleType:
    spec = importlib.util.find_spec(mod_name)
    if spec is None:
        raise ImportError(f"[Franchise] Модуль не найден: {mod_name}")

    module = types.ModuleType(mod_name)
    module.__spec__    = spec
    module.__loader__  = spec.loader
    module.__file__    = spec.origin
    module.__package__ = spec.parent
    module.__builtins__ = __builtins__

    spec.loader.exec_module(module)
    return module


def _build_dispatcher(franchise_id: int) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["franchise_id"] = franchise_id
    dp.update.middleware(BanMiddleware())
    dp.update.outer_middleware(_FranchiseUserMiddleware(franchise_id))

    for mod_name in _HANDLER_MODULES:
        module = _load_module_isolated(mod_name)
        dp.include_router(module.router)

    return dp


async def _poll(token: str, franchise_id: int):
    bot = Bot(token=token)
    try:
        dp = _build_dispatcher(franchise_id)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, handle_signals=False)
    except TelegramUnauthorizedError:
        print(f"[Franchise] Невалидный токен: {token[:15]}...")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Franchise] Ошибка поллинга ({token[:15]}...): {e}")
        traceback.print_exc()
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


def start_franchise(token: str, franchise_id: int = 0):
    if token in _running and not _running[token].done():
        return
    task = asyncio.create_task(_poll(token, franchise_id))
    _running[token] = task
    print(f"[Franchise] Запущен бот {token[:15]}...")


def stop_franchise(token: str):
    task = _running.pop(token, None)
    if task and not task.done():
        task.cancel()
        print(f"[Franchise] Остановлен бот {token[:15]}...")


async def start_all_franchises():
    franchises = await get_all_franchises()
    for row in franchises:
        fid, owner_id, bot_token, project_name, markup, is_active, total_earned = row
        if is_active:
            start_franchise(bot_token, fid)
