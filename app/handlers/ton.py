import asyncio
from decimal import Decimal

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import get_balance, deincrement_balance, increment_balance, get_referrer_id, add_transaction
from app.helpers import exit_button, ebal_button, effective_markup, get_section_photo, unified_send, send_admin_notification, process_franchise_reward
from app.states import UserState
from app.config import COMMISSION_TON, REFERRAL_PERCENT, AVAILABLE_URL
from app.utils.fragmentapi import TonSender, get_ton_to_usd_price, price_usd_to_rub
from app.utils.walletapi import WalletApi
from app.queue_manager import purchase_queue

router = Router()
fragment_ton = TonSender()
wallet = WalletApi()


async def ton_to_rub(ton_amount: float) -> float:
    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()
    return float(Decimal(str(ton_amount)) * Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub)))


async def show_buy_ton(call: CallbackQuery, username: str, bot: Bot, franchise_id: int = 0):
    photo = await get_section_photo(franchise_id, "ton")
    text = (
        '<b><tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> Покупка TON</b>\n\n'
        '<tg-emoji emoji-id="6037397706505195857">👁</tg-emoji> Выберите, кому будем покупать TON'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Себе", callback_data="ton_self", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Другу", callback_data="ton_friend", icon_custom_emoji_id="5870772616305839506")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1).as_markup()
    await unified_send(call, bot, text, markup, photo=photo)


async def show_buy_ton2(event, username: str, bot: Bot, franchise_id: int = 0):
    user_id = event.from_user.id
    balance = await get_balance(user_id)

    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()

    commission = Decimal(str(await effective_markup(COMMISSION_TON[0], franchise_id)))
    ton_price_rub = Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub))
    final_sum = ton_price_rub * (Decimal("1") + commission / Decimal("100"))
    final_sum = final_sum.quantize(Decimal("0.01"))

    balance_dec = Decimal(str(balance))
    max_can_buy = int(balance_dec // final_sum) if final_sum > 0 else 0
    can_buy = "✅" if max_can_buy >= 1 else "❌"

    text = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь найден</b>\n\n'
        "<tg-emoji emoji-id='6043896193887506430'>📌</tg-emoji> Минимальное количество TON: 1 <tg-emoji emoji-id='5776023601941582822'>💎</tg-emoji>\n\n"
        '<tg-emoji emoji-id="6039614175917903752">📰</tg-emoji> Введите количество TON:\n'
        f" ├ 1 TON → {final_sum:.2f} ₽\n"
        f' └ <a href="{AVAILABLE_URL}">Доступно к покупке</a>: {max_can_buy} <tg-emoji emoji-id="5776023601941582822">💎</tg-emoji> ({can_buy})'
    )

    if isinstance(event, CallbackQuery):
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=event.message.message_id,
            reply_markup=await exit_button(), parse_mode='HTML', disable_web_page_preview=True
        )
    else:
        await bot.send_message(user_id, text, reply_markup=await exit_button(), parse_mode='HTML', disable_web_page_preview=True)


