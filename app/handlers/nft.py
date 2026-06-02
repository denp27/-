import asyncio
from io import BytesIO
import time
from datetime import datetime
from decimal import Decimal

import aiohttp
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, BufferedInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytoniq_core import Cell, StateInit

from app.database import (
    get_balance, deincrement_balance, increment_balance, get_referrer_id,
    db_get_collection_address, get_rented_nft, add_rent_nft, add_transaction
)
from app.helpers import exit_button, ebal_button, effective_markup
from app.states import UserState
from app.config import COMMISSION_NFT, ADMINS_IDS, REFERRAL_PERCENT, INSTRUCTION_URL
from app.utils.martketapi import MarketApi
from app.utils.fragmentapi import get_ton_to_usd_price, price_usd_to_rub
from app.utils.walletapi import WalletApi

router = Router()
marketapp = MarketApi()
wallet = WalletApi()

rent_locks = {}
nav_context: dict[int, dict] = {}  # user_id -> {collection_name, page}


async def ton_to_rub(ton_amount: float) -> float:
    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()
    return float(Decimal(str(ton_amount)) * Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub)))


def extract_rent_details(gift_info: dict) -> tuple:
    sd = gift_info.get('status_details') or {}

    price = None
    for key in ('price_per_day', 'price', 'daily_price', 'min_price', 'pricePerDay'):
        val = sd.get(key) if sd.get(key) is not None else gift_info.get(key)
        if val is not None:
            try:
                price = int(val)
                break
            except (ValueError, TypeError):
                continue

    min_dur_raw = sd.get('min_duration') or sd.get('duration_min') or gift_info.get('min_duration') or 86400
    max_dur_raw = sd.get('max_duration') or sd.get('duration_max') or gift_info.get('max_duration') or 86400 * 30

    return price, int(min_dur_raw), int(max_dur_raw)


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


async def get_photo_gift(name: str) -> BytesIO | None:
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    url = f"https://nft.fragment.com/collection/{name}.webp"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return BytesIO(await response.read())
    return None


async def full_photo_gift(name: str) -> BytesIO | None:
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    url = f"https://nft.fragment.com/gift/{name}.large.jpg"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return BytesIO(await response.read())
    return None


