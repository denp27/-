from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import get_user, get_balance, get_referrals_count, user_exists, add_user
from app.helpers import exit_button
from app.states import UserState
from app.config import REFERRAL_PERCENT

router = Router()


async def show_profile(user_id: int, bot: Bot, call):
    user = await get_user(user_id)
    uid = user[1]
    balance = user[3]
    stars_buyed = user[4]
    referrals_count = await get_referrals_count(user_id)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{user_id}"

    import app.config as config
    text = (
        f'<b><tg-emoji emoji-id="5870994129244131212">👤</tg-emoji> Профиль</b>\n'
        f'<b>├ Баланс:</b> <code>{balance:.2f} ₽</code>\n'
        f'<b>├ Куплено звёзд:</b> <code>{stars_buyed}</code> ⭐️\n'
        f'<b>└ ID:</b> <code>{uid}</code>\n\n'
        f'<b><tg-emoji emoji-id="5870772616305839506">👥</tg-emoji> Реферальная программа</b>\n'
        f'<b>├ Рефералов:</b> <code>{referrals_count}</code>\n'
        f'<b>├ Процент:</b> <code>{config.REFERRAL_PERCENT}%</code> от прибыли\n'
        f'<b>└ Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n'
        f'<blockquote><tg-emoji emoji-id="6028435952299413210">ℹ</tg-emoji> Приглашайте друзей и получайте {config.REFERRAL_PERCENT}% от прибыли с их покупок!</blockquote>'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Создать чек", callback_data="create_check", icon_custom_emoji_id="6032644646587338669")
    builder.button(text="Промокод", callback_data="promo_code", icon_custom_emoji_id="5886285355279193209")
    builder.button(text="История покупок", callback_data="purchase_history", icon_custom_emoji_id="5203910550542631009")
    builder.button(text="Пополнить баланс", callback_data="deposit", icon_custom_emoji_id="5879814368572478751")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(2, 1, 1, 1).as_markup()

    await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=markup)


@router.callback_query(F.data == "profile")
async def profile(call: CallbackQuery, bot: Bot, state: FSMContext):
    try:
        await state.clear()
    except:
        pass
    user_id = call.from_user.id
    if not await user_exists(user_id):
        await add_user(user_id, call.from_user.username, None)
    await show_profile(user_id, bot, call=call)


@router.callback_query(F.data == "promo_code")
async def promo_code_handler(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="profile", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()
    await state.set_state(UserState.wait_promo_code)
    await bot.edit_message_text(
        text='<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Введите промокод для активации:</b>',
        chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=markup
    )


@router.message(UserState.wait_promo_code)
async def promo_code_message(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    promo_code = message.text.strip()
    try:
        await bot.delete_message(user_id, message.message_id)
        await bot.delete_message(user_id, message.message_id - 1)
    except:
        pass

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="profile", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()

    from app.database import use_promo
    result, reward = await use_promo(promo_code, user_id)
    if not result:
        await bot.send_message(user_id, f'<tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> {reward}', reply_markup=markup, parse_mode='HTML')
    else:
        await bot.send_message(
            user_id,
            f'<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji> <b>Промокод успешно активирован!</b>\n\nВы получили <code>{reward}</code> ₽',
            reply_markup=markup, parse_mode='HTML'
        )
    await state.clear()


@router.callback_query(F.data == "top_referrers")
async def top_referrers_handler(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    from app.database import get_top_referrers, get_user_referral_rank
    top_users = await get_top_referrers(3)
    medals = ["<tg-emoji emoji-id='5794164805065514131'>🥇</tg-emoji>", "<tg-emoji emoji-id='5794085322400733645'>🥈</tg-emoji>", "<tg-emoji emoji-id='5794280000383358988'>🥉</tg-emoji>"]

    text = '<b><tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> Топ по рефералам</b>\n\n'

    if top_users:
        for i, (uid, username, refs_count) in enumerate(top_users):
            medal = medals[i]
            display_name = f"@{username}" if username and username != "Неизвестно" else f"ID: {str(uid)[:4]}***"
            text += f"{medal} <b>{i+1} место</b> — {display_name}\n"
            text += f"    └ Рефералов: <code>{refs_count}</code>\n\n"
    else:
        text += "<i>Пока нет рефералов</i>\n\n"

    user_rank, user_refs = await get_user_referral_rank(user_id)
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if user_rank:
        if user_rank <= 3:
            text += f'<tg-emoji emoji-id="6041731551845159060">🎉</tg-emoji> <b>Поздравляем! Вы на {user_rank} месте!</b>\n'
            text += f"<tg-emoji emoji-id='6032609071373226027'>👥</tg-emoji> Ваших рефералов: <code>{user_refs}</code>"
        else:
            text += f'<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> <b>Ваша позиция:</b> {user_rank} место\n'
            text += f"<tg-emoji emoji-id='6032609071373226027'>👥</tg-emoji> Ваших рефералов: <code>{user_refs}</code>\n\n"
            if top_users:
                need_for_top3 = top_users[-1][2] - user_refs + 1
                text += f"<i>До топ-3 осталось пригласить: {need_for_top3} чел.</i>"
    else:
        text += '<tg-emoji emoji-id="5870921681735781843">📊</tg-emoji> <b>Вы ещё не пригласили рефералов</b>\n\n'
        text += "<i>Приглашайте друзей по реферальной ссылке и попадите в топ!</i>"

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")

    await bot.edit_message_text(
        text=text, chat_id=user_id, message_id=call.message.message_id,
        parse_mode="HTML", reply_markup=builder.as_markup()
    )
