import asyncio
from decimal import Decimal

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import get_balance, deincrement_balance, increment_balance, add_stars, add_transaction
from app.helpers import exit_button, ebal_button, effective_markup, get_section_photo, unified_send, send_admin_notification
from app.states import UserState
from app.config import COMMISSION_STARS, AVAILABLE_URL
from app.utils.fragmentapi import StarSender
from app.utils.walletapi import WalletApi
from app.queue_manager import purchase_queue

router = Router()
fragment = StarSender()
wallet = WalletApi()


async def process_referral_reward(user_id: int, profit: float, bot: Bot) -> None:
    from app.database import get_referrer_id, increment_balance
    import app.config as config
    referrer_id = await get_referrer_id(user_id)
    if referrer_id and config.REFERRAL_PERCENT > 0:
        try:
            profit_dec = Decimal(str(profit))
            referral_reward = profit_dec * (Decimal(str(config.REFERRAL_PERCENT)) / Decimal("100"))
            if referral_reward > 0:
                reward_float = float(referral_reward)
                await increment_balance(referrer_id, reward_float)
                try:
                    await bot.send_message(
                        referrer_id,
                        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> <b>Реферальное вознаграждение!</b>\n\nРеферал совершил покупку\n'
                        f"Ваш заработок: <code>{reward_float:.2f} ₽</code> ({config.REFERRAL_PERCENT}% от прибыли)",
                        parse_mode='HTML'
                    )
                except:
                    pass
        except Exception as e:
            print(f"Ошибка при расчёте реферального вознаграждения: {e}")


async def show_buy_stars(call: CallbackQuery, username: str, bot: Bot, franchise_id: int = 0):
    photo = await get_section_photo(franchise_id, "stars")
    text = (
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Покупка звёзд</b>\n\n'
        '<tg-emoji emoji-id="6037397706505195857">👁</tg-emoji> Выберите, кому будем отправлять звёзды'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Себе", callback_data="stars_self", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Другу", callback_data="stars_friend", icon_custom_emoji_id="5870772616305839506")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1).as_markup()
    await unified_send(call, bot, text, markup, photo=photo)


