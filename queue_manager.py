import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, TelegramObject


class CallbackAnswerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        try:
            await event.answer()
        except TelegramBadRequest:
            pass
        return result


class RateLimitMiddleware(BaseMiddleware):

    def __init__(self, rate: int = 5, window: float = 1.0):
        self._rate = rate
        self._window = window
        self._counts: dict[int, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        from app.config import ADMINS_IDS
        if user.id in ADMINS_IDS:
            return await handler(event, data)

        now = time.monotonic()
        uid = user.id
        self._counts[uid] = [t for t in self._counts[uid] if now - t < self._window]

        if len(self._counts[uid]) >= self._rate:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("⚠️ Слишком много запросов. Подождите секунду.", show_alert=False)
                except Exception:
                    pass
            return None

        self._counts[uid].append(now)
        return await handler(event, data)


class BanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        from app.config import ADMINS_IDS
        if user.id in ADMINS_IDS:
            return await handler(event, data)

        from app.database import is_user_banned
        banned, reason = await is_user_banned(user.id)

        if banned:
            bot = data.get("bot")
            if bot:
                text = (
                    '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
                    '<b>Ваш аккаунт заблокирован.</b>'
                )
                if reason:
                    text += f'\n\n<b>Причина:</b> {reason}'
                text += '\n\n<i>Если вы считаете это ошибкой — обратитесь в поддержку.</i>'
                try:
                    await bot.send_message(user.id, text, parse_mode='HTML')
                except Exception:
                    pass
            return

        return await handler(event, data)
