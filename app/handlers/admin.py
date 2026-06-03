import asyncio
import re
import time
from collections import deque
from typing import Optional

import aiosqlite
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.text_decorations import HtmlDecoration
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramNotFound, TelegramForbiddenError,
    TelegramConflictError, TelegramUnauthorizedError, TelegramRetryAfter, TelegramMigrateToChat
)

from app.database import (
    get_count_users, get_count_starsbuyed, get_users_ids,
    user_exists, get_user, get_user_by_username, get_balance,
    increment_balance, deincrement_balance,
    get_promo, create_promo, deactive_promo, get_active_promos, get_uses_promo,
    get_all_required_channels, add_required_channel, remove_required_channel,
    get_franchise_stats, get_all_franchises_paginated, get_franchises_count,
    get_franchise_by_id, set_franchise_active, delete_franchise,
    ban_user, unban_user, is_user_banned,
    get_pending_withdraw_requests, get_pending_withdraw_count,
    get_withdraw_request, approve_withdraw_request, reject_withdraw_request,
    get_all_gifts, add_gift, delete_gift, toggle_gift_active,
    DATABASE_NAME
)
from app.states import AdminState
import app.config as config
from app.config import (
    ADMINS_IDS, COMMISSION_STARS, COMMISSION_TON, COMMISSION_PREMIUM,
    COMMISSION_NFT, COMMISSION_NUMBERS
)
from app.utils.fragmentapi import StarSender
from app.utils.walletapi import WalletApi

router = Router()
router.message.filter(F.from_user.func(lambda u: u.id in ADMINS_IDS))
router.callback_query.filter(F.from_user.func(lambda u: u.id in ADMINS_IDS))
htmls = HtmlDecoration()
fragment = StarSender()
wallet = WalletApi()


async def admin_exit_button():
    builder = InlineKeyboardBuilder()
    builder.button(text="Админ-панель", callback_data="adminka", icon_custom_emoji_id="5873147866364514353")
    return builder.as_markup()


def apply_html_formatting(text, entities):
    formatted = htmls.unparse(text, entities or [])
    formatted = formatted.replace('emoji_id="', 'emoji-id="')
    return formatted


