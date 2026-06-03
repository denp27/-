import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _write_env(key: str, value: str) -> None:
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            ENV_FILE.write_text("".join(lines), encoding="utf-8")
            os.environ[key] = value
            return
    with open(ENV_FILE, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")
    os.environ[key] = value


async def main():
    load_dotenv(ENV_FILE)

    api_id = os.getenv("PYROGRAM_API_ID", "").strip()
    api_hash = os.getenv("PYROGRAM_API_HASH", "").strip()
    phone = os.getenv("PYROGRAM_PHONE", "").strip()

    print("=" * 60)
    print("  Pyrogram Session Initializer")
    print("  Запустите этот скрипт один раз для создания сессии.")
    print("=" * 60)

    if not api_id:
        api_id = input("\n[Pyrogram] Введите API ID (получить на my.telegram.org): ").strip()
        _write_env("PYROGRAM_API_ID", api_id)
    else:
        print(f"[Pyrogram] API ID загружен из .env: {api_id}")

    if not api_hash:
        api_hash = input("[Pyrogram] Введите API Hash: ").strip()
        _write_env("PYROGRAM_API_HASH", api_hash)
    else:
        print(f"[Pyrogram] API Hash загружен из .env")

    if not phone:
        phone = input("[Pyrogram] Введите номер телефона (например +79001234567): ").strip()
        _write_env("PYROGRAM_PHONE", phone)
    else:
        print(f"[Pyrogram] Номер телефона загружен из .env: {phone}")

    session_path = BASE_DIR / "pyrogram_session.session"
    if session_path.exists():
        overwrite = input(f"\n[Pyrogram] Файл сессии уже существует: {session_path}\nПересоздать? (y/N): ").strip().lower()
        if overwrite != "y":
            print("[Pyrogram] Отмена. Существующая сессия сохранена.")
            return

    session_name = str(BASE_DIR / "pyrogram_session")
    client = Client(
        name=session_name,
        api_id=int(api_id),
        api_hash=api_hash,
        phone_number=phone,
    )

    print("\n[Pyrogram] Запускаем авторизацию (введите код из Telegram)...")
    await client.start()
    me = await client.get_me()
    print(f"\n[Pyrogram] Авторизован: @{me.username} ({me.first_name})")
    print(f"[Pyrogram] Сессия сохранена: {session_path}")
    print("[Pyrogram] Теперь можно запускать: python main.py")
    await client.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Pyrogram] Отменено пользователем.")
