# database.py
import aiosqlite
from app.config import BASE_DIR

DATABASE_NAME = str(BASE_DIR / "database.db")


async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")

        # ========== ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="users"'
        )
        row = await cursor.fetchone()

        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER UNIQUE,
                    username TEXT DEFAULT 'Неизвестно',
                    balance REAL DEFAULT 0,
                    stars_buyed INTEGER DEFAULT 0,
                    referral_id INTEGER DEFAULT NULL,
                    referrals_count INTEGER DEFAULT 0,
                    registration_time REAL DEFAULT (strftime('%s','now')),
                    is_banned INTEGER DEFAULT 0,
                    ban_reason TEXT DEFAULT NULL
                )
            ''')
            print('Таблица "users" создана')
        else:
            print('Выполнено подключение к таблице "users".')
            cursor2 = await conn.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in await cursor2.fetchall()]
            if 'referrals_count' not in columns:
                await conn.execute('ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0')
                print('Добавлена колонка referrals_count')
            if 'is_banned' not in columns:
                await conn.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
                print('Добавлена колонка is_banned')
            if 'ban_reason' not in columns:
                await conn.execute('ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT NULL')
                print('Добавлена колонка ban_reason')

        # ========== ТАБЛИЦА ЗАДАНИЙ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="tasks"'
        )
        row = await cursor.fetchone()

        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    reward REAL NOT NULL,
                    task_type TEXT DEFAULT 'stars',
                    is_active INTEGER DEFAULT 1,
                    require_photo INTEGER DEFAULT 0,
                    instruction_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    franchise_id INTEGER DEFAULT NULL
                )
            ''')
            print('Таблица "tasks" создана')
        else:
            print('Выполнено подключение к таблице "tasks".')
            cursor2 = await conn.execute("PRAGMA table_info(tasks)")
            columns = [column[1] for column in await cursor2.fetchall()]
            if 'require_photo' not in columns:
                await conn.execute('ALTER TABLE tasks ADD COLUMN require_photo INTEGER DEFAULT 0')
                print('Добавлена колонка require_photo')
            if 'instruction_text' not in columns:
                await conn.execute('ALTER TABLE tasks ADD COLUMN instruction_text TEXT')
                print('Добавлена колонка instruction_text')

        # ========== ТАБЛИЦА ВЫПОЛНЕННЫХ ЗАДАНИЙ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS completed_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_id INTEGER,
                photo_file_id TEXT,
                proof_text TEXT,
                status TEXT DEFAULT 'pending',
                completed_at TIMESTAMP,
                reviewed_by INTEGER DEFAULT NULL,
                reviewed_at TIMESTAMP,
                reward_given INTEGER DEFAULT 0,
                rejection_reason TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        ''')
        print('Таблица "completed_tasks" проверена')

        # ========== ТАБЛИЦА КОЛЛЕКЦИЙ NFT ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="collections_address"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS collections_address (
                    id INTEGER PRIMARY KEY,
                    collection_name TEXT UNIQUE,
                    collection_address TEXT,
                    added_time REAL DEFAULT (strftime('%s','now'))
                )
            ''')
            print('Таблица "collections_address" создана')
        else:
            print('Выполнено подключение к таблице "collections_address".')

        # ========== ТАБЛИЦА АРЕНДЫ NFT ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="rented"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rented (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    nft_address TEXT,
                    rent_start_time REAL,
                    rent_duration INTEGER,
                    rent_end_time REAL,
                    UNIQUE(user_id, nft_address)
                )
            ''')
            print('Таблица "rented" создана')
        else:
            print('Выполнено подключение к таблице "rented".')

        # ========== ТАБЛИЦА АРЕНДЫ НОМЕРОВ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="rented_num"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rented_num (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    nft_address TEXT,
                    rent_start_time REAL,
                    rent_duration INTEGER,
                    rent_end_time REAL,
                    nft_name TEXT,
                    UNIQUE(user_id, nft_address)
                )
            ''')
            print('Таблица "rented_num" создана')
        else:
            print('Выполнено подключение к таблице "rented_num".')

        # ========== ТАБЛИЦА ОБЯЗАТЕЛЬНЫХ КАНАЛОВ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="required_channels"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS required_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_url TEXT NOT NULL,
                    channel_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    added_time REAL DEFAULT (strftime('%s','now'))
                )
            ''')
            print('Таблица "required_channels" создана')
        else:
            print('Выполнено подключение к таблице "required_channels".')

        # ========== ТАБЛИЦА ПРОМОКОДОВ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="promocodes"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promocodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    reward REAL NOT NULL,
                    max_uses INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            print('Таблица "promocodes" создана')
        else:
            print('Выполнено подключение к таблице "promocodes".')

        # ========== ТАБЛИЦА ИСПОЛЬЗОВАННЫХ ПРОМОКОДОВ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS uses_promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL
            )
        ''')
        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_uses_promocodes_code_user ON uses_promocodes(code, user_id)'
        )

        # ========== ТАБЛИЦА ФРАНШИЗ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="franchises"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS franchises (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER UNIQUE NOT NULL,
                    bot_token TEXT UNIQUE NOT NULL,
                    project_name TEXT DEFAULT 'MstiStars',
                    markup REAL DEFAULT 0,
                    total_earned REAL DEFAULT 0,
                    support_url TEXT DEFAULT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_time REAL DEFAULT (strftime('%s','now'))
                )
            ''')
            print('Таблица "franchises" создана')
        else:
            print('Выполнено подключение к таблице "franchises".')
            cursor2 = await conn.execute("PRAGMA table_info(franchises)")
            cols = [c[1] for c in await cursor2.fetchall()]
            if 'total_earned' not in cols:
                await conn.execute('ALTER TABLE franchises ADD COLUMN total_earned REAL DEFAULT 0')
                print('Добавлена колонка total_earned в franchises')
            if 'support_url' not in cols:
                await conn.execute('ALTER TABLE franchises ADD COLUMN support_url TEXT DEFAULT NULL')
                print('Добавлена колонка support_url в franchises')

        # ========== ТАБЛИЦА ФОТО ФРАНШИЗ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS franchise_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                franchise_id INTEGER NOT NULL,
                section TEXT NOT NULL,
                file_id TEXT NOT NULL,
                UNIQUE(franchise_id, section),
                FOREIGN KEY(franchise_id) REFERENCES franchises(id)
            )
        ''')

        # ========== ТАБЛИЦА КАНАЛОВ ФРАНШИЗ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS franchise_required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                franchise_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                channel_url TEXT NOT NULL,
                channel_name TEXT,
                is_active INTEGER DEFAULT 1,
                UNIQUE(franchise_id, channel_id),
                FOREIGN KEY(franchise_id) REFERENCES franchises(id)
            )
        ''')

        # ========== ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ ФРАНШИЗ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS franchise_users (
                franchise_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (franchise_id, user_id),
                FOREIGN KEY(franchise_id) REFERENCES franchises(id)
            )
        ''')

        # ========== ТАБЛИЦА ТРАНЗАКЦИЙ ОТПРАВКИ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tx_sent (
                req_id TEXT PRIMARY KEY,
                tx_hash TEXT,
                kind TEXT,
                sent_at REAL DEFAULT (strftime('%s','now'))
            )
        ''')

        # ========== ТАБЛИЦА ТРАНЗАКЦИЙ ПОКУПОК ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                cost_rub REAL NOT NULL,
                recipient TEXT DEFAULT NULL,
                created_at REAL DEFAULT (strftime('%s','now'))
            )
        ''')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, type)'
        )

        # ========== ТАБЛИЦА ПОДАРКОВ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                emoji_id TEXT NOT NULL,
                count_stars INTEGER NOT NULL,
                gift_id TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                added_time REAL DEFAULT (strftime('%s','now'))
            )
        ''')

        # ========== ТАБЛИЦА ЧЕКОВ ==========
        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="checks"'
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_id TEXT UNIQUE NOT NULL,
                    creator_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    cost_rub REAL NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    used_by INTEGER DEFAULT NULL,
                    created_at REAL DEFAULT (strftime('%s','now'))
                )
            ''')
            print('Таблица "checks" создана')
        else:
            print('Выполнено подключение к таблице "checks".')

        # ========== ТАБЛИЦА ЗАЯВОК НА ВЫВОД ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                franchise_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                comment TEXT DEFAULT NULL,
                created_at REAL DEFAULT (strftime('%s','now')),
                resolved_at REAL DEFAULT NULL
            )
        ''')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_wr_franchise ON withdraw_requests(franchise_id, status)'
        )
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_wr_status ON withdraw_requests(status, created_at)'
        )

        # ========== ТАБЛИЦА ИНВОЙСОВ ДЕПОЗИТОВ ==========
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS deposit_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                provider TEXT NOT NULL,
                created_at REAL DEFAULT (strftime('%s','now')),
                credited_at REAL DEFAULT NULL
            )
        ''')

        # ========== ИНДЕКСЫ ДЛЯ ОПТИМИЗАЦИИ ==========
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(is_active)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_completed_tasks_user ON completed_tasks(user_id, status)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_completed_tasks_task ON completed_tasks(task_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_submissions_status ON completed_tasks(status)')

        await conn.commit()
        print("База данных успешно инициализирована!")


# ========== ФУНКЦИИ ДЛЯ TX SENT ==========

async def is_tx_sent(req_id: str) -> bool:
    if not req_id:
        return False
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT 1 FROM tx_sent WHERE req_id = ?', (str(req_id),)) as cursor:
            return await cursor.fetchone() is not None


async def mark_tx_sent(req_id: str, tx_hash: str | None, kind: str) -> bool:
    if not req_id:
        return True
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO tx_sent (req_id, tx_hash, kind) VALUES (?, ?, ?)',
                (str(req_id), tx_hash, kind),
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def update_tx_hash(req_id: str, tx_hash: str) -> None:
    if not req_id:
        return
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE tx_sent SET tx_hash = ? WHERE req_id = ?',
            (tx_hash, str(req_id)),
        )
        await conn.commit()