async def get_right_emoji(gift_name: str):
    name = gift_name.replace(" ", "").lower()
    if name.endswith('s'):
        name = name[:-1]

    emojis = {
        'plushpepe': "<tg-emoji emoji-id='5359622339296256165'>🎁</tg-emoji>",
        'heartlocket': "<tg-emoji emoji-id='5363950815927104909'>❤️</tg-emoji>",
        'durov’scap': "<tg-emoji emoji-id='5339564150534200424'>🛡️</tg-emoji>",
        'preciouspeache': "<tg-emoji emoji-id='5357395115285438516'>🍑</tg-emoji>",
        'heroichelmet': "<tg-emoji emoji-id='5366142743896678777'>👑</tg-emoji>",
        'mightyarm': "<tg-emoji emoji-id='5364235490654452043'>💪</tg-emoji>",
        'astralshard': "<tg-emoji emoji-id='5357449287707942316'>🔮</tg-emoji>",
        'nailbracelet': "<tg-emoji emoji-id='5364250321176521188'>📿</tg-emoji>",
        'lootbag': "<tg-emoji emoji-id='5357255816611128661'>🎒</tg-emoji>",
        'scaredcat': "<tg-emoji emoji-id='5283202115047545146'>🐱</tg-emoji>",
        'minioscar': "<tg-emoji emoji-id='5305751006884158046'>🏆</tg-emoji>",
        'iongem': "<tg-emoji emoji-id='5280858699286471614'>💎</tg-emoji>",
        'perfumebottle': "<tg-emoji emoji-id='5339174012884897838'>🌸</tg-emoji>",
        'magicpotion': "<tg-emoji emoji-id='5283069434917836059'>🧪</tg-emoji>",
        'artisanbrick': "<tg-emoji emoji-id='5429579840355330334'>🧱</tg-emoji>",
        'westsidesign': "<tg-emoji emoji-id='5438211869921805121'>🌵</tg-emoji>",
        'gemsignet': "<tg-emoji emoji-id='5357444327020716492'>💍</tg-emoji>",
        'bondedring': "<tg-emoji emoji-id='5363986103378407862'>🍸</tg-emoji>",
        'kissedfrog': "<tg-emoji emoji-id='5280987947737310654'>🐸</tg-emoji>",
        'genielamp': "<tg-emoji emoji-id='5357559088546867143'>🪔</tg-emoji>",
        'swisswatche': "<tg-emoji emoji-id='5357266669993485636'>⌚</tg-emoji>",
        'sharptongue': "<tg-emoji emoji-id='5280511481245361900'>👅</tg-emoji>",
        'lowrider': "<tg-emoji emoji-id='5438564134549486110'>🚗</tg-emoji>",
        'electricskull': "<tg-emoji emoji-id='5280892620938175180'>💀</tg-emoji>",
        'nekohelmet': "<tg-emoji emoji-id='5364288168428334204'>🐱</tg-emoji>",
        'blingbinkie': "<tg-emoji emoji-id='5325975200427178583'>👶</tg-emoji>",
        'toybear': "<tg-emoji emoji-id='5357570547519613136'>🧸</tg-emoji>",
        'vintagecigar': "<tg-emoji emoji-id='5282814202191303521'>🚬</tg-emoji>",
        'signetring': "<tg-emoji emoji-id='5359502505413729010'>💍</tg-emoji>",
        'voodoodoll': "<tg-emoji emoji-id='5282758917372269775'>👹</tg-emoji>",
        'diamongring': "<tg-emoji emoji-id='5357128638334526881'>💍</tg-emoji>",
        'khabib’spapakha': "<tg-emoji emoji-id='5265221419146448610'>🎩</tg-emoji>",
        'eternalrose': "<tg-emoji emoji-id='5305523588365833765'>🌹</tg-emoji>",
        'cupidcharm': "<tg-emoji emoji-id='5364008110790828280'>❤️</tg-emoji>",
        'ionicdryer': "<tg-emoji emoji-id='5363990973871318260'>💨</tg-emoji>",
        'skystilettos': "<tg-emoji emoji-id='5364327252630729088'>👠</tg-emoji>",
        'lovepotion': "<tg-emoji emoji-id='5357317569650911348'>🧪</tg-emoji>",
        'madpumpkin': "<tg-emoji emoji-id='5282810164922045067'>🎃</tg-emoji>",
        'ufcstrike': "<tg-emoji emoji-id='5308052937556136027'>🥊</tg-emoji>",
        'valentineboxe': "<tg-emoji emoji-id='5305764639110353096'>💝</tg-emoji>",
        'recordplayer': "<tg-emoji emoji-id='5282724652123187331'>📀</tg-emoji>",
        'trappedheart': "<tg-emoji emoji-id='5282968352862527007'>❤️</tg-emoji>",
        'lovecandle': "<tg-emoji emoji-id='5337218424080722143'>🎃</tg-emoji>",
        'crystalball': "<tg-emoji emoji-id='5280496526169235279'>🔮</tg-emoji>",
        'tophat': "<tg-emoji emoji-id='5357421327470847015'>🎩</tg-emoji>",
        'skullflower': "<tg-emoji emoji-id='5283147556077982460'>💀</tg-emoji>",
        'flyingbroom': "<tg-emoji emoji-id='5280603307646149925'>🧹</tg-emoji>",
        'snoopcigar': "<tg-emoji emoji-id='5438642075321003231'>🚬</tg-emoji>",
        'sakuraflower': "<tg-emoji emoji-id='5280764381804650651'>🌸</tg-emoji>",
        'sleighbell': "<tg-emoji emoji-id='5406823037741850333'>🔔</tg-emoji>",
        'hangingstar': "<tg-emoji emoji-id='5339260912958201287'>⭐️</tg-emoji>",
        'berryboxe': "<tg-emoji emoji-id='5305764639110353096'>🍓</tg-emoji>",
        'jollychimp': "<tg-emoji emoji-id='5429390050045492605'>🐵</tg-emoji>",
        'joyfulbundle': "<tg-emoji emoji-id='5364026733769027361'>🎁</tg-emoji>",
        'evileye': "<tg-emoji emoji-id='5280606318418227210'>👁️</tg-emoji>",
        'bunnymuffin': "<tg-emoji emoji-id='5359317697265951988'>🧁</tg-emoji>",
        'jellybunnie': "<tg-emoji emoji-id='5337260982911655617'>🐰</tg-emoji>",
        'bowtie': "<tg-emoji emoji-id='5364224873495294898'>🎀</tg-emoji>",
        'eternalcandle': "<tg-emoji emoji-id='5280954545776649464'>🕯️</tg-emoji>",
        'lightsword': "<tg-emoji emoji-id='5364063777861953151'>🗡️</tg-emoji>",
        'springbasket': "<tg-emoji emoji-id='5197633391415029566'>🌸</tg-emoji>",
        'jinglebell': "<tg-emoji emoji-id='5426838912486104197'>🔔</tg-emoji>",
        'spyagaric': "<tg-emoji emoji-id='5283117495601876329'>🍄</tg-emoji>",
        'snowmittens': "<tg-emoji emoji-id='5404591969735308062'>🧤</tg-emoji>",
        'restlessjar': "<tg-emoji emoji-id='5363811508662855070'>🧪</tg-emoji>",
        'snowglobe': "<tg-emoji emoji-id='5407132395646246517'>❄️</tg-emoji>",
        'snoopdogg': "<tg-emoji emoji-id='5436006606078769970'>🐶</tg-emoji>",
        'moonpendant': "<tg-emoji emoji-id='5422709589193815905'>🌙</tg-emoji>",
        'swagbag': "<tg-emoji emoji-id='5436023090163253817'>💼</tg-emoji>",
        'inputkey': "<tg-emoji emoji-id='5364020626325533516'>🔑</tg-emoji>",
        'starnotepad': "<tg-emoji emoji-id='5357053450637045218'>📒</tg-emoji>",
        'easteregg': "<tg-emoji emoji-id='5197436686207841933'>🥚</tg-emoji>",
        'faithamulet': "<tg-emoji emoji-id='5426849198932784730'>🔮</tg-emoji>",
        'hexpot': "<tg-emoji emoji-id='5280588940980542826'>💀</tg-emoji>",
        'prettyposie': "<tg-emoji emoji-id='5363905353698275608'>🌸</tg-emoji>",
        'cookieheart': "<tg-emoji emoji-id='5427132542220264551'>🍪</tg-emoji>",
        'stellarrocket': "<tg-emoji emoji-id='5465184436339372102'>🚀</tg-emoji>",
        'santahat': "<tg-emoji emoji-id='5404715222411799587'>🎅</tg-emoji>",
        'spicedwine': "<tg-emoji emoji-id='5337303756490957158'>🍷</tg-emoji>",
        'moneypot': "<tg-emoji emoji-id='5386516410891526768'>💰</tg-emoji>",
        'cloverpin': "<tg-emoji emoji-id='5384220072266983375'>🍀</tg-emoji>",
        'diamondring': "<tg-emoji emoji-id='5357128638334526881'>🐦</tg-emoji>",
        'skystiletto': "<tg-emoji emoji-id='5364327252630729088'>👠</tg-emoji>",
        'rarebird': "<tg-emoji emoji-id='5422812530969967956'>🐦</tg-emoji>",
        'snowmitten': "<tg-emoji emoji-id='5404591969735308062'>🧤</tg-emoji>",
        'deskcalendar': "<tg-emoji emoji-id='5283255338282275938'>📒</tg-emoji>",
        'lushbouquet': "<tg-emoji emoji-id='5364312357684145343'>🌸</tg-emoji>",
        'witchhat': "<tg-emoji emoji-id='5280793368538932792'>🔮</tg-emoji>",
        'victorymedal': "<tg-emoji emoji-id='5253614420352858658'>🏅</tg-emoji>",
        'jacks-in-the-box': "<tg-emoji emoji-id='5431821190513583006'>🪔</tg-emoji>",
        'moussecake': "<tg-emoji emoji-id='5364186540912174002'>🧁</tg-emoji>",
        'homemadecake': "<tg-emoji emoji-id='5280641391121161373'>🧁</tg-emoji>",
        'bigyear': "<tg-emoji emoji-id='5452081775314495740'>🎉</tg-emoji>",
        'lolpop': "<tg-emoji emoji-id='5280744689379598105'>🍭</tg-emoji>",
        'happybrownie': "<tg-emoji emoji-id='5429557223057551362'>🧁</tg-emoji>",
        'gingercookie': "<tg-emoji emoji-id='5407011006985559397'>🍪</tg-emoji>",
        'whipcupcake': "<tg-emoji emoji-id='5364118624594326109'>🧁</tg-emoji>",
        'hypnolollipop': "<tg-emoji emoji-id='5283145099356689157'>🍭</tg-emoji>",
        'jesterhat': "<tg-emoji emoji-id='5359303618363158143'>🪔</tg-emoji>",
        'freshsock': "<tg-emoji emoji-id='5364209677901000500'>🧦</tg-emoji>",
        'icecream': "<tg-emoji emoji-id='5323507733125692367'>🍦</tg-emoji>",
        'winterwreath': "<tg-emoji emoji-id='5406592505372235508'>❄️</tg-emoji>",
        'partysparkler': "<tg-emoji emoji-id='5426978447383615815'>🎉</tg-emoji>",
        'tamagadget': "<tg-emoji emoji-id='5447346032704772414'>🎮</tg-emoji>",
        'holidaydrink': "<tg-emoji emoji-id='5427334027726055110'>🍷</tg-emoji>",
        'petsnake': "<tg-emoji emoji-id='5447347286835225347'>🐍</tg-emoji>",
        'b-daycandle': "<tg-emoji emoji-id='5282912629956826465'>🕯️</tg-emoji>",
        'instantramen': "<tg-emoji emoji-id='5429194014853199906'>🍜</tg-emoji>",
        'xmasstocking': "<tg-emoji emoji-id='5427369620120037285'>🧦</tg-emoji>",
        'lunarsnake': "<tg-emoji emoji-id='5451885057222403366'>🐍</tg-emoji>",
        'snakeboxe': "<tg-emoji emoji-id='5447410216696047103'>🐍</tg-emoji>",
        'candycane': "<tg-emoji emoji-id='5427211676992692614'>🍬</tg-emoji>",
    }

    return emojis.get(name, "🎁")


