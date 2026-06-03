import asyncio
import time
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import aiohttp
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from pytoniq_core import Cell, StateInit

from app.database import (
    get_balance, deincrement_balance, increment_balance, get_referrer_id,
    get_rented_num, add_rent_num, add_transaction
)
from app.helpers import exit_button, ebal_button, effective_markup
from app.states import UserState
from app.config import COMMISSION_NUMBERS, ADMINS_IDS, REFERRAL_PERCENT, INSTRUCTION_URL
from app.utils.martketapi import MarketApi
from app.utils.fragmentapi import get_ton_to_usd_price, price_usd_to_rub
from app.utils.walletapi import WalletApi

router = Router()
marketapp = MarketApi()
wallet = WalletApi()


async def ton_to_rub(ton_amount: float) -> float:
    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()
    return float(Decimal(str(ton_amount)) * Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub)))


def parse_api_response(response):
    message = response["transaction"]["messages"][0]
    address = message["address"]
    amount = int(message["amount"])
    body = Cell.one_from_boc(message["payload"])
    state_init = StateInit.deserialize(Cell.one_from_boc(message["stateInit"]).begin_parse()) if message.get("stateInit") else None
    return address, amount, body, state_init


def unixtime_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def diff_unix_with_months(t1: int, t2: int) -> str:
    diff = int(abs(t2 - t1))
    minutes = diff // 60
    hours = minutes // 60
    days = hours // 24
    months = days // 30
    days = days % 30
    hours = hours % 24
    minutes = minutes % 60
    parts = []
    if months > 1:
        parts.append(f"{months} мес.")
    if days > 1:
        parts.append(f"{days} дн.")
    if hours > 1:
        parts.append(f"{hours} ч.")
    if minutes > 1:
        parts.append(f"{minutes} мин.")
    if not parts:
        parts.append("1 мин.")
    return " ".join(parts)


async def get_photo_number(number: str):
    try:
        number = number.replace("+", "").replace(" ", "").replace("-", "")
        async with aiohttp.ClientSession() as session:
            url = f"https://nft.fragment.com/number/{number}.webp"
            response = await session.get(url)
            if response.status == 200:
                return BytesIO(await response.read())
    except FileNotFoundError:
        pass
    return None