# ========== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========

async def add_user(user_id: int, username: str, referral_id: int = None):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO users (user_id, username, referral_id) VALUES (?, ?, ?)',
                (user_id, username, referral_id)
            )
            await conn.commit()
        except Exception:
            print(f"Пользователь {user_id} уже существует.")


async def get_user(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT * FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()


async def get_balance(user_id: int) -> float:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT balance FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0


async def increment_balance(user_id: int, amount: float) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (amount, user_id)
        )
        await conn.commit()


async def deincrement_balance(user_id: int, amount: float) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?',
            (amount, user_id, amount)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def user_exists(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,)) as cursor:
            return await cursor.fetchone() is not None


async def ban_user(user_id: int, reason: str = None) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?',
            (reason, user_id)
        )
        await conn.commit()


async def unban_user(user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = ?',
            (user_id,)
        )
        await conn.commit()


async def is_user_banned(user_id: int) -> tuple[bool, str | None]:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT is_banned, ban_reason FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False, None
            return bool(row[0]), row[1]


async def get_count_users():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM users') as cursor:
            return (await cursor.fetchone())[0]


# ========== ФУНКЦИИ ДЛЯ ЗАДАНИЙ ==========

async def add_task(title: str, description: str, reward: float, task_type: str = "stars", 
                   require_photo: bool = False, instruction_text: str = None, franchise_id: int = None) -> int:
    """Добавить новое задание"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'INSERT INTO tasks (title, description, reward, task_type, require_photo, instruction_text, franchise_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (title, description, reward, task_type, 1 if require_photo else 0, instruction_text, franchise_id)
        )
        await conn.commit()
        return cursor.lastrowid


async def get_active_tasks(franchise_id: int = None):
    """Получить активные задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        if franchise_id:
            async with conn.execute(
                'SELECT id, title, description, reward, task_type, require_photo, instruction_text, created_at FROM tasks WHERE is_active = 1 AND (franchise_id IS NULL OR franchise_id = ?) ORDER BY created_at DESC',
                (franchise_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [{'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 
                        'type': row[4], 'require_photo': bool(row[5]), 'instruction_text': row[6], 
                        'created_at': row[7]} for row in rows]
        else:
            async with conn.execute(
                'SELECT id, title, description, reward, task_type, require_photo, instruction_text, created_at FROM tasks WHERE is_active = 1 ORDER BY created_at DESC'
            ) as cursor:
                rows = await cursor.fetchall()
                return [{'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 
                        'type': row[4], 'require_photo': bool(row[5]), 'instruction_text': row[6], 
                        'created_at': row[7]} for row in rows]


async def get_all_tasks(franchise_id: int = None):
    """Получить все задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        if franchise_id:
            async with conn.execute(
                'SELECT id, title, description, reward, task_type, is_active, require_photo, instruction_text, created_at, franchise_id FROM tasks WHERE franchise_id = ? ORDER BY created_at DESC',
                (franchise_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [{'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 
                        'type': row[4], 'is_active': bool(row[5]), 'require_photo': bool(row[6]), 
                        'instruction_text': row[7], 'created_at': row[8], 'franchise_id': row[9]} for row in rows]
        else:
            async with conn.execute(
                'SELECT id, title, description, reward, task_type, is_active, require_photo, instruction_text, created_at, franchise_id FROM tasks ORDER BY created_at DESC'
            ) as cursor:
                rows = await cursor.fetchall()
                return [{'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 
                        'type': row[4], 'is_active': bool(row[5]), 'require_photo': bool(row[6]), 
                        'instruction_text': row[7], 'created_at': row[8], 'franchise_id': row[9]} for row in rows]


async def get_task_by_id(task_id: int):
    """Получить задание по ID"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, title, description, reward, task_type, is_active, require_photo, instruction_text, created_at, franchise_id FROM tasks WHERE id = ?',
            (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 
                       'type': row[4], 'is_active': bool(row[5]), 'require_photo': bool(row[6]), 
                       'instruction_text': row[7], 'created_at': row[8], 'franchise_id': row[9]}
            return None


async def update_task_status(task_id: int, is_active: bool):
    """Обновить статус задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE tasks SET is_active = ? WHERE id = ?',
            (1 if is_active else 0, task_id)
        )
        await conn.commit()


async def delete_task(task_id: int):
    """Удалить задание"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute('DELETE FROM completed_tasks WHERE task_id = ?', (task_id,))
        await conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        await conn.commit()


async def update_task_photo_requirement(task_id: int, require_photo: bool):
    """Обновить требование фото для задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE tasks SET require_photo = ? WHERE id = ?',
            (1 if require_photo else 0, task_id)
        )
        await conn.commit()


async def update_task_instruction(task_id: int, instruction_text: str):
    """Обновить инструкцию задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE tasks SET instruction_text = ? WHERE id = ?',
            (instruction_text, task_id)
        )
        await conn.commit()


# ========== ФУНКЦИИ ДЛЯ ВЫПОЛНЕНИЯ ЗАДАНИЙ ==========

async def is_task_completed(user_id: int, task_id: int) -> bool:
    """Проверить, выполнено ли задание"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ? AND status = "completed"',
            (user_id, task_id)
        ) as cursor:
            return await cursor.fetchone() is not None


async def complete_task_without_photo(user_id: int, task_id: int, reward: float) -> bool:
    """Выполнить задание без фото"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            
            async with conn.execute(
                'SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ? AND status = "completed"',
                (user_id, task_id)
            ) as cursor:
                if await cursor.fetchone():
                    await conn.rollback()
                    return False
            
            await conn.execute(
                'INSERT INTO completed_tasks (user_id, task_id, status, completed_at, reward_given) VALUES (?, ?, "completed", CURRENT_TIMESTAMP, 1)',
                (user_id, task_id)
            )
            
            await conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
            
            await conn.commit()
            return True
        except Exception as e:
            await conn.rollback()
            print(f"Ошибка: {e}")
            return False


async def create_submission(user_id: int, task_id: int, photo_file_id: str, proof_text: str, reward: float) -> int:
    """Создать заявку на выполнение задания"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'INSERT INTO completed_tasks (user_id, task_id, photo_file_id, proof_text, status, completed_at, reward_given) VALUES (?, ?, ?, ?, "pending", CURRENT_TIMESTAMP, 0)',
            (user_id, task_id, photo_file_id, proof_text)
        )
        await conn.commit()
        return cursor.lastrowid


async def get_pending_submissions():
    """Получить все заявки на проверку"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT ct.*, t.title, t.reward FROM completed_tasks ct JOIN tasks t ON ct.task_id = t.id WHERE ct.status = "pending" ORDER BY ct.completed_at ASC'
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]


