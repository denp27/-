import asyncio
from decimal import Decimal

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import (
    get_balance, deincrement_balance, increment_balance, add_transaction,
    get_active_gifts, get_gift_by_key,
)
from app.helpers import exit_button, ebal_button, effective_markup, send_admin_notification
from app.states import UserState
from app.config import COMMISSION_STARS, SUPPORT_URL
from app.utils.fragmentapi import StarSender
from app.queue_manager import purchase_queue
from app.pyrogram_client import get_pyrogram_client

router = Router()
fragment = StarSender()
_fragment_lock = asyncio.Lock()


async def show_hidden_gifts(call: CallbackQuery, bot: Bot, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass

    user_id = call.from_user.id
    text = (
        "<b><tg-emoji emoji-id='6032644646587338669'>🎁</tg-emoji> Покупка подарка</b>\n\n"
        "<tg-emoji emoji-id='6032850693348399258'>🔎</tg-emoji> Выберите, кому будем отправлять подарок:"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Себе", callback_data="self_gift")
    builder.button(text="👥 Другу", callback_data="friend_gift")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    markup = builder.adjust(2, 1).as_markup()
    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=markup
    )


@router.callback_query(F.data == "hidden_gifts")
async def hidden_gifts_handler(call: CallbackQuery, bot: Bot, state: FSMContext):
    await show_hidden_gifts(call, bot, state)


@router.callback_query(F.data.in_({"self_gift", "friend_gift"}))
async def show_gifts(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    type_gift = call.data.split("_")[0]

    if type_gift == "self":
        username = call.from_user.username
        if not username:
            await bot.answer_callback_query(
                call.id,
                "❌ У вас нет username! Установите username в настройках Telegram.",
                show_alert=True
            )
            return
        await state.update_data(receiver=username, franchise_id=franchise_id)
        await show_gifts_list(call, username, bot, franchise_id=franchise_id)

    elif type_gift == "friend":
        username = call.from_user.username
        text = (
            "<b><tg-emoji emoji-id='6032644646587338669'>🎁</tg-emoji> Покупка подарка другу</b>\n\n"
            "<tg-emoji emoji-id='6032850693348399258'>🔎</tg-emoji> Введите <b>юзернейм пользователя</b>, "
            "которому будем дарить подарок:\n"
            f"— Пример: <code>@{username if username else 'exampleuser'}</code>"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="hidden_gifts")
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=call.message.message_id,
            parse_mode='HTML', reply_markup=builder.as_markup()
        )
        await state.set_state(UserState.wait_gift_username)
        await state.update_data(message_id=call.message.message_id, franchise_id=franchise_id)


@router.message(UserState.wait_gift_username)
async def get_gift_username(message: Message, bot: Bot, state: FSMContext):
    username = message.text.strip()
    try:
        await bot.delete_message(message.from_user.id, message.message_id)
    except Exception:
        pass

    user_id = message.from_user.id
    data = await state.get_data()
    msg_id = data.get("message_id")
    franchise_id: int = data.get("franchise_id", 0)

    app = get_pyrogram_client()
    if app is None:
        await bot.edit_message_text(
            text="<b>❌ Сервис временно недоступен. Попробуйте позже.</b>",
            chat_id=user_id, message_id=msg_id, parse_mode='HTML',
            reply_markup=await exit_button()
        )
        await state.clear()
        return

    try:
        if username.startswith("@"):
            username = username[1:]
        chat = await app.get_chat(username)
        if chat.type.name != "PRIVATE":
            await bot.edit_message_text(
                text=(
                    "<b>❌ Указанный юзернейм установлен не у пользователя!</b>\n\n"
                    "Убедитесь, что вы ввели правильный юзернейм и попробуйте снова."
                ),
                chat_id=user_id, message_id=msg_id, parse_mode='HTML',
                reply_markup=await exit_button()
            )
            await state.clear()
            return
    except Exception:
        await bot.edit_message_text(
            text=(
                "<b>❌ Неверный юзернейм!</b>\n\n"
                "Убедитесь, что вы ввели правильный юзернейм и попробуйте снова."
            ),
            chat_id=user_id, message_id=msg_id, parse_mode='HTML',
            reply_markup=await exit_button()
        )
        await state.clear()
        return

    await state.update_data(receiver=username)
    await show_gifts_list(message, username, bot, msg_id, franchise_id=franchise_id)


async def show_gifts_list(
    call: CallbackQuery | Message,
    username: str,
    bot: Bot,
    msg_id: int = None,
    franchise_id: int = 0,
):
    user_id = call.from_user.id

    try:
        price = await fragment.get_price_star()
        commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
        star_price = price * (Decimal("1") + commission / Decimal("100"))
        star_price = star_price.quantize(Decimal("0.01"))
        if star_price <= Decimal("0.01"):
            star_price = Decimal("1.65")
    except Exception:
        star_price = Decimal("1.65")

    gifts = await get_active_gifts()

    text = (
        f"<b><tg-emoji emoji-id='6032644646587338669'>🎁</tg-emoji> Покупка подарка</b>\n\n"
        f"<b><tg-emoji emoji-id='6032693626394382504'>👤</tg-emoji> Получатель: @{username}</b>\n\n"
        "<tg-emoji emoji-id='6032850693348399258'>🔎</tg-emoji> Выберите нужный подарок для покупки:"
    )

    builder = InlineKeyboardBuilder()

    if not gifts:
        text += "\n\n<i>Подарки временно недоступны.</i>"
    else:
        for gift in gifts:
            gift_key = gift[1]
            name = gift[2]
            emoji_id = gift[3]
            count_stars = gift[4]
            cost = float(count_stars * star_price)
            builder.button(
                text=f"{name} | {cost:.0f} ₽",
                callback_data=f"bg:{gift_key}",
                icon_custom_emoji_id=emoji_id,
            )

    builder.button(text="🔙 Назад", callback_data="hidden_gifts")

    n = len(gifts)
    rows = [2] * (n // 2)
    if n % 2:
        rows.append(1)
    rows.append(1)
    markup = builder.adjust(*rows).as_markup()

    if isinstance(call, CallbackQuery):
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=call.message.message_id,
            parse_mode='HTML', reply_markup=markup
        )
    else:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=msg_id,
            parse_mode='HTML', reply_markup=markup
        )


