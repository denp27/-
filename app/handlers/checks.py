import uuid
import urllib.parse
from decimal import Decimal

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

import app.database as db
from app.helpers import exit_button, effective_markup, send_admin_notification
from app.states import CheckState
from app.config import COMMISSION_STARS, COMMISSION_PREMIUM, COMMISSION_TON
from app.utils.fragmentapi import (
    StarSender, PremiumSender, get_price_premium,
    TonSender, get_ton_to_usd_price, price_usd_to_rub,
)
from app.queue_manager import purchase_queue

router = Router()
fragment = StarSender()
premium_frag = PremiumSender()
fragment_ton = TonSender()

_TYPE_ICONS = {
    'stars': '6028338546736107668',
    'premium': '5773677501825945508',
    'ton': '5776023601941582822',
}

_TYPE_LABELS = {
    'stars': lambda a: f'{int(a)} ⭐️',
    'premium': lambda a: f'Premium {int(a)} мес.',
    'ton': lambda a: f'{int(a)} TON',
}


def _gen_check_id() -> str:
    return uuid.uuid4().hex[:12]


def _make_share_url(link: str, label: str) -> str:
    return f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={urllib.parse.quote('🎁 ' + label)}"



@router.callback_query(F.data == "create_check")
async def show_check_menu(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    await state.clear()
    user_id = call.from_user.id

    text = (
        '<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Создание чека</b>\n\n'
        '<blockquote>'
        '<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Чек — это ссылка, по которой ваш друг\n'
        'получит выбранный товар автоматически.\n\n'
        'Оплата списывается сразу при создании чека.'
        '</blockquote>\n\n'
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Выберите тип чека:</b>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Звёзды", callback_data="check_type:stars", icon_custom_emoji_id="6028338546736107668")
    builder.button(text="Premium", callback_data="check_type:premium", icon_custom_emoji_id="5773677501825945508")
    builder.button(text="TON", callback_data="check_type:ton", icon_custom_emoji_id="5776023601941582822")
    builder.button(text="Назад", callback_data="profile", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(2, 1, 1)

    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )



@router.callback_query(F.data == "check_type:stars")
async def check_stars_menu(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id

    await bot.edit_message_text(
        '<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Загружаем актуальную цену…</b>',
        chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML'
    )

    price = await fragment.get_price_star()
    commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
    star_price = price * (Decimal("1") + commission / Decimal("100"))
    star_price = star_price.quantize(Decimal("0.01"))

    if star_price == 0:
        await bot.edit_message_text(
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Ошибка получения цены. Попробуйте позже.',
            chat_id=user_id, message_id=call.message.message_id,
            reply_markup=await exit_button(), parse_mode='HTML'
        )
        return

    await state.update_data({'star_price': float(star_price), 'check_type': 'stars'})

    quantities = [50, 100, 150, 250, 500, 1000, 2500, 5000]

    text = (
        '<b><tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji> Чек на звёзды</b>\n\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> 1 звезда → <code>{star_price:.2f} ₽</code>\n\n'
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Выберите количество звёзд:</b>'
    )

    builder = InlineKeyboardBuilder()
    for qty in quantities:
        total = float(star_price * qty)
        builder.button(text=f"{qty} ⭐ — {total:,.2f} ₽", callback_data=f"check_stars_qty:{qty}")
    builder.button(text="Своё количество", callback_data="check_stars_custom", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Назад", callback_data="create_check", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(2, 2, 2, 2, 1, 1)

    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("check_stars_qty:"))
async def check_stars_qty(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    stars = int(call.data.split(":")[1])

    data = await state.get_data()
    star_price = Decimal(str(data.get('star_price', 0)))
    if star_price == 0:
        price = await fragment.get_price_star()
        commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
        star_price = price * (Decimal("1") + commission / Decimal("100"))
        star_price = star_price.quantize(Decimal("0.01"))

    total = float(star_price * stars)
    balance = await db.get_balance(user_id)
    await state.update_data({'check_amount': stars, 'check_cost': total, 'check_type': 'stars'})

    await _show_confirm(call.message, user_id, bot, 'stars', stars, total, balance, edit=True)


@router.callback_query(F.data == "check_stars_custom")
async def check_stars_custom(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="check_type:stars", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        '<b><tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> Введите количество звёзд</b>\n\n'
        '<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Минимум: <b>50</b> | Максимум: <b>5 000</b>',
        chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(CheckState.wait_stars_amount)


@router.message(CheckState.wait_stars_amount)
async def check_stars_amount_msg(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except Exception:
        pass

    try:
        stars = int(message.text.strip())
    except Exception:
        await bot.send_message(user_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Введите целое число', parse_mode='HTML', reply_markup=await exit_button())
        return

    if stars < 50:
        await bot.send_message(user_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Минимум 50 звёзд', parse_mode='HTML', reply_markup=await exit_button())
        return
    if stars > 5000:
        await bot.send_message(user_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Максимум 5 000 звёзд', parse_mode='HTML', reply_markup=await exit_button())
        return

    data = await state.get_data()
    star_price = Decimal(str(data.get('star_price', 0)))
    if star_price == 0:
        price = await fragment.get_price_star()
        commission = Decimal(str(await effective_markup(COMMISSION_STARS[0], franchise_id)))
        star_price = price * (Decimal("1") + commission / Decimal("100"))
        star_price = star_price.quantize(Decimal("0.01"))

    total = float(star_price * stars)
    balance = await db.get_balance(user_id)
    await state.update_data({'check_amount': stars, 'check_cost': total, 'check_type': 'stars'})
    await state.set_state(None)

    msg = await bot.send_message(user_id, '⏳', parse_mode='HTML')
    await _show_confirm(msg, user_id, bot, 'stars', stars, total, balance, edit=True)



@router.callback_query(F.data == "check_type:premium")
async def check_premium_menu(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id

    msg = await bot.edit_message_text(
        '<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Загружаем актуальные тарифы…</b>',
        chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML'
    )

    markup_pct = await effective_markup(COMMISSION_PREMIUM[0], franchise_id)
    three_data = await get_price_premium(markup=markup_pct, months='3')
    six_data = await get_price_premium(markup=markup_pct, months='6')
    twelve_data = await get_price_premium(markup=markup_pct, months='12')

    p3 = three_data['price_to_rub']
    p6 = six_data['price_to_rub']
    p12 = twelve_data['price_to_rub']
    await state.update_data({'check_type': 'premium', 'p3': p3, 'p6': p6, 'p12': p12})

    text = (
        '<b><tg-emoji emoji-id="5773677501825945508">🔹</tg-emoji> Чек на Telegram Premium</b>\n\n'
        '<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Выберите срок подписки:</b>\n\n'
        '<i>Тарифы формируются в реальном времени и включают комиссию сервиса.</i>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"3 мес. — {p3:.0f} ₽", callback_data="check_premium_qty:3", icon_custom_emoji_id="5794164805065514131")
    builder.button(text=f"6 мес. — {p6:.0f} ₽", callback_data="check_premium_qty:6", icon_custom_emoji_id="5794324702402976226")
    builder.button(text=f"12 мес. — {p12:.0f} ₽", callback_data="check_premium_qty:12", icon_custom_emoji_id="5794375786743995258")
    builder.button(text="Назад", callback_data="create_check", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(2, 1, 1)

    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=msg.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("check_premium_qty:"))
async def check_premium_qty(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    months = call.data.split(":")[1]

    data = await state.get_data()
    prices = {'3': data.get('p3', 0), '6': data.get('p6', 0), '12': data.get('p12', 0)}
    total = prices.get(months, 0)
    balance = await db.get_balance(user_id)
    await state.update_data({'check_amount': int(months), 'check_cost': total, 'check_type': 'premium'})

    await _show_confirm(call.message, user_id, bot, 'premium', int(months), total, balance, edit=True)



@router.callback_query(F.data == "check_type:ton")
async def check_ton_menu(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    balance = await db.get_balance(user_id)

    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()
    commission = Decimal(str(await effective_markup(COMMISSION_TON[0], franchise_id)))
    ton_price_rub = Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub))
    final_sum = ton_price_rub * (Decimal("1") + commission / Decimal("100"))
    final_sum = final_sum.quantize(Decimal("0.01"))

    max_can_buy = int(Decimal(str(balance)) // final_sum) if final_sum > 0 else 0
    await state.update_data({'check_type': 'ton', 'ton_price': float(final_sum)})

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="create_check", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        f'<b><tg-emoji emoji-id="5776023601941582822">💎</tg-emoji> Чек на TON</b>\n\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> 1 TON → <code>{final_sum:.2f} ₽</code>\n'
        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> Доступно: <code>{max_can_buy} TON</code>\n\n'
        f'<tg-emoji emoji-id="5870676941614354370">🖋</tg-emoji> <b>Введите количество TON:</b>\n'
        f'<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Минимум: <b>1 TON</b>',
        chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup()
    )
    await state.set_state(CheckState.wait_ton_amount)


@router.message(CheckState.wait_ton_amount)
async def check_ton_amount_msg(message: Message, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = message.from_user.id
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except Exception:
        pass

    try:
        tons = int(message.text.strip())
    except Exception:
        await bot.send_message(user_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Введите целое число', parse_mode='HTML', reply_markup=await exit_button())
        return

    if tons < 1:
        await bot.send_message(user_id, '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Минимум 1 TON', parse_mode='HTML', reply_markup=await exit_button())
        return

    data = await state.get_data()
    ton_price = Decimal(str(data.get('ton_price', 0)))
    if ton_price == 0:
        ton_price_usd = await get_ton_to_usd_price()
        usd_price_rub = await price_usd_to_rub()
        commission = Decimal(str(await effective_markup(COMMISSION_TON[0], franchise_id)))
        ton_price_rub = Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub))
        ton_price = ton_price_rub * (Decimal("1") + commission / Decimal("100"))
        ton_price = ton_price.quantize(Decimal("0.01"))

    total = float(ton_price * tons)
    balance = await db.get_balance(user_id)
    await state.update_data({'check_amount': tons, 'check_cost': total, 'check_type': 'ton'})
    await state.set_state(None)

    msg = await bot.send_message(user_id, '⏳', parse_mode='HTML')
    await _show_confirm(msg, user_id, bot, 'ton', tons, total, balance, edit=True)



async def _show_confirm(msg, user_id: int, bot: Bot, check_type: str, amount, total: float, balance: float, edit: bool = True):
    label = _TYPE_LABELS[check_type](amount)
    icon = _TYPE_ICONS[check_type]
    can_afford = balance >= total

    extra_note = ''
    if check_type == 'premium':
        extra_note = '\n<tg-emoji emoji-id="5870875489362513438">🗑</tg-emoji> <i>Не активируется, если у получателя уже есть Premium.</i>'

    afford_icon = '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji>' if can_afford else '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji>'
    text = (
        f'<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Подтверждение чека</b>\n\n'
        f'<tg-emoji emoji-id="{icon}">🎁</tg-emoji> Содержимое: <b>{label}</b>\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Стоимость: <b><code>{total:,.2f} ₽</code></b>\n'
        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> Ваш баланс: <code>{balance:.2f} ₽</code>'
        f'  {afford_icon}\n\n'
        f'<blockquote><tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> После создания чека вы получите '
        f'ссылку. Ваш друг получит {label} при переходе в бот.{extra_note}</blockquote>'
    )

    builder = InlineKeyboardBuilder()
    if can_afford:
        builder.button(text="Создать чек", callback_data="check_confirm", icon_custom_emoji_id="5870633910337015697")
    else:
        need = total - balance
        builder.button(text="Пополнить баланс", callback_data=f"deposit_auto:{need:.2f}", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Назад", callback_data=f"check_type:{check_type}", icon_custom_emoji_id="5960671702059848143")
    builder.adjust(1)

    if edit:
        await bot.edit_message_text(
            text=text, chat_id=user_id, message_id=msg.message_id,
            parse_mode='HTML', reply_markup=builder.as_markup()
        )
    else:
        await bot.send_message(user_id, text, parse_mode='HTML', reply_markup=builder.as_markup())



@router.callback_query(F.data == "check_confirm")
async def check_confirm(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id

    data = await state.get_data()
    check_type = data.get('check_type')
    check_amount = data.get('check_amount')
    check_cost = data.get('check_cost')

    if not check_type or check_amount is None or check_cost is None:
        await call.answer("⚠️ Данные устарели, начните заново", show_alert=True)
        return

    balance = await db.get_balance(user_id)
    if balance < check_cost:
        await call.answer("❌ Недостаточно средств", show_alert=True)
        return

    deducted = await db.deincrement_balance(user_id, check_cost)
    if not deducted:
        await call.answer("❌ Недостаточно средств", show_alert=True)
        return

    check_id = _gen_check_id()
    success = await db.create_check(check_id, user_id, check_type, float(check_amount), check_cost)
    if not success:
        await db.increment_balance(user_id, check_cost)
        await call.answer("❌ Ошибка создания чека", show_alert=True)
        return
    await state.clear()

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=chk{check_id}"
    label = _TYPE_LABELS[check_type](check_amount)
    icon = _TYPE_ICONS[check_type]
    new_balance = balance - check_cost

    share_url = _make_share_url(link, f'Чек на {label}')

    text = (
        f'<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Чек успешно создан!</b>\n\n'
        f'<tg-emoji emoji-id="{icon}">🎁</tg-emoji> Содержимое: <b>{label}</b>\n'
        f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Оплачено: <code>{check_cost:,.2f} ₽</code>\n'
        f'<tg-emoji emoji-id="5769126056262898415">👛</tg-emoji> Остаток баланса: <code>{new_balance:.2f} ₽</code>\n\n'
        f'<tg-emoji emoji-id="5769289093221454192">🔗</tg-emoji> <b>Ссылка на чек:</b>\n'
        f'<code>{link}</code>\n\n'
        f'<blockquote><tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Отправьте ссылку другу — он получит '
        f'{label} автоматически при переходе в бот.</blockquote>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Поделиться чеком", url=share_url, icon_custom_emoji_id="5963103826075456248")
    builder.button(text="Профиль", callback_data="profile", icon_custom_emoji_id="5870994129244131212")
    builder.adjust(1)

    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=builder.as_markup(),
        disable_web_page_preview=True
    )



async def activate_check(message: Message, bot: Bot, check_id: str, franchise_id: int = 0):
    user_id = message.from_user.id
    username = message.from_user.username

    check = await db.get_check(check_id)

    if not check:
        await bot.send_message(
            user_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Чек не найден</b>\n\n'
            '<i>Ссылка недействительна или чек был удалён.</i>',
            parse_mode='HTML', reply_markup=await exit_button()
        )
        return

    _cid, creator_id, check_type, amount, cost_rub, is_active, used_by, _ = check

    if not is_active:
        await bot.send_message(
            user_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Чек уже активирован</b>\n\n'
            '<i>Этот чек был использован ранее.</i>',
            parse_mode='HTML', reply_markup=await exit_button()
        )
        return

    if creator_id == user_id:
        await bot.send_message(
            user_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Нельзя активировать свой чек</b>\n\n'
            '<i>Чек предназначен для другого пользователя.</i>',
            parse_mode='HTML', reply_markup=await exit_button()
        )
        return

    if not username:
        await bot.send_message(
            user_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Требуется юзернейм</b>\n\n'
            'Установите юзернейм в настройках Telegram и попробуйте снова.',
            parse_mode='HTML', reply_markup=await exit_button()
        )
        return

    claimed = await db.mark_check_used(check_id, user_id)
    if not claimed:
        await bot.send_message(
            user_id,
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Чек уже активирован</b>',
            parse_mode='HTML', reply_markup=await exit_button()
        )
        return

    label = _TYPE_LABELS[check_type](amount)
    icon = _TYPE_ICONS[check_type]

    processing_msg = await bot.send_message(
        user_id,
        f'<tg-emoji emoji-id="5345906554510012647">🔄</tg-emoji> <b>Активируем чек…</b>\n\n'
        f'<tg-emoji emoji-id="{icon}">🎁</tg-emoji> Вы получаете: <b>{label}</b>',
        parse_mode='HTML'
    )

    async def do_activation():
        success = False
        error_text = 'Неизвестная ошибка'

        try:
            if check_type == 'stars':
                checked = await fragment.check_right_recipient(username)
                if not checked:
                    error_text = 'Аккаунт не найден на Fragment'
                else:
                    result = await fragment.send_stars(checked, int(amount))
                    success = bool(result)
                    if not success:
                        error_text = 'Ошибка при отправке звёзд'

            elif check_type == 'premium':
                checked = await premium_frag.check_right_recipient(username, int(amount))
                if checked == "not_founded":
                    error_text = 'Аккаунт не найден'
                elif checked == "premium_already":
                    error_text = 'У вас уже есть Telegram Premium'
                elif not checked:
                    error_text = 'Ошибка проверки аккаунта'
                else:
                    result = await premium_frag.send_premium(checked, int(amount))
                    success = bool(result)
                    if not success:
                        error_text = 'Ошибка при отправке Premium'

            elif check_type == 'ton':
                checked = await fragment_ton.check_right_recipient(username)
                if not checked:
                    error_text = 'Аккаунт не найден на Fragment'
                else:
                    result = await fragment_ton.send_ton(checked, int(amount))
                    success = bool(result)
                    if not success:
                        error_text = 'Ошибка при отправке TON'

        except Exception as e:
            print(f"[check activation error] {e}")
            error_text = 'Внутренняя ошибка сервиса'

        if success:
            await bot.edit_message_text(
                f'<b><tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> Чек активирован!</b>\n\n'
                f'<tg-emoji emoji-id="{icon}">🎁</tg-emoji> Вы получили: <b>{label}</b>\n\n'
                f'<i>В некоторых случаях возможна задержка до 5 минут.</i>',
                chat_id=user_id, message_id=processing_msg.message_id,
                parse_mode='HTML', reply_markup=await exit_button()
            )
            try:
                await bot.send_message(
                    creator_id,
                    f'<tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> <b>Ваш чек активирован!</b>\n\n'
                    f'Пользователь получил <b>{label}</b>.',
                    parse_mode='HTML'
                )
            except Exception:
                pass
            await send_admin_notification(
                bot,
                f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Чек активирован</b>\n\n'
                f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Отправитель: <code>{creator_id}</code>\n'
                f'<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Получатель: <code>{user_id}</code>\n'
                f'<tg-emoji emoji-id="5884479287171485878">📦</tg-emoji> Тип: <code>{check_type}</code>\n'
                f'<tg-emoji emoji-id="5904462880941545555">🪙</tg-emoji> Содержимое: <b>{label}</b>\n'
                f'<tg-emoji emoji-id="5879814368572478751">🏧</tg-emoji> Оплачено: <code>{cost_rub:.2f} ₽</code>',
                parse_mode='HTML'
            )
        else:
            await db.reactivate_check(check_id)
            await db.increment_balance(creator_id, cost_rub)
            await bot.edit_message_text(
                f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Ошибка активации</b>\n\n'
                f'{error_text}\n\n'
                f'<i>Средства возвращены создателю чека. Чек можно использовать повторно.</i>',
                chat_id=user_id, message_id=processing_msg.message_id,
                parse_mode='HTML', reply_markup=await exit_button()
            )
            try:
                await bot.send_message(
                    creator_id,
                    f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Ошибка активации чека</b>\n\n'
                    f'Причина: {error_text}\n'
                    f'Средства возвращены на ваш баланс. Чек активен снова.',
                    parse_mode='HTML'
                )
            except Exception:
                pass

    await purchase_queue.add(do_activation)
