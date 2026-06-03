import random

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import add_user, user_exists, increment_referrals_count, get_all_required_channels
from app.helpers import check_subscription, show_subscription_required, exit_button, unified_send, franchise_branding, get_section_photo
from app.config import REFERRAL_PERCENT, SUPPORT_URL

router = Router()

EMOJI_GROUPS = [
    ("🍎", "🍏"), ("🐶", "🐱"), ("🌞", "🌙"), ("🔴", "🔵"),
    ("⚽", "🏀"), ("🍕", "🍔"), ("🚗", "🚙"), ("🐸", "🐢"),
    ("🍊", "🍋"), ("🌹", "🌻"), ("🐧", "🐤"), ("🍇", "🍓"),
    ("🦊", "🐺"), ("☀️", "⭐"), ("🎸", "🎹"), ("🍦", "🧁"),
    ("🐟", "🐠"), ("🏠", "🏰"), ("✈️", "🚀"), ("📱", "💻"),
]

captcha_data = {}
pending_checks: dict[int, str] = {}  # user_id -> check_id awaiting activation after subscription


async def show_start(event, bot: Bot, franchise_id: int = 0):
    from app.database import get_count_starsbuyed
    project_name, support_url = await franchise_branding(franchise_id)
    photo = await get_section_photo(franchise_id, "start")
    text = (
        f'<b><tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> Приветствую в <u>{project_name}</u></b>\n\n'
        f'<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Куплено звёзд через нас:</b> {await get_count_starsbuyed()} <tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji>\n\n'
        "У нас вы можете:\n"
        "<blockquote>"
        '<tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji> Приобрести и подарить звёзды по низким ценам!\n'
        '<tg-emoji emoji-id="5773677501825945508">🔹</tg-emoji> Приобрести Telegram Premium\n'
        '<tg-emoji emoji-id="5776023601941582822">💎</tg-emoji> Купить TON на аккаунт'
        "</blockquote>\n\n"
        '<tg-emoji emoji-id="6039451237743595514">📎</tg-emoji> <i>Выберите действие ниже</i>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="FAQ", callback_data="faq_button", icon_custom_emoji_id="6028435952299413210")
    builder.button(text="Купить TON", callback_data="buy_ton", icon_custom_emoji_id="5776023601941582822")
    builder.button(text="Купить звёзды", callback_data="buy_stars", icon_custom_emoji_id="6028338546736107668")
    builder.button(text="Купить премиум", callback_data="buy_premium", icon_custom_emoji_id="5773677501825945508")
    builder.button(text="Купить подарок", callback_data="hidden_gifts", icon_custom_emoji_id="6032625495328165724")
    builder.button(text="Аренда NFT", callback_data="nft_rent", icon_custom_emoji_id="6044004057696177711")
    builder.button(text="Аренда Номера", callback_data="rent_number", icon_custom_emoji_id="5346132555689119666")
    builder.button(text="Профиль", callback_data="profile", icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Топ", callback_data="top_referrers", icon_custom_emoji_id="5870921681735781843")
    builder.button(text="Франшиза", callback_data="franchise", icon_custom_emoji_id="5873147866364514353")
    builder.button(text="Поддержка 24/7", url=support_url, icon_custom_emoji_id="6039422865189638057")
    markup = builder.adjust(1, 1, 2, 2, 1, 2, 2, 1, 1).as_markup()
    await unified_send(event, bot, text, markup, photo=photo)


async def show_captcha(message_or_bot, bot: Bot, user_id: int, username: str, referrer_id: int):
    main_emoji, different_emoji = random.choice(EMOJI_GROUPS)
    correct_index = random.randint(0, 2)
    emojis = [main_emoji, main_emoji, main_emoji]
    emojis[correct_index] = different_emoji
    captcha_data[user_id] = {
        "referrer_id": referrer_id,
        "username": username,
        "correct_index": correct_index
    }

    text = (
        '<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Подтвердите, что вы не робот</b>\n\n'
        f"Выберите <b>непохожий</b> эмодзи:\n\n"
        f"<code>{emojis[0]}  {emojis[1]}  {emojis[2]}</code>"
    )

    builder = InlineKeyboardBuilder()
    for i, emoji in enumerate(emojis):
        builder.button(text=emoji, callback_data=f"captcha_{i}")
    builder.adjust(3)

    await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML", reply_markup=builder.as_markup())


@router.message(CommandStart())
async def starter(message: Message, bot: Bot, franchise_id: int = 0):
    user_id = message.from_user.id
    username = message.from_user.username

    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        try:
            ref_code = message.text.split()[1]
            if ref_code.startswith('chk'):
                check_id = ref_code[3:]
                is_subscribed, not_subscribed_channels = await check_subscription(bot, user_id, franchise_id)
                if not is_subscribed:
                    pending_checks[user_id] = check_id
                    await show_subscription_required(bot, user_id, not_subscribed_channels)
                    return
                if not await user_exists(user_id):
                    await add_user(user_id, username, None)
                from app.handlers.checks import activate_check
                await activate_check(message, bot, check_id, franchise_id)
                return
            elif ref_code.startswith('ref'):
                referrer_id = int(ref_code[3:])
                if referrer_id == user_id:
                    referrer_id = None
                elif not await user_exists(referrer_id):
                    referrer_id = None
        except (ValueError, IndexError):
            referrer_id = None

    is_subscribed, not_subscribed_channels = await check_subscription(bot, user_id, franchise_id)
    if not is_subscribed:
        if referrer_id and not await user_exists(user_id):
            captcha_data[user_id] = {
                "referrer_id": referrer_id,
                "username": username,
                "needs_captcha": True,
                "franchise_id": franchise_id,
            }
        await show_subscription_required(bot, user_id, not_subscribed_channels)
        return

    if not await user_exists(user_id) and referrer_id:
        await show_captcha(message, bot, user_id, username, referrer_id)
        return

    if not await user_exists(user_id):
        await add_user(user_id, username, None)

    await show_start(message, bot, franchise_id)


@router.callback_query(F.data.startswith('captcha_'))
async def captcha_handler(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id

    if user_id not in captcha_data:
        await bot.answer_callback_query(call.id, "⚠️ Капча устарела, используйте /start", show_alert=True)
        return

    selected_index = int(call.data.split('_')[1])
    data = captcha_data[user_id]
    correct_index = data["correct_index"]
    referrer_id = data["referrer_id"]
    username = data["username"]

    if selected_index == correct_index:
        franchise_id = data.get("franchise_id", 0)
        is_subscribed, not_subscribed_channels = await check_subscription(bot, user_id, franchise_id)
        if not is_subscribed:
            captcha_data[user_id]["captcha_passed"] = True
            if len(not_subscribed_channels) == 1:
                await bot.answer_callback_query(call.id, "✅ Капча пройдена! Теперь подпишитесь на канал", show_alert=True)
            else:
                await bot.answer_callback_query(call.id, f"✅ Капча пройдена! Теперь подпишитесь на {len(not_subscribed_channels)} каналов", show_alert=True)
            await show_subscription_required(bot, user_id, not_subscribed_channels, call.message.message_id)
            return

        del captcha_data[user_id]
        await add_user(user_id, username, referrer_id)
        await increment_referrals_count(referrer_id)

        try:
            await bot.send_message(
                referrer_id,
                f'<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> <b>У вас новый реферал!</b>\n\n'
                f"Пользователь <code>{user_id}</code> зарегистрировался по вашей ссылке.\n"
                f"Вы будете получать {REFERRAL_PERCENT}% от каждого его пополнения!",
                parse_mode='HTML'
            )
        except:
            pass

        await bot.answer_callback_query(call.id, "✅ Капча пройдена!", show_alert=False)
        await show_start(call, bot, franchise_id)
    else:
        main_emoji, different_emoji = random.choice(EMOJI_GROUPS)
        new_correct_index = random.randint(0, 2)
        emojis = [main_emoji, main_emoji, main_emoji]
        emojis[new_correct_index] = different_emoji
        captcha_data[user_id]["correct_index"] = new_correct_index

        text = (
            '<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> <b>Неправильно! Попробуйте ещё раз</b>\n\n'
            f"Выберите <b>непохожий</b> эмодзи:\n\n"
            f"<code>{emojis[0]}  {emojis[1]}  {emojis[2]}</code>"
        )

        builder = InlineKeyboardBuilder()
        for i, emoji in enumerate(emojis):
            builder.button(text=emoji, callback_data=f"captcha_{i}")
        builder.adjust(3)

        await bot.edit_message_text(
            chat_id=user_id, message_id=call.message.message_id,
            text=text, parse_mode="HTML", reply_markup=builder.as_markup()
        )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    user_id = call.from_user.id
    _franchise_id = franchise_id
    if user_id in captcha_data:
        _franchise_id = captcha_data[user_id].get("franchise_id", franchise_id)
    is_subscribed, not_subscribed_channels = await check_subscription(bot, user_id, _franchise_id)

    if not is_subscribed:
        if len(not_subscribed_channels) == 1:
            await bot.answer_callback_query(call.id, "❌ Вы не подписаны на канал!", show_alert=True)
        else:
            await bot.answer_callback_query(call.id, f"❌ Вы не подписаны на {len(not_subscribed_channels)} каналов!", show_alert=True)
        return

    if user_id in pending_checks:
        check_id = pending_checks.pop(user_id)
        if not await user_exists(user_id):
            await add_user(user_id, call.from_user.username, None)
        await bot.answer_callback_query(call.id, "✅ Подписка подтверждена!", show_alert=False)
        from app.handlers.checks import activate_check
        await activate_check(call.message, bot, check_id, _franchise_id)
        return

    if user_id in captcha_data:
        data = captcha_data[user_id]

        if data.get("captcha_passed"):
            referrer_id = data["referrer_id"]
            username = data["username"]
            del captcha_data[user_id]

            if not await user_exists(user_id):
                await add_user(user_id, username, referrer_id)
                await increment_referrals_count(referrer_id)
                try:
                    await bot.send_message(
                        referrer_id,
                        f'<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> <b>У вас новый реферал!</b>\n\n'
                        f"Пользователь <code>{user_id}</code> зарегистрировался по вашей ссылке.\n"
                        f"Вы будете получать {REFERRAL_PERCENT}% от каждого его пополнения!",
                        parse_mode='HTML'
                    )
                except:
                    pass

            await bot.answer_callback_query(call.id, "✅ Подписка подтверждена!", show_alert=False)
            await show_start(call, bot, data.get("franchise_id", 0))

        elif data.get("needs_captcha"):
            referrer_id = data["referrer_id"]
            username = data["username"]
            franchise_id_stored = data.get("franchise_id", 0)
            await bot.answer_callback_query(call.id, "✅ Подписка подтверждена! Теперь пройдите капчу", show_alert=False)

            main_emoji, different_emoji = random.choice(EMOJI_GROUPS)
            correct_index = random.randint(0, 2)
            emojis = [main_emoji, main_emoji, main_emoji]
            emojis[correct_index] = different_emoji

            captcha_data[user_id] = {
                "referrer_id": referrer_id,
                "username": username,
                "correct_index": correct_index,
                "franchise_id": franchise_id_stored,
            }

            text = (
                '<tg-emoji emoji-id="6037249452824072506">🔒</tg-emoji> <b>Подтвердите, что вы не робот</b>\n\n'
                f"Выберите <b>непохожий</b> эмодзи:\n\n"
                f"<code>{emojis[0]}  {emojis[1]}  {emojis[2]}</code>"
            )

            builder = InlineKeyboardBuilder()
            for i, emoji in enumerate(emojis):
                builder.button(text=emoji, callback_data=f"captcha_{i}")
            builder.adjust(3)

            await bot.edit_message_text(
                chat_id=user_id, message_id=call.message.message_id,
                text=text, parse_mode="HTML", reply_markup=builder.as_markup()
            )
    else:
        if not await user_exists(user_id):
            await add_user(user_id, call.from_user.username, None)
        await bot.answer_callback_query(call.id, "✅ Подписка подтверждена!", show_alert=False)
        await show_start(call, bot, _franchise_id)


@router.callback_query(F.data.startswith('back_to'))
async def back_to_menu(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    try:
        await state.clear()
    except:
        pass
    type_menu = call.data.split('_')[2]
    if type_menu == 'menu':
        await show_start(call, bot, franchise_id)
    elif type_menu == 'buy':
        from app.handlers.stars import show_buy_stars
        await show_buy_stars(call, call.from_user.username, bot, franchise_id)
    elif type_menu == 'gifts':
        from app.handlers.gifts import show_hidden_gifts
        await show_hidden_gifts(call, bot, state)


@router.callback_query(F.data == "faq_button")
async def faq_button(call: CallbackQuery, bot: Bot):
    from app.config import PRIVACY_URL
    text = (
        '<tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> <b>Информация о проекте</b>\n\n'
        f"Политика конфиденциальности:\n{PRIVACY_URL}\n\n"
        f"Пользовательское соглашение:\n{PRIVACY_URL}"
    )
    from app.helpers import exit_button
    await bot.edit_message_text(
        text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
        parse_mode='HTML', reply_markup=await exit_button(), disable_web_page_preview=True
    )
