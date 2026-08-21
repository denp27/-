import asyncio
import re
import time
from collections import deque

import aiohttp

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter, TelegramAPIError

from app.states import FranchiseState
from app.database import (
    get_franchise_by_owner, create_franchise, update_franchise_name,
    update_franchise_markup, update_franchise_support_url, set_franchise_photo, get_franchise_photo,
    delete_franchise_photo, get_franchise_required_channels, add_franchise_required_channel,
    remove_franchise_required_channel, get_franchise_users_ids,
    create_withdraw_request, get_franchise_pending_request, get_franchise_withdraw_history,
)

router = Router()

PHOTO_SECTIONS = {
    "stars": "Покупка звёзд",
    "premium": "Покупка премиум",
    "ton": "Покупка TON",
    "nft": "Аренда NFT",
    "numbers": "Аренда номеров",
    "start": "Главная страница",
}


async def _edit(bot: Bot, user_id: int, msg_id: int, text: str, markup):
    try:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=markup
        )
    except TelegramBadRequest:
        try:
            await bot.delete_message(user_id, msg_id)
        except Exception:
            pass
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)


def _back_kb(callback_data: str = "franchise_menu"):
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=callback_data, icon_custom_emoji_id="5960671702059848143")
    return builder.as_markup()


async def _franchise_menu_text_kb(user_id: int):
    franchise = await get_franchise_by_owner(user_id)

    if franchise is None:
        text = (
            '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Франшиза</b>\n\n'
            '<i>Запустите собственный бот на базе нашего сервиса — '
            'с вашим брендом, своей наценкой и дизайном.</i>\n\n'
            '<b>📜 Инструкция по созданию бота:</b>\n'
            '<blockquote>'
            '<b>1.</b> Перейдите в @BotFather и пропишите /newbot\n'
            '<b>2.</b> Введите имя бота, затем его @username\n'
            '<b>3.</b> Заполните разделы About и Description\n'
            '<b>4.</b> Скопируйте токен и отправьте его сюда'
            '</blockquote>\n\n'
            '<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Нажмите кнопку ниже, чтобы создать франшизу:</b>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Создать франшизу", callback_data="franchise_create", icon_custom_emoji_id="5870676941614354370")
        builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
        builder.adjust(1)
    else:
        fid, owner_id, bot_token, project_name, markup, is_active, total_earned = franchise[:7]
        token_preview = bot_token[:10] + "..." + bot_token[-5:] if len(bot_token) > 15 else bot_token
        status_line = (
            '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Активна</b>'
            if is_active else
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Неактивна</b>'
        )
        text = (
            '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Управление франшизой</b>\n\n'
            '<blockquote>'
            f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Проект:</b> {project_name}\n'
            f'<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Токен:</b> <code>{token_preview}</code>\n'
            f'<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Статус:</b> {status_line}'
            '</blockquote>\n\n'
            '<blockquote>'
            f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Ваша наценка:</b> {markup}%\n'
            f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Всего заработано:</b> {total_earned:.2f} ₽'
            '</blockquote>\n\n'
            '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Выберите действие ниже:</i>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Название", callback_data="franchise_edit_name", icon_custom_emoji_id="5870676941614354370")
        builder.button(text="Наценка", callback_data="franchise_edit_markup", icon_custom_emoji_id="5870930636742595124")
        builder.button(text="Фото", callback_data="franchise_photos", icon_custom_emoji_id="6035128606563241721")
        builder.button(text="Каналы", callback_data="franchise_channels", icon_custom_emoji_id="6039422865189638057")
        builder.button(text="Рассылка", callback_data="franchise_mailing", icon_custom_emoji_id="6039422865189638057")
        builder.button(text="Поддержка", callback_data="franchise_edit_support", icon_custom_emoji_id="6039422865189638057")
        builder.button(text="Вывод баланса", callback_data="franchise_withdraw", icon_custom_emoji_id="5879814368572478751")
        builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
        builder.adjust(2, 2, 2, 1, 1)

    return text, builder.as_markup()


                                                                                

@router.callback_query(F.data.in_({"franchise", "franchise_menu"}))
async def franchise_menu_handler(call: CallbackQuery, bot: Bot, state: FSMContext):
    await call.answer()
    await state.clear()
    text, kb = await _franchise_menu_text_kb(call.from_user.id)
    await _edit(bot, call.from_user.id, call.message.message_id, text, kb)


                                                                                

@router.callback_query(F.data == "franchise_create")
async def franchise_create_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id

    if not call.from_user.is_premium:
        await call.answer(
            "⭐️ Создание франшизы доступно только пользователям с Telegram Premium.",
            show_alert=True
        )
        return

    if await get_franchise_by_owner(user_id):
        await call.answer("❌ У вас уже есть франшиза!", show_alert=True)
        return

    text = (
        '<tg-emoji emoji-id="5873147866364514353">🏘</tg-emoji> <b>Создание франшизы</b>\n\n'
        '<i>Запустите собственного бота на базе нашего сервиса.</i>\n\n'
        '<b>📜 Инструкция:</b>\n'
        '<blockquote>'
        '<b>1.</b> Перейдите в @BotFather и пропишите /newbot\n'
        '<b>2.</b> Введите имя бота, затем его @username\n'
        '<b>3.</b> Заполните разделы About и Description\n'
        '<b>4.</b> Скопируйте токен и отправьте его сюда'
        '</blockquote>\n\n'
        '<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Пришлите токен нового бота:</b>'
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_token)
    await state.update_data(bot_msg_id=call.message.message_id)


@router.message(FranchiseState.wait_token)
async def process_franchise_token(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    token = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.telegram.org/bot{token}/getMe") as resp:
            result = await resp.json()

    if not result.get("ok"):
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Неверный токен!</b>\n\n'
            '<blockquote>Проверьте токен в @BotFather и попробуйте снова.</blockquote>\n\n'
            '<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Пришлите токен нового бота:</b>',
            _back_kb("franchise_menu")
        )
        return

    bot_username = result["result"].get("username", "")
    await state.update_data(token=token, bot_username=bot_username)

    text = (
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Бот найден:</b> @{bot_username}\n\n'
        '<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Введите название вашего проекта</b>\n\n'
        '<blockquote>'
        'Это название будет отображаться вместо «MstiStars» в вашем боте.\n'
        'Максимум 50 символов.'
        '</blockquote>\n\n'
        '📝 Пример: <code>MyStars</code>'
    )
    await _edit(bot, user_id, bot_msg_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_project_name)


@router.message(FranchiseState.wait_project_name)
async def process_franchise_name(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    project_name = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if len(project_name) > 50:
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Слишком длинное название</b>\n\n'
            '<blockquote>Максимум 50 символов. Попробуйте снова:</blockquote>',
            _back_kb("franchise_menu")
        )
        return

    await state.update_data(project_name=project_name)

    text = (
        f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Название:</b> {project_name}\n\n'
        '<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Укажите вашу наценку (%)</b>\n\n'
        '<blockquote>'
        'Наценка добавляется поверх основной наценки сервиса.\n'
        'Разрешённый диапазон: от 0 до 100%.'
        '</blockquote>\n\n'
        '📝 Пример: <code>5</code> (для 5%)'
    )
    await _edit(bot, user_id, bot_msg_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_markup)


@router.message(FranchiseState.wait_markup)
async def process_franchise_markup(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    try:
        markup_val = float(message.text.strip())
    except (ValueError, AttributeError):
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Введите корректное число. Например: <code>5</code>',
            _back_kb("franchise_menu")
        )
        return

    if markup_val < 0 or markup_val > 100:
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Наценка должна быть от 0 до 100%.',
            _back_kb("franchise_menu")
        )
        return

    token = data["token"]
    project_name = data["project_name"]
    bot_username = data.get("bot_username", "")

    success = await create_franchise(user_id, token, project_name, markup_val)
    await state.clear()

    if success:
        from app.franchise_runner import start_franchise
        from app.database import get_franchise_by_owner as _get_f
        new_f = await _get_f(user_id)
        start_franchise(token, new_f[0] if new_f else 0)
        text = (
            '<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> <b>Франшиза успешно создана!</b>\n\n'
            '<blockquote>'
            f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> <b>Название:</b> {project_name}\n'
            f'<tg-emoji emoji-id="6030400221232501136">🤖</tg-emoji> <b>Бот:</b> @{bot_username}\n'
            f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Наценка:</b> {markup_val}%'
            '</blockquote>\n\n'
            '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Настройте фотографии и управляйте своей франшизой.</i>'
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5870982283724328568")
        await _edit(bot, user_id, bot_msg_id, text, builder.as_markup())
    else:
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Ошибка при создании франшизы.</b>\n\n'
            '<blockquote>Возможно, данный токен уже используется.</blockquote>',
            _back_kb("franchise_menu")
        )


                                                                                

@router.callback_query(F.data == "franchise_edit_name")
async def franchise_edit_name_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    text = (
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Изменение названия проекта</b>\n\n'
        '<blockquote>'
        f'Текущее название: <b>{franchise[3]}</b>'
        '</blockquote>\n\n'
        'Введите новое название (максимум 50 символов):'
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_edit_name)
    await state.update_data(bot_msg_id=call.message.message_id)


@router.message(FranchiseState.wait_edit_name)
async def process_franchise_edit_name(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    new_name = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if len(new_name) > 50:
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Название слишком длинное (максимум 50 символов). Попробуйте снова:',
            _back_kb("franchise_menu")
        )
        return

    await update_franchise_name(user_id, new_name)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5870982283724328568")
    await _edit(
        bot, user_id, bot_msg_id,
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Название успешно изменено!</b>\n\n'
        f'<blockquote>'
        f'<tg-emoji emoji-id="5870801517140775623">🔗</tg-emoji> Новое название: <b>{new_name}</b>'
        f'</blockquote>',
        builder.as_markup()
    )


                                                                                

@router.callback_query(F.data == "franchise_edit_markup")
async def franchise_edit_markup_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    text = (
        '<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Изменение наценки</b>\n\n'
        '<blockquote>'
        f'Текущая наценка: <b>{franchise[4]}%</b>'
        '</blockquote>\n\n'
        'Введите новую наценку (от 0 до 100%):\n'
        '📝 Пример: <code>10</code>'
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_edit_markup)
    await state.update_data(bot_msg_id=call.message.message_id)


@router.message(FranchiseState.wait_edit_markup)
async def process_franchise_edit_markup(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    try:
        markup_val = float(message.text.strip())
    except (ValueError, AttributeError):
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Введите корректное число. Например: <code>10</code>',
            _back_kb("franchise_menu")
        )
        return

    if markup_val < 0 or markup_val > 100:
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Наценка должна быть от 0 до 100%.',
            _back_kb("franchise_menu")
        )
        return

    await update_franchise_markup(user_id, markup_val)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5870982283724328568")
    await _edit(
        bot, user_id, bot_msg_id,
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Наценка успешно изменена!</b>\n\n'
        f'<blockquote>'
        f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> Новая наценка: <b>{markup_val}%</b>'
        f'</blockquote>',
        builder.as_markup()
    )


                                                                                

