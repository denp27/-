import os

from pyrogram import Client

from app.config import BASE_DIR

_client: Client | None = None


async def setup_pyrogram() -> Client:
    global _client

    api_id = os.getenv("PYROGRAM_API_ID", "").strip()
    api_hash = os.getenv("PYROGRAM_API_HASH", "").strip()
    phone = os.getenv("PYROGRAM_PHONE", "").strip()

    if not api_id:
        api_id = input("\n[Pyrogram] Введите API ID (получить на my.telegram.org): ").strip()
        _write_env("PYROGRAM_API_ID", api_id)
    if not api_hash:
        api_hash = input("[Pyrogram] Введите API Hash: ").strip()
        _write_env("PYROGRAM_API_HASH", api_hash)
    if not phone:
        phone = input("[Pyrogram] Введите номер телефона (например +79001234567): ").strip()
        _write_env("PYROGRAM_PHONE", phone)

    session_name = str(BASE_DIR / "pyrogram_session")
    _client = Client(
        name=session_name,
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


def _write_env(key: str, value: str) -> None:
    env_file = BASE_DIR / ".env"
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            env_file.write_text("".join(lines), encoding="utf-8")
            os.environ[key] = value
            return
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")
    os.environ[key] = value
