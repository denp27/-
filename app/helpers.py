from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.config import BASE_DIR
from app.database import get_all_required_channels, get_franchise_required_channels

_ASSETS_DIR = BASE_DIR / "assets"
_START_FILE_ID_CACHE = _ASSETS_DIR / ".start_media_file_id"
_START_MEDIA_FILE_ID: Optional[str] = None
_START_MEDIA_KIND: Optional[str] = None


def _load_start_media_cache() -> tuple[Optional[str], Optional[str]]:
    try:
        if not _START_FILE_ID_CACHE.is_file():
            return None, None
        raw = _START_FILE_ID_CACHE.read_text(encoding="utf-8").strip()
        if not raw:
            return None, None
        if "|" in raw:
            kind, file_id = raw.split("|", 1)
            return kind.strip() or None, file_id.strip() or None
        return "animation", raw
    except Exception:
        return None, None


def _save_start_media_cache(kind: str, file_id: str) -> None:
    try:
        _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        _START_FILE_ID_CACHE.write_text(f"{kind}|{file_id}", encoding="utf-8")
    except Exception:
        pass


def _clear_start_media_cache() -> None:
    global _START_MEDIA_FILE_ID, _START_MEDIA_KIND
    _START_MEDIA_FILE_ID = None
    _START_MEDIA_KIND = None
    try:
        if _START_FILE_ID_CACHE.is_file():
            _START_FILE_ID_CACHE.unlink()
    except Exception:
        pass


def get_start_media_path() -> Optional[Path]:
    for name in ("start.gif", "start.mp4"):
        path = _ASSETS_DIR / name
        if path.is_file():
            return path
    return None