async def get_submission_by_id(submission_id: int):
    """Получить заявку по ID"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT ct.*, t.title, t.reward FROM completed_tasks ct JOIN tasks t ON ct.task_id = t.id WHERE ct.id = ?',
            (submission_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, row))
            return None


async def approve_submission(submission_id: int, admin_id: int) -> bool:
    """Одобрить заявку и выдать награду"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            
            async with conn.execute(
                'SELECT user_id, reward FROM completed_tasks WHERE id = ? AND status = "pending"',
                (submission_id,)
            ) as cursor:
                submission = await cursor.fetchone()
            
            if not submission:
                await conn.rollback()
                return False
            
            user_id, reward = submission
            
            await conn.execute(
                'UPDATE completed_tasks SET status = "completed", reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, reward_given = 1 WHERE id = ?',
                (admin_id, submission_id)
            )
            
            await conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
            
            await conn.commit()
            return True
        except Exception as e:
            await conn.rollback()
            print(f"Ошибка: {e}")
            return False


async def reject_submission(submission_id: int, admin_id: int, reason: str) -> None:
    """Отклонить заявку"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE completed_tasks SET status = "rejected", reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, rejection_reason = ? WHERE id = ?',
            (admin_id, reason, submission_id)
        )
        await conn.commit()


async def get_user_completed_tasks(user_id: int):
    """Получить выполненные задания пользователя"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT t.id, t.title, t.description, t.reward, ct.completed_at FROM tasks t JOIN completed_tasks ct ON t.id = ct.task_id WHERE ct.user_id = ? AND ct.status = "completed" ORDER BY ct.completed_at DESC',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{'id': row[0], 'title': row[1], 'description': row[2], 'reward': row[3], 'completed_at': row[4]} for row in rows]


