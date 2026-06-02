import asyncio

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import increment_balance, create_deposit_invoice, mark_invoice_credited
from app.helpers import exit_button, send_admin_notification
from app.states import DepositState
from app.config import PLATEGA_MERCHANT_ID, PLATEGA_SECRET
from app.utils.cryptobotapi import CryptoApi
from app.utils.plategaapi import PlategaAPI

router = Router()
crypto = CryptoApi()
platega_api = PlategaAPI(PLATEGA_MERCHANT_ID, PLATEGA_SECRET)


@router.callback_query(F.data.startswith("deposit_auto:"))
async def deposit_auto(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    amount = float(call.data.split(":")[1])

    await state.set_state(DepositState.wait_amount)
    await state.update_data({'amount': amount})

    builder = InlineKeyboardBuilder()
    builder.button(text="СБП", callback_data="platega", icon_custom_emoji_id="5363972466857252756")
    builder.button(text="CryptoBot", callback_data="cryptobot", icon_custom_emoji_id="5260752406890711732")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        chat_id=user_id,
        message_id=call.message.message_id,
        text=f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Выберите способ пополнения:</b>\n\n<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма: <b>{amount:.2f} ₽</b>',
        reply_markup=builder.adjust(1).as_markup(),
        parse_mode='HTML'
    )
    await call.answer()


@router.callback_query(F.data == "deposit")
async def deposit(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=call.message.message_id,
        text='<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Введите сумму для пополнения в рублях:</b>',
        parse_mode='HTML',
        reply_markup=await exit_button()
    )
    await state.set_state(DepositState.wait_amount)


