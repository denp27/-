from datetime import datetime

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import (
    get_user_transactions,
    get_user_transactions_count,
    get_user_transactions_stats,
)

router = Router()

ITEMS_PER_PAGE = 5


_TYPES: dict[str, dict] = {
    'all':     {'label': 'Все',     'icon': '<tg-emoji emoji-id="5203910550542631009">📋</tg-emoji>', 'emoji_id': '5203910550542631009'},
    'stars':   {'label': 'Звёзды',  'icon': '<tg-emoji emoji-id="6028338546736107668">⭐️</tg-emoji>', 'emoji_id': '6028338546736107668'},
    'premium': {'label': 'Premium', 'icon': '<tg-emoji emoji-id="5773677501825945508">🔹</tg-emoji>', 'emoji_id': '5773677501825945508'},
    'ton':     {'label': 'TON',     'icon': '<tg-emoji emoji-id="5776023601941582822">💎</tg-emoji>', 'emoji_id': '5776023601941582822'},
    'nft':     {'label': 'NFT',     'icon': '<tg-emoji emoji-id="6044004057696177711">🎁</tg-emoji>', 'emoji_id': '6044004057696177711'},
    'numbers': {'label': 'Номера',  'icon': '<tg-emoji emoji-id="5346132555689119666">📞</tg-emoji>', 'emoji_id': '5346132555689119666'},
}

_MONTHS = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек']


def _fmt_date(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}, {dt.strftime('%H:%M')}"


def _fmt_amount(type_: str, amount: float, recipient: str | None) -> str:
    amt = int(amount) if amount == int(amount) else f"{amount:.2f}"
    if type_ == 'stars':
        desc = f"{amt} ⭐️"
    elif type_ == 'premium':
        desc = f"{amt} мес."
    elif type_ == 'ton':
        desc = f"{amt} TON"
    elif type_ == 'nft':
        n = int(amount)
        day_word = 'день' if n == 1 else ('дня' if 2 <= n <= 4 else 'дней')
        desc = f"{n} {day_word}"
    elif type_ == 'numbers':
        n = int(amount)
        day_word = 'день' if n == 1 else ('дня' if 2 <= n <= 4 else 'дней')
        desc = f"{n} {day_word}"
    else:
        desc = str(amt)

    if recipient:
        if type_ in ('stars', 'premium', 'ton'):
            recip = recipient if recipient.startswith('@') else f"@{recipient}"
            return f"{desc} → {recip}"
        else:
            return f"{recipient}  ·  {desc}"
    return desc


def _fmt_type_name(type_: str) -> str:
    names = {
        'stars':   'Покупка звёзд',
        'premium': 'Telegram Premium',
        'ton':     'Покупка TON',
        'nft':     'Аренда NFT',
        'numbers': 'Аренда номера',
    }
    return names.get(type_, type_)


def _build_message(
    transactions: list,
    type_filter: str,
    page: int,
    total: int,
    count: int,
    spent: float,
) -> str:
    meta = _TYPES.get(type_filter, _TYPES['all'])
    icon = meta['icon']
    label = meta['label']

    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    tg_icon = '<tg-emoji emoji-id="5203910550542631009">📋</tg-emoji>'
    if type_filter == 'all':
        header = f'<b>{tg_icon} История покупок</b>'
    else:
        header = f'<b>{tg_icon} История покупок  ·  {icon} {label}</b>'

    if count == 0:
        stats_line = '<i>Покупок пока нет</i>'
    else:
        stats_line = f'<b>{count}</b> покупок  ·  потрачено <b>{spent:,.2f} ₽</b>'

    lines = [
        header,
        '',
        f'<blockquote>{stats_line}</blockquote>',
        '',
    ]

    if not transactions:
        lines.append(
            '<tg-emoji emoji-id="5203910550542631009">📋</tg-emoji>'
            ' <i>История пуста — совершите первую покупку!</i>'
        )
    else:
        lines.append('─────────────────────')
        for i, tx in enumerate(transactions, start=page * ITEMS_PER_PAGE + 1):
            _, tx_type, amount, cost_rub, recipient, created_at = tx
            type_icon = _TYPES.get(tx_type, {}).get('icon', '📦')
            type_name = _fmt_type_name(tx_type)
            amount_str = _fmt_amount(tx_type, amount, recipient)
            date_str = _fmt_date(created_at)

            lines.append(
                f'<b>{i}.</b> {type_icon} <b>{type_name}</b>\n'
                f'   {amount_str}\n'
                f'   <code>💰 {cost_rub:,.2f} ₽  ·  {date_str}</code>'
            )

        lines.append('─────────────────────')
        lines.append(f'<i>Страница {page + 1} из {total_pages}</i>')

    return '\n'.join(lines)


def _build_keyboard(type_filter: str, page: int, total: int) -> any:
    _ORDER = ['all', 'stars', 'premium', 'ton', 'nft', 'numbers']

    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    builder = InlineKeyboardBuilder()

    for key in _ORDER:
        meta = _TYPES[key]
        active = (key == type_filter)
        btn_text = f"• {meta['label']}" if active else meta['label']
        builder.button(
            text=btn_text,
            callback_data=f"hist:{key}:0",
            icon_custom_emoji_id=meta['emoji_id'],
        )

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️", callback_data=f"hist:{type_filter}:{page - 1}")
        nav_buttons += 1
    if total_pages > 1:
        builder.button(text=f"{page + 1} / {total_pages}", callback_data="hist_noop")
        nav_buttons += 1
    if page + 1 < total_pages:
        builder.button(text="▶️", callback_data=f"hist:{type_filter}:{page + 1}")
        nav_buttons += 1

    builder.button(text="Назад", callback_data="profile", icon_custom_emoji_id="5960671702059848143")

    rows = [1, 3, 2]
    if nav_buttons > 0:
        rows.append(nav_buttons)
    rows.append(1)
    builder.adjust(*rows)
    return builder.as_markup()


async def show_history(call: CallbackQuery, bot: Bot, type_filter: str = 'all', page: int = 0):
    user_id = call.from_user.id
    total = await get_user_transactions_count(user_id, type_filter)
    count, spent = await get_user_transactions_stats(user_id, type_filter)
    transactions = await get_user_transactions(user_id, type_filter, ITEMS_PER_PAGE, page * ITEMS_PER_PAGE)

    text = _build_message(transactions, type_filter, page, total, count, spent)
    markup = _build_keyboard(type_filter, page, total)

    try:
        await bot.edit_message_text(
            text=text,
            chat_id=user_id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=markup,
        )
    except Exception:
        pass


@router.callback_query(F.data == "purchase_history")
async def history_entry(call: CallbackQuery, bot: Bot):
    await show_history(call, bot, 'all', 0)


@router.callback_query(F.data.startswith("hist:"))
async def history_paginated(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    type_filter = parts[1]
    page = int(parts[2])
    await show_history(call, bot, type_filter, page)


@router.callback_query(F.data == "hist_noop")
async def history_noop(call: CallbackQuery):
    await call.answer()