@router.callback_query(F.data == "ton_self")
async def buy_ton_self(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    username = call.from_user.username
    if not username:
        await bot.answer_callback_query(call.id, "⚠️ Установите username в настройках Telegram", show_alert=True)
        return

    msg = await bot.edit_message_text('<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Проверяем пользователя…</b>', chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML")
    await asyncio.sleep(0.5)

    result = await fragment_ton.check_right_recipient(username)
    if not result:
        await bot.edit_message_text(text="❌ Пользователь не найден", chat_id=user_id, message_id=msg.message_id, reply_markup=await exit_button())
        return

    await state.update_data({"username": username})
    await show_buy_ton2(call, username, bot, franchise_id)
    await state.set_state(UserState.wait_tons)


@router.callback_query(F.data == "ton_friend")
async def buy_ton_friend(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    username = call.from_user.username
    text = (
        '<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Введите юзернейм друга, которому вы желаете купить TON:</b>\n'
        f"└ Пример: @{username} или {username}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="buy_ton", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text=text, parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(UserState.wait_username_ton)


@router.message(UserState.wait_username_ton)
async def wait_username_ton(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    username = message.text
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    result = await fragment_ton.check_right_recipient(username)
    if not result:
        await bot.send_message(text="❌ Пользователь не найден", chat_id=user_id, reply_markup=await exit_button())
        return

    await state.update_data({"username": username})
    await show_buy_ton2(message, username, bot, franchise_id)
    await state.set_state(UserState.wait_tons)


async def _execute_ton_purchase(bot: Bot, user_id: int, username: str, tons: int, ton_price: Decimal, ton_price_rub: Decimal, msg_id: int = None, franchise_id: int = 0):
    total_cost = float(tons * ton_price)
    if Decimal(str(await get_balance(user_id))) < tons * ton_price:
        text = "❌ Недостаточно средств\nПополните баланс в профиле!"
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await ebal_button(total_cost))
            except:
                await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost))
        else:
            await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost))
        return

    ton_balance = await wallet.get_balance_ton()
    if ton_balance < tons:
        text = "❌ Недостаточно баланса бота\nАдминистратору отправлено уведомление об этом, ожидайте!"
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button())
            except:
                await bot.send_message(user_id, text, reply_markup=await exit_button())
        else:
            await bot.send_message(user_id, text, reply_markup=await exit_button())
        need = float(tons) - float(ton_balance)
        await send_admin_notification(
            bot,
            f"<b>❌ Недостаточно баланса TON</b>\nПользователю <code>{user_id}</code> не хватает <code>{need:.2f} TON</code>",
            franchise_id=franchise_id,
            parse_mode='HTML'
        )
        return

    deducted = await deincrement_balance(user_id, total_cost)
    if not deducted:
        text = "❌ Недостаточно средств\nПополните баланс в профиле!"
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await ebal_button(total_cost))
            except:
                await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost))
        else:
            await bot.send_message(user_id, text, reply_markup=await ebal_button(total_cost))
        return

    result = None
    try:
        result = await fragment_ton.send_ton(username, tons)
    except Exception as e:
        print("Error with sending TON:", e)

    if not result:
        await increment_balance(user_id, total_cost)
        text = "❌ Произошла ошибка при отправке TON"
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button())
            except:
                await bot.send_message(user_id, text, reply_markup=await exit_button())
        else:
            await bot.send_message(user_id, text, reply_markup=await exit_button())
        return

    await add_transaction(user_id, 'ton', tons, total_cost, username)

    base_price = float(tons) * float(ton_price_rub)
    profit = total_cost - base_price
    await process_franchise_reward(franchise_id, base_price)
    referrer_id = await get_referrer_id(user_id)
    if referrer_id and REFERRAL_PERCENT > 0:
        try:
            profit_dec = Decimal(str(profit))
            referral_reward = profit_dec * (Decimal(str(REFERRAL_PERCENT)) / Decimal("100"))
            if referral_reward > 0:
                reward_float = float(referral_reward)
                await increment_balance(referrer_id, reward_float)
                try:
                    await bot.send_message(
                        referrer_id,
                        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> <b>Реферальное вознаграждение!</b>\n\nРеферал совершил покупку\n'
                        f"Ваш заработок: <code>{reward_float:.2f} ₽</code> ({REFERRAL_PERCENT}% от прибыли)",
                        parse_mode='HTML'
                    )
                except:
                    pass
        except Exception as e:
            print(f"Ошибка при расчёте реферального вознаграждения: {e}")

    success_text = '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>TON успешно отправлены</b>\n\n<i>В некоторых случаях бывают задержки до 5 минут!</i>'
    if msg_id:
        try:
            await bot.edit_message_text(text=success_text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button(), parse_mode='HTML')
        except:
            await bot.send_message(user_id, success_text, reply_markup=await exit_button(), parse_mode='HTML')
    else:
        await bot.send_message(user_id, success_text, reply_markup=await exit_button(), parse_mode='HTML')

    await send_admin_notification(
        bot,
        f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь купил TON</b>\n\n🆔 ID: <code>{user_id}</code>\n💎 TON: <code>{tons}</code>\n💸 Потрачено: <code>{total_cost:.2f} ₽</code>',
        franchise_id=franchise_id,
        parse_mode='HTML'
    )


@router.message(UserState.wait_tons)
async def buy_tons_amount(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    balance = await get_balance(user_id)

    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()

    commission = Decimal(str(await effective_markup(COMMISSION_TON[0], franchise_id)))
    ton_price_rub = Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub))
    ton_price = ton_price_rub * (Decimal("1") + commission / Decimal("100"))
    ton_price = ton_price.quantize(Decimal("0.01"))

    balance_dec = Decimal(str(balance))
    max_by_user_balance = int(balance_dec // ton_price) if ton_price > 0 else 0

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    try:
        tons = int(message.text)
    except:
        await bot.send_message(user_id, "❌ Количество TON должно быть целым числом", reply_markup=await exit_button())
        return

    if balance < float(tons * ton_price):
        await bot.send_message(user_id, "❌ Недостаточно средств\nПополните баланс в профиле!", reply_markup=await ebal_button(float(tons) * float(ton_price)))
        return
    if tons < 1:
        await bot.send_message(user_id, "❌ Количество TON должно быть не менее 1", reply_markup=await exit_button())
        return
    if tons > max_by_user_balance:
        await bot.send_message(user_id, f"❌ Количество TON должно быть не более {max_by_user_balance}", reply_markup=await exit_button())
        return

    data = await state.get_data()
    username = data.get('username')
    await state.clear()

    queue_size = purchase_queue.queue_size()
    wait_msg = f"\n\n⏳ В очереди перед вами: {queue_size} покупок" if queue_size > 0 else ""

    queued_msg = await bot.send_message(user_id, f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Добавлено в очередь покупок...</b>{wait_msg}', parse_mode='HTML')

    async def purchase_task():
        await _execute_ton_purchase(bot, user_id, username, tons, ton_price, ton_price_rub, queued_msg.message_id, franchise_id)

    await purchase_queue.add(purchase_task)