@router.message(DepositState.wait_amount)
async def deposit_amount(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id

    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("❌ Неверная сумма.", reply_markup=await exit_button())
        return

    if amount < 1:
        await message.answer("❌ Сумма должна быть больше 1 рубля!", reply_markup=await exit_button())
        return

    await state.set_data({'amount': amount})

    builder = InlineKeyboardBuilder()
    builder.button(text="СБП", callback_data="platega", icon_custom_emoji_id="5363972466857252756")
    builder.button(text="CryptoBot", callback_data="cryptobot", icon_custom_emoji_id="5260752406890711732")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")

    await bot.send_message(
        chat_id=user_id,
        text=f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> <b>Выберите способ пополнения:</b>\n\n<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма: <b>{amount:.2f} ₽</b>',
        reply_markup=builder.adjust(1).as_markup(),
        parse_mode='HTML'
    )


@router.callback_query(F.data == "cryptobot")
async def cryptobot_deposit(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    data = await state.get_data()
    amount = data['amount']

    curse = float(await crypto.RubToUsd())
    text = (
        '<tg-emoji emoji-id="5260752406890711732">👾</tg-emoji> Способ пополнения: <b>CryptoBot</b>\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма: <b>{amount:.2f} ₽</b>\n'
        f"<tg-emoji emoji-id='5936143551854285132'>📊</tg-emoji> Курс: <b>{curse:.2f}</b> ₽ за <b>1</b> USDT\n\n"
        "<i>Ожидайте подтверждения оплаты...</i>\n"
        '<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <i>Автоматическая проверка в течение 30 минут</i>'
    )

    usd = amount / curse
    invoice = await crypto.createInvoice('USDT', usd, f"Пополнение баланса на {amount:.2f} ₽")

    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить", url=invoice['result']['mini_app_invoice_url'], icon_custom_emoji_id="5890848474563352982")
    builder.button(text="Назад", callback_data="deposit", icon_custom_emoji_id="5960671702059848143")

    invoice_id = invoice['result']['invoice_id']
    message_id = call.message.message_id

    await create_deposit_invoice(str(invoice_id), user_id, amount, 'cryptobot')

    await bot.edit_message_text(text=text, chat_id=user_id, message_id=message_id, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())
    asyncio.create_task(auto_check_crypto_payment(bot, user_id, invoice_id, amount, message_id, state, franchise_id))


async def auto_check_crypto_payment(bot: Bot, user_id: int, invoice_id: int, amount: float, message_id: int, state: FSMContext, franchise_id: int = 0):
    max_attempts = 60
    attempt = 0

    while attempt < max_attempts:
        try:
            await asyncio.sleep(30)
            attempt += 1

            result = await crypto.getPaidInvoice(invoice_id)
            paid = len(result['result']['items']) > 0

            if paid:
                credited = await mark_invoice_credited(str(invoice_id))
                if not credited:
                    try:
                        await bot.edit_message_text(
                            text=f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽',
                            chat_id=user_id, message_id=message_id, parse_mode='HTML',
                            reply_markup=await exit_button()
                        )
                    except Exception:
                        pass
                    await state.clear()
                    return

                try:
                    user_info = await bot.get_chat(user_id)
                    user_name = user_info.full_name
                except Exception:
                    user_name = str(user_id)
                await send_admin_notification(
                    bot,
                    f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь пополнил баланс</b>\n\n'
                    f"👤 Пользователь: <a href='tg://user?id={user_id}'>{user_name}</a>\n"
                    f"💰 Сумма: <b>{amount:.2f} ₽</b>\n"
                    f"⚙️ Метод оплаты: <a href='https://t.me/send'><b>CryptoBot</b></a>",
                    franchise_id=franchise_id,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )

                await increment_balance(user_id, amount)

                try:
                    await bot.edit_message_text(
                        text=f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽',
                        chat_id=user_id, message_id=message_id, parse_mode='HTML',
                        reply_markup=await exit_button()
                    )
                except Exception:
                    await bot.send_message(user_id, f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽', parse_mode='HTML')

                await state.clear()
                return

        except Exception as e:
            print(f"Ошибка проверки CryptoBot платежа: {e}")
            continue

    try:
        await bot.edit_message_text(
            text='<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Время ожидания платежа истекло</b>\n\nЕсли вы оплатили, обратитесь в поддержку.',
            chat_id=user_id, message_id=message_id, parse_mode='HTML',
            reply_markup=await exit_button()
        )
    except:
        pass
    await state.clear()


@router.callback_query(F.data == "platega")
async def platega_deposit(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id

    try:
        data = await state.get_data()
        amount = data['amount']
    except:
        await call.answer("❌ Ошибка! Попробуйте снова", show_alert=True)
        return

    text = (
        '<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> Способ пополнения: <b>СБП</b>\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Сумма: <b>{amount:.2f} ₽</b>\n\n'
        "<i>Ожидайте подтверждения оплаты...</i>\n"
        '<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <i>Автоматическая проверка в течение 30 минут</i>'
    )

    invoice = await platega_api.create_invoice(amount=amount)
    url_pay = invoice['redirect']
    transaction_id = invoice['transactionId']
    message_id = call.message.message_id

    await create_deposit_invoice(str(transaction_id), user_id, amount, 'platega')

    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить", url=url_pay, icon_custom_emoji_id="5890848474563352982")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        chat_id=user_id, message_id=message_id, text=text, parse_mode='HTML',
        reply_markup=builder.adjust(1).as_markup()
    )
    asyncio.create_task(auto_check_platega_payment(bot, user_id, transaction_id, amount, message_id, state, franchise_id))


async def auto_check_platega_payment(bot: Bot, user_id: int, transaction_id: str, amount: float, message_id: int, state: FSMContext, franchise_id: int = 0):
    max_attempts = 60
    attempt = 0

    while attempt < max_attempts:
        try:
            await asyncio.sleep(30)
            attempt += 1

            invoice = await platega_api.check_invoice(transaction_id)
            status = invoice.get("status", "").upper()

            if status == "CONFIRMED":
                credited = await mark_invoice_credited(str(transaction_id))
                if not credited:
                    try:
                        await bot.edit_message_text(
                            text=f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽',
                            chat_id=user_id, message_id=message_id, parse_mode='HTML',
                            reply_markup=await exit_button()
                        )
                    except Exception:
                        pass
                    await state.clear()
                    return

                try:
                    user_info = await bot.get_chat(user_id)
                    user_name = user_info.full_name
                except Exception:
                    user_name = str(user_id)
                await send_admin_notification(
                    bot,
                    f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Пользователь пополнил баланс</b>\n\n'
                    f"👤 Пользователь: <a href='tg://user?id={user_id}'>{user_name}</a>\n"
                    f"💰 Сумма: <b>{amount:.2f} ₽</b>\n"
                    f"⚙️ Метод оплаты: <a href='https://platega.io/'><b>СБП</b></a>",
                    franchise_id=franchise_id,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )

                await increment_balance(user_id, amount)

                try:
                    await bot.edit_message_text(
                        text=f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽',
                        chat_id=user_id, message_id=message_id, parse_mode='HTML',
                        reply_markup=await exit_button()
                    )
                except Exception:
                    await bot.send_message(user_id, f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Платёж прошёл успешно!</b>\n\n💰 Ваш баланс пополнен на {amount:.2f} ₽', parse_mode='HTML')

                await state.clear()
                return

            elif status in ("FAILED", "EXPIRED", "CANCELED", "REFUNDED", "CHARGEBACKED"):
                try:
                    await bot.edit_message_text(
                        text='<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Платёж не прошёл</b>\n\nПопробуйте снова или выберите другой способ оплаты.',
                        chat_id=user_id, message_id=message_id, parse_mode='HTML',
                        reply_markup=await exit_button()
                    )
                except:
                    pass
                await state.clear()
                return

        except Exception as e:
            print(f"Ошибка проверки Platega платежа: {e}")
            continue

    try:
        await bot.edit_message_text(
            text='<tg-emoji emoji-id="5983150113483134607">⏰</tg-emoji> <b>Время ожидания платежа истекло</b>\n\nЕсли вы оплатили, обратитесь в поддержку.',
            chat_id=user_id, message_id=message_id, parse_mode='HTML',
            reply_markup=await exit_button()
        )
    except:
        pass
    await state.clear()