@router.callback_query(F.data == "rent_number")
async def rent_number(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    from app.helpers import get_section_photo, unified_send
    photo = await get_section_photo(franchise_id, "numbers")
    builder = InlineKeyboardBuilder()
    builder.button(text="Доступные номера", callback_data="available_numbers:0", icon_custom_emoji_id="6039605143601680423")
    builder.button(text="Мои номера", callback_data="my_numbers", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    await unified_send(
        call, bot,
        '<b>☎️ Аренда Номера</b>\n\nВыберите категорию:',
        builder.adjust(1).as_markup(),
        photo=photo,
    )


@router.callback_query(F.data.startswith("available_numbers:"))
async def show_numbers(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    page = int(call.data.split(":")[1])
    numbers_data = await marketapp.get_numbers_rent(0)
    all_numbers = numbers_data['items']

    per_page = 8
    total_pages = max(1, (len(all_numbers) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_numbers = all_numbers[page * per_page:(page + 1) * per_page]

    cost_rub = await ton_to_rub(1)
    markup_pct = await effective_markup(COMMISSION_NUMBERS[0], franchise_id)

    text = (
        f"<b>☎️ Доступные номера для аренды</b>\n\n"
        f"📱 Найдено номеров: <code>{len(all_numbers)}</code>\n"
        f"📄 Страница: <code>{page + 1}</code>/<code>{total_pages}</code>\n\nВыберите номер 👇"
    )

    builder = InlineKeyboardBuilder()
    for number in page_numbers:
        min_duration = int(number['min_duration']) // 86400
        max_duration = int(number['max_duration']) // 86400
        cost_per_day_ton = int(number['price_per_day']) / 1_000_000_000
        cost_per_day_rub = cost_rub * cost_per_day_ton
        cost_per_day_rub_with_commission = cost_per_day_rub * (1 + markup_pct / 100)
        cost_min = cost_per_day_rub_with_commission * min_duration
        builder.button(
            text=f"{number['nft_name']} • {cost_min:.0f} ₽ ({min_duration}д - {max_duration}дн)",
            callback_data=f"rent_number:{number['nft_address']}"
        )

    nav_row = []
    if page > 0:
        nav_row.append(("◀️", f"available_numbers:{page - 1}"))
    nav_row.append((f"{page + 1}/{total_pages}", "current_page"))
    if page < total_pages - 1:
        nav_row.append(("▶️", f"available_numbers:{page + 1}"))

    for text_btn, callback in nav_row:
        builder.button(text=text_btn, callback_data=callback)
    builder.button(text="Назад", callback_data="rent_number", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(*([1] * len(page_numbers)), len(nav_row), 1).as_markup()

    try:
        await bot.edit_message_text(
            text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
            parse_mode='HTML', reply_markup=markup
        )
    except TelegramBadRequest:
        try:
            if call.message.photo:
                await bot.delete_message(call.from_user.id, call.message.message_id)
            await bot.send_message(chat_id=call.from_user.id, text=text, parse_mode='HTML', reply_markup=markup)
        except:
            pass


@router.callback_query(F.data == "my_numbers")
async def my_numbers(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    user_numbers = await get_rented_num(user_id)
    builder = InlineKeyboardBuilder()

    text = "<b>☎️ Мои арендованные номера:</b>\n\n"
    if len(user_numbers) == 0:
        text += 'У вас пока нет активных аренд номеров.\n\nВы можете арендовать номер в разделе "☎️ Аренда Номера".'
        builder.button(text="☎️ Аренда Номера", callback_data="available_numbers:0")
    for number in user_numbers:
        end_time = int(number['end_time'])
        end_time_str = datetime.fromtimestamp(end_time).strftime("%d.%m.%Y %H:%M")
        nft_name = number.get('nft_name') or number['nft_address']
        builder.button(
            text=f"📞 {nft_name} | {end_time_str}",
            callback_data=f"show_my_number:{number['nft_address']}"
        )

    builder.button(text="Назад", callback_data="rent_number", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())


@router.callback_query(F.data.startswith("show_my_number:"))
async def show_my_number(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    nft_address = call.data.split(":")[1]

    try:
        await bot.delete_message(user_id, call.message.message_id)
    except:
        pass

    await bot.answer_callback_query(call.id, "⌛ Подождите, идет загрузка информации о номере...")

    info = await marketapp.get_info_gift(nft_address)
    number = info['name']

    user_numbers = await get_rented_num(user_id)
    number_info = next((n for n in user_numbers if n['nft_address'] == nft_address), None)

    if number_info:
        start_time = int(time.time())
        end_time = int(number_info['end_time'])
        total = diff_unix_with_months(start_time, end_time)
        end_time_str = unixtime_to_str(end_time)
    else:
        total = "N/A"
        end_time_str = "N/A"

    photo = await get_photo_number(number)

    text = (
        f"<b>☎️ Арендованный номер</b>\n<code>{number}</code>\n\n"
        "<b>📊 Информация об аренде:</b>\n"
        f"├ Осталось: <b>{total}</b>\n"
        f"└ Истекает: <b>{end_time_str}</b>\n\n"
        "<i>📌 Привяжите номер к своему Fragment аккаунту</i>"
    )

    await state.update_data({"nft_address": nft_address})
    builder = InlineKeyboardBuilder()
    builder.button(text="Привязать", callback_data=f"connect_number:{nft_address}", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Инструкция", url=INSTRUCTION_URL, icon_custom_emoji_id="6028435952299413210")
    builder.button(text="Назад", callback_data="my_numbers", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()

    if photo:
        photo_file = BufferedInputFile(photo.getvalue(), filename="number.webp")
        await bot.send_photo(user_id, photo_file, caption=text, parse_mode='HTML', reply_markup=markup)
    else:
        await bot.send_message(user_id, text=text, parse_mode='HTML', reply_markup=markup)
    await bot.answer_callback_query(call.id)


@router.callback_query(F.data.startswith("connect_number:"))
async def connect_number(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    nft_address = call.data.split(":")[1]
    try:
        await bot.delete_message(user_id, call.message.message_id)
    except:
        pass

    text = (
        "<b>🔗 Привязка номера Fragment</b>\n\n"
        "Отправьте ссылку на передачу номера в Fragment.\n\n"
        "<b>💡 Формат ссылки:</b>\n<code>tc://...</code>\n\n"
        'Или нажмите "Назад" для возврата.'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Инструкция", url=INSTRUCTION_URL, icon_custom_emoji_id="6028435952299413210")
    builder.button(text="Назад", callback_data="my_numbers", icon_custom_emoji_id="5960671702059848143")
    await bot.send_message(text=text, chat_id=user_id, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())
    await state.update_data({"nft_address": nft_address})
    await state.set_state(UserState.wait_bind_number)


@router.callback_query(F.data.startswith("rent_number:"))
async def process_rent_number(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    try:
        await state.clear()
    except:
        pass

    nft_address = call.data.split(":")[1]
    info = await marketapp.get_info_gift(nft_address)
    detail = info['status_details']
    min_duration = int(detail['min_duration']) // 86400
    max_duration = int(detail['max_duration']) // 86400

    price_per_day_ton = float(detail['price_per_day']) / 1_000_000_000
    price_per_day_rub = await ton_to_rub(price_per_day_ton)
    markup_pct = await effective_markup(COMMISSION_NUMBERS[0], franchise_id)
    price_per_day_rub_with_commission = price_per_day_rub * (1 + markup_pct / 100)

    price_min_rub = price_per_day_rub_with_commission * min_duration
    price_max_rub = price_per_day_rub_with_commission * max_duration

    number = info['name']
    photo = await get_photo_number(number)

    text = (
        f"<b>☎️ Аренда номера</b>\n<code>{number}</code>\n\n"
        f"<b>💰 Условия аренды:</b>\n"
        f"├ Цена за день: <b>{price_per_day_rub_with_commission:.2f} ₽</b>\n"
        f"├ Минимальный срок: <b>{min_duration} дн.</b> (<code>{price_min_rub:.2f} ₽</code>)\n"
        f"└ Максимальный срок: <b>{max_duration} дн.</b> (<code>{price_max_rub:.2f} ₽</code>)\n\n"
        f"<i>📌 Выберите действие ниже</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Взять в аренду", callback_data=f"proc_rent:{nft_address}", icon_custom_emoji_id="5454386656628991407")
    number_clean = number.replace("+", "").replace(" ", "").replace("-", "")
    builder.button(text="Посмотреть", url=f"https://fragment.com/number/{number_clean}", icon_custom_emoji_id="6037397706505195857")
    builder.button(text='Назад', callback_data='available_numbers:0', icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_media(
        media=InputMediaPhoto(media=BufferedInputFile(photo.getvalue(), filename="number.webp"), caption=text, parse_mode='HTML'),
        chat_id=call.from_user.id, message_id=call.message.message_id,
        reply_markup=builder.adjust(1).as_markup()
    )


@router.callback_query(F.data.startswith("proc_rent:"))
async def process_rent_number_final(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    nft_address = call.data.split(":")[1]
    info = await marketapp.get_info_gift(nft_address)
    detail = info['status_details']

    price_day_ton = float(detail['price_per_day']) / 1_000_000_000
    price_day_rub = await ton_to_rub(price_day_ton)
    markup_pct = await effective_markup(COMMISSION_NUMBERS[0], franchise_id)
    price_day_rub_with_commission = price_day_rub * (1 + markup_pct / 100)

    min_duration = int(detail['min_duration']) // 86400
    max_duration = int(detail['max_duration']) // 86400

    await state.update_data({
        "nft_address": nft_address,
        "min_duration": detail['min_duration'],
        "max_duration": detail['max_duration'],
        "price_per_day_rub": price_day_rub_with_commission,
        "price_per_day_ton": price_day_ton,
        "name": info['name']
    })

    text = (
        f"<b>☎️ Аренда номера {info['name']}</b>\n\n"
        f"Введите количество дней аренды (от {min_duration} до {max_duration} дн.):"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=f"rent_number:{nft_address}", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_caption(
        caption=text, chat_id=call.from_user.id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(UserState.wait_rent_num_duration)


@router.message(UserState.wait_rent_num_duration)
async def rent_num_duration_handler(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id

    try:
        days = int(message.text)
    except ValueError:
        await bot.send_message(user_id, "❌ Количество дней должно быть целым числом!", reply_markup=await exit_button())
        await state.clear()
        return

    data = await state.get_data()
    name = data.get("name")
    nft_address = data.get("nft_address")
    min_duration = data.get("min_duration", 0) // 86400
    max_duration = data.get("max_duration", 0) // 86400
    day_price_rub = data.get("price_per_day_rub")
    day_price_ton = data.get("price_per_day_ton")

    if days < min_duration or days > max_duration:
        await bot.send_message(user_id, f"❌ Количество дней должно быть от {min_duration} до {max_duration}!", reply_markup=await exit_button())
        await state.clear()
        return

    balance = await get_balance(user_id)
    if balance < days * day_price_rub:
        await bot.send_message(user_id, "❌ Недостаточно средств на балансе для аренды!\nПополните баланс в профиле.", reply_markup=await ebal_button(float(days * day_price_rub) - balance))
        await state.clear()
        return

    balance_wallet = await wallet.get_balance_ton()
    if balance_wallet < days * day_price_ton:
        try:
            for admin in ADMINS_IDS:
                await bot.send_message(admin, f"❌ Недостаточно средств на балансе маркета для аренды номера!\nИД пользователя: {user_id}\nКоличество дней: {days}")
        except:
            pass
        await bot.send_message(user_id, "❌ Ошибка при оплате аренды. Ожидайте, пока баланс нашего маркета обновится!", reply_markup=await exit_button())
        await state.clear()
        return

    total_cost = days * day_price_rub
    deducted = await deincrement_balance(user_id, total_cost)
    if not deducted:
        await bot.send_message(user_id, "❌ Недостаточно средств на балансе для аренды!\nПополните баланс в профиле.", reply_markup=await ebal_button(float(total_cost) - balance))
        await state.clear()
        return

    result = await marketapp.rent_nft(nft_address, days * 86400, str(int(day_price_ton * 1_000_000_000)))
    if not result:
        await increment_balance(user_id, total_cost)
        await bot.send_message(user_id, "❌ Ошибка при аренде номера!", reply_markup=await exit_button())
        await state.clear()
        return

    address, amount, body, state_init = parse_api_response(result)
    result = await wallet.send_ton(address, amount, body, state_init)
    if not result:
        await increment_balance(user_id, total_cost)
        await bot.send_message(user_id, "❌ Ошибка при оплате аренды!", reply_markup=await exit_button())
        await state.clear()
        return

    base_price_ton = days * day_price_ton
    base_price_rub = await ton_to_rub(base_price_ton)
    profit = total_cost - base_price_rub
    referrer_id = await get_referrer_id(user_id)
    if referrer_id and REFERRAL_PERCENT > 0:
        try:
            referral_reward = Decimal(str(profit)) * (Decimal(str(REFERRAL_PERCENT)) / Decimal("100"))
            if referral_reward > 0:
                await increment_balance(referrer_id, float(referral_reward))
        except Exception as e:
            print(f"Ошибка реферального вознаграждения: {e}")

    await bot.send_message(user_id, f"✅ Номер {name} успешно арендован!", reply_markup=await exit_button())
    start_time = time.time()
    end_time = start_time + days * 86400
    await add_rent_num(user_id, nft_address, start_time, days * 86400, end_time, name)
    await add_transaction(user_id, 'numbers', days, total_cost, name)
    await state.clear()


@router.message(UserState.wait_bind_number)
async def process_bind_number(message: Message, bot: Bot, state: FSMContext):
    try:
        user_id = message.from_user.id
        tonconnect_url = message.text
        if not tonconnect_url.startswith("tc://"):
            await bot.send_message(user_id, "❌ Неверный формат ссылки!", reply_markup=await exit_button())
            return
        try:
            await bot.delete_message(user_id, message.message_id)
            await bot.delete_message(user_id, message.message_id - 1)
        except:
            pass

        data = await state.get_data()
        nft_address = data.get("nft_address")
        result = await marketapp.connect(nft_address, tonconnect_url)
        if not result:
            await bot.send_message(user_id, "❌ Произошла ошибка при привязке!", reply_markup=await exit_button())
            return
        await bot.send_message(user_id, "<b>✅ Номер успешно привязан!</b>\n\nНомер автоматически привязан к вашему Fragment аккаунту.", reply_markup=await exit_button(), parse_mode='HTML')
    except:
        await bot.send_message(user_id, "❌ Произошла ошибка!", reply_markup=await exit_button())
    finally:
        await state.clear()
