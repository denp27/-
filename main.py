import asyncio

from app.bot import main


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("*" * 100)
        print("Bot stopped.")
        print("*" * 100)