async def get_pending_submissions_count() -> int:
    """Получить количество заявок на проверку"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM completed_tasks WHERE status = "pending"') as cursor:
            return (await cursor.fetchone())[0]


# ========== ФУНКЦИИ ДЛЯ СТАТИСТИКИ ==========

async def get_tasks_statistics() -> dict:
    """Получить статистику по заданиям"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM tasks') as cursor:
            total_tasks = (await cursor.fetchone())[0]
        
        async with conn.execute('SELECT COUNT(*) FROM tasks WHERE is_active = 1') as cursor:
            active_tasks = (await cursor.fetchone())[0]
        
        async with conn.execute('SELECT COUNT(*) FROM completed_tasks WHERE status = "completed"') as cursor:
            completed_tasks = (await cursor.fetchone())[0]
        
        async with conn.execute('SELECT SUM(reward) FROM completed_tasks WHERE status = "completed" AND reward_given = 1') as cursor:
            total_rewards = (await cursor.fetchone())[0] or 0
        
        async with conn.execute('SELECT COUNT(*) FROM completed_tasks WHERE status = "pending"') as cursor:
            pending_submissions = (await cursor.fetchone())[0]
        
        return {
            'total_tasks': total_tasks,
            'active_tasks': active_tasks,
            'completed_tasks': completed_tasks,
            'total_rewards': total_rewards,
            'pending_submissions': pending_submissions
        }


# ========== ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ==========

async def get_all_users(limit: int = 100, offset: int = 0):
    """Получить всех пользователей с пагинацией"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT user_id, username, balance, registration_time FROM users ORDER BY registration_time DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{'user_id': row[0], 'username': row[1], 'balance': row[2], 'registered_at': row[3]} for row in rows]


async def get_users_count() -> int:
    """Получить количество пользователей"""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM users') as cursor:
            return (await cursor.fetchone())[0]


print("Модуль database.py загружен")