@router.callback_query(F.data.startswith('buy_'))
async def buyer(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    username = call.from_user.username
    if username is None:
        await bot.answer_callback_query(call.id, "⚠️ Установите username", show_alert=True)
        return
    data = call.data.split('_')
    type_of_buy = data[1]
    if type_of_buy == 'stars':
        await show_buy_stars(call, username, bot, franchise_id)
    elif type_of_buy == 'premium':
        from app.handlers.premium import show_buy_premium
        await show_buy_premium(call, username, bot, franchise_id)
    elif type_of_buy == 'ton':
        from app.handlers.ton import show_buy_ton
        await show_buy_ton(call, username, bot, franchise_id)


@router.callback_query(F.data == "stars_self")
async def buy_stars_self(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    balance = await get_balance(user_id)
    username = call.from_user.username
    if not username:
        await bot.answer_callback_query(call.id, "⚠️ Установите username в настройках Telegram", show_alert=True)
        return

    username_check = await fragment.check_right_recipient(username)
    await state.update_data({'username': username_check})

    if username_check is None or username_check is False:
        await bot.answer_callback_query(call.id, "❌ Ваш аккаунт не найден", show_alert=True)
        return

    price = await fragment.get_price_star()
    commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
    star_price = price * (Decimal("1") + commission / Decimal("100"))
    star_price = star_price.quantize(Decimal("0.01"))

    if star_price == 0:
        await bot.answer_callback_query(call.id, "❌ Ошибка получения цены звёзд", show_alert=True)
        return

    text = (
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Покупка звёзд</b>\n\n'
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Выберите количество звёзд для покупки:</b>'
    )

    quantities = [50, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500, 5000, 10000, 25000]
    builder = InlineKeyboardBuilder()
    for qty in quantities:
        total_price = float(star_price * qty)
        builder.button(text=f"{qty} ⭐ — {total_price:,.2f} ₽", callback_data=f"quick_stars:{qty}")
    builder.button(text="Указать своё количество", callback_data="custom_stars_amount", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Назад", callback_data="buy_stars", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 2, 2, 2, 2, 2, 1, 1, 1).as_markup()

    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text=text, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True
    )
    await state.update_data({'star_price': float(star_price)})


@router.callback_query(F.data == "custom_stars_amount")
async def custom_stars_amount(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    balance = await get_balance(user_id)

    data = await state.get_data()
    star_price = Decimal(str(data.get('star_price', 0)))

    if star_price == 0:
        price = await fragment.get_price_star()
        commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
        star_price = price * (Decimal("1") + commission / Decimal("100"))
        star_price = star_price.quantize(Decimal("0.01"))

    balance_dec = Decimal(str(balance))
    max_by_user_balance = int(balance_dec // star_price)
    available_stars = await fragment.get_count_stars()
    max_can_buy = min(max_by_user_balance, available_stars)
    can_buy = "✅" if max_can_buy >= 50 else "❌"

    text = (
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Покупка звёзд</b>\n\n'
        "<tg-emoji emoji-id='6043896193887506430'>📌</tg-emoji> Минимальное количество звёзд: 50 <tg-emoji emoji-id='6028338546736107668'>⭐️</tg-emoji>\n\n"
        '<tg-emoji emoji-id="6039614175917903752">📰</tg-emoji> Введите количество звёзд:\n'
        f" ├ 1 <tg-emoji emoji-id='6028338546736107668'>🌟</tg-emoji> → {star_price:.2f} ₽\n"
        f' └ <a href="{AVAILABLE_URL}">Доступно к покупке</a>: {max_can_buy} <tg-emoji emoji-id="6028338546736107668">🌟</tg-emoji> ({can_buy})'
    )

    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text=text, reply_markup=await exit_button(), parse_mode='HTML', disable_web_page_preview=True
    )
    await state.set_state(UserState.wait_stars)


@router.callback_query(F.data == "stars_friend")
async def buy_stars_friend(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    username = call.from_user.username
    text = (
        '<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Введите юзернейм друга, которому вы желаете купить звезды:</b>\n'
        f"└ Пример: @{username} или {username}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="buy_stars", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text=text, parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(UserState.wait_username)


@router.message(UserState.wait_username)
async def buy_stars_username(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    balance = await get_balance(user_id)
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    username = await fragment.check_right_recipient(message.text)
    await state.update_data({'username': username})

    if username is None or username is False:
        await bot.send_message(user_id, "❌ Пользователь не найден", reply_markup=await exit_button())
        return

    price = await fragment.get_price_star()
    commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
    star_price = price * (Decimal("1") + commission / Decimal("100"))
    star_price = star_price.quantize(Decimal("0.01"))

    if star_price == 0:
        await bot.send_message(user_id, "❌ Ошибка получении цены звёзд\nПопробуйте позже.", reply_markup=await exit_button())
        return

    balance_dec = Decimal(str(balance))
    max_by_user_balance = int(balance_dec // star_price)
    available_stars = await fragment.get_count_stars()
    max_can_buy = min(max_by_user_balance, available_stars)

    text = (
        '<b><tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Покупка звёзд</b>\n\n'
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Выберите количество звёзд для покупки:</b>'
    )

    quantities = [50, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500, 5000, 10000, 25000]
    builder = InlineKeyboardBuilder()
    for qty in quantities:
        total_price = float(star_price * qty)
        builder.button(text=f"{qty} ⭐ — {total_price:,.2f} ₽", callback_data=f"quick_stars:{qty}")
    builder.button(text="Указать своё количество", callback_data="custom_stars_amount", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Назад", callback_data="buy_stars", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 2, 2, 2, 2, 2, 1, 1, 1).as_markup()

    await bot.send_message(user_id, text, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)
    await state.update_data({'star_price': float(star_price)})


async def _execute_stars_purchase(bot: Bot, user_id: int, username: str, stars: int, star_price: Decimal, price: Decimal, message_id: int = None, franchise_id: int = 0):
    total_cost = float(stars * star_price)
    if Decimal(str(await get_balance(user_id))) < stars * star_price:
        text = "❌ Недостаточно средств\nПополните баланс в профиле!"
        if message_id:
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=message_id, reply_markup=await ebal_button(total_cost), parse_mode='HTML')
        else:
            await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost), parse_mode='HTML')
        return

    ton_balance = await wallet.get_balance_ton()
    required_ton = stars * await fragment.ton_price_star()
    if ton_balance < required_ton:
        text = (
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Недостаточно TON на кошельке</b>\n\n'
            f"Требуется: {required_ton:.2f} TON\nДоступно: {ton_balance:.2f} TON\n\n"
            "Пожалуйста, свяжитесь с администратором."
        )
        if message_id:
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=message_id, reply_markup=await exit_button(), parse_mode='HTML')
        else:
            await bot.send_message(user_id, text, reply_markup=await exit_button(), parse_mode='HTML')
        return

    if message_id:
        await bot.edit_message_text(text='<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Обработка покупки...</b>', chat_id=user_id, message_id=message_id, parse_mode='HTML')

    deducted = await deincrement_balance(user_id, total_cost)
    if not deducted:
        text = "❌ Недостаточно средств\nПополните баланс в профиле!"
        if message_id:
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=message_id, reply_markup=await ebal_button(total_cost), parse_mode='HTML')
        else:
            await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost), parse_mode='HTML')
        return

    result = await fragment.send_stars(username, stars)

    if not result:
        await increment_balance(user_id, total_cost)
        text = '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Произошла ошибка при покупке</b>\n\nПопробуйте позже или обратитесь в поддержку.'
        if message_id:
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=message_id, reply_markup=await exit_button(), parse_mode='HTML')
        else:
            await bot.send_message(user_id, text, reply_markup=await exit_button(), parse_mode='HTML')
        return

    await add_stars(user_id, stars)
    await add_transaction(user_id, 'stars', stars, total_cost, username)

    base_price = float(stars * price)
    profit = total_cost - base_price
    await process_referral_reward(user_id, profit, bot)

    await send_admin_notification(
        bot,
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь купил звёзды</b>\n\n🆔 ID: <code>{user_id}</code>\n⭐️ Звёзд: <code>{stars}</code>\n💸 Потрачено: <code>{required_ton:.2f} TON</code>',
        franchise_id=franchise_id,
        parse_mode='HTML'
    )

    success_text = '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Звёзды успешно куплены</b>\n\n<i>В некоторых случаях бывают задержки до 5 минут!</i>'
    if message_id:
        await bot.edit_message_text(text=success_text, chat_id=user_id, message_id=message_id, reply_markup=await exit_button(), parse_mode='HTML')
    else:
        await bot.send_message(user_id, success_text, reply_markup=await exit_button(), parse_mode='HTML')


