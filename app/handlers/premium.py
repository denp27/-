import asyncio
from decimal import Decimal

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import get_balance, deincrement_balance, increment_balance, get_referrer_id, add_transaction
from app.helpers import exit_button, ebal_button, effective_markup, get_section_photo, unified_send, send_admin_notification
from app.states import UserState
from app.config import COMMISSION_PREMIUM, REFERRAL_PERCENT
from app.utils.fragmentapi import PremiumSender, get_price_premium, get_ton_to_usd_price, price_usd_to_rub
from app.utils.walletapi import WalletApi
from app.queue_manager import purchase_queue

router = Router()
premium_frag = PremiumSender()
wallet = WalletApi()


async def show_buy_premium(call: CallbackQuery, username: str, bot: Bot, franchise_id: int = 0):
    photo = await get_section_photo(franchise_id, "premium")
    text = (
        '<b><tg-emoji emoji-id="5884479287171485878">📦</tg-emoji> Покупка Premium</b>\n\n'
        '<tg-emoji emoji-id="6037397706505195857">👁</tg-emoji> Выберите, кому будем покупать премиум'
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Себе", callback_data="premium_self", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Другу", callback_data="premium_friend", icon_custom_emoji_id="5870772616305839506")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1).as_markup()
    await unified_send(call, bot, text, markup, photo=photo)


async def _show_premium_tariffs(bot: Bot, user_id: int, msg_id: int, username: str, state: FSMContext, franchise_id: int = 0):
    msg2 = await bot.edit_message_text('<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Получаем стоимость подписки…</b>', chat_id=user_id, message_id=msg_id, parse_mode="HTML")
    await asyncio.sleep(0.7)

    markup_pct = await effective_markup(COMMISSION_PREMIUM[0], franchise_id)
    three_data = await get_price_premium(markup=markup_pct, months='3')
    six_data = await get_price_premium(markup=markup_pct, months='6')
    twelve_data = await get_price_premium(markup=markup_pct, months='12')

    msg3 = await bot.edit_message_text('<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Обновляем данные…</b>', chat_id=user_id, message_id=msg2.message_id, parse_mode="HTML")
    await asyncio.sleep(0.7)

    three = three_data['price_to_rub']
    six = six_data['price_to_rub']
    twelve = twelve_data['price_to_rub']

    await state.update_data({'three': three, 'six': six, 'twelve': twelve})

    builder = InlineKeyboardBuilder()
    builder.button(text=f"3 месяца — {three:.0f} ₽", callback_data="premium_buy:3", icon_custom_emoji_id="5794164805065514131")
    builder.button(text=f"6 месяцев — {six:.0f} ₽", callback_data="premium_buy:6", icon_custom_emoji_id="5794324702402976226")
    builder.button(text=f"12 месяцев — {twelve:.0f} ₽", callback_data="premium_buy:12", icon_custom_emoji_id="5794375786743995258")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")

    final_text = (
        '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь найден!</b>\n\n'
        '<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Выберите вариант подарочной подписки Telegram Premium:</b>\n\n'
        '<i>Все тарифы формируются в реальном времени и включают комиссию сервиса.</i>'
    )

    await bot.edit_message_text(text=final_text, chat_id=user_id, message_id=msg3.message_id, reply_markup=builder.adjust(2, 1, 1).as_markup(), parse_mode='HTML')