async def send_start_screen(bot: Bot, chat_id: int, text: str, markup=None):
    global _START_MEDIA_FILE_ID, _START_MEDIA_KIND

    if _START_MEDIA_FILE_ID is None:
        _START_MEDIA_KIND, _START_MEDIA_FILE_ID = _load_start_media_cache()

    if _START_MEDIA_FILE_ID:
        try:
            if _START_MEDIA_KIND == "video":
                return await bot.send_video(
                    chat_id=chat_id,
                    video=_START_MEDIA_FILE_ID,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            return await bot.send_animation(
                chat_id=chat_id,
                animation=_START_MEDIA_FILE_ID,
                caption=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except TelegramBadRequest:
            _clear_start_media_cache()

    media_path = get_start_media_path()
    if not media_path:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )

    media = FSInputFile(str(media_path))
    if media_path.suffix.lower() == ".mp4":
        msg = await bot.send_video(
            chat_id=chat_id,
            video=media,
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        file_id = msg.video.file_id if msg.video else None
        kind = "video"
    else:
        msg = await bot.send_animation(
            chat_id=chat_id,
            animation=media,
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        file_id = None
        if msg.animation:
            file_id = msg.animation.file_id
        elif msg.video:
            file_id = msg.video.file_id
        kind = "animation"

    if file_id:
        _START_MEDIA_FILE_ID = file_id
        _START_MEDIA_KIND = kind
        _save_start_media_cache(kind, file_id)
    return msg


async def send_admin_notification(source_bot: Bot, text: str, franchise_id: int = 0, **kwargs):
    from app.config import ADMINS_IDS, TOKEN

    if not ADMINS_IDS:
        return

    notify_bot = source_bot
    close_notify_bot = False
    if franchise_id and TOKEN:
        notify_bot = Bot(token=TOKEN)
        close_notify_bot = True

    try:
        for admin_id in ADMINS_IDS:
            try:
                await notify_bot.send_message(admin_id, text, **kwargs)
            except Exception as e:
                print(f"[AdminNotify] failed to send notification to {admin_id}: {e}")
    finally:
        if close_notify_bot:
            await notify_bot.session.close()


async def check_subscription(bot: Bot, user_id: int, franchise_id: int = 0) -> tuple[bool, list]:
    if franchise_id:
        required_channels = await get_franchise_required_channels(franchise_id)
    else:
        required_channels = await get_all_required_channels()
    if not required_channels:
        return True, []

    not_subscribed = []
    for channel_id, channel_url, channel_name in required_channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_subscribed.append((channel_id, channel_url, channel_name))
        except Exception as e:
            print(f"[Ошибка проверки подписки на {channel_id}] {e}")
            not_subscribed.append((channel_id, channel_url, channel_name))

    return len(not_subscribed) == 0, not_subscribed


async def show_subscription_required(bot: Bot, user_id: int, not_subscribed_channels: list, message_id: int = None):
    if len(not_subscribed_channels) == 1:
        text = (
            '<tg-emoji emoji-id="6039486778597970865">🔔</tg-emoji> <b>Для использования бота необходимо подписаться на наш канал</b>\n\n'
            'Подпишитесь и нажмите <b>Проверить подписку</b>'
        )
    else:
        text = (
            f'<tg-emoji emoji-id="6039486778597970865">🔔</tg-emoji> <b>Для использования бота необходимо подписаться на наши каналы ({len(not_subscribed_channels)})</b>\n\n'
            "Подпишитесь на все каналы и нажмите <b>Проверить подписку</b>"
        )

    builder = InlineKeyboardBuilder()
    for i, (channel_id, channel_url, channel_name) in enumerate(not_subscribed_channels, 1):
        button_text = channel_name if channel_name else f"Канал {i}"
        builder.button(text=button_text, url=channel_url, icon_custom_emoji_id="6039422865189638057")
    builder.button(text="Проверить подписку", callback_data="check_subscription", icon_custom_emoji_id="5870633910337015697")
    builder.adjust(1)

    if message_id:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=message_id,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    else:
        await bot.send_message(
            chat_id=user_id, text=text,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )


async def effective_markup(base_pct, franchise_id: int = 0) -> float:
    if not franchise_id:
        return float(base_pct)
    from app.database import get_franchise_by_id
    row = await get_franchise_by_id(franchise_id)
    franchise_markup = float(row[4]) if row else 0.0
    return float(base_pct) + franchise_markup


def format_stars_price() -> str:
    from app.config import STARS_PRICE_MODE, STARS_PRICE_RUB, COMMISSION_STARS
    if STARS_PRICE_MODE[0] == "fixed":
        return f"{Decimal(str(STARS_PRICE_RUB[0])).quantize(Decimal('0.01'))} ₽"
    return f"{COMMISSION_STARS[0]}%"


async def calc_star_sell_price(cost, franchise_id: int = 0) -> Decimal:
    from app.config import STARS_PRICE_MODE, STARS_PRICE_RUB, COMMISSION_STARS
    cost = Decimal(str(cost or 0))
    if cost <= 0:
        return Decimal("0")

    if STARS_PRICE_MODE[0] == "fixed":
        sell = Decimal(str(STARS_PRICE_RUB[0] or 0))
    else:
        pct = Decimal(str(COMMISSION_STARS[0]))
        sell = cost * (Decimal("1") + pct / Decimal("100"))

    if sell < cost:
        sell = cost

    if franchise_id:
        from app.database import get_franchise_by_id
        row = await get_franchise_by_id(franchise_id)
        fr_markup = Decimal(str(row[4] or 0)) if row else Decimal("0")
        if fr_markup > 0:
            sell += cost * fr_markup / Decimal("100")

    return sell.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def process_franchise_reward(franchise_id: int, base_price: float) -> float:
    if not franchise_id or base_price <= 0:
        return 0.0
    from app.database import get_franchise_by_id, increment_franchise_earned
    row = await get_franchise_by_id(franchise_id)
    if not row:
        return 0.0
    owner_id = row[1]
    fr_markup = float(row[4] or 0)
    if fr_markup <= 0:
        return 0.0
    earned = round(base_price * fr_markup / 100.0, 2)
    if earned > 0:
        await increment_franchise_earned(owner_id, earned)
    return earned


async def franchise_branding(franchise_id: int = 0) -> tuple[str, str]:
                                                                                              
    from app.config import SUPPORT_URL
    if not franchise_id:
        return "MstiStars", SUPPORT_URL
    from app.database import get_franchise_by_id
    row = await get_franchise_by_id(franchise_id)
    if not row:
        return "MstiStars", SUPPORT_URL
    project_name = row[3] or "MstiStars"
    support_url = row[7] if len(row) > 7 and row[7] else SUPPORT_URL
    return project_name, support_url


async def get_section_photo(franchise_id: int, section: str) -> str | None:
    if not franchise_id:
        return None
    from app.database import get_franchise_photo
    return await get_franchise_photo(franchise_id, section)


async def exit_button():
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    return builder.as_markup()


async def ebal_button(need: float):
    builder = InlineKeyboardBuilder()
    builder.button(text="Пополнить баланс", callback_data=f"deposit_auto:{need}", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    return builder.adjust(1).as_markup()


async def admin_exit_button():
    builder = InlineKeyboardBuilder()
    builder.button(text="Админ-панель", callback_data="adminka", icon_custom_emoji_id="5873147866364514353")
    return builder.as_markup()


async def safe_edit_text(bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode: str = "HTML", disable_web_page_preview: bool = False):
                                                                                                                  
    try:
        return await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            parse_mode=parse_mode, reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "no text in the message" in msg or "message can't be edited" in msg or "message to edit not found" in msg:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            return await bot.send_message(
                chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        raise


def install_edit_text_fallback():                 
    from aiogram import Bot as _Bot
    if getattr(_Bot, "_edit_text_fallback_installed", False):
        return
    original = _Bot.edit_message_text

    async def patched(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "no text in the message" not in msg and "message can't be edited" not in msg:
                raise
            chat_id = kwargs.get("chat_id")
            message_id = kwargs.get("message_id")
            text = kwargs.get("text")
            if text is None and args:
                text = args[0]
            if chat_id is None or message_id is None or text is None:
                raise
            try:
                await self.delete_message(chat_id, message_id)
            except Exception:
                pass
            return await self.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=kwargs.get("parse_mode", "HTML"),
                reply_markup=kwargs.get("reply_markup"),
                disable_web_page_preview=kwargs.get("disable_web_page_preview", False),
            )

    _Bot.edit_message_text = patched
    _Bot._edit_text_fallback_installed = True


async def unified_send(event, bot: Bot, text: str, markup=None, photo: str | None = None):
    user_id = event.from_user.id
    if isinstance(event, CallbackQuery):
        msg_id = event.message.message_id
        try:
            if photo:
                if event.message.photo:
                    return await bot.edit_message_media(
                        chat_id=user_id, message_id=msg_id,
                        media=InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                        reply_markup=markup
                    )
                else:
                    try:
                        await bot.delete_message(user_id, msg_id)
                    except TelegramBadRequest:
                        pass
                    return await bot.send_photo(user_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                if event.message.photo:
                    try:
                        await bot.delete_message(user_id, msg_id)
                    except TelegramBadRequest:
                        pass
                    return await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
                return await bot.edit_message_text(
                    chat_id=user_id, message_id=msg_id,
                    text=text, parse_mode="HTML", reply_markup=markup
                )
        except TelegramBadRequest:
            if photo:
                return await bot.send_photo(user_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=markup)
            return await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
    elif isinstance(event, Message):
        if photo:
            return await bot.send_photo(user_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=markup)
        return await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