@router.callback_query(F.data.startswith("quick_stars:"))
async def quick_stars_buy(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    balance = await get_balance(user_id)
    stars = int(call.data.split(":")[1])

    price = await fragment.get_price_star()
    commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
    star_price = price * (Decimal("1") + commission / Decimal("100"))
    star_price = star_price.quantize(Decimal("0.01"))

    if star_price == 0:
        await bot.answer_callback_query(call.id, "❌ Ошибка получения цены звёзд", show_alert=True)
        return

    balance_dec = Decimal(str(balance))
    available_stars = await fragment.get_count_stars()
    max_can_buy = min(int(balance_dec // star_price), available_stars)

    if balance_dec < stars * star_price:
        need = float(stars * star_price - balance_dec)
        await bot.edit_message_text(
            text=f"❌ Недостаточно средств\n\nНеобходимо: {need:.2f} ₽",
            chat_id=user_id, message_id=call.message.message_id,
            reply_markup=await ebal_button(need)
        )
        return

    if stars > 25000:
        await bot.answer_callback_query(call.id, "❌ Максимальное количество звёзд - 25000", show_alert=True)
        return
    if stars < 50:
        await bot.answer_callback_query(call.id, "❌ Минимальное количество звёзд - 50", show_alert=True)
        return
    if stars > max_can_buy:
        await bot.answer_callback_query(call.id, f"❌ Доступно только {max_can_buy} звёзд", show_alert=True)
        return

    data = await state.get_data()
    username = data.get('username')
    await state.clear()

    ahead = purchase_queue.queue_size() + (1 if purchase_queue.is_processing() else 0)
    wait_msg = f"\n\n⏳ В очереди перед вами: {ahead} покупок" if ahead > 0 else ""

    await bot.edit_message_text(
        text=f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Добавлено в очередь покупок...</b>{wait_msg}',
        chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML'
    )

    message_id = call.message.message_id

    async def purchase_task():
        await _execute_stars_purchase(bot, user_id, username, stars, star_price, price, message_id, franchise_id)

    await purchase_queue.add(purchase_task)


@router.message(UserState.wait_stars)
async def buy_stars_stars(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    price = await fragment.get_price_star()
    commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
    star_price = price * (Decimal("1") + commission / Decimal("100"))
    star_price = star_price.quantize(Decimal("0.01"))

    if star_price == 0:
        await bot.send_message(user_id, "❌ Ошибка получении цены звёзд\nПопробуйте позже.", reply_markup=await exit_button())
        return

    balance_dec = Decimal(str(balance))
    available_stars = await fragment.get_count_stars()
    max_can_buy = min(int(balance_dec // star_price), available_stars)

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    try:
        stars = int(message.text)
    except:
        await bot.send_message(user_id, "❌ Количество звёзд должно быть целым числом", reply_markup=await exit_button())
        return

    if balance_dec < stars * star_price:
        await bot.send_message(user_id, "❌ Недостаточно средств\nПополните баланс в профиле!", reply_markup=await ebal_button(float(stars) * float(star_price)))
        return
    if stars > 5000:
        await bot.send_message(user_id, "❌ Максимальное количество звёзд за одну покупку: 5000", reply_markup=await exit_button())
        return
    if stars < 50:
        await bot.send_message(user_id, "❌ Количество звёзд должно быть не менее 50", reply_markup=await exit_button())
        return
    if stars > max_can_buy:
        await bot.send_message(user_id, f"❌ Количество звёзд должно быть не более {max_can_buy}", reply_markup=await exit_button())
        return

    data = await state.get_data()
    username = data.get('username')
    await state.clear()

    ahead = purchase_queue.queue_size() + (1 if purchase_queue.is_processing() else 0)
    wait_msg = f"\n\n⏳ В очереди перед вами: {ahead} покупок" if ahead > 0 else ""

    queued_msg = await bot.send_message(user_id, f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Добавлено в очередь покупок...</b>{wait_msg}', parse_mode='HTML')

    async def purchase_task():
        await _execute_stars_purchase(bot, user_id, username, stars, star_price, price, queued_msg.message_id, franchise_id)

    await purchase_queue.add(purchase_task)
