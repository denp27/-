import os

from pyrogram import Client

from app.config import BASE_DIR

_client: Client | None = None


async def setup_pyrogram() -> Client | None:
    global _client

    api_id = os.getenv("PYROGRAM_API_ID", "").strip()
    api_hash = os.getenv("PYROGRAM_API_HASH", "").strip()
    phone = os.getenv("PYROGRAM_PHONE", "").strip()

    session_file = BASE_DIR / "pyrogram_session.session"

    if not all([api_id, api_hash, phone]):
        print(
            "[Pyrogram] Отсутствуют учётные данные в .env "
            "(PYROGRAM_API_ID, PYROGRAM_API_HASH, PYROGRAM_PHONE).\n"
            "[Pyrogram] Запустите session_init.py для первоначальной настройки."
        )
        return None

    if not session_file.exists():
        print(
            f"[Pyrogram] Файл сессии не найден: {session_file}\n"
            "[Pyrogram] Запустите session_init.py для создания сессии."
        )
        return None

    _client = Client(
        name=str(BASE_DIR / "pyrogram_session"),
        api_id=int(api_id),
        api_hash=api_hash,
        phone_number=phone,
    )
    await _client.start()
    me = await _client.get_me()
    print(f"[Pyrogram] Авторизован: @{me.username} ({me.first_name})")
    return _client


def get_pyrogram_client() -> Client | None:
    return _client