@router.callback_query(F.data.startswith('bg:'))
async def buy_gift_prelast(call: CallbackQuery, bot: Bot, state: FSMContext):
    gift_key = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    data = await state.get_data()
    is_anonymous = data.get("gift_anonymous", "Нет")

    await state.update_data(gift=gift_key)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Анонимно: {is_anonymous}",
        icon_custom_emoji_id='6032625495328165724',
        callback_data='gift_toggle_anon',
    )
    builder.button(text="📤 Отправить подарок", callback_data="send_gift_now")
    builder.button(text="🔙 Назад", callback_data="back_to_gifts")
    markup = builder.adjust(1).as_markup()

    await bot.edit_message_text(
        text=(
            "<b>🎁 Подтверждение отправки подарка</b>\n\n"
            f"<b>Анонимность:</b> {is_anonymous}\n\n"
            "<i>Нажмите кнопку ниже, чтобы отправить подарок.</i>"
        ),
        chat_id=user_id,
        message_id=call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup,
    )


@router.callback_query(F.data == 'gift_toggle_anon')
async def toggle_gift_anon(call: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    current = data.get("gift_anonymous", "Нет")
    new_status = "Да" if current == "Нет" else "Нет"
    await state.update_data(gift_anonymous=new_status)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Анонимно: {new_status}",
        icon_custom_emoji_id='6032625495328165724',
        callback_data='gift_toggle_anon',
    )
    builder.button(text="📤 Отправить подарок", callback_data="send_gift_now")
    builder.button(text="🔙 Назад", callback_data="back_to_gifts")
    markup = builder.adjust(1).as_markup()

    await bot.edit_message_text(
        text=(
            "<b>🎁 Подтверждение отправки подарка</b>\n\n"
            f"<b>Анонимность:</b> {new_status}\n\n"
            "<i>Нажмите кнопку ниже, чтобы отправить подарок.</i>"
        ),
        chat_id=call.from_user.id,
        message_id=call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup,
    )