async def send_message_with_retry(
    bot: Bot, chat_id: int, text: str, parse_mode=None, reply_markup=None,
    photo_file_id: Optional[str] = None, attempt: int = 0, max_attempts: int = 3
):
    if attempt >= max_attempts:
        return False

    try:
        if photo_file_id:
            await bot.send_photo(chat_id, photo=photo_file_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        return True

    except (TelegramForbiddenError, TelegramNotFound):
        return False
    except TelegramMigrateToChat as e:
        return await send_message_with_retry(bot, e.migrate_to_chat_id, text, parse_mode, reply_markup, photo_file_id, attempt + 1, max_attempts)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await send_message_with_retry(bot, chat_id, text, parse_mode, reply_markup, photo_file_id, attempt + 1, max_attempts)
    except TelegramBadRequest:
        return False
    except (TelegramConflictError, TelegramUnauthorizedError):
        return False
    except TelegramAPIError:
        if attempt < max_attempts - 1:
            await asyncio.sleep(2 ** attempt)
            return await send_message_with_retry(bot, chat_id, text, parse_mode, reply_markup, photo_file_id, attempt + 1, max_attempts)
        return False
    except Exception:
        if attempt < max_attempts - 1:
            await asyncio.sleep(1)
            return await send_message_with_retry(bot, chat_id, text, parse_mode, reply_markup, photo_file_id, attempt + 1, max_attempts)
        return False


async def update_progress(progress_message: Message, current: int, total_users: int, success: int, failed: int, speed_stats: dict):
    try:
        percent = (current / total_users) * 100 if total_users > 0 else 0
        filled = int(percent / 10)
        progress_bar = '🟩' * filled + '⬜️' * (10 - filled)
        avg_speed = speed_stats.get("avg_speed", 0)
        remaining = total_users - current
        eta_seconds = int(remaining / avg_speed) if avg_speed > 0 else 0
        eta_minutes = eta_seconds // 60
        eta_text = f"{eta_minutes}м {eta_seconds % 60}с" if eta_minutes > 0 else f"{eta_seconds}с"

        await progress_message.edit_text(
            f"<b>📢 Статус рассылки:</b>\n\n"
            f"Прогресс: <code>{progress_bar}</code> <b>{percent:.1f}%</b>\n"
            f"Обработано: <b>{current}</b>/<b>{total_users}</b>\n"
            f"✅ Успешно: <b>{success}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>\n"
            f"📊 Скорость: <b>{speed_stats.get('current_speed', 0):.1f}</b> сообщ/сек\n"
            f"📉 Средняя: <b>{avg_speed:.1f}</b> сообщ/сек\n"
            f"⏱ Осталось: ~<b>{eta_text}</b>",
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            pass
    except Exception:
        pass


async def broadcast(bot: Bot, start_msg: Message, users: list, text: str, photo_file_id: str = None, keyboard=None, max_concurrent: int = 20):
    total_users = len(users)
    if not total_users:
        await start_msg.reply("<b>❌ Нет пользователей для рассылки.</b>", parse_mode="HTML")
        return

    progress_message = await start_msg.reply("<b>📢 Подготовка к рассылке...</b>\n\n⏳ Инициализация...", parse_mode="HTML")

    semaphore = asyncio.Semaphore(max_concurrent)
    progress_lock = asyncio.Lock()
    rate_limiter = asyncio.Semaphore(28)

    processed = 0
    success = 0
    failed = 0
    tasks = []
    start_time = time.time()
    message_timestamps = deque(maxlen=100)
    speed_stats = {"current_speed": 0.0, "avg_speed": 0.0, "last_update": start_time}
    rate_limit_counter = {"count": 0, "reset_time": time.time()}

    def calculate_speed():
        now = time.time()
        current_speed = (len(message_timestamps) - 1) / (message_timestamps[-1] - message_timestamps[0]) if len(message_timestamps) >= 2 and (message_timestamps[-1] - message_timestamps[0]) > 0 else 0
        elapsed = now - start_time
        avg_speed = processed / elapsed if elapsed > 0 and processed > 0 else 0
        return {"current_speed": current_speed, "avg_speed": avg_speed, "last_update": now}

    async def rate_limit_wait():
        async with rate_limiter:
            now = time.time()
            if now - rate_limit_counter["reset_time"] >= 1.0:
                rate_limit_counter["count"] = 0
                rate_limit_counter["reset_time"] = now
            rate_limit_counter["count"] += 1
            if rate_limit_counter["count"] >= 28:
                sleep_time = 1.0 - (now - rate_limit_counter["reset_time"])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                rate_limit_counter["count"] = 0
                rate_limit_counter["reset_time"] = time.time()

    async def process_user(uid: int):
        nonlocal processed, success, failed
        async with semaphore:
            await rate_limit_wait()
            result = await send_message_with_retry(bot, uid, text, "HTML", keyboard, photo_file_id)
            async with progress_lock:
                processed += 1
                if result:
                    success += 1
                else:
                    failed += 1
                message_timestamps.append(time.time())
                now = time.time()
                if now - speed_stats["last_update"] > 2.0 or processed % 50 == 0:
                    speed_stats.update(calculate_speed())
                update_interval = max(1, total_users // 20)
                if processed % update_interval == 0 or processed == total_users:
                    await update_progress(progress_message, processed, total_users, success, failed, speed_stats)

    try:
        for uid in users:
            tasks.append(asyncio.create_task(process_user(uid)))
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        pass

    elapsed = time.time() - start_time
    avg_speed = processed / elapsed if elapsed > 0 else 0
    success_rate = (success / total_users * 100) if total_users > 0 else 0

    final_message = (
        "<b>✅ Рассылка завершена!</b>\n\n"
        f"📝 <b>Статистика:</b>\n"
        f"├ Успешно: <b>{success}</b> ({success_rate:.1f}%)\n"
        f"├ Ошибок: <b>{failed}</b> ({(failed/total_users*100):.1f}%)\n"
        f"└ Всего: <b>{total_users}</b>\n\n"
        f"⏱ <b>Производительность:</b>\n"
        f"├ Время: <b>{elapsed:.1f}</b> сек\n"
        f"├ Скорость: <b>{avg_speed:.1f}</b> сообщ/сек\n"
        f"└ В минуту: <b>{avg_speed*60:.1f}</b> сообщ/мин"
    )

    try:
        await progress_message.edit_text(final_message, parse_mode="HTML")
    except Exception:
        await start_msg.reply(final_message, parse_mode="HTML")


async def cleanup_users(bot: Bot, admin_id: int):
    all_users = await get_users_ids()
    removed_users = []
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        for index, user_id in enumerate(all_users, start=1):
            try:
                await bot.get_chat(user_id)
            except (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest):
                await conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                removed_users.append(user_id)
            await asyncio.sleep(0.05)
        await conn.commit()
    await bot.send_message(admin_id, f"✅ Очистка завершена\nУдалено пользователей: {len(removed_users)}")


async def _show_adminka_text(bot: Bot, user_id: int):
    pending_wr = await get_pending_withdraw_count()
    wr_label = f"Заявки на вывод ({pending_wr})" if pending_wr else "Заявки на вывод"

    builder = InlineKeyboardBuilder()
    builder.button(text="Рассылка", callback_data="mailing", icon_custom_emoji_id="6039422865189638057")
    builder.button(text="Пользователь", callback_data="info_user", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Очистка БД", callback_data="cleaner", icon_custom_emoji_id="5870875489362513438")
    builder.button(text="Выдать баланс", callback_data="give_balance", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Снять баланс", callback_data="take_balance", icon_custom_emoji_id="5890848474563352982")
    builder.button(text="Промокоды", callback_data="promo_menu", icon_custom_emoji_id="6032644646587338669")
    builder.button(text="Подарки", callback_data="admin_gifts", icon_custom_emoji_id="6032644646587338669")
    builder.button(text="Франшизы", callback_data="admin_franchises:0", icon_custom_emoji_id="5873147866364514353")
    builder.button(text="Задания", callback_data="admin_tasks", icon_custom_emoji_id="5879905000972358125")
    builder.button(text=wr_label, callback_data="admin_withdraws:0", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Настройки", callback_data="settings", icon_custom_emoji_id="5870982283724328568")
    markup = builder.adjust(1, 2, 2, 2, 2, 2, 1).as_markup()

    balance = await wallet.get_balance_ton()
    franchise_count, franchise_earned = await get_franchise_stats()
    text = (
        '<b><tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> Вы вошли в панель администратора</b>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> <b>Пользователей:</b> {await get_count_users()}\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> <b>Куплено звёзд:</b> {await get_count_starsbuyed()}'
        '</blockquote>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> <b>Баланс кошелька:</b> {balance:.2f} TON\n'
        f'<tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji> <b>Доступно к покупке:</b> {await fragment.get_count_stars()} звёзд'
        '</blockquote>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Франшиз:</b> {franchise_count}\n'
        f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Заработано франшизами:</b> {franchise_earned:.2f} ₽'
        '</blockquote>\n\n'
        f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Наценки:</b>\n'
        f'<blockquote>'
        f'Stars: {COMMISSION_STARS[0]}%  ·  TON: {COMMISSION_TON[0]}%  ·  Premium: {COMMISSION_PREMIUM[0]}%\n'
        f'NFT: {COMMISSION_NFT[0]}%  ·  Номера: {COMMISSION_NUMBERS[0]}%'
        '</blockquote>\n\n'
        '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Выберите действие ниже</i>'
    )
    return text, markup


@router.message(F.text == "/admin")
async def admin_message_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMINS_IDS:
        return
    text, markup = await _show_adminka_text(bot, user_id)
    await bot.send_message(user_id, text=text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "adminka")
async def adminka(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    if user_id not in ADMINS_IDS:
        return
    text, markup = await _show_adminka_text(bot, user_id)
    await bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "cleaner")
async def cleaner(call: CallbackQuery, bot: Bot):
    await call.answer("⏳ Очистка началась...", show_alert=True)
    asyncio.create_task(cleanup_users(bot, call.from_user.id))


@router.callback_query(F.data == "promo_menu")
async def promo_menu(call: CallbackQuery, bot: Bot, state: FSMContext):
    try:
        await state.clear()
    except:
        pass
    user_id = call.from_user.id

    builder = InlineKeyboardBuilder()
    builder.button(text="Создать", callback_data="create_promo", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Список", callback_data="list_promo", icon_custom_emoji_id="5870528606328852614")
    builder.button(text="Удалить промокод", callback_data="delete_promo", icon_custom_emoji_id="5870875489362513438")
    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text='<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Панель управления промокодами</b>\n\nВыберите действие ниже:',
        parse_mode="HTML", reply_markup=builder.adjust(2, 1, 1).as_markup()
    )


@router.callback_query(F.data == 'create_promo')
async def creates_promo(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await state.set_state(AdminState.wait_create_promo)

    text = (
        "<b>➕ Создание промокода</b>\n\n"
        "Введите промокод, награду (в рублях) и максимальное количество использований в формате:\n"
        "<code>ПРОМОКОД НАГРАДА МАКС_ИСПОЛЬЗОВАНИЙ</code>\n\n"
        "Пример:\n<code>WELCOME100 100 50</code>\n\n"
        "Или нажмите 'Отмена' для возврата."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="promo_menu", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=text, parse_mode="HTML", reply_markup=builder.as_markup())


@router.message(AdminState.wait_create_promo)
async def process_create_promo(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        promo_code, reward_str, max_uses_str = message.text.strip().split()
        reward = int(reward_str)
        max_uses = int(max_uses_str)
    except ValueError:
        builder = InlineKeyboardBuilder()
        builder.button(text="Назад", callback_data="promo_menu", icon_custom_emoji_id="5960671702059848143")
        await bot.send_message(user_id, "❌ Неверный формат ввода. Используйте:\n<code>ПРОМОКОД НАГРАДА МАКС_ИСПОЛЬЗОВАНИЙ</code>", reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
        await state.clear()
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="promo_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()

    if await get_promo(promo_code):
        await bot.send_message(user_id, "❌ Промокод с таким именем уже существует в базе данных", reply_markup=markup)
        await state.clear()
        return

    await create_promo(promo_code, reward, max_uses)
    await bot.send_message(user_id, "✅ Промокод успешно создан", reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == 'delete_promo')
async def deletes_promo(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await state.set_state(AdminState.wait_delete_promo)

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="promo_menu", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text="<b>➖ Удаление промокода</b>\n\nВведите промокод для удаления или нажмите 'Отмена' для возврата.",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )


@router.message(AdminState.wait_delete_promo)
async def process_delete_promo(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    promo_code = message.text.strip()

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="promo_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()

    if not await get_promo(promo_code):
        await bot.send_message(user_id, "❌ Промокод не найден в базе данных", reply_markup=markup)
        await state.clear()
        return

    await deactive_promo(promo_code)
    await bot.send_message(user_id, "✅ Промокод успешно удален", reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == "list_promo")
async def list_promo(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    promo_codes = await get_active_promos()

    if not promo_codes:
        text = "<b>📋 Список промокодов</b>\n\n❌ Промокодов пока нет\n\n<i>Создайте новый промокод для отображения.</i>"
    else:
        text = "<b>📋 Активные промокоды</b>\n\n"
        for idx, (code, reward, max_uses) in enumerate(promo_codes, 1):
            uses = await get_uses_promo(code)
            remaining = max_uses - uses
            usage_percent = (uses / max_uses * 100) if max_uses > 0 else 0
            text += (
                f"<b>{idx}. {code}</b>\n"
                f"├ 💰 Награда: <code>{reward:.2f} ₽</code>\n"
                f"├ 📊 Использовано: <code>{uses}/{max_uses}</code> ({usage_percent:.1f}%)\n"
                f"└ 📋 Осталось: <code>{remaining}</code>\n\n"
            )

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="promo_menu", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=text, parse_mode="HTML", reply_markup=builder.adjust(1).as_markup())

# admin_tasks.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.database import (
    get_all_tasks, add_task, update_task_status, 
    delete_task, get_task_by_id, update_task_photo_requirement,
    get_pending_submissions, approve_submission, reject_submission,
    get_submission_by_id
)
from app.config import ADMIN_IDS

router = Router()

# FSM состояния для добавления задания
class AddTaskStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_reward = State()
    waiting_for_require_photo = State()
    waiting_for_instruction = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ========== УПРАВЛЕНИЕ ЗАДАНИЯМИ ==========

@router.callback_query(F.data == "admin_tasks")
async def admin_tasks_menu(callback: CallbackQuery):
    """Админ-меню управления заданиями"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task")],
        [InlineKeyboardButton(text="📋 Список всех заданий", callback_data="admin_list_tasks")],
        [InlineKeyboardButton(text="⏳ Заявки на проверку", callback_data="admin_pending_submissions")],
        [InlineKeyboardButton(text="📊 Статистика заданий", callback_data="admin_tasks_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adminka")]
    ])
    
    await callback.message.edit_text(
        "⚙️ <b>Управление заданиями</b>\n\n"
        "Здесь вы можете:\n"
        "• ➕ Добавлять новые задания\n"
        "• 📋 Просматривать все задания\n"
        "• 🔄 Активировать/деактивировать задания\n"
        "• 🗑️ Удалять задания\n"
        "• 📸 Проверять заявки с фото\n"
        "• 📊 Смотреть статистику",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_task")
async def admin_add_task_start(callback: CallbackQuery, state: FSMContext):
    """Начать добавление нового задания"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ <b>Добавление нового задания (Шаг 1/5)</b>\n\n"
        "Введите <b>название</b> задания:\n"
        "Пример: Подпишись на канал\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )
    await state.set_state(AddTaskStates.waiting_for_title)
    await callback.answer()


@router.message(AddTaskStates.waiting_for_title)
async def admin_add_task_title(message: Message, state: FSMContext):
    """Получить название задания"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Добавление задания отменено")
        return
    
    await state.update_data(title=message.text)
    await message.answer(
        "📝 <b>Шаг 2/5:</b> Введите <b>описание</b> задания:\n"
        "Пример: Подпишись на наш Telegram канал и получи звезды\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )
    await state.set_state(AddTaskStates.waiting_for_description)


@router.message(AddTaskStates.waiting_for_description)
async def admin_add_task_description(message: Message, state: FSMContext):
    """Получить описание задания"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Добавление задания отменено")
        return
    
    await state.update_data(description=message.text)
    await message.answer(
        "💰 <b>Шаг 3/5:</b> Введите <b>награду</b> за задание (в Stars):\n"
        "Пример: 50\n\n"
        "Награда должна быть положительным числом\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )
    await state.set_state(AddTaskStates.waiting_for_reward)


@router.message(AddTaskStates.waiting_for_reward)
async def admin_add_task_reward(message: Message, state: FSMContext):
    """Получить награду"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Добавление задания отменено")
        return
    
    try:
        reward = float(message.text)
        if reward <= 0:
            await message.answer("❌ Награда должна быть положительным числом! Попробуйте снова:")
            return
        
        await state.update_data(reward=reward)
        
        # Спрашиваем, требуется ли фото
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📸 Да, требуется фото", callback_data="require_photo_yes")],
            [InlineKeyboardButton(text="📝 Нет, фото не нужно", callback_data="require_photo_no")]
        ])
        
        await message.answer(
            "📸 <b>Шаг 4/5:</b> Требуется ли от пользователя фото подтверждение?\n\n"
            "Выберите один из вариантов:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(AddTaskStates.waiting_for_require_photo)
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число! Попробуйте снова:")


@router.callback_query(AddTaskStates.waiting_for_require_photo)
async def admin_add_task_require_photo(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора требования фото"""
    require_photo = (callback.data == "require_photo_yes")
    await state.update_data(require_photo=require_photo)
    
    if require_photo:
        await callback.message.edit_text(
            "📝 <b>Шаг 5/5:</b> Введите <b>инструкцию</b> для пользователя:\n"
            "Что именно нужно сфотографировать?\n\n"
            "Пример: Сделай скриншот подписки на канал\n\n"
            "Для пропуска отправьте 'пропустить'",
            parse_mode="HTML"
        )
        await state.set_state(AddTaskStates.waiting_for_instruction)
    else:
        # Создаем задание без инструкции
        data = await state.get_data()
        task_id = await add_task(
            title=data['title'],
            description=data['description'],
            reward=data['reward'],
            task_type="stars",
            require_photo=False
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить еще", callback_data="admin_add_task")],
            [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_list_tasks")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]
        ])
        
        await callback.message.edit_text(
            f"✅ <b>Задание успешно добавлено!</b>\n\n"
            f"📋 <b>Название:</b> {data['title']}\n"
            f"📝 <b>Описание:</b> {data['description']}\n"
            f"⭐ <b>Награда:</b> {data['reward']} Stars\n"
            f"📸 <b>Фото:</b> Не требуется\n"
            f"🆔 <b>ID задания:</b> {task_id}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()
    
    await callback.answer()


@router.message(AddTaskStates.waiting_for_instruction)
async def admin_add_task_instruction(message: Message, state: FSMContext):
    """Получить инструкцию и создать задание"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Добавление задания отменено")
        return
    
    instruction_text = message.text if message.text.lower() != "пропустить" else None
    
    data = await state.get_data()
    task_id = await add_task(
        title=data['title'],
        description=data['description'],
        reward=data['reward'],
        task_type="stars",
        require_photo=True,
        instruction_text=instruction_text
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить еще", callback_data="admin_add_task")],
        [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_list_tasks")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]
    ])
    
    await message.answer(
        f"✅ <b>Задание успешно добавлено!</b>\n\n"
        f"📋 <b>Название:</b> {data['title']}\n"
        f"📝 <b>Описание:</b> {data['description']}\n"
        f"⭐ <b>Награда:</b> {data['reward']} Stars\n"
        f"📸 <b>Фото:</b> Требуется\n"
        f"📝 <b>Инструкция:</b> {instruction_text or 'Не указана'}\n"
        f"🆔 <b>ID задания:</b> {task_id}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "admin_list_tasks")
async def admin_list_tasks(callback: CallbackQuery):
    """Показать список всех заданий"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    tasks = await get_all_tasks()
    
    if not tasks:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]
        ])
        
        await callback.message.edit_text(
            "📋 <b>Список заданий</b>\n\n😕 Нет созданных заданий.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        keyboard_buttons = []
        for task in tasks:
            status_icon = "✅" if task['is_active'] else "❌"
            photo_icon = "📸" if task.get('require_photo') else "📝"
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"{status_icon} {photo_icon} {task['title']} (ID:{task['id']})",
                    callback_data=f"edit_task_{task['id']}"
                )
            ])
        
        keyboard_buttons.append([InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task")])
        keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        text = "📋 <b>Список всех заданий</b>\n\n"
        for task in tasks:
            status_text = "Активно ✅" if task['is_active'] else "Неактивно ❌"
            photo_text = "📸 С фото" if task.get('require_photo') else "📝 Без фото"
            text += f"<b>{task['id']}. {task['title']}</b>\n"
            text += f"   ⭐ {task['reward']} Stars | {status_text} | {photo_text}\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("edit_task_"))
async def admin_edit_task(callback: CallbackQuery):
    """Редактировать задание"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_")[2])
    task = await get_task_by_id(task_id)
    
    if not task:
        await callback.answer("❌ Задание не найдено!", show_alert=True)
        return
    
    status_text = "Активно ✅" if task['is_active'] else "Неактивно ❌"
    action_text = "Деактивировать" if task['is_active'] else "Активировать"
    action_icon = "🔒" if task['is_active'] else "✅"
    photo_status = "Требуется фото 📸" if task.get('require_photo') else "Фото не требуется 📝"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{action_icon} {action_text}", callback_data=f"toggle_task_{task_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить задание", callback_data=f"delete_task_{task_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_list_tasks")]
    ])
    
    text = f"📋 <b>Редактирование задания #{task['id']}</b>\n\n"
    text += f"📌 <b>Название:</b> {task['title']}\n"
    text += f"📝 <b>Описание:</b> {task['description']}\n"
    text += f"⭐ <b>Награда:</b> {task['reward']} Stars\n"
    text += f"📊 <b>Статус:</b> {status_text}\n"
    text += f"📸 <b>Фото:</b> {photo_status}\n"
    if task.get('instruction_text'):
        text += f"📖 <b>Инструкция:</b> {task['instruction_text']}\n"
    text += f"📅 <b>Создано:</b> {task['created_at']}\n\n"
    text += f"Выберите действие:"
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_task_"))
async def admin_toggle_task(callback: CallbackQuery):
    """Активировать/деактивировать задание"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_")[2])
    task = await get_task_by_id(task_id)
    
    if task:
        new_status = not task['is_active']
        await update_task_status(task_id, new_status)
        status_text = "активировано ✅" if new_status else "деактивировано ❌"
        await callback.answer(f"Задание {status_text}!")
        await admin_list_tasks(callback)
    else:
        await callback.answer("❌ Задание не найдено!", show_alert=True)


@router.callback_query(F.data.startswith("delete_task_"))
async def admin_delete_task(callback: CallbackQuery):
    """Удалить задание"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_")[2])
    task = await get_task_by_id(task_id)
    
    if task:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{task_id}")],
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"edit_task_{task_id}")]
        ])
        
        await callback.message.edit_text(
            f"⚠️ <b>Подтверждение удаления</b>\n\n"
            f"Вы уверены, что хотите удалить задание?\n\n"
            f"📌 <b>Название:</b> {task['title']}\n"
            f"⭐ <b>Награда:</b> {task['reward']} Stars\n\n"
            f"Это действие нельзя отменить!",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Задание не найдено!", show_alert=True)


@router.callback_query(F.data.startswith("confirm_delete_"))
async def admin_confirm_delete(callback: CallbackQuery):
    """Подтверждение удаления задания"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    task_id = int(callback.data.split("_")[2])
    await delete_task(task_id)
    
    await callback.answer("✅ Задание удалено!", show_alert=True)
    await admin_list_tasks(callback)


# ========== МОДЕРАЦИЯ ЗАЯВОК ==========

@router.callback_query(F.data == "admin_pending_submissions")
async def admin_pending_submissions(callback: CallbackQuery):
    """Показать заявки на проверку"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    submissions = await get_pending_submissions()
    
    if not submissions:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]
        ])
        
        await callback.message.edit_text(
            "✅ <b>Заявки на проверку</b>\n\n"
            "Нет заявок, ожидающих проверки.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        text = "⏳ <b>Заявки на проверку заданий</b>\n\n"
        
        for sub in submissions:
            text += f"🆔 Заявка #{sub['id']}\n"
            text += f"👤 Пользователь ID: {sub['user_id']}\n"
            text += f"📋 Задание ID: {sub['task_id']}\n"
            text += f"⭐ Награда: {sub['reward']} Stars\n"
            text += f"📅 Подана: {sub['created_at']}\n\n"
        
        # Создаем клавиатуру с заявками
        keyboard_buttons = []
        for sub in submissions:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"📸 Заявка #{sub['id']} (ID:{sub['user_id']})",
                    callback_data=f"view_submission_{sub['id']}"
                )
            ])
        
        keyboard_buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_pending_submissions")])
        keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("view_submission_"))
async def admin_view_submission(callback: CallbackQuery, bot=None):
    """Просмотреть заявку"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    submission_id = int(callback.data.split("_")[2])
    submission = await get_submission_by_id(submission_id)
    
    if not submission:
        await callback.answer("❌ Заявка не найдена!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_submission_{submission_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_submission_{submission_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_pending_submissions")]
    ])
    
    # Отправляем фото пользователя
    if submission.get('photo_file_id'):
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=submission['photo_file_id'],
            caption=f"📸 <b>Просмотр заявки #{submission['id']}</b>\n\n"
                   f"👤 Пользователь ID: {submission['user_id']}\n"
                   f"📋 Задание ID: {submission['task_id']}\n"
                   f"⭐ Награда: {submission['reward']} Stars\n"
                   f"📝 Пояснение: {submission['proof_text'] or 'Нет пояснения'}\n\n"
                   f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"📸 <b>Просмотр заявки #{submission['id']}</b>\n\n"
            f"👤 Пользователь ID: {submission['user_id']}\n"
            f"📋 Задание ID: {submission['task_id']}\n"
            f"⭐ Награда: {submission['reward']} Stars\n"
            f"📝 Пояснение: {submission['proof_text'] or 'Нет пояснения'}\n\n"
            f"⚠️ Фото не загружено\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("approve_submission_"))
async def admin_approve_submission(callback: CallbackQuery):
    """Одобрить заявку и выдать награду"""
    admin_id = callback.from_user.id
    
    if not is_admin(admin_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    submission_id = int(callback.data.split("_")[2])
    submission = await get_submission_by_id(submission_id)
    
    if not submission:
        await callback.answer("❌ Заявка не найдена!", show_alert=True)
        return
    
    # Одобряем заявку и выдаем награду
    success = await approve_submission(submission_id, admin_id)
    
    if success:
        # Уведомляем пользователя
        try:
            from app.keyboards import main_menu
            await callback.bot.send_message(
                submission['user_id'],
                f"✅ <b>Ваше задание одобрено!</b>\n\n"
                f"Вы получили +{submission['reward']} Stars на баланс!\n"
                f"Продолжайте выполнять задания!",
                reply_markup=main_menu(submission['user_id'], False),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Не удалось уведомить пользователя {submission['user_id']}: {e}")
        
        await callback.answer(f"✅ Заявка #{submission_id} одобрена! Награда выдана.")
        await admin_pending_submissions(callback)
    else:
        await callback.answer("❌ Ошибка при одобрении заявки!", show_alert=True)


@router.callback_query(F.data.startswith("reject_submission_"))
async def admin_reject_submission(callback: CallbackQuery, state: FSMContext):
    """Отклонить заявку"""
    admin_id = callback.from_user.id
    
    if not is_admin(admin_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    submission_id = int(callback.data.split("_")[2])
    submission = await get_submission_by_id(submission_id)
    
    if not submission:
        await callback.answer("❌ Заявка не найдена!", show_alert=True)
        return
    
    # Сохраняем в состояние
    await state.update_data(submission_id=submission_id, user_id=submission['user_id'])
    
    await callback.message.answer(
        "❌ <b>Отклонение заявки</b>\n\n"
        "Напишите причину отклонения (отправится пользователю):\n"
        "Пример: Неверное фото, попробуйте еще раз\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text & ~F.text.startswith('/'))
async def process_rejection_reason(message: Message, state: FSMContext):
    """Обработка причины отклонения"""
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    submission_id = data.get('submission_id')
    user_id = data.get('user_id')
    
    if submission_id and user_id:
        reason = message.text
        await reject_submission(submission_id, message.from_user.id, reason)
        
        # Уведомляем пользователя
        try:
            await message.bot.send_message(
                user_id,
                f"❌ <b>Ваше задание отклонено</b>\n\n"
                f"<b>Причина:</b> {reason}\n\n"
                f"Вы можете попробовать выполнить задание еще раз!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        await message.answer(f"✅ Заявка #{submission_id} отклонена! Причина отправлена пользователю.")
        await state.clear()
        
        # Возвращаемся в список заявок
        from app.handlers.admin_tasks import admin_pending_submissions
        await admin_pending_submissions(message)
    else:
        await message.answer("❌ Ошибка: заявка не найдена")


@router.callback_query(F.data == "admin_tasks_stats")
async def admin_tasks_statistics(callback: CallbackQuery):
    """Показать статистику по заданиям"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    from app.database import get_tasks_statistics
    stats = await get_tasks_statistics()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_list_tasks")],
        [InlineKeyboardButton(text="⏳ Заявки", callback_data="admin_pending_submissions")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]
    ])
    
    await callback.message.edit_text(
        f"📊 <b>Статистика заданий</b>\n\n"
        f"📋 <b>Всего заданий:</b> {stats['total_tasks']}\n"
        f"✅ <b>Активных заданий:</b> {stats['active_tasks']}\n"
        f"📝 <b>Выполнено заданий:</b> {stats['completed_tasks']}\n"
        f"⭐ <b>Всего выдано наград:</b> {stats['total_rewards']} Stars\n"
        f"⏳ <b>Заявок на проверку:</b> {stats['pending_submissions']}\n\n"
        f"💡 <b>Совет:</b> Регулярно проверяйте заявки пользователей!",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "mailing")
async def mailing(call: CallbackQuery, bot: Bot, state: FSMContext):
    await bot.send_message(call.from_user.id, '<tg-emoji emoji-id="6039422865189638057">📢</tg-emoji> <b>Введите текст рассылки:</b>', parse_mode="HTML")
    await state.set_state(AdminState.wait_mailing_text)


@router.message(AdminState.wait_mailing_text)
async def wait_mailing_text(message: Message, bot: Bot, state: FSMContext):
    if message.photo:
        text = message.caption or ""
        entities = message.caption_entities or []
        photo_file_id = message.photo[-1].file_id
    else:
        text = message.text or ""
        entities = message.entities or []
        photo_file_id = None

    buttons = re.findall(r"\{([^{}]+)\}:([^{}]+)", text)
    keyboard = None
    if buttons:
        kb = InlineKeyboardBuilder()
        for btn_text, btn_url in buttons:
            kb.button(text=btn_text.strip(), url=btn_url.strip())
        kb.adjust(1)
        keyboard = kb.as_markup()
        text = re.sub(r"\{[^{}]+\}:([^{}]+)", "", text).strip()

    formatted_text = apply_html_formatting(text, entities)
    users = await get_users_ids()

    await state.clear()
    await broadcast(bot, message, users, formatted_text, photo_file_id, keyboard)


@router.callback_query(F.data == "settings")
async def settings(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id

    builder = InlineKeyboardBuilder()
    # Наценки — 3 пары
    builder.button(text=f"Stars {COMMISSION_STARS[0]}%", callback_data="change_commission_stars", icon_custom_emoji_id="5904462880941545555")
    builder.button(text=f"TON {COMMISSION_TON[0]}%", callback_data="change_commission_ton", icon_custom_emoji_id="5769126056262898415")
    builder.button(text=f"Premium {COMMISSION_PREMIUM[0]}%", callback_data="change_commission_premium", icon_custom_emoji_id="5884479287171485878")
    builder.button(text=f"NFT {COMMISSION_NFT[0]}%", callback_data="change_commission_nft", icon_custom_emoji_id="6032644646587338669")
    builder.button(text=f"Номера {COMMISSION_NUMBERS[0]}%", callback_data="change_commission_numbers", icon_custom_emoji_id="5346132555689119666")
    builder.button(text=f"Рефералы {config.REFERRAL_PERCENT}%", callback_data="change_referral_percent", icon_custom_emoji_id="5870772616305839506")
    # Управление
    builder.button(text="Управление каналами", callback_data="manage_channels", icon_custom_emoji_id="6039422865189638057")
    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")

    channels = await get_all_required_channels()
    channels_info = f'<tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> <b>Каналов:</b> {len(channels)}' if channels else '<tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> <b>Каналы:</b> не настроены'

    await bot.edit_message_text(
        text=(
            f'<tg-emoji emoji-id="5870982283724328568">⚙️</tg-emoji> <b>Настройки</b>\n\n'
            f'<blockquote>'
            f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Наценки</b> (нажмите кнопку для изменения)\n'
            f'├ Stars: <code>{COMMISSION_STARS[0]}%</code>  ·  TON: <code>{COMMISSION_TON[0]}%</code>\n'
            f'├ Premium: <code>{COMMISSION_PREMIUM[0]}%</code>  ·  NFT: <code>{COMMISSION_NFT[0]}%</code>\n'
            f'├ Номера: <code>{COMMISSION_NUMBERS[0]}%</code>  ·  Рефералы: <code>{config.REFERRAL_PERCENT}%</code>\n'
            f'└ {channels_info}'
            f'</blockquote>'
        ),
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=builder.adjust(2, 2, 2, 1, 1).as_markup()
    )


@router.callback_query(F.data == "change_commission_numbers")
async def change_comission_number(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение наценки аренды номеров</b>\n\n<b>Текущая наценка:</b> {COMMISSION_NUMBERS[0]}%\n\n<b>Введите новую наценку в процентах:</b>\n└ Пример: 15 (для 15%)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_commission)
    await state.update_data({"commission_type": "COMMISSION_NUMBERS"})


@router.callback_query(F.data == "change_commission_stars")
async def change_commission_stars(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение наценки Stars</b>\n\n<b>Текущая наценка:</b> {COMMISSION_STARS[0]}%\n\n<b>Введите новую наценку в процентах:</b>\n└ Пример: 15 (для 15%)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_commission)
    await state.update_data({"commission_type": "COMMISSION_STARS"})


@router.callback_query(F.data == "change_commission_ton")
async def change_commission_ton(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение наценки TON</b>\n\n<b>Текущая наценка:</b> {COMMISSION_TON[0]}%\n\n<b>Введите новую наценку в процентах:</b>\n└ Пример: 15 (для 15%)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_commission)
    await state.update_data({"commission_type": "COMMISSION_TON"})


@router.callback_query(F.data == "change_commission_premium")
async def change_commission_premium(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение наценки Premium</b>\n\n<b>Текущая наценка:</b> {COMMISSION_PREMIUM[0]}%\n\n<b>Введите новую наценку в процентах:</b>\n└ Пример: 15 (для 15%)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_commission)
    await state.update_data({"commission_type": "COMMISSION_PREMIUM"})


@router.callback_query(F.data == "change_commission_nft")
async def change_commission_nft(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение наценки NFT</b>\n\n<b>Текущая наценка:</b> {COMMISSION_NFT[0]}%\n\n<b>Введите новую наценку в процентах:</b>\n└ Пример: 15 (для 15%)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_commission)
    await state.update_data({"commission_type": "COMMISSION_NFT"})


@router.message(AdminState.wait_new_commission)
async def process_new_commission(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        new_commission = float(message.text)
        data = await state.get_data()
        commission_type = data.get("commission_type", "COMMISSION_STARS")

        try:
            await bot.delete_message(user_id, message.message_id)
            await bot.delete_message(user_id, message.message_id - 1)
        except:
            pass

        if new_commission < 0 or new_commission > 100:
            await bot.send_message(user_id, "❌ Наценка должна быть в диапазоне от 0 до 100%", reply_markup=await admin_exit_button())
            await state.clear()
            return

        if commission_type == "COMMISSION_STARS":
            COMMISSION_STARS[0] = int(new_commission)
            category_name = "Stars ⭐"
        elif commission_type == "COMMISSION_TON":
            COMMISSION_TON[0] = int(new_commission)
            category_name = "TON 💎"
        elif commission_type == "COMMISSION_PREMIUM":
            COMMISSION_PREMIUM[0] = int(new_commission)
            category_name = "Premium 👑"
        elif commission_type == "COMMISSION_NFT":
            COMMISSION_NFT[0] = int(new_commission)
            category_name = "NFT 🎁"
        elif commission_type == "COMMISSION_NUMBERS":
            COMMISSION_NUMBERS[0] = int(new_commission)
            category_name = "Номера 📞"
        else:
            category_name = commission_type

        await bot.send_message(
            user_id,
            f"✅ <b>Наценка успешно изменена!</b>\n\n📈 Категория: <b>{category_name}</b>\n🆕 Новая наценка: <b>{int(new_commission)}%</b>",
            parse_mode="HTML", reply_markup=await admin_exit_button()
        )
        await state.clear()

    except ValueError:
        await bot.send_message(user_id, "❌ Введите корректное число!", reply_markup=await admin_exit_button())
        await state.clear()


@router.callback_query(F.data == "change_referral_percent")
async def change_referral_percent(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await bot.edit_message_text(
        text=f"<b>Изменение реферального процента</b>\n\n<b>Текущий процент:</b> {config.REFERRAL_PERCENT}%\n\n<b>Введите новый процент:</b>\n└ Пример: 30 (для 30% от прибыли)",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="settings", icon_custom_emoji_id="5870657884844462243").as_markup()
    )
    await state.set_state(AdminState.wait_new_referral_percent)


@router.message(AdminState.wait_new_referral_percent)
async def process_new_referral_percent(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        new_percent = float(message.text)

        try:
            await bot.delete_message(user_id, message.message_id)
            await bot.delete_message(user_id, message.message_id - 1)
        except:
            pass

        if new_percent < 0 or new_percent > 100:
            await bot.send_message(user_id, "❌ Процент должен быть в диапазоне от 0 до 100%", reply_markup=await admin_exit_button())
            return

                                 
        config.REFERRAL_PERCENT = int(new_percent)

                              
        try:
            from dotenv import set_key
            set_key(str(config.ENV_FILE), "REFERRAL_PERCENT", str(int(new_percent)))
        except Exception as e:
            print(f"Warning: could not update .env: {e}")

        await bot.send_message(
            user_id,
            f"✅ <b>Реферальный процент успешно изменён!</b>\n\n🆕 Новый процент: <b>{int(new_percent)}%</b>",
            parse_mode="HTML", reply_markup=await admin_exit_button()
        )
        await state.clear()

    except ValueError:
        await bot.send_message(user_id, "❌ Введите корректное число!", reply_markup=await admin_exit_button())


@router.callback_query(F.data == "manage_channels")
async def manage_channels(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    channels = await get_all_required_channels()

    builder = InlineKeyboardBuilder()
    if channels:
        text = '📢 <b>Обязательные каналы для подписки:</b>\n\n'
        for i, (channel_id, channel_url, channel_name) in enumerate(channels, 1):
            display_name = channel_name if channel_name else f"Канал {i}"
            text += f"{i}. <b>{display_name}</b>\n   ├ ID: <code>{channel_id}</code>\n   └ URL: {channel_url}\n\n"
            builder.button(text=f"🗑 Удалить {display_name}", callback_data=f"remove_channel_{i-1}", icon_custom_emoji_id="5870875489362513438")
        builder.adjust(1)
    else:
        text = '📢 <b>Обязательные каналы для подписки</b>\n\n❌ Каналы не настроены'

    builder.button(text="Добавить канал", callback_data="add_channel", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Назад", callback_data="settings", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data == "add_channel")
async def add_channel_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    text = (
        "<b>➕ Добавление обязательного канала</b>\n\n"
        "⬇️ <b>Введите ID канала:</b>\n\n"
        "📝 <b>Примеры:</b>\n"
        "├ <code>-1001234567890</code> - для публичных каналов\n"
        "└ <code>-1001234567890</code> - для приватных каналов\n\n"
        "💡 <i>Чтобы получить ID канала, перешлите сообщение из канала боту @username_to_id_bot</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="manage_channels", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(AdminState.wait_channel_id)


@router.message(AdminState.wait_channel_id)
async def process_channel_id(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    channel_id = message.text.strip()

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    if channel_id.startswith('@'):
        await bot.send_message(user_id, "❌ Используйте числовой ID канала, а не @username!\n\n💡 Используйте @getmyid_bot для получения ID", parse_mode="HTML", reply_markup=await admin_exit_button())
        return

    if not channel_id.startswith('-'):
        await bot.send_message(user_id, "❌ Неверный формат ID канала!\n\nID должен начинаться с '-' и быть числом (например: -1001234567890)", parse_mode="HTML", reply_markup=await admin_exit_button())
        return

    try:
        int(channel_id)
    except ValueError:
        await bot.send_message(user_id, "❌ ID канала должен быть числом!\n\n📝 Правильный формат: <code>-1001234567890</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
        return

    try:
        chat = await bot.get_chat(channel_id)

        if chat.type not in ['channel', 'supergroup']:
            await bot.send_message(user_id, f"❌ Это не канал и не супергруппа!\n\nТип чата: <code>{chat.type}</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
            await state.clear()
            return

        try:
            bot_member = await bot.get_chat_member(channel_id, bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await bot.send_message(user_id, f"❌ Бот не является администратором канала!\n\n📢 Канал: <b>{chat.title}</b>\n🤖 Статус бота: <code>{bot_member.status}</code>\n\nДобавьте бота как администратора.", parse_mode="HTML", reply_markup=await admin_exit_button())
                await state.clear()
                return
        except TelegramBadRequest as e:
            await bot.send_message(user_id, f"❌ Не удалось проверить статус бота в канале!\n\nОшибка: <code>{str(e)}</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
            await state.clear()
            return

        try:
            await bot.get_chat_member(channel_id, user_id)
            can_check = True
        except Exception:
            can_check = False

        await state.update_data(channel_id=channel_id, channel_title=chat.title)

        text = (
            "<b>➕ Добавление обязательного канала</b>\n\n"
            f"✅ Канал найден: <b>{chat.title}</b>\n"
            f"🤖 Статус бота: <code>administrator</code>\n"
            f"{'✅' if can_check else '⚠️'} Проверка подписки: <code>{'работает' if can_check else 'может не работать'}</code>\n\n"
            "⬇️ <b>Введите URL канала для подписки:</b>\n\n"
            "📝 <b>Пример:</b> <code>https://t.me/your_channel</code>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="manage_channels", icon_custom_emoji_id="5870657884844462243")
        await bot.send_message(user_id, text=text, parse_mode="HTML", reply_markup=builder.as_markup())
        await state.set_state(AdminState.wait_channel_url)

    except TelegramBadRequest as e:
        error_text = str(e).lower()
        msg = "❌ Канал не найден!\n\nПроверьте ID и убедитесь что бот добавлен в канал." if 'chat not found' in error_text else f"❌ Ошибка при получении информации о канале!\n\nОшибка: <code>{str(e)}</code>"
        await bot.send_message(user_id, msg, parse_mode="HTML", reply_markup=await admin_exit_button())
        await state.clear()
    except Exception as e:
        await bot.send_message(user_id, f"❌ Неожиданная ошибка!\n\nОшибка: <code>{str(e)}</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
        await state.clear()


@router.message(AdminState.wait_channel_url)
async def process_channel_url(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    channel_url = message.text.strip()

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    if not (channel_url.startswith('https://t.me/') or channel_url.startswith('http://t.me/')):
        await bot.send_message(user_id, "❌ Неверный формат URL! Должен начинаться с https://t.me/", reply_markup=await admin_exit_button())
        return

    await state.update_data(channel_url=channel_url)

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="manage_channels", icon_custom_emoji_id="5870657884844462243")
    await bot.send_message(
        user_id,
        "<b>➕ Добавление обязательного канала</b>\n\n⬇️ <b>Введите название канала (будет отображаться на кнопке):</b>\n\n📝 <b>Пример:</b> <code>Наш канал</code>\n\n💡 <i>Или отправьте '-' чтобы не указывать название</i>",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_channel_name)


@router.message(AdminState.wait_channel_name)
async def process_channel_name(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    channel_name = message.text.strip()

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    if channel_name == '-':
        channel_name = None

    data = await state.get_data()
    channel_id = data['channel_id']
    channel_url = data['channel_url']

    success = await add_required_channel(channel_id, channel_url, channel_name)

    if success:
        await bot.send_message(
            user_id,
            f"✅ <b>Канал успешно добавлен!</b>\n\n📢 ID: <code>{channel_id}</code>\n🔗 URL: {channel_url}\n📝 Название: {channel_name or 'Не указано'}",
            parse_mode="HTML", reply_markup=await admin_exit_button()
        )
    else:
        await bot.send_message(user_id, "❌ Ошибка! Канал с таким ID уже существует", reply_markup=await admin_exit_button())

    await state.clear()


@router.callback_query(F.data.startswith("remove_channel_"))
async def remove_channel_confirm(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    channel_index = int(call.data.split('_')[-1])

    channels = await get_all_required_channels()
    if channel_index >= len(channels):
        await bot.answer_callback_query(call.id, "❌ Канал не найден!", show_alert=True)
        return

    channel_id, channel_url, channel_name = channels[channel_index]
    display_name = channel_name if channel_name else f"Канал {channel_index + 1}"

    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"confirm_remove_{channel_id}", icon_custom_emoji_id="5870633910337015697")
    builder.button(text="Отмена", callback_data="manage_channels", icon_custom_emoji_id="5870657884844462243")
    builder.adjust(1)

    await bot.edit_message_text(
        text=f"🗑 <b>Удаление канала</b>\n\nВы уверены что хотите удалить канал?\n\n📢 <b>{display_name}</b>\n└ ID: <code>{channel_id}</code>",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("confirm_remove_"))
async def remove_channel_execute(call: CallbackQuery, bot: Bot):
    channel_id = call.data.replace("confirm_remove_", "")
    success = await remove_required_channel(channel_id)

    if success:
        await bot.answer_callback_query(call.id, "✅ Канал успешно удалён!", show_alert=True)
    else:
        await bot.answer_callback_query(call.id, "❌ Ошибка при удалении канала!", show_alert=True)

    await manage_channels(call, bot)


async def _build_user_card(bot: Bot, uid: int) -> tuple[str, any]:
    """Строит карточку пользователя для админа."""
    user_data = await get_user(uid)
    username = user_data[2] if user_data[2] else "Не указан"
    balance = user_data[3]
    stars_buyed = user_data[4]
    is_banned, ban_reason = await is_user_banned(uid)

    try:
        user_info = await bot.get_chat(uid)
        full_name = user_info.full_name
    except Exception:
        full_name = "Неизвестно"

    username_display = f"@{username}" if username != "Не указан" else "Не указан"

    if is_banned:
        ban_line = (
            f'\n<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
            f'<b>Статус:</b> <b>ЗАБЛОКИРОВАН</b>'
        )
        if ban_reason:
            ban_line += f'\n<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <b>Причина:</b> {ban_reason}'
    else:
        ban_line = (
            f'\n<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> '
            f'<b>Статус:</b> Активен'
        )

    text = (
        '<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Информация о пользователе</b>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Имя:</b> <a href="tg://user?id={uid}">{full_name}</a>\n'
        f'<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> <b>ID:</b> <code>{uid}</code>\n'
        f'<tg-emoji emoji-id="6039614175917903752">📰</tg-emoji> <b>Username:</b> {username_display}'
        f'{ban_line}'
        '</blockquote>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Баланс:</b> <code>{balance:.2f} ₽</code>\n'
        f'<tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji> <b>Куплено звёзд:</b> <code>{stars_buyed}</code>'
        '</blockquote>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Выдать баланс", callback_data=f"admin_add_balance:{uid}", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Снять баланс", callback_data=f"admin_remove_balance:{uid}", icon_custom_emoji_id="5890848474563352982")

    if is_banned:
        builder.button(
            text="Разблокировать",
            callback_data=f"admin_unban:{uid}",
            icon_custom_emoji_id="5870633910337015697"
        )
    else:
        builder.button(
            text="Заблокировать",
            callback_data=f"admin_ban_ask:{uid}",
            icon_custom_emoji_id="5870657884844462243"
        )

    builder.button(text="Обновить", callback_data=f"admin_refresh_user:{uid}", icon_custom_emoji_id="5345906554510012647")
    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1, 1, 1).as_markup()

    return text, markup


@router.callback_query(F.data == "info_user")
async def info_user(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="adminka", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        text=(
            "<b>👤 Информация о пользователе</b>\n\n"
            "⬇️ <b>Введите ID или @username пользователя:</b>\n\n"
            "📝 <b>Примеры:</b>\n"
            "├ <code>123456789</code> - поиск по ID\n"
            "└ <code>@username</code> или <code>username</code> - поиск по юзернейму"
        ),
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_user_id)


@router.message(AdminState.wait_user_id)
async def process_user_info(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except Exception:
        pass

    search_query = message.text.strip()
    user_data = None

    if search_query.isdigit():
        target_user_id = int(search_query)
        if not await user_exists(target_user_id):
            await bot.send_message(user_id, "❌ Пользователь с таким ID не найден в базе данных", reply_markup=await admin_exit_button())
            await state.clear()
            return
        user_data = await get_user(target_user_id)
    else:
        username_query = search_query.replace('@', '').lower()
        user_data = await get_user_by_username(username_query)
        if not user_data:
            await bot.send_message(user_id, f"❌ Пользователь с username <code>@{username_query}</code> не найден в базе данных", parse_mode="HTML", reply_markup=await admin_exit_button())
            await state.clear()
            return

    uid = user_data[1]
    text, markup = await _build_user_card(bot, uid)
    await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
    await state.clear()


@router.callback_query(F.data.startswith("admin_refresh_user:"))
async def admin_refresh_user(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    target_user_id = int(call.data.split(":")[1])

    if not await user_exists(target_user_id):
        await call.answer("❌ Пользователь не найден", show_alert=True)
        return

    text, markup = await _build_user_card(bot, target_user_id)
    try:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    except TelegramBadRequest:
        pass
    await call.answer("✅ Данные обновлены", show_alert=False)



@router.callback_query(F.data.startswith("admin_ban_ask:"))
async def admin_ban_ask(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    target_id = int(call.data.split(":")[1])

    await state.update_data({"ban_target_id": target_id, "ban_msg_id": call.message.message_id})
    await state.set_state(AdminState.wait_ban_reason)

    builder = InlineKeyboardBuilder()
    builder.button(text="Без причины", callback_data=f"admin_ban_confirm:{target_id}:noreason", icon_custom_emoji_id="5870657884844462243")
    builder.button(text="Отмена", callback_data=f"admin_refresh_user:{target_id}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    await bot.edit_message_text(
        text=(
            '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Блокировка пользователя</b>\n\n'
            f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ID:</b> <code>{target_id}</code>\n\n'
            '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Введите причину блокировки</b> '
            'или нажмите «Без причины»:'
        ),
        chat_id=user_id, message_id=call.message.message_id,
        parse_mode="HTML", reply_markup=builder.as_markup()
    )


@router.message(AdminState.wait_ban_reason)
async def admin_ban_reason_text(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    reason = message.text.strip()

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    data = await state.get_data()
    target_id = data.get("ban_target_id")
    msg_id = data.get("ban_msg_id")

    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить бан", callback_data=f"admin_ban_exec:{target_id}", icon_custom_emoji_id="5870633910337015697")
    builder.button(text="Отмена", callback_data=f"admin_refresh_user:{target_id}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    await state.update_data({"ban_reason": reason})

    try:
        await bot.edit_message_text(
            text=(
                '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Подтверждение блокировки</b>\n\n'
                f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ID:</b> <code>{target_id}</code>\n'
                f'<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <b>Причина:</b> {reason}\n\n'
                '<i>Подтвердите действие:</i>'
            ),
            chat_id=user_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        await bot.send_message(
            user_id,
            text=(
                '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Подтверждение блокировки</b>\n\n'
                f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>ID:</b> <code>{target_id}</code>\n'
                f'<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <b>Причина:</b> {reason}\n\n'
                '<i>Подтвердите действие:</i>'
            ),
            parse_mode="HTML", reply_markup=builder.as_markup()
        )


@router.callback_query(F.data.startswith("admin_ban_confirm:"))
async def admin_ban_confirm(call: CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    target_id = int(parts[1])
    await state.clear()

    if not await user_exists(target_id):
        await call.answer("❌ Пользователь не найден", show_alert=True)
        return

    await ban_user(target_id, reason=None)

    try:
        await bot.send_message(
            target_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Ваш аккаунт заблокирован.</b>\n\n'
            '<i>Если вы считаете это ошибкой — обратитесь в поддержку.</i>',
            parse_mode="HTML"
        )
    except Exception:
        pass

    text, markup = await _build_user_card(bot, target_id)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    except TelegramBadRequest:
        pass
    await call.answer("🚫 Пользователь заблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin_ban_exec:"))
async def admin_ban_exec(call: CallbackQuery, bot: Bot, state: FSMContext):
    target_id = int(call.data.split(":")[1])
    data = await state.get_data()
    reason = data.get("ban_reason")
    await state.clear()

    if not await user_exists(target_id):
        await call.answer("❌ Пользователь не найден", show_alert=True)
        return

    await ban_user(target_id, reason=reason)

    try:
        text_user = (
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Ваш аккаунт заблокирован.</b>'
        )
        if reason:
            text_user += f'\n\n<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <b>Причина:</b> {reason}'
        text_user += '\n\n<i>Если вы считаете это ошибкой — обратитесь в поддержку.</i>'
        await bot.send_message(target_id, text_user, parse_mode="HTML")
    except Exception:
        pass

    text, markup = await _build_user_card(bot, target_id)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    except TelegramBadRequest:
        pass
    await call.answer("🚫 Пользователь заблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin_unban:"))
async def admin_unban(call: CallbackQuery, bot: Bot, state: FSMContext):
    target_id = int(call.data.split(":")[1])

    if not await user_exists(target_id):
        await call.answer("❌ Пользователь не найден", show_alert=True)
        return

    await unban_user(target_id)

    try:
        await bot.send_message(
            target_id,
            '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Ваш аккаунт разблокирован.</b>\n\n'
            '<i>Теперь вы можете пользоваться ботом.</i>',
            parse_mode="HTML"
        )
    except Exception:
        pass

    text, markup = await _build_user_card(bot, target_id)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    except TelegramBadRequest:
        pass
    await call.answer("✅ Пользователь разблокирован", show_alert=True)


@router.callback_query(F.data == "give_balance")
async def give_balance(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="adminka", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        text="<b>💸 Выдача баланса</b>\n\n⬇️ <b>Введите данные в формате:</b>\n<code>ID СУММА</code>\n\n📝 <b>Пример:</b> <code>123456789 500</code>\n└ Выдаст пользователю 123456789 сумму 500 ₽",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_balance_add)


@router.callback_query(F.data.startswith("admin_add_balance:"))
async def admin_add_balance_callback(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    target_id = int(call.data.split(":")[1])
    await state.update_data({"target_user_id": target_id})

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="adminka", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        text=f"<b>💸 Выдача баланса</b>\n\n👤 <b>Пользователь:</b> <code>{target_id}</code>\n\n⬇️ <b>Введите сумму для выдачи:</b>\n└ Пример: 500",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_balance_add)


@router.message(AdminState.wait_balance_add)
async def process_add_balance(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    try:
        data = await state.get_data()
        target_id = data.get("target_user_id")

        if target_id:
            amount = float(message.text)
        else:
            parts = message.text.split()
            if len(parts) != 2:
                await bot.send_message(user_id, "❌ Неверный формат! Используйте: <code>ID СУММА</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
                return
            target_id = int(parts[0])
            amount = float(parts[1])

        if amount <= 0:
            await bot.send_message(user_id, "❌ Сумма должна быть больше 0!", reply_markup=await admin_exit_button())
            return

        if not await user_exists(target_id):
            await bot.send_message(user_id, "❌ Пользователь с таким ID не найден в базе данных", reply_markup=await admin_exit_button())
            await state.clear()
            return

        await increment_balance(target_id, amount)

        try:
            await bot.send_message(target_id, f"🎉 <b>Вам начислен баланс!</b>\n\n💰 <b>Сумма:</b> {amount:.2f} ₽", parse_mode="HTML")
        except:
            pass

        await bot.send_message(user_id, f"✅ <b>Баланс успешно выдан!</b>\n\n👤 <b>Пользователь:</b> <code>{target_id}</code>\n💰 <b>Сумма:</b> {amount:.2f} ₽", parse_mode="HTML", reply_markup=await admin_exit_button())
        await state.clear()

    except ValueError:
        await bot.send_message(user_id, "❌ Неверный формат данных! Проверьте правильность ввода.", reply_markup=await admin_exit_button())


@router.callback_query(F.data == "take_balance")
async def take_balance(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="adminka", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        text="<b>💸 Снятие баланса</b>\n\n⬇️ <b>Введите данные в формате:</b>\n<code>ID СУММА</code>\n\n📝 <b>Пример:</b> <code>123456789 500</code>\n└ Снимет у пользователя 123456789 сумму 500 ₽",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_balance_remove)


@router.callback_query(F.data.startswith("admin_remove_balance:"))
async def admin_remove_balance_callback(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    target_id = int(call.data.split(":")[1])
    await state.update_data({"target_user_id": target_id})

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="adminka", icon_custom_emoji_id="5870657884844462243")
    await bot.edit_message_text(
        text=f"<b>💸 Снятие баланса</b>\n\n👤 <b>Пользователь:</b> <code>{target_id}</code>\n\n⬇️ <b>Введите сумму для снятия:</b>\n└ Пример: 500",
        chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await state.set_state(AdminState.wait_balance_remove)


@router.message(AdminState.wait_balance_remove)
async def process_remove_balance(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    try:
        data = await state.get_data()
        target_id = data.get("target_user_id")

        if target_id:
            amount = float(message.text)
        else:
            parts = message.text.split()
            if len(parts) != 2:
                await bot.send_message(user_id, "❌ Неверный формат! Используйте: <code>ID СУММА</code>", parse_mode="HTML", reply_markup=await admin_exit_button())
                return
            target_id = int(parts[0])
            amount = float(parts[1])

        if amount <= 0:
            await bot.send_message(user_id, "❌ Сумма должна быть больше 0!", reply_markup=await admin_exit_button())
            return

        if not await user_exists(target_id):
            await bot.send_message(user_id, "❌ Пользователь с таким ID не найден в базе данных", reply_markup=await admin_exit_button())
            await state.clear()
            return

        current_balance = await get_balance(target_id)
        if current_balance < amount:
            await bot.send_message(user_id, f"⚠️ <b>У пользователя недостаточно средств!</b>\n\n💰 <b>Текущий баланс:</b> {current_balance:.2f} ₽\n📉 <b>Пытаетесь снять:</b> {amount:.2f} ₽", parse_mode="HTML", reply_markup=await admin_exit_button())
            return

        await deincrement_balance(target_id, amount)

        try:
            await bot.send_message(target_id, f"⚠️ <b>С вашего баланса снята сумма!</b>\n\n💸 <b>Сумма:</b> {amount:.2f} ₽", parse_mode="HTML")
        except:
            pass

        await bot.send_message(user_id, f"✅ <b>Баланс успешно снят!</b>\n\n👤 <b>Пользователь:</b> <code>{target_id}</code>\n💸 <b>Сумма:</b> {amount:.2f} ₽", parse_mode="HTML", reply_markup=await admin_exit_button())
        await state.clear()

    except ValueError:
        await bot.send_message(user_id, "❌ Неверный формат данных! Проверьте правильность ввода.", reply_markup=await admin_exit_button())


                                                                                 

FRANCHISES_PER_PAGE = 5


async def _get_bot_username(token: str) -> str:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return "@" + data["result"].get("username", "?")
    except Exception:
        pass
    return "?"


async def _build_franchises_page(page: int):
    offset = page * FRANCHISES_PER_PAGE
    franchises = await get_all_franchises_paginated(offset, FRANCHISES_PER_PAGE)
    total = await get_franchises_count()
    total_pages = max(1, (total + FRANCHISES_PER_PAGE - 1) // FRANCHISES_PER_PAGE)

    if not franchises:
        text = (
            '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Управление франшизами</b>\n\n'
            '<blockquote>Франшиз пока нет.</blockquote>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
        return text, builder.as_markup()

    text = (
        '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Управление франшизами</b>\n\n'
        '<blockquote>'
        f'Всего: <b>{total}</b>  ·  Страница <b>{page + 1}</b> из <b>{total_pages}</b>'
        '</blockquote>\n\n'
        '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Выберите франшизу:</i>'
    )

    builder = InlineKeyboardBuilder()
    for f in franchises:
        fid, owner_id, bot_token, project_name, markup, is_active, total_earned = f
        status = "✅" if is_active else "❌"
        username = await _get_bot_username(bot_token)
        builder.button(
            text=f"{status} {project_name} ({username})",
            callback_data=f"admin_franchise:{fid}:{page}"
        )

    nav = []
    if page > 0:
        nav.append(("◀️", f"admin_franchises:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(("▶️", f"admin_franchises:{page + 1}"))

    for nav_text, nav_cb in nav:
        builder.button(text=nav_text, callback_data=nav_cb)

    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
    rows = [1] * len(franchises)
    if nav:
        rows.append(len(nav))
    rows.append(1)
    builder.adjust(*rows)
    return text, builder.as_markup()


@router.callback_query(F.data.startswith("admin_franchises:"))
async def admin_franchises_list(call: CallbackQuery, bot: Bot):
    page = int(call.data.split(":")[1])
    text, kb = await _build_franchises_page(page)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=kb
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("admin_franchise:"))
async def admin_franchise_detail(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    fid = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    franchise = await get_franchise_by_id(fid)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    fid, owner_id, bot_token, project_name, markup, is_active, total_earned = franchise[:7]
    username = await _get_bot_username(bot_token)
    token_preview = bot_token[:10] + "..." + bot_token[-5:] if len(bot_token) > 15 else bot_token
    status_line = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Активна</b>'
        if is_active else
        '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Неактивна</b>'
    )

    text = (
        '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Франшиза</b>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Проект:</b> {project_name}\n'
        f'<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Бот:</b> {username}\n'
        f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Владелец:</b> <code>{owner_id}</code>\n'
        f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Токен:</b> <code>{token_preview}</code>\n'
        f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Статус:</b> {status_line}'
        '</blockquote>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Наценка:</b> {markup}%\n'
        f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Заработано:</b> {total_earned:.2f} ₽'
        '</blockquote>'
    )

    toggle_text = "Деактивировать" if is_active else "Активировать"
    toggle_cb = f"admin_franchise_toggle:{fid}:{page}"
    toggle_emoji = "5870657884844462243" if is_active else "5870633910337015697"

    builder = InlineKeyboardBuilder()
    builder.button(text=toggle_text, callback_data=toggle_cb, icon_custom_emoji_id=toggle_emoji)
    builder.button(text="Удалить франшизу", callback_data=f"admin_franchise_del:{fid}:{page}", icon_custom_emoji_id="5870875489362513438")
    builder.button(text="Назад", callback_data=f"admin_franchises:{page}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("admin_franchise_toggle:"))
async def admin_franchise_toggle(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    fid = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    franchise = await get_franchise_by_id(fid)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    new_status = not bool(franchise[5])
    await set_franchise_active(fid, new_status)

    from app.franchise_runner import start_franchise, stop_franchise
    token = franchise[2]
    if new_status:
        start_franchise(token, fid)
    else:
        stop_franchise(token)

    await call.answer("✅ Статус изменён", show_alert=False)

    franchise = await get_franchise_by_id(fid)
    fid, owner_id, bot_token, project_name, markup, is_active, total_earned = franchise[:7]
    username = await _get_bot_username(bot_token)
    token_preview = bot_token[:10] + "..." + bot_token[-5:] if len(bot_token) > 15 else bot_token
    status_line = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Активна</b>'
        if is_active else
        '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Неактивна</b>'
    )
    text = (
        '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Франшиза</b>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Проект:</b> {project_name}\n'
        f'<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Бот:</b> {username}\n'
        f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> <b>Владелец:</b> <code>{owner_id}</code>\n'
        f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Статус:</b> {status_line}'
        '</blockquote>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Наценка:</b> {markup}%\n'
        f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Заработано:</b> {total_earned:.2f} ₽'
        '</blockquote>'
    )
    toggle_text = "Деактивировать" if is_active else "Активировать"
    toggle_emoji = "5870657884844462243" if is_active else "5870633910337015697"
    builder = InlineKeyboardBuilder()
    builder.button(text=toggle_text, callback_data=f"admin_franchise_toggle:{fid}:{page}", icon_custom_emoji_id=toggle_emoji)
    builder.button(text="Удалить франшизу", callback_data=f"admin_franchise_del:{fid}:{page}", icon_custom_emoji_id="5870875489362513438")
    builder.button(text="Назад", callback_data=f"admin_franchises:{page}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("admin_franchise_del:"))
async def admin_franchise_delete(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    fid = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    franchise = await get_franchise_by_id(fid)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    from app.franchise_runner import stop_franchise
    stop_franchise(franchise[2])

    await delete_franchise(fid)
    await call.answer("✅ Франшиза удалена", show_alert=True)

    text, kb = await _build_franchises_page(page)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=kb
        )
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  WITHDRAW REQUESTS — admin management
# ═══════════════════════════════════════════════════════════════════════════

_WR_PER_PAGE = 5


async def _build_withdraws_page(page: int):
    """Build the paginated list of pending withdraw requests."""
    offset = page * _WR_PER_PAGE
    requests = await get_pending_withdraw_requests(limit=_WR_PER_PAGE, offset=offset)
    total = await get_pending_withdraw_count()
    total_pages = max(1, (total + _WR_PER_PAGE - 1) // _WR_PER_PAGE)

    if not requests:
        text = (
            '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Заявки на вывод</b>\n\n'
            '<blockquote>Нет ожидающих заявок.</blockquote>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
        return text, builder.as_markup()

    text = (
        '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> '
        f'<b>Заявки на вывод</b>  —  всего: <b>{total}</b>\n'
        f'<i>Страница {page + 1}/{total_pages}</i>\n\n'
    )
    builder = InlineKeyboardBuilder()
    from datetime import datetime
    for row in requests:
        rid, franchise_id, owner_id, amount, created_at, project_name = row
        dt = datetime.fromtimestamp(created_at).strftime("%d.%m %H:%M")
        pname = project_name or f"#{franchise_id}"
        text += f'<b>#{rid}</b>  {pname}  —  <b>{amount:.0f} ₽</b>  ({dt})\n'
        builder.button(
            text=f"#{rid} · {pname} · {amount:.0f} ₽",
            callback_data=f"adm_wr_view:{rid}:{page}"
        )

    nav = []
    if page > 0:
        nav.append(("◀️", f"admin_withdraws:{page - 1}"))
    if (page + 1) < total_pages:
        nav.append(("▶️", f"admin_withdraws:{page + 1}"))

    rows = [1] * len(requests)
    if nav:
        for t, cb in nav:
            builder.button(text=t, callback_data=cb)
        rows.append(len(nav))
    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
    rows.append(1)
    builder.adjust(*rows)
    return text, builder.as_markup()


@router.callback_query(F.data.startswith("admin_withdraws:"))
async def admin_withdraws_list(call: CallbackQuery, bot: Bot):
    page = int(call.data.split(":")[1])
    text, kb = await _build_withdraws_page(page)
    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id,
            message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=kb
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("adm_wr_view:"))
async def admin_withdraw_view(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    req_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0

    req = await get_withdraw_request(req_id)
    if not req:
        await call.answer("❌ Заявка не найдена", show_alert=True)
        return

    rid, franchise_id, owner_id, amount, status, comment, created_at, resolved_at = req
    if status != 'pending':
        await call.answer("⚠️ Заявка уже обработана", show_alert=True)
        text, kb = await _build_withdraws_page(back_page)
        try:
            await bot.edit_message_text(
                text=text, chat_id=call.from_user.id,
                message_id=call.message.message_id,
                parse_mode="HTML", reply_markup=kb
            )
        except TelegramBadRequest:
            pass
        return

    from datetime import datetime
    franchise = await get_franchise_by_id(franchise_id)
    project_name = franchise[3] if franchise else f"#{franchise_id}"
    dt = datetime.fromtimestamp(created_at).strftime("%d.%m.%Y %H:%M")

    try:
        user_info = await bot.get_chat(owner_id)
        user_display = f"<a href='tg://user?id={owner_id}'>{user_info.full_name}</a>"
    except Exception:
        user_display = f"<code>{owner_id}</code>"

    text = (
        '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Заявка на вывод</b>\n\n'
        '<blockquote>'
        f'🆔 Номер: <b>#{rid}</b>\n'
        f'🏘 Проект: <b>{project_name}</b>\n'
        f'👤 Владелец: {user_display}\n'
        f'💰 Сумма: <b>{amount:.2f} ₽</b>\n'
        f'🕐 Создана: {dt}'
        '</blockquote>'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оплачено", callback_data=f"adm_wr_approve:{req_id}:{back_page}")
    builder.button(text="❌ Отклонить", callback_data=f"adm_wr_reject:{req_id}:{back_page}")
    builder.button(text="Назад к списку", callback_data=f"admin_withdraws:{back_page}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(2, 1)

    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id,
            message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("adm_wr_approve:"))
async def admin_withdraw_approve_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    req_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0

    req = await get_withdraw_request(req_id)
    if not req:
        await call.answer("❌ Заявка не найдена", show_alert=True)
        return
    if req[4] != 'pending':
        await call.answer("⚠️ Заявка уже обработана", show_alert=True)
        return

    rid, franchise_id, owner_id, amount, *_ = req

    await state.set_state(AdminState.wait_withdraw_approve_check)
    await state.update_data(wr_req_id=req_id, wr_back_page=back_page,
                            wr_bot_msg_id=call.message.message_id,
                            wr_amount=amount, wr_owner_id=owner_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data=f"adm_wr_view:{req_id}:{back_page}",
                   icon_custom_emoji_id="5870657884844462243")

    try:
        await bot.edit_message_text(
            chat_id=call.from_user.id, message_id=call.message.message_id,
            text=(
                f'<b>✅ Подтверждение выплаты #{req_id}</b>\n\n'
                f'💰 Сумма: <b>{amount:.2f} ₽</b>\n\n'
                'Введите текст чека CryptoBot (или скриншот-подтверждение), '
                'который будет отправлен владельцу:'
            ),
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.message(AdminState.wait_withdraw_approve_check)
async def admin_withdraw_approve_check(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    req_id = data.get("wr_req_id")
    back_page = data.get("wr_back_page", 0)
    bot_msg_id = data.get("wr_bot_msg_id")
    amount = data.get("wr_amount", 0)
    owner_id = data.get("wr_owner_id")
    check_text = message.text.strip() if message.text else None
    await state.clear()

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if not check_text:
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data=f"admin_withdraws:{back_page}",
                       icon_custom_emoji_id="5870657884844462243")
        try:
            await bot.edit_message_text(
                chat_id=user_id, message_id=bot_msg_id,
                text=(
                    f'<b>✅ Подтверждение выплаты #{req_id}</b>\n\n'
                    '❌ Текст чека не может быть пустым.\n\nВведите текст чека CryptoBot:'
                ),
                parse_mode="HTML", reply_markup=builder.as_markup()
            )
        except TelegramBadRequest:
            pass
        await state.set_state(AdminState.wait_withdraw_approve_check)
        await state.update_data(wr_req_id=req_id, wr_back_page=back_page,
                                wr_bot_msg_id=bot_msg_id, wr_amount=amount,
                                wr_owner_id=owner_id)
        return

    success = await approve_withdraw_request(req_id, check_text)
    if not success:
        try:
            await bot.send_message(user_id, "⚠️ Заявка уже обработана.")
        except Exception:
            pass
        text, kb = await _build_withdraws_page(back_page)
        try:
            await bot.edit_message_text(
                text=text, chat_id=user_id, message_id=bot_msg_id,
                parse_mode="HTML", reply_markup=kb
            )
        except TelegramBadRequest:
            pass
        return

    try:
        await bot.send_message(
            owner_id,
            '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Выплата подтверждена!</b>\n\n'
            f'<blockquote>💰 Сумма: <b>{amount:.2f} ₽</b>\n'
            f'🆔 Заявка: <b>#{req_id}</b></blockquote>\n\n'
            f'<b>Чек:</b>\n<blockquote>{check_text}</blockquote>',
            parse_mode="HTML"
        )
    except Exception:
        pass

    text, kb = await _build_withdraws_page(back_page)
    try:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=bot_msg_id,
            parse_mode="HTML", reply_markup=kb
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("adm_wr_reject:"))
async def admin_withdraw_reject_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    req_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0

    req = await get_withdraw_request(req_id)
    if not req:
        await call.answer("❌ Заявка не найдена", show_alert=True)
        return
    if req[4] != 'pending':
        await call.answer("⚠️ Заявка уже обработана", show_alert=True)
        return

    await state.set_state(AdminState.wait_withdraw_reject_reason)
    await state.update_data(wr_req_id=req_id, wr_back_page=back_page,
                            wr_bot_msg_id=call.message.message_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="Без причины", callback_data=f"adm_wr_reject_confirm:{req_id}:{back_page}:0")
    builder.button(text="Отмена", callback_data=f"admin_withdraws:{back_page}", icon_custom_emoji_id="5870657884844462243")
    builder.adjust(1)

    try:
        await bot.edit_message_text(
            chat_id=call.from_user.id, message_id=call.message.message_id,
            text=(
                f'<b>❌ Отклонение заявки #{req_id}</b>\n\n'
                'Введите причину отклонения или нажмите «Без причины»:'
            ),
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.message(AdminState.wait_withdraw_reject_reason)
async def admin_withdraw_reject_reason(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    req_id = data.get("wr_req_id")
    back_page = data.get("wr_back_page", 0)
    bot_msg_id = data.get("wr_bot_msg_id")
    reason = message.text.strip() if message.text else None
    await state.clear()

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    await _do_reject_withdraw(bot, user_id, bot_msg_id, req_id, back_page, reason)


@router.callback_query(F.data.startswith("adm_wr_reject_confirm:"))
async def admin_withdraw_reject_no_reason(call: CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    req_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0
    await state.clear()
    await _do_reject_withdraw(bot, call.from_user.id, call.message.message_id, req_id, back_page, None)


async def _do_reject_withdraw(bot: Bot, admin_id: int, msg_id: int, req_id: int, back_page: int, reason: Optional[str]):
    req = await get_withdraw_request(req_id)
    if not req:
        return

    rid, franchise_id, owner_id, amount, status, *_ = req
    success = await reject_withdraw_request(req_id, reason)
    if not success:
        try:
            await bot.send_message(admin_id, "⚠️ Заявка уже обработана.", parse_mode="HTML")
        except Exception:
            pass
        return

    # Notify franchise owner
    reason_line = f'\n<i>Причина: {reason}</i>' if reason else ''
    try:
        await bot.send_message(
            owner_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Заявка на вывод отклонена</b>\n\n'
            f'<blockquote>💰 Сумма: <b>{amount:.2f} ₽</b>\n'
            f'🆔 Заявка: <b>#{req_id}</b></blockquote>'
            f'{reason_line}\n\n'
            '<i>Обратитесь в поддержку, если считаете это ошибкой.</i>',
            parse_mode="HTML"
        )
    except Exception:
        pass

    text, kb = await _build_withdraws_page(back_page)
    try:
        await bot.edit_message_text(
            text=text, chat_id=admin_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=kb
        )
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  ADMIN — GIFTS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

async def _build_gifts_page():
    gifts = await get_all_gifts()

    if not gifts:
        text = (
            '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Управление подарками</b>\n\n'
            '<blockquote>Подарки ещё не добавлены.</blockquote>\n\n'
            '<i>Формат добавления:</i>\n'
            '<code>ключ|Название|emoji_id|звёзд|gift_id</code>\n'
            'Пример:\n'
            '<code>work_bear|Медведь|5447213743417105726|50|6026193266406327981</code>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Добавить подарок", callback_data="admin_add_gift",
                       icon_custom_emoji_id="5870676941614354370")
        builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")
        return text, builder.adjust(1).as_markup()

    lines = []
    for g in gifts:
        # (id, key, name, emoji_id, count_stars, gift_id, is_active, added_time)
        status = "✅" if g[6] else "❌"
        lines.append(f"{status} <b>{g[2]}</b> — {g[4]} ⭐  <code>{g[1]}</code>")

    text = (
        '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> '
        f'<b>Управление подарками</b>  —  всего: <b>{len(gifts)}</b>\n\n'
        + "\n".join(lines)
    )

    builder = InlineKeyboardBuilder()
    for g in gifts:
        status_icon = "✅" if g[6] else "❌"
        builder.button(
            text=f"{status_icon} {g[2]} ({g[4]}⭐)",
            callback_data=f"admin_gift_view:{g[1]}",
        )
    builder.button(text="➕ Добавить подарок", callback_data="admin_add_gift",
                   icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Назад", callback_data="adminka", icon_custom_emoji_id="5960671702059848143")

    rows = [1] * len(gifts) + [1, 1]
    return text, builder.adjust(*rows).as_markup()


@router.callback_query(F.data == "admin_gifts")
async def admin_gifts_menu(call: CallbackQuery, bot: Bot, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    text, markup = await _build_gifts_page()
    await bot.edit_message_text(
        chat_id=call.from_user.id, message_id=call.message.message_id,
        text=text, parse_mode="HTML", reply_markup=markup,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("admin_gift_view:"))
async def admin_gift_view(call: CallbackQuery, bot: Bot, state: FSMContext):
    key = call.data.split(":", 1)[1]
    from app.database import get_gift_by_key
    gift = await get_gift_by_key(key)
    if not gift:
        await bot.answer_callback_query(call.id, "❌ Подарок не найден", show_alert=True)
        return

    # (id, key, name, emoji_id, count_stars, gift_id, is_active, added_time)
    status = "✅ Активен" if gift[6] else "❌ Отключён"
    toggle_label = "❌ Отключить" if gift[6] else "✅ Включить"
    text = (
        f'<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Подарок: {gift[2]}</b>\n\n'
        f'<blockquote>'
        f'🔑 Ключ: <code>{gift[1]}</code>\n'
        f'⭐ Звёзд: <b>{gift[4]}</b>\n'
        f'🆔 Gift ID: <code>{gift[5]}</code>\n'
        f'🖼 Emoji ID: <code>{gift[3]}</code>\n'
        f'📌 Статус: {status}'
        f'</blockquote>'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=toggle_label, callback_data=f"admin_gift_toggle:{key}",
                   icon_custom_emoji_id="5870633910337015697")
    builder.button(text="🗑 Удалить", callback_data=f"admin_gift_del:{key}",
                   icon_custom_emoji_id="5870875489362513438")
    builder.button(text="🔙 Назад", callback_data="admin_gifts",
                   icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1).as_markup()
    await bot.edit_message_text(
        chat_id=call.from_user.id, message_id=call.message.message_id,
        text=text, parse_mode="HTML", reply_markup=markup,
    )


@router.callback_query(F.data.startswith("admin_gift_toggle:"))
async def admin_gift_toggle(call: CallbackQuery, bot: Bot):
    key = call.data.split(":", 1)[1]
    from app.database import get_gift_by_key
    gift = await get_gift_by_key(key)
    if not gift:
        await bot.answer_callback_query(call.id, "❌ Подарок не найден", show_alert=True)
        return
    new_state = not bool(gift[6])
    await toggle_gift_active(key, new_state)
    label = "включён" if new_state else "отключён"
    await bot.answer_callback_query(call.id, f"✅ Подарок {label}", show_alert=False)
    # Refresh the view
    call.data = f"admin_gift_view:{key}"
    await admin_gift_view(call, bot, None)


@router.callback_query(F.data.startswith("admin_gift_del:"))
async def admin_gift_del(call: CallbackQuery, bot: Bot):
    key = call.data.split(":", 1)[1]
    deleted = await delete_gift(key)
    if deleted:
        await bot.answer_callback_query(call.id, "🗑 Подарок удалён", show_alert=True)
    else:
        await bot.answer_callback_query(call.id, "❌ Ошибка удаления", show_alert=True)
    text, markup = await _build_gifts_page()
    await bot.edit_message_text(
        chat_id=call.from_user.id, message_id=call.message.message_id,
        text=text, parse_mode="HTML", reply_markup=markup,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "admin_add_gift")
async def admin_add_gift_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AdminState.wait_gift_data)
    await state.update_data(gift_msg_id=call.message.message_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin_gifts",
                   icon_custom_emoji_id="5870657884844462243")

    await bot.edit_message_text(
        chat_id=call.from_user.id, message_id=call.message.message_id,
        text=(
            '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Добавление подарка</b>\n\n'
            'Отправьте данные подарка в одну строку через символ <b>|</b>:\n\n'
            '<code>ключ|Название|emoji_id|звёзд|gift_id</code>\n\n'
            '<b>Пример:</b>\n'
            '<code>work_bear|Медведь 1 мая|5447213743417105726|50|6026193266406327981</code>\n\n'
            '<blockquote>'
            '• <b>ключ</b> — уникальный slug (латиница, цифры, _)\n'
            '• <b>Название</b> — отображается на кнопке\n'
            '• <b>emoji_id</b> — ID кастомного эмодзи для кнопки\n'
            '• <b>звёзд</b> — сколько звёзд стоит подарок\n'
            '• <b>gift_id</b> — ID подарка в Telegram'
            '</blockquote>'
        ),
        parse_mode="HTML", reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
    )


@router.message(AdminState.wait_gift_data)
async def admin_add_gift_submit(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    msg_id = data.get("gift_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    raw = message.text.strip()
    parts = [p.strip() for p in raw.split("|")]

    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin_gifts",
                   icon_custom_emoji_id="5870657884844462243")

    if len(parts) != 5:
        await bot.edit_message_text(
            chat_id=user_id, message_id=msg_id,
            text=(
                "❌ <b>Неверный формат!</b>\n\n"
                "Необходимо ровно 5 параметров через <b>|</b>:\n"
                "<code>ключ|Название|emoji_id|звёзд|gift_id</code>"
            ),
            parse_mode="HTML", reply_markup=builder.as_markup(),
        )
        return

    key, name, emoji_id, stars_raw, gift_id = parts

    if not key.replace("_", "").isalnum():
        await bot.edit_message_text(
            chat_id=user_id, message_id=msg_id,
            text="❌ <b>Ключ</b> должен содержать только латиницу, цифры и _",
            parse_mode="HTML", reply_markup=builder.as_markup(),
        )
        return

    try:
        count_stars = int(stars_raw)
        if count_stars <= 0:
            raise ValueError
    except ValueError:
        await bot.edit_message_text(
            chat_id=user_id, message_id=msg_id,
            text="❌ <b>Количество звёзд</b> должно быть положительным целым числом",
            parse_mode="HTML", reply_markup=builder.as_markup(),
        )
        return

    success = await add_gift(key, name, emoji_id, count_stars, gift_id)
    await state.clear()

    if not success:
        await bot.edit_message_text(
            chat_id=user_id, message_id=msg_id,
            text=f"❌ Не удалось добавить подарок. Ключ <code>{key}</code> уже существует.",
            parse_mode="HTML", reply_markup=builder.as_markup(),
        )
        return

    text, markup = await _build_gifts_page()
    await bot.edit_message_text(
        chat_id=user_id, message_id=msg_id,
        text=text, parse_mode="HTML", reply_markup=markup,
        disable_web_page_preview=True,
    )