async def _show_photos_menu(bot: Bot, user_id: int, msg_id: int, franchise_id: int):
    text = (
        '<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> <b>Управление фотографиями</b>\n\n'
        '<blockquote>'
        'Установите фото для каждого раздела — оно будет отображаться '
        'при открытии соответствующего меню в вашем боте.'
        '</blockquote>\n\n'
        '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Выберите раздел:</i>'
    )
    builder = InlineKeyboardBuilder()
    for section_key, section_name in PHOTO_SECTIONS.items():
        photo = await get_franchise_photo(franchise_id, section_key)
        emoji_id = "5870633910337015697" if photo else "5870676941614354370"
        builder.button(text=section_name, callback_data=f"franchise_photo_{section_key}", icon_custom_emoji_id=emoji_id)
    builder.button(text="Назад", callback_data="franchise_menu", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)
    await _edit(bot, user_id, msg_id, text, builder.as_markup())


@router.callback_query(F.data == "franchise_photos")
async def franchise_photos_menu(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return
    await state.update_data(bot_msg_id=call.message.message_id)
    await _show_photos_menu(bot, user_id, call.message.message_id, franchise[0])


@router.callback_query(F.data.startswith("franchise_photo_"))
async def franchise_photo_section(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    section = call.data.replace("franchise_photo_", "")

    if section not in PHOTO_SECTIONS:
        await call.answer("❌ Неизвестный раздел", show_alert=True)
        return

    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    fid = franchise[0]
    section_name = PHOTO_SECTIONS[section]
    existing_photo = await get_franchise_photo(fid, section)

    builder = InlineKeyboardBuilder()
    if existing_photo:
        builder.button(text="Удалить фото", callback_data=f"franchise_photo_del_{section}", icon_custom_emoji_id="5870875489362513438")
    builder.button(text="Назад", callback_data="franchise_photos", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    status_line = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Фото установлено.'
        if existing_photo else
        '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Фото не установлено.'
    )
    text = (
        f'<tg-emoji emoji-id="6035128606563241721">🖼</tg-emoji> <b>Раздел «{section_name}»</b>\n\n'
        f'<blockquote>{status_line}</blockquote>\n\n'
        'Отправьте новое фото для этого раздела:'
    )
    await _edit(bot, user_id, call.message.message_id, text, builder.as_markup())
    await state.set_state(FranchiseState.wait_photo)
    await state.update_data(photo_section=section, bot_msg_id=call.message.message_id)


@router.callback_query(F.data.startswith("franchise_photo_del_"))
async def franchise_photo_delete(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    section = call.data.replace("franchise_photo_del_", "")
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    await delete_franchise_photo(franchise[0], section)
    await call.answer("✅ Фото удалено", show_alert=False)
    await state.update_data(bot_msg_id=call.message.message_id)
    await _show_photos_menu(bot, user_id, call.message.message_id, franchise[0])


@router.callback_query(F.data == "franchise_edit_support")
async def franchise_edit_support_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    current = franchise[7] if franchise and len(franchise) > 7 else None
    current_line = f'Текущая ссылка: <code>{current}</code>' if current else 'Ссылка не установлена.'
    text = (
        '<tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> <b>Ссылка на тех. поддержку</b>\n\n'
        f'<blockquote>{current_line}</blockquote>\n\n'
        'Введите новую ссылку на поддержку:\n'
        '📝 Пример: <code>https://t.me/support</code>\n\n'
        '<i>Или отправьте «-» чтобы убрать ссылку.</i>'
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_edit_support_url)
    await state.update_data(bot_msg_id=call.message.message_id)


@router.message(FranchiseState.wait_edit_support_url)
async def process_franchise_edit_support(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    text_input = message.text.strip() if message.text else ""

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if text_input == '-':
        new_url = None
    elif not (text_input.startswith('https://') or text_input.startswith('http://')):
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Неверный формат ссылки.\n\n'
            'Ссылка должна начинаться с <code>https://</code> или <code>http://</code>',
            _back_kb("franchise_menu")
        )
        return
    else:
        new_url = text_input

    await update_franchise_support_url(user_id, new_url)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5873147866364514353")
    result_text = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Ссылка на поддержку обновлена!</b>\n\n'
        f'<blockquote>{"Удалена" if new_url is None else f"Новая ссылка: <code>{new_url}</code>"}</blockquote>'
    )
    await _edit(bot, user_id, bot_msg_id, result_text, builder.as_markup())


@router.message(FranchiseState.wait_photo)
async def process_franchise_photo(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    section = data.get("photo_section")
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if not message.photo:
        section_name = PHOTO_SECTIONS.get(section, section) if section else "?"
        await _edit(
            bot, user_id, bot_msg_id,
            f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Нужно фото, не файл</b>\n\n'
            f'<blockquote>Раздел «{section_name}»</blockquote>\n\n'
            'Отправьте фотографию:',
            _back_kb("franchise_photos")
        )
        return

    franchise = await get_franchise_by_owner(user_id)
    if not franchise or not section:
        await state.clear()
        return

    file_id = message.photo[-1].file_id
    await set_franchise_photo(franchise[0], section, file_id)
    await state.clear()

    section_name = PHOTO_SECTIONS.get(section, section)
    builder = InlineKeyboardBuilder()
    builder.button(text="К фотографиям", callback_data="franchise_photos", icon_custom_emoji_id="6035128606563241721")
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5873147866364514353")
    builder.adjust(1)
    await _edit(
        bot, user_id, bot_msg_id,
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Фото для раздела «{section_name}» установлено!</b>',
        builder.as_markup()
    )


                                                                                

async def _show_franchise_channels(bot: Bot, user_id: int, msg_id: int, franchise_id: int):
    channels = await get_franchise_required_channels(franchise_id)
    builder = InlineKeyboardBuilder()
    if channels:
        text = '<tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> <b>Обязательные каналы вашего бота:</b>\n\n'
        for i, (channel_id, channel_url, channel_name) in enumerate(channels, 1):
            display_name = channel_name if channel_name else f"Канал {i}"
            text += f"{i}. <b>{display_name}</b>\n   ├ ID: <code>{channel_id}</code>\n   └ URL: {channel_url}\n\n"
            builder.button(text=f"🗑 Удалить {display_name}", callback_data=f"fr_rm_ch:{i-1}")
        builder.adjust(1)
    else:
        text = '<tg-emoji emoji-id="6039422865189638057">📣</tg-emoji> <b>Обязательные каналы для вашего бота</b>\n\n❌ Каналы не настроены'

    builder.button(text="➕ Добавить канал", callback_data="fr_add_ch", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="⬅️ Назад", callback_data="franchise_menu", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)
    await _edit(bot, user_id, msg_id, text, builder.as_markup())


@router.callback_query(F.data == "franchise_channels")
async def franchise_channels_menu(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return
    await state.update_data(bot_msg_id=call.message.message_id)
    await _show_franchise_channels(bot, user_id, call.message.message_id, franchise[0])


@router.callback_query(F.data == "fr_add_ch")
async def fr_add_channel_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return
    text = (
        "<b>➕ Добавление обязательного канала</b>\n\n"
        "⬇️ <b>Введите ID канала</b> (числовой, начинается с -):\n\n"
        "📝 Пример: <code>-1001234567890</code>"
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_channels"))
    await state.set_state(FranchiseState.wait_channel_id)
    await state.update_data(bot_msg_id=call.message.message_id, franchise_id=franchise[0])


@router.message(FranchiseState.wait_channel_id)
async def fr_process_channel_id(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    channel_id = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if not channel_id.startswith('-') or not channel_id[1:].isdigit():
        await _edit(
            bot, user_id, bot_msg_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Неверный формат ID!\n\n'
            'ID должен быть числом, начинающимся с «-»\n📝 Пример: <code>-1001234567890</code>',
            _back_kb("franchise_channels")
        )
        return

    try:
        from aiogram.exceptions import TelegramBadRequest as TBR
        chat = await bot.get_chat(channel_id)
        if chat.type not in ['channel', 'supergroup']:
            await _edit(bot, user_id, bot_msg_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Это не канал/супергруппа.', _back_kb("franchise_channels"))
            await state.clear()
            return
        bot_member = await bot.get_chat_member(channel_id, bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await _edit(bot, user_id, bot_msg_id, f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Бот не является администратором канала <b>{chat.title}</b>. Добавьте бота как админа.', _back_kb("franchise_channels"))
            await state.clear()
            return
    except Exception as e:
        await _edit(bot, user_id, bot_msg_id, f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Канал не найден или ошибка: <code>{e}</code>', _back_kb("franchise_channels"))
        await state.clear()
        return

    await state.update_data(new_channel_id=channel_id, new_channel_title=chat.title)
    text = (
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Канал найден: <b>{chat.title}</b>\n\n'
        '⬇️ <b>Введите URL для подписки:</b>\n📝 Пример: <code>https://t.me/yourchannel</code>'
    )
    await _edit(bot, user_id, bot_msg_id, text, _back_kb("franchise_channels"))
    await state.set_state(FranchiseState.wait_channel_url)


@router.message(FranchiseState.wait_channel_url)
async def fr_process_channel_url(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    url = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    if not (url.startswith('https://t.me/') or url.startswith('http://t.me/')):
        await _edit(bot, user_id, bot_msg_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> URL должен начинаться с <code>https://t.me/</code>', _back_kb("franchise_channels"))
        return

    await state.update_data(new_channel_url=url)
    await _edit(
        bot, user_id, bot_msg_id,
        '<b>➕ Добавление канала</b>\n\n⬇️ <b>Введите название канала</b> (будет на кнопке):\n\n<i>Или «-» чтобы не указывать</i>',
        _back_kb("franchise_channels")
    )
    await state.set_state(FranchiseState.wait_channel_name)


@router.message(FranchiseState.wait_channel_name)
async def fr_process_channel_name(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    name_input = message.text.strip() if message.text else ""
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    franchise_id = data.get("franchise_id")
    channel_id = data.get("new_channel_id")
    channel_url = data.get("new_channel_url")

    try:
        await bot.delete_message(user_id, message.message_id)
    except Exception:
        pass

    channel_name = None if name_input == '-' else name_input
    success = await add_franchise_required_channel(franchise_id, channel_id, channel_url, channel_name)
    await state.clear()

    if success:
        builder = InlineKeyboardBuilder()
        builder.button(text="К каналам", callback_data="franchise_channels", icon_custom_emoji_id="6039422865189638057")
        await _edit(
            bot, user_id, bot_msg_id,
            f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Канал добавлен!</b>\n\n'
            f'<blockquote>ID: <code>{channel_id}</code>\nURL: {channel_url}</blockquote>',
            builder.as_markup()
        )
    else:
        await _edit(bot, user_id, bot_msg_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибка! Канал уже добавлен.', _back_kb("franchise_channels"))


@router.callback_query(F.data.startswith("fr_rm_ch:"))
async def fr_remove_channel(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    idx = int(call.data.split(":")[1])
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return
    channels = await get_franchise_required_channels(franchise[0])
    if idx >= len(channels):
        await call.answer("❌ Канал не найден", show_alert=True)
        return
    channel_id, _, _ = channels[idx]
    await remove_franchise_required_channel(franchise[0], channel_id)
    await call.answer("✅ Канал удалён", show_alert=False)
    await _show_franchise_channels(bot, user_id, call.message.message_id, franchise[0])


                                                                                

@router.callback_query(F.data == "franchise_mailing")
async def franchise_mailing_start(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return
    text = (
        '<tg-emoji emoji-id="6039422865189638057">📢</tg-emoji> <b>Рассылка по вашей базе</b>\n\n'
        '<blockquote>Введите текст рассылки. Поддерживается HTML-форматирование и фото.\n\n'
        'Чтобы добавить кнопки, используйте формат:\n<code>{Текст кнопки}:https://link.com</code></blockquote>'
    )
    await _edit(bot, user_id, call.message.message_id, text, _back_kb("franchise_menu"))
    await state.set_state(FranchiseState.wait_mailing_text)
    await state.update_data(bot_msg_id=call.message.message_id)


@router.message(FranchiseState.wait_mailing_text)
async def fr_process_mailing(message: Message, bot: Bot, state: FSMContext, franchise_id: int):
    user_id = message.from_user.id
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

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

    from aiogram.utils.text_decorations import HtmlDecoration
    formatted_text = HtmlDecoration().unparse(text, entities)

    await state.clear()

    users = await get_franchise_users_ids(franchise_id)
    total = len(users)
    if not total:
        await bot.edit_message_text(
            chat_id=user_id, message_id=bot_msg_id,
            text='<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Нет пользователей для рассылки.',
            parse_mode="HTML", reply_markup=_back_kb("franchise_menu")
        )
        return

    await bot.edit_message_text(
        chat_id=user_id, message_id=bot_msg_id,
        text='<tg-emoji emoji-id="6039422865189638057">📢</tg-emoji> <b>Рассылка начата...</b>\n\n⏳ Подождите.',
        parse_mode="HTML"
    )

    success = 0
    failed = 0
    semaphore = asyncio.Semaphore(20)
    start_time = time.time()

    async def send_one(uid: int):
        nonlocal success, failed
        async with semaphore:
            try:
                if photo_file_id:
                    await bot.send_photo(uid, photo=photo_file_id, caption=formatted_text, parse_mode="HTML", reply_markup=keyboard)
                else:
                    await bot.send_message(uid, formatted_text, parse_mode="HTML", reply_markup=keyboard)
                success += 1
            except (TelegramForbiddenError, TelegramNotFound):
                failed += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    if photo_file_id:
                        await bot.send_photo(uid, photo=photo_file_id, caption=formatted_text, parse_mode="HTML", reply_markup=keyboard)
                    else:
                        await bot.send_message(uid, formatted_text, parse_mode="HTML", reply_markup=keyboard)
                    success += 1
                except Exception:
                    failed += 1
            except Exception:
                failed += 1

    await asyncio.gather(*[send_one(uid) for uid in users], return_exceptions=True)

    elapsed = time.time() - start_time
    builder = InlineKeyboardBuilder()
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5873147866364514353")
    try:
        await bot.edit_message_text(
            chat_id=user_id, message_id=bot_msg_id,
            text=(
                '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Рассылка завершена!</b>\n\n'
                '<blockquote>'
                f'✅ Успешно: <b>{success}</b>\n'
                f'❌ Ошибок: <b>{failed}</b>\n'
                f'📊 Всего: <b>{total}</b>\n'
                f'⏱ Время: <b>{elapsed:.1f}</b> сек'
                '</blockquote>'
            ),
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except TelegramBadRequest:
        pass


                                                                                

@router.callback_query(F.data == "franchise_withdraw")
async def franchise_withdraw_show(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    await state.clear()
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    franchise_id = franchise[0]
    total_earned = float(franchise[6] or 0)

    pending = await get_franchise_pending_request(franchise_id)
    history = await get_franchise_withdraw_history(franchise_id, limit=5)

    text = (
        '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Вывод баланса</b>\n\n'
        '<blockquote>'
        f'<tg-emoji emoji-id="5870930636742595124">📊</tg-emoji> <b>Баланс:</b> {total_earned:.2f} ₽\n'
    )
    if pending:
        req_id, req_amount, req_ts = pending
        from datetime import datetime
        dt = datetime.fromtimestamp(req_ts).strftime("%d.%m.%Y %H:%M")
        text += (
            f'<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Заявка #{ req_id} на рассмотрении</b>\n'
            f'   Сумма: {req_amount:.2f} ₽  ·  {dt}'
        )
    text += '</blockquote>'

    if history:
        STATUS_EMOJI = {'pending': '⏳', 'paid': '✅', 'rejected': '❌'}
        STATUS_RU    = {'pending': 'В обработке', 'paid': 'Оплачено', 'rejected': 'Отклонено'}
        text += '\n\n<b>📋 История (последние 5):</b>\n<blockquote>'
        for row in history:
            rid, ramount, rstatus, rcomment, rts, _ = row
            from datetime import datetime as _dt
            dts = _dt.fromtimestamp(rts).strftime("%d.%m")
            em = STATUS_EMOJI.get(rstatus, '?')
            ru = STATUS_RU.get(rstatus, rstatus)
            line = f'{em} #{rid} — {ramount:.0f} ₽ — {ru} ({dts})'
            if rcomment and rstatus == 'rejected':
                line += f'\n   <i>↳ {rcomment}</i>'
            text += line + '\n'
        text += '</blockquote>'

    builder = InlineKeyboardBuilder()
    if not pending and total_earned >= 1000:
        builder.button(
            text=f"Создать заявку ({total_earned:.0f} ₽)",
            callback_data="franchise_withdraw_create",
            icon_custom_emoji_id="5879814368572478751"
        )
    elif not pending and total_earned < 1000:
        text += f'\n\n<i>Минимальная сумма вывода: 1000 ₽</i>'
    builder.button(text="Назад", callback_data="franchise_menu", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    await call.answer()
    await _edit(bot, user_id, call.message.message_id, text, builder.as_markup())


@router.callback_query(F.data == "franchise_withdraw_create")
async def franchise_withdraw_create(call: CallbackQuery, bot: Bot, state: FSMContext):
    from app.config import ADMINS_IDS, TOKEN as _MAIN_TOKEN

    user_id = call.from_user.id
    franchise = await get_franchise_by_owner(user_id)
    if not franchise:
        await call.answer("❌ Франшиза не найдена", show_alert=True)
        return

    franchise_id = franchise[0]
    project_name = franchise[3]
    total_earned = float(franchise[6] or 0)

    if total_earned < 1000:
        await call.answer("❌ Минимальная сумма вывода: 1000 ₽", show_alert=True)
        return

    req_id = await create_withdraw_request(franchise_id, user_id, total_earned)
    if req_id is None:
        await call.answer("❌ У вас уже есть активная заявка на вывод", show_alert=True)
        return

    await call.answer("✅ Заявка создана", show_alert=False)

    builder = InlineKeyboardBuilder()
    builder.button(text="Управление франшизой", callback_data="franchise_menu", icon_custom_emoji_id="5873147866364514353")
    await _edit(
        bot, user_id, call.message.message_id,
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Заявка на вывод создана!</b>\n\n'
        f'<blockquote>'
        f'💰 Сумма: <b>{total_earned:.2f} ₽</b>\n'
        f'🆔 Номер заявки: <b>#{req_id}</b>'
        f'</blockquote>\n\n'
        '<i>Ожидайте подтверждения администратора. '
        'Средства будут зачислены после проверки.</i>',
        builder.as_markup()
    )

    try:
        user_info = await bot.get_chat(user_id)
        user_display = f"<a href='tg://user?id={user_id}'>{user_info.full_name}</a>"
    except Exception:
        user_display = f"<code>{user_id}</code>"

    admin_text = (
        '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Новая заявка на вывод!</b>\n\n'
        '<blockquote>'
        f'🆔 Заявка: <b>#{req_id}</b>\n'
        f'👤 Владелец: {user_display}\n'
        f'🏘 Проект: <b>{project_name}</b>\n'
        f'💰 Сумма: <b>{total_earned:.2f} ₽</b>'
        '</blockquote>'
    )
    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(text="✅ Оплачено", callback_data=f"adm_wr_approve:{req_id}")
    admin_kb.button(text="❌ Отклонить", callback_data=f"adm_wr_reject:{req_id}")
    admin_kb.adjust(2)

    main_bot = Bot(token=_MAIN_TOKEN)
    try:
        for admin_id in ADMINS_IDS:
            try:
                await main_bot.send_message(
                    admin_id, admin_text,
                    parse_mode="HTML", reply_markup=admin_kb.as_markup()
                )
            except Exception:
                pass
    finally:
        await main_bot.session.close()