@router.callback_query(F.data == "nft_rent")
async def rent_nft(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    from app.helpers import get_section_photo, unified_send
    photo = await get_section_photo(franchise_id, "nft")
    text = '<b><tg-emoji emoji-id="6032644646587338669">🎁</tg-emoji> Аренда NFT</b>\n\nВыберите категорию:'
    builder = InlineKeyboardBuilder()
    builder.button(text="Все подарки", callback_data="all_gifts", icon_custom_emoji_id="6032644646587338669")
    builder.button(text="Арендуемые подарки", callback_data='rentable_gifts', icon_custom_emoji_id="5870994129244131212")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    await unified_send(call, bot, text, builder.adjust(1).as_markup(), photo=photo)


@router.callback_query(F.data == "all_gifts")
async def all_gifts(call: CallbackQuery, bot: Bot):
    await show_gifts_page(call, bot, page=0)


@router.callback_query(F.data.startswith("gifts_page:"))
async def gifts_page_handler(call: CallbackQuery, bot: Bot):
    page = int(call.data.split(":")[1])
    await call.answer()
    await show_gifts_page(call, bot, page)


@router.callback_query(F.data == "current_page")
async def current_page_handler(call: CallbackQuery, bot: Bot):
    await call.answer()


@router.callback_query(F.data.startswith("nft_rent_sort:"))
async def rent_sort_handler(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    parts = call.data.split(":")
    collection_name = parts[1]
    page = int(parts[2])
    sort = parts[3]
    await call.answer()
    await show_rentable_gifts_page(call, bot, collection_name, page, franchise_id=franchise_id, sort=sort)


@router.callback_query(F.data.startswith("nft_"))
async def nft_gift_handler(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    gift_name_encoded = call.data[4:]

    if gift_name_encoded.startswith("rent_page:"):
        page_data = gift_name_encoded.split(":")
        gift_name = page_data[1]
        page = int(page_data[2])
        sort = page_data[3] if len(page_data) > 3 else 'asc'
        await show_rentable_gifts_page(call, bot, gift_name, page, franchise_id=franchise_id, sort=sort)
        await call.answer()
        return

    gift_name = gift_name_encoded[:-1].replace("_", " ")
    await bot.answer_callback_query(call.id, "⌛ Подождите, идет поиск информации о подарке...")

    collection_address = await db_get_collection_address(gift_name + 's')
    if not collection_address:
        return await bot.answer_callback_query(call.id, text="📌 Информация о коллекции скоро появится!", show_alert=True)

    gifts = await marketapp.get_gifts_to_rent(collection_address)
    if not gifts:
        return await bot.answer_callback_query(call.id, text="📌 В данной коллекции нет подарков для аренды!", show_alert=True)

    await show_rentable_gifts_page(call, bot, gift_name, 0, gifts, collection_address, franchise_id=franchise_id)


@router.callback_query(F.data.startswith("gorent"))
async def go_rent_handler(call: CallbackQuery, bot: Bot, state: FSMContext, franchise_id: int = 0):
    user_id = call.from_user.id
    nft_address = call.data.split(":")[1]
    ctx = nav_context.get(user_id, {})
    collection_name = ctx.get("collection_name")
    back_page = ctx.get("page", 0)
    gift_info = await marketapp.get_info_gift(nft_address)
    if not gift_info:
        return await bot.answer_callback_query(call.id, text="❌ Информация о подарке не найдена!", show_alert=True)

    basic_name = gift_info['name']
    await state.update_data({'nft_address': nft_address, 'basic_name': basic_name})
    price_in_nanotons, min_duration, max_duration = extract_rent_details(gift_info)
    if price_in_nanotons is None:
        return await bot.answer_callback_query(call.id, text="❌ Не удалось получить цену аренды для этого подарка.", show_alert=True)

    price_in_tons = price_in_nanotons / 1_000_000_000
    price_in_rub = await ton_to_rub(price_in_tons)
    markup_pct = await effective_markup(COMMISSION_NFT[0], franchise_id)
    price_rub_with_commission = price_in_rub * (1 + markup_pct / 100)

    await state.update_data({'price_per_day_rub': price_rub_with_commission, 'price_in_nanotons': price_in_nanotons})
    await state.update_data({'min_duration': min_duration, 'max_duration': max_duration})

    text = (
        f"<b>🎁 {basic_name}</b>\n\n"
        f"💰 Цена за день: {price_rub_with_commission:.2f}\n"
        f"📅 Доступный период:  {min_duration // 86400} - {max_duration // 86400} дн.\n\n"
        "⬇️ Введите количество дней аренды:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=f"rent_gift:{nft_address}", icon_custom_emoji_id="5960671702059848143")
    await call.message.edit_caption(caption=text, parse_mode='HTML', reply_markup=builder.as_markup())
    await state.set_state(UserState.wait_rent_duration)


@router.callback_query(F.data.startswith("rentable_gifts"))
async def rentable_gifts(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    if len(parts) == 1:
        return await show_rented_gifts(call, bot, send_or_edit=True)
    if parts[1] == "delete":
        await bot.delete_message(call.from_user.id, call.message.message_id)
        return await show_rented_gifts(call, bot, send_or_edit=False)
    if parts[1] == "page":
        page = int(parts[2])
        return await show_rented_gifts(call, bot, send_or_edit=True, page=page)


async def show_rented_gifts(call: CallbackQuery, bot: Bot, send_or_edit: bool = True, page: int = 1):
    user_id = call.from_user.id
    await bot.answer_callback_query(call.id, "⌛ Подождите, идет поиск информации о подарках...")

    gifts = await get_rented_nft(user_id)
    addreses = [gift[0] for gift in gifts]
    rents = (await marketapp.my_rents())['items']

    real_gifts = [
        {"name": rented['nft_name'], "nft_address": rented['nft_address']}
        for nft in addreses
        for rented in rents
        if rented['nft_address'] == nft
    ]

    ITEMS_PER_PAGE = 5
    total = len(real_gifts)
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * ITEMS_PER_PAGE
    page_items = real_gifts[start:start + ITEMS_PER_PAGE]

    text = "<b><tg-emoji emoji-id='6042137469204303531'>🏠</tg-emoji> Ваши арендованные подарки</b>\n\n"
    builder = InlineKeyboardBuilder()

    if not real_gifts:
        text += 'У вас пока нет активных аренд NFT подарков.\nВы можете арендовать NFT в разделе "🎁 Купить подарок"'
        builder.button(text="Купить подарок", callback_data="all_gifts", icon_custom_emoji_id="6032644646587338669")
    else:
        text += f"📦 Активных аренд: <b>{total}</b>\n"
        text += f"📄 Страница: <b>{page}/{total_pages}</b>\n\nВыберите NFT для просмотра информации:\n"

    for gift in page_items:
        builder.button(text="🎁 " + gift['name'], callback_data=f"my_nft:{gift['nft_address']}")

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rentable_gifts:page:{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"rentable_gifts:page:{page+1}"))
        if nav_row:
            builder.row(*nav_row)

    builder.button(text="Назад", callback_data="nft_rent", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(1).as_markup()

    if send_or_edit:
        await call.message.edit_text(text=text, parse_mode='HTML', reply_markup=markup)
    else:
        await bot.send_message(user_id, text=text, parse_mode='HTML', reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("my_nft:"))
async def my_nft(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    try:
        await bot.delete_message(user_id, call.message.message_id)
    except:
        pass

    nft_address = call.data.split(":")[1]
    await bot.answer_callback_query(call.id, "⌛ Подождите, идет поиск информации о подарке...")

    gift_info = await marketapp.get_info_gift(nft_address)
    name = gift_info['name']
    photo_name = gift_info['name'].replace("'", "'").replace(" #", "-").replace(" ", "").replace("'", "").lower()
    attributes = gift_info['attributes']
    model = attributes[0]['value'] if len(attributes) > 0 else "N/A"
    backdrop = attributes[1]['value'] if len(attributes) > 1 else "N/A"
    symbol = attributes[2]['value'] if len(attributes) > 2 else "N/A"

    start_time = int(time.time())
    end_time = int(gift_info['status_details']['end_time'])
    total = diff_unix_with_months(start_time, end_time)

    photo = await full_photo_gift(photo_name)
    photo = BufferedInputFile(photo.getvalue(), filename="gift.jpg")

    text = (
        f"<b>🎁 {name}</b>\n\n"
        "<b>📊 Информация об аренде:</b>\n"
        f"  ├ Осталось: <b>{total}</b>\n"
        f"  └ Истекает: <b>{unixtime_to_str(end_time)}</b>\n\n"
        "<b>🎨 Атрибуты:</b>\n"
        f"  ├ Модель: <b>{model}</b>\n"
        f"  ├ Фон: <b>{backdrop}</b>\n"
        f"  └ Символ: <b>{symbol}</b>\n\n"
    )

    await state.update_data({"nft_address": nft_address})
    builder = InlineKeyboardBuilder()
    builder.button(text="Привязать", callback_data=f"bind", icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Инструкция", url=INSTRUCTION_URL, icon_custom_emoji_id="6028435952299413210")
    builder.button(text="Назад", callback_data="rentable_gifts:delete", icon_custom_emoji_id="5960671702059848143")
    await bot.send_photo(user_id, photo, caption=text, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())
    await bot.answer_callback_query(call.id)


@router.callback_query(F.data == "bind")
async def binder(call: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    try:
        await bot.delete_message(user_id, call.message.message_id)
    except:
        pass

    text = (
        "<b>🔗 Привязка Fragment</b>\n\n"
        "Отправьте ссылку на передачу NFT подарка в Fragment.\n\n"
        "<b>💡 Формат ссылки:</b>\n<code>tc://...</code>\n\n"
        'Или нажмите "Назад" для возврата.'
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Инструкция", url=INSTRUCTION_URL, icon_custom_emoji_id="6028435952299413210")
    builder.button(text="Назад", callback_data="back_to_menu", icon_custom_emoji_id="5960671702059848143")
    await bot.send_message(text=text, chat_id=user_id, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())
    await state.set_state(UserState.wait_bind)


@router.message(UserState.wait_bind)
async def process_bind(message: Message, bot: Bot, state: FSMContext):
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
        await bot.send_message(user_id, "<b>✅ Fragment успешно привязан!</b>\n\nNFT автоматически привязан к вашему Fragment аккаунту.", reply_markup=await exit_button(), parse_mode='HTML')
    except:
        await bot.send_message(user_id, "❌ Произошла ошибка!", reply_markup=await exit_button())
    finally:
        await state.clear()


@router.message(UserState.wait_rent_duration)
async def rent_duration_handler(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    try:
        if user_id not in rent_locks:
            rent_locks[user_id] = asyncio.Lock()

        async with rent_locks[user_id]:
            try:
                duration = int(message.text)
            except ValueError:
                await bot.send_message(user_id, "❌ Количество дней должно быть целым числом!", reply_markup=await exit_button())
                return

            data = await state.get_data()
            nft_address = data.get("nft_address")
            max_duration = data.get("max_duration", 0) // 86400
            min_duration = data.get("min_duration", 0) // 86400
            price_per_day_rub = data.get("price_per_day_rub")
            price_in_nanotons = data.get("price_in_nanotons")
            balance = await get_balance(user_id)

            try:
                for i in range(2):
                    await bot.delete_message(user_id, message.message_id - i)
            except:
                pass

            if duration < 1:
                await bot.send_message(user_id, "❌ Количество дней должно быть не менее 1", reply_markup=await exit_button())
                return
            if duration < min_duration or duration > max_duration:
                await bot.send_message(user_id, f"❌ Количество дней должно быть от {min_duration} до {max_duration}!", reply_markup=await exit_button())
                return
            if balance < duration * price_per_day_rub:
                await bot.send_message(user_id, "❌ Недостаточно средств на балансе для аренды!\nПополните баланс в профиле.", reply_markup=await ebal_button(float(duration * price_per_day_rub)))
                return

            wallet_balance = await wallet.get_balance()
            if wallet_balance < duration * price_in_nanotons:
                try:
                    for admin in ADMINS_IDS:
                        await bot.send_message(admin, f"❌ Недостаточно средств на балансе маркета для аренды!\nИД пользователя: {user_id}\nКоличество дней: {duration}")
                except:
                    pass
                await bot.send_message(user_id, "❌ Ошибка при оплате аренды. Ожидайте, пока баланс нашего маркета обновится!", reply_markup=await exit_button())
                return

            total_cost = duration * price_per_day_rub
            deducted = await deincrement_balance(user_id, total_cost)
            if not deducted:
                await bot.send_message(user_id, "❌ Недостаточно средств на балансе для аренды!\nПополните баланс в профиле.", reply_markup=await ebal_button(float(total_cost)))
                return

            result = await marketapp.rent_nft(nft_address, duration * 86400, str(price_in_nanotons))
            if not result:
                await increment_balance(user_id, total_cost)
                await bot.send_message(user_id, "❌ Ошибка при аренде подарка!", reply_markup=await exit_button())
                return

            address, amount, body, state_init = parse_api_response(result)
            result = await wallet.send_ton_nano(address, amount, body, state_init)
            if not result:
                await increment_balance(user_id, total_cost)
                await bot.send_message(user_id, "❌ Ошибка при оплате аренды!", reply_markup=await exit_button())
                return

            base_price_ton = duration * price_in_nanotons / 1_000_000_000
            base_price_rub = await ton_to_rub(base_price_ton)
            profit = total_cost - base_price_rub
            referrer_id = await get_referrer_id(user_id)
            if referrer_id and REFERRAL_PERCENT > 0:
                try:
                    referral_reward = Decimal(str(profit)) * (Decimal(str(REFERRAL_PERCENT)) / Decimal("100"))
                    if referral_reward > 0:
                        reward_float = float(referral_reward)
                        await increment_balance(referrer_id, reward_float)
                except Exception as e:
                    print(f"Ошибка реферального вознаграждения: {e}")

            start_time = time.time()
            end_time = start_time + duration * 86400
            await add_rent_nft(user_id, nft_address, start_time, duration * 86400, end_time)
            nft_display_name = data.get('basic_name') or nft_address[:12]
            await add_transaction(user_id, 'nft', duration, total_cost, nft_display_name)

            try:
                for admin in ADMINS_IDS:
                    await bot.send_message(admin, f"✅ Пользователь {user_id} арендовал подарок {nft_address} на {duration} дн.")
            except:
                pass
            await bot.send_message(user_id, f"<b>✅ Подарок успешно арендован на {duration} дн.</b>\n\nЗайдите в арендованные подарки, чтобы получить подарок.", reply_markup=await exit_button(), parse_mode='HTML')

    except Exception as e:
        print(f"[rent_duration_handler] Ошибка: {e}")
        try:
            await bot.send_message(user_id, "❌ Произошла ошибка при обработке вашего запроса.", reply_markup=await exit_button())
        except:
            pass
    finally:
        await state.clear()
        if user_id in rent_locks:
            del rent_locks[user_id]


@router.callback_query(F.data.startswith("rent_gift:"))
async def rent_gift_handler(call: CallbackQuery, bot: Bot, franchise_id: int = 0):
    user_id = call.from_user.id
    nft_address = call.data.split(":")[1]
    ctx = nav_context.get(user_id, {})
    collection_name = ctx.get("collection_name")
    back_page = ctx.get("page", 0)
    gift_info = await marketapp.get_info_gift(nft_address)
    if not gift_info:
        return await bot.answer_callback_query(call.id, text="❌ Информация о подарке не найдена!", show_alert=True)

    basic_name = gift_info['name']
    name = gift_info['name'].replace("'", "'").replace(" #", "-").replace(" ", "").replace("'", "")
    attributes = gift_info['attributes']
    model = attributes[0]['value'] if len(attributes) > 0 else "N/A"
    backdrop = attributes[1]['value'] if len(attributes) > 1 else "N/A"
    symbol = attributes[2]['value'] if len(attributes) > 2 else "N/A"

    price_in_nanotons, min_duration, max_duration = extract_rent_details(gift_info)
    if price_in_nanotons is None:
        return await bot.answer_callback_query(call.id, text="❌ Не удалось получить цену аренды для этого подарка.", show_alert=True)

    price_in_tons = price_in_nanotons / 1_000_000_000
    price_in_rub = await ton_to_rub(price_in_tons)
    markup_pct = await effective_markup(COMMISSION_NFT[0], franchise_id)
    price_rub_with_commission = price_in_rub * (1 + markup_pct / 100)

    photo = await full_photo_gift(name)
    builder = InlineKeyboardBuilder()
    gorent_cb = f"gorent:{gift_info['address']}"
    back_cb = f"nft_rent_page:{collection_name}:{back_page}" if collection_name else "all_gifts"
    builder.button(text="Взять в аренду", callback_data=gorent_cb, icon_custom_emoji_id="5870676941614354370")
    builder.button(text="Посмотреть", url=f"https://t.me/nft/{name}", icon_custom_emoji_id="6037397706505195857")
    builder.button(text="Назад", callback_data=back_cb, icon_custom_emoji_id="5960671702059848143")

    if call.message.photo:
        await bot.delete_message(user_id, call.message.message_id)

    if photo:
        text = (
            f"🎁 <b>{basic_name}</b>\n\n\n"
            f"<b>🎨 Атрибуты:</b>\n"
            f"├ Модель: <b>{model}</b>\n"
            f"├ Фон: <b>{backdrop}</b>\n"
            f"└ Символ: <b>{symbol}</b>\n\n\n"
            f"<b>💰 Условия аренды:</b>\n"
            f"  • Цена за день: {price_rub_with_commission:.2f} ₽\n"
            f"  • Период аренды: {min_duration // 86400} - {max_duration // 86400} дн.\n"
            f"  • Полная стоимость: {price_rub_with_commission:.2f} - {price_rub_with_commission * (max_duration // 86400):.2f} ₽"
        )
        file = BufferedInputFile(photo.getvalue(), filename="gift.jpg")
        await bot.send_photo(chat_id=user_id, photo=file, caption=text, parse_mode='HTML', reply_markup=builder.adjust(1).as_markup())


async def show_rentable_gifts_page(call: CallbackQuery, bot: Bot, collection_name: str, page: int, gifts: list = None, collection_address: str = None, franchise_id: int = 0, sort: str = 'asc'):
    user_id = call.from_user.id
    nav_context[user_id] = {"collection_name": collection_name, "page": page}

    if gifts is None:
        if collection_address is None:
            collection_address = await db_get_collection_address(collection_name + 's')
        if not collection_address:
            await bot.answer_callback_query(call.id, "❌ Коллекция не найдена", show_alert=True)
            return
        gifts = await marketapp.get_gifts_to_rent(collection_address)
        if not gifts:
            await bot.answer_callback_query(call.id, "❌ Нет подарков для аренды", show_alert=True)
            return

    gifts = sorted(gifts, key=lambda x: int(x["price_per_day"]), reverse=(sort == 'desc'))

    per_page = 10
    total_pages = (len(gifts) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    page_gifts = gifts[page * per_page:(page + 1) * per_page]

    sort_label = "Цена ↑" if sort == 'asc' else "Цена ↓"
    next_sort = 'desc' if sort == 'asc' else 'asc'

    right_emoji = await get_right_emoji(collection_name) or "📦"
    text = (
        f"<b>{right_emoji} {collection_name}</b>\n\n"
        f"🎁 NFT в коллекции: {len(gifts)}\n"
        f"Страница: <code>{page + 1}</code>/<code>{total_pages}</code>"
    )

    builder = InlineKeyboardBuilder()
    ton_price_usd = await get_ton_to_usd_price()
    usd_price_rub = await price_usd_to_rub()
    ton_to_rub_rate = float(Decimal(str(ton_price_usd)) * Decimal(str(usd_price_rub)))
    markup_pct = await effective_markup(COMMISSION_NFT[0], franchise_id)

    for gift in page_gifts:
        try:
            name = gift['name']
            price_ton = float(gift['price_per_day']) / 1_000_000_000
            price_rub = price_ton * ton_to_rub_rate
            price_rub_with_commission = price_rub * (1 + markup_pct / 100)
            min_days = gift['min_duration'] // 86400
            max_days = gift['max_duration'] // 86400
            button_text = f"{price_rub_with_commission:.0f}₽/д | {min_days}д - {max_days}д"
            builder.button(text=button_text, callback_data=f"rent_gift:{gift['nft_address']}")
            gift_slug, number = name.split("#")
            gift_slug = gift_slug.strip().replace(" ", "").lower()
            url = f"https://t.me/nft/{gift_slug}-{number.strip()}"
            builder.button(text=" ", icon_custom_emoji_id="6030466823290360017", url=url)
        except Exception:
            continue

    builder.button(text=sort_label, callback_data=f"nft_rent_sort:{collection_name}:{page}:{next_sort}")

    nav_row = []
    if page > 0:
        nav_row.append(("◀️", f"nft_rent_page:{collection_name}:{page - 1}:{sort}"))
    nav_row.append((f"{page + 1}/{total_pages}", "current_page"))
    if page < total_pages - 1:
        nav_row.append(("▶️", f"nft_rent_page:{collection_name}:{page + 1}:{sort}"))

    for text_btn, callback in nav_row:
        builder.button(text=text_btn, callback_data=callback)
    builder.button(text="Назад к списку", callback_data="all_gifts", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(*([2] * len(page_gifts)), 1, len(nav_row), 1).as_markup()

    gift_name_for_url = collection_name.replace(" ", "").replace("'", "")
    if gift_name_for_url == "SwissWatche":
        gift_name_for_url = "SwissWatch"
    elif gift_name_for_url == "PreciousPeache":
        gift_name_for_url = "PreciousPeach"
    elif gift_name_for_url == "BlingBinkie":
        gift_name_for_url = "blingbinky"

    photo_gift = await get_photo_gift(gift_name_for_url)

    try:
        if photo_gift:
            photo_file = BufferedInputFile(photo_gift.getvalue(), filename="gift.webp")
            if call.message.photo:
                await bot.edit_message_media(
                    chat_id=user_id, message_id=call.message.message_id,
                    media=InputMediaPhoto(media=photo_file, caption=text, parse_mode="HTML"),
                    reply_markup=markup
                )
            else:
                await bot.delete_message(user_id, call.message.message_id)
                await bot.send_photo(chat_id=user_id, photo=photo_file, caption=text, parse_mode='HTML', reply_markup=markup)
        else:
            if call.message.photo:
                await bot.delete_message(user_id, call.message.message_id)
                await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)
            else:
                await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=markup)
    except Exception as e:
        print(f"[show_rentable_gifts_page] Error: {e}")
        try:
            await bot.delete_message(user_id, call.message.message_id)
            await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)
        except:
            await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)


async def show_gifts_page(call: CallbackQuery, bot: Bot, page: int):
    user_id = call.from_user.id
    all_gifts = await marketapp.get_collections_gifts(True)
    if not all_gifts:
        await call.answer("❌ Не удалось загрузить коллекции. Попробуйте позже.", show_alert=True)
        return
    all_gifts = [g for g in all_gifts if g["floor"] is not None]
    all_gifts = sorted(all_gifts, key=lambda x: int(x["floor"]), reverse=True)

    per_page = 10
    total_pages = max(1, (len(all_gifts) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_gifts = all_gifts[page * per_page:(page + 1) * per_page]

    text = (
        f"<b>📦 Все коллекции</b>\n\n"
        f"Найдено коллекций: <code>{len(all_gifts)}</code>\n"
        f"Страница: <code>{page + 1}</code>/<code>{total_pages}</code>"
    )

    builder = InlineKeyboardBuilder()
    for gift in page_gifts:
        gift_name = gift['name']
        name_for_emoji = gift_name.replace(" ", "").lower()

        try:
            emoji = await get_right_emoji(name_for_emoji)
            emoji = emoji.split("'")[1]
        except Exception as e:
            print(f"[debug] error getting emoji for {gift_name} | {name_for_emoji}: {e}")
            emoji = "5773677501825945508"
        callback_data = "nft_" + gift_name.replace(" ", "_")
        builder.button(text=f"{gift_name}", callback_data=callback_data, icon_custom_emoji_id=emoji)

    nav_row = []
    if page > 0:
        nav_row.append(("◀️", f"gifts_page:{page - 1}"))
    nav_row.append((f"{page + 1}/{total_pages}", "current_page"))
    if page < total_pages - 1:
        nav_row.append(("▶️", f"gifts_page:{page + 1}"))

    for text_btn, callback in nav_row:
        builder.button(text=text_btn, callback_data=callback)
    builder.button(text="Назад в меню", callback_data="nft_rent", icon_custom_emoji_id="5960671702059848143")
    markup = builder.adjust(*([1] * len(page_gifts)), len(nav_row), 1).as_markup()

    try:
        if call.message.photo:
            await bot.delete_message(user_id, call.message.message_id)
            await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)
        else:
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=call.message.message_id, parse_mode='HTML', reply_markup=markup)
    except Exception as e:
        try:
            await bot.delete_message(user_id, call.message.message_id)
            await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)
        except:
            await bot.send_message(chat_id=user_id, text=text, parse_mode='HTML', reply_markup=markup)
