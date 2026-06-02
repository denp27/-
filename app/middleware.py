from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


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