@router.callback_query(F.data == 'send_gift_now')
async def send_gift_now_handler(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    await state.set_state(None)
    await send_gift_process(call, bot, state, franchise_id)


async def _wait_for_stars_balance(required_stars: int, max_attempts: int = 30) -> bool:
    app = get_pyrogram_client()
    if app is None:
        return False
    for attempt in range(max_attempts):
        try:
            current = await app.get_stars_balance()
            print(f"[Gifts] Balance check {attempt + 1}/{max_attempts}: {current}/{required_stars}")
            if current >= required_stars:
                return True
            await asyncio.sleep(1.5)
        except Exception as e:
            print(f"[Gifts] Balance check error: {e}")
            await asyncio.sleep(1.5)
    return False


async def _process_gift_sending(gift_data: dict) -> None:
    bot: Bot = gift_data['bot']
    user_id: int = gift_data['user_id']
    receiver: str = gift_data['receiver']
    gift_id: str = gift_data['gift_id']
    gift_price_stars: int = gift_data['gift_price_stars']
    gift_anonymous: str = gift_data['gift_anonymous']
    total_price: float = gift_data['total_price']
    message_id: int = gift_data.get('message_id')
    franchise_id: int = gift_data.get('franchise_id', 0)

    deducted = await deincrement_balance(user_id, total_price)
    if not deducted:
        try:
            await bot.edit_message_text(
                text=(
                    "<b><tg-emoji emoji-id='5251296048546073580'>❌</tg-emoji> Недостаточно средств</b>\n"
                    "Баланс изменился во время обработки."
                ),
                chat_id=user_id, message_id=message_id,
                parse_mode='HTML', reply_markup=await exit_button()
            )
        except Exception:
            pass
        return

    try:
        app = get_pyrogram_client()
        if app is None:
            raise RuntimeError("Pyrogram client not initialized")

        current_stars = await app.get_stars_balance()
        print(f"[Gifts] Stars balance: {current_stars}, required: {gift_price_stars}")

        if current_stars < gift_price_stars:
            me = await app.get_me()
            need_stars = max(50, gift_price_stars - current_stars)
            async with _fragment_lock:
                await fragment.send_stars(me.username, need_stars)
            balance_ok = await _wait_for_stars_balance(gift_price_stars, max_attempts=60)
            if not balance_ok:
                raise RuntimeError(f"Timeout: stars balance did not reach {gift_price_stars}")

        clean_receiver = receiver[1:] if receiver.startswith("@") else receiver
        await app.send_gift(
            chat_id=f"@{clean_receiver}",
            gift_id=int(gift_id),
            hide_my_name=gift_anonymous == "Да",
        )
        print(f"[Gifts] Gift sent to @{clean_receiver}, deducted {total_price:.2f} ₽ from {user_id}")

        await add_transaction(user_id, 'gift', gift_price_stars, total_price, clean_receiver)
        await send_admin_notification(
            bot,
            f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь купил подарок</b>\n\n'
            f'🆔 ID: <code>{user_id}</code>\n'
            f'🎁 Звёзд: <code>{gift_price_stars}</code>\n'
            f'👤 Получатель: @{clean_receiver}\n'
            f'💸 Сумма: <code>{total_price:.2f} ₽</code>',
            franchise_id=franchise_id,
            parse_mode='HTML',
        )

        builder = InlineKeyboardBuilder()
        builder.button(text='🆘 Поддержка 24/7', url=SUPPORT_URL)
        builder.button(text="🔙 Назад в меню", callback_data="back_to_menu")
        markup = builder.adjust(1).as_markup()

        await bot.edit_message_text(
            text=(
                "<b><tg-emoji emoji-id='5890925363067886150'>⭐️</tg-emoji> Подарок успешно отправлен!</b>\n\n"
                "Спасибо, что воспользовались <b>нашим сервисом.</b>\n\n"
                "<i>(Если подарок так и не пришёл, сообщите нам в поддержку, "
                "и мы оперативно решим этот вопрос!)</i>"
            ),
            chat_id=user_id, message_id=message_id,
            parse_mode='HTML', reply_markup=markup,
        )

    except Exception as e:
        print(f'[Gifts] Sending error: {e}')
        await increment_balance(user_id, total_price)
        try:
            await bot.edit_message_text(
                text="❌ Ошибка отправки подарка!\n\nСредства возвращены на баланс.",
                chat_id=user_id, message_id=message_id,
                parse_mode='HTML', reply_markup=await exit_button()
            )
        except Exception:
            pass


async def send_gift_process(event: CallbackQuery | Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = event.from_user.id
    balance = await get_balance(user_id)
    data = await state.get_data()
    franchise_id = franchise_id or data.get("franchise_id", 0)

    receiver = data.get("receiver") or (
        event.from_user.username if event.from_user and event.from_user.username else None
    )
    if not receiver:
        if isinstance(event, CallbackQuery):
            await bot.answer_callback_query(event.id, "❌ Не указан получатель подарка!", show_alert=True)
        else:
            await bot.send_message(user_id, "❌ Не указан получатель подарка!")
        return

    gift_key = data.get("gift")
    gift_anonymous = data.get("gift_anonymous", "Нет")
    message_id = (
        event.message.message_id if isinstance(event, CallbackQuery)
        else data.get("message_id")
    )

    if not gift_key:
        if isinstance(event, CallbackQuery):
            await bot.answer_callback_query(event.id, "❌ Ошибка! Попробуйте снова.", show_alert=True)
        return

    gift = await get_gift_by_key(gift_key)
    if not gift:
        if isinstance(event, CallbackQuery):
            await bot.answer_callback_query(event.id, "❌ Подарок не найден!", show_alert=True)
        return

    # (id, key, name, emoji_id, count_stars, gift_id, is_active, added_time)
    gift_price_stars = gift[4]
    gift_id = gift[5]

    try:
        price = await fragment.get_price_star()
        commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
        star_price = price * (Decimal("1") + commission / Decimal("100"))
        star_price = star_price.quantize(Decimal("0.01"))
        if star_price <= Decimal("0.01"):
            star_price = Decimal("1.65")
    except Exception as e:
        print(f'[Gifts] Failed to get star price: {e}')
        if isinstance(event, CallbackQuery):
            await bot.answer_callback_query(event.id, "❌ Ошибка получения цены!", show_alert=True)
        return

    total_price = float(gift_price_stars * star_price)

    if balance < total_price:
        try:
            await bot.edit_message_text(
                text="❌ Недостаточно средств для отправки подарка!",
                chat_id=user_id, message_id=message_id,
                parse_mode='HTML',
                reply_markup=await ebal_button(total_price - balance),
            )
        except Exception:
            pass
        return

    queue_size = purchase_queue.queue_size()
    wait_msg = f"\n\n⏳ В очереди перед вами: {queue_size}" if queue_size > 0 else ""
    try:
        await bot.edit_message_text(
            text=(
                f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji>'
                f' <b>Добавлено в очередь...</b>{wait_msg}\n\n'
                '🎁 Подарок будет отправлен автоматически.'
            ),
            chat_id=user_id, message_id=message_id, parse_mode='HTML',
        )
    except Exception:
        pass

    gift_data = {
        'bot': bot,
        'user_id': user_id,
        'receiver': receiver,
        'gift_id': gift_id,
        'gift_price_stars': gift_price_stars,
        'gift_anonymous': gift_anonymous,
        'total_price': total_price,
        'message_id': message_id,
        'franchise_id': franchise_id,
    }

    async def purchase_task():
        await _process_gift_sending(gift_data)

    await purchase_queue.add(purchase_task)