@router.callback_query(F.data == "premium_self")
async def buy_premium_self(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    username = call.from_user.username
    if not username:
        await bot.answer_callback_query(call.id, "⚠️ Установите username в настройках Telegram", show_alert=True)
        return

    msg = await bot.edit_message_text('<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Получаем данные пользователя…</b>', chat_id=user_id, message_id=call.message.message_id, parse_mode="HTML")
    await asyncio.sleep(1)

    username_check = await premium_frag.check_right_recipient(username, 3)
    if username_check == "not_founded":
        await bot.edit_message_text("❌ Пользователь не найден", chat_id=user_id, message_id=msg.message_id, reply_markup=await exit_button())
        return
    if username_check == "premium_already":
        await bot.edit_message_text("❌ Вы уже имеете премиум", chat_id=user_id, message_id=msg.message_id, reply_markup=await exit_button())
        return
    if not username_check:
        await bot.edit_message_text("❌ Произошла ошибка", chat_id=user_id, message_id=msg.message_id, reply_markup=await exit_button())
        return

    await state.update_data({'username': username_check})
    await _show_premium_tariffs(bot, user_id, msg.message_id, username_check, state, franchise_id)


@router.callback_query(F.data == "premium_friend")
async def buy_premium_friend(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    username = call.from_user.username
    text = (
        '<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Введите юзернейм друга, которому вы желаете купить премиум:</b>\n'
        f"└ Пример: @{username} или {username}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="buy_premium", icon_custom_emoji_id="5960671702059848143")
    await bot.edit_message_text(
        chat_id=user_id, message_id=call.message.message_id,
        text=text, parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(UserState.wait_username_premium)


@router.message(UserState.wait_username_premium)
async def buy_premium_username(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    msg = await bot.send_message(user_id, '<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Получаем данные пользователя…</b>', parse_mode="HTML")
    await asyncio.sleep(1)

    username = await premium_frag.check_right_recipient(message.text, 3)
    if username == "not_founded":
        await bot.send_message(user_id, "❌ Пользователь не найден", reply_markup=await exit_button())
        return
    if username == "premium_already":
        await bot.send_message(user_id, "❌ Пользователь уже имеет премиум", reply_markup=await exit_button())
        return
    if not username:
        await bot.send_message(user_id, "❌ Произошла ошибка", reply_markup=await exit_button())
        return

    await state.update_data({'username': username})
    await _show_premium_tariffs(bot, user_id, msg.message_id, username, state, franchise_id)


async def _execute_premium_purchase(bot: Bot, user_id: int, username: str, tariff: str, price: float, msg_id: int = None, franchise_id: int = 0):
    try:
        balance = await get_balance(user_id)
        if balance < price:
            text = "<b>❌ Недостаточно средств</b>"
            if msg_id:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await ebal_button(price), parse_mode='HTML')
            else:
                await bot.send_message(user_id, text, reply_markup=await ebal_button(price), parse_mode='HTML')
            return

        pricer = await get_price_premium(markup=0, months=tariff)
        pricer = pricer['price_ton']

        wallet_balance = await wallet.get_balance_ton()
        if wallet_balance < pricer:
            await send_admin_notification(
                bot,
                "❌ Пользователь не смог купить Premium.\n\nПополните баланс кошелька",
                franchise_id=franchise_id
            )
            text = "<b>❌ Произошла ошибка</b>"
            if msg_id:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button(), parse_mode='HTML')
            else:
                await bot.send_message(user_id, text, reply_markup=await exit_button(), parse_mode='HTML')
            return

        deducted = await deincrement_balance(user_id, price)
        if not deducted:
            text = "<b>❌ Недостаточно средств</b>"
            if msg_id:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await ebal_button(price), parse_mode='HTML')
            else:
                await bot.send_message(user_id, text, reply_markup=await ebal_button(price), parse_mode='HTML')
            return

        result = await premium_frag.send_premium(username, int(tariff))
        if not result:
            await increment_balance(user_id, price)
            text = "<b>❌ Произошла ошибка</b>"
            if msg_id:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button(), parse_mode='HTML')
            else:
                await bot.send_message(user_id, text, reply_markup=await exit_button(), parse_mode='HTML')
            return

        await add_transaction(user_id, 'premium', int(tariff), float(price), username)

        base_price = pricer * float(Decimal(str(await get_ton_to_usd_price())) * Decimal(str(await price_usd_to_rub())))
        profit = float(price) - base_price
        referrer_id = await get_referrer_id(user_id)
        if referrer_id and REFERRAL_PERCENT > 0:
            try:
                referral_reward = Decimal(str(profit)) * (Decimal(str(REFERRAL_PERCENT)) / Decimal("100"))
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
                print(f"Ошибка реферального вознаграждения: {e}")

        success_text = f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Подписка успешно куплена</b>\n └ Оставшийся баланс: {balance - float(price):.2f} ₽'
        if msg_id:
            try:
                await bot.edit_message_text(text=success_text, chat_id=user_id, message_id=msg_id, parse_mode="HTML", reply_markup=await exit_button())
            except:
                await bot.send_message(user_id, success_text, parse_mode="HTML", reply_markup=await exit_button())
        else:
            await bot.send_message(user_id, success_text, parse_mode="HTML", reply_markup=await exit_button())

        await send_admin_notification(
            bot,
            f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь купил Premium</b>\n\n🆔 ID: <code>{user_id}</code>\n🎁 Срок: <code>{tariff} мес.</code>\n💸 Потрачено: <code>{price:.2f} ₽</code>',
            franchise_id=franchise_id,
            parse_mode='HTML'
        )

    except Exception as e:
        print("[SEND PREMIUM] Error: ", e)
        text = "❌ Произошла ошибка"
        if msg_id:
            try:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=await exit_button())
            except:
                await bot.send_message(user_id, text, reply_markup=await exit_button())
        else:
            await bot.send_message(user_id, text, reply_markup=await exit_button())


@router.callback_query(F.data.startswith("premium_buy"))
async def premium_buy_final(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    balance = await get_balance(user_id)

    try:
        tariff = call.data.split(':')[1]
        data = await state.get_data()
        username = data.get('username')
        three = data.get('three')
        six = data.get('six')
        twelve = data.get('twelve')

        if tariff == '3':
            price = three
        elif tariff == '6':
            price = six
        elif tariff == '12':
            price = twelve

        if not username:
            await bot.edit_message_text(text="<b>❌ Произошла ошибка</b>", chat_id=user_id, message_id=call.message.message_id, reply_markup=await exit_button(), parse_mode='HTML')
            return

        if price > balance:
            await bot.edit_message_text(
                text=f"<b>❌ Недостаточно средств</b>\n ├ Необходимо: {price:.2f} ₽\n └ Ваш баланс: {balance:.2f} ₽",
                chat_id=user_id, message_id=call.message.message_id,
                reply_markup=await ebal_button(float(price) - float(balance)), parse_mode='HTML'
            )
            return

        await state.clear()

        queue_size = purchase_queue.queue_size()
        wait_msg = f"\n\n⏳ В очереди перед вами: {queue_size} покупок" if queue_size > 0 else ""

        await bot.edit_message_text(
            text=f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Добавлено в очередь покупок...</b>{wait_msg}',
            chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML'
        )

        message_id = call.message.message_id

        async def purchase_task():
            await _execute_premium_purchase(bot, user_id, username, tariff, price, message_id, franchise_id)

        await purchase_queue.add(purchase_task)

    except Exception as e:
        await bot.edit_message_text(text="❌ Произошла ошибка", chat_id=user_id, message_id=call.message.message_id, reply_markup=await exit_button())
