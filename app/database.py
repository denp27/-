import aiosqlite

from app.config import BASE_DIR

DATABASE_NAME = str(BASE_DIR / "database.db")


async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")

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
                    registration_time REAL DEFAULT (strftime('%s','now'))
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

        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="uses_promocodes"'
        )
        row = await cursor.fetchone()

        if row is None:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS uses_promocodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    user_id INTEGER NOT NULL
                )
            ''')
            print('Таблица "uses_promocodes" создана')
        else:
            print('Выполнено подключение к таблице "uses_promocodes".')

        await conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_uses_promocodes_code_user ON uses_promocodes(code, user_id)'
        )

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

        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="franchise_photos"'
        )
        row = await cursor.fetchone()
        if row is None:
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
            print('Таблица "franchise_photos" создана')
        else:
            print('Выполнено подключение к таблице "franchise_photos".')

        cursor = await conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" AND name="franchise_required_channels"'
        )
        row = await cursor.fetchone()
        if row is None:
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
            print('Таблица "franchise_required_channels" создана')
        else:
            print('Выполнено подключение к таблице "franchise_required_channels".')

        cursor2 = await conn.execute("PRAGMA table_info(users)")
        user_columns = [c[1] for c in await cursor2.fetchall()]
        if 'is_banned' not in user_columns:
            await conn.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
            print('Добавлена колонка is_banned')
        if 'ban_reason' not in user_columns:
            await conn.execute('ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT NULL')
            print('Добавлена колонка ban_reason')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS franchise_users (
                franchise_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (franchise_id, user_id),
                FOREIGN KEY(franchise_id) REFERENCES franchises(id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tx_sent (
                req_id TEXT PRIMARY KEY,
                tx_hash TEXT,
                kind TEXT,
                sent_at REAL DEFAULT (strftime('%s','now'))
            )
        ''')

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

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                franchise_id INTEGER NOT NULL,
                owner_id    INTEGER NOT NULL,
                amount      REAL    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                comment     TEXT    DEFAULT NULL,
                created_at  REAL    DEFAULT (strftime('%s','now')),
                resolved_at REAL    DEFAULT NULL
            )
        ''')
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_wr_franchise ON withdraw_requests(franchise_id, status)'
        )
        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_wr_status ON withdraw_requests(status, created_at)'
        )

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS deposit_invoices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id  TEXT    UNIQUE NOT NULL,
                user_id     INTEGER NOT NULL,
                amount      REAL    NOT NULL,
                provider    TEXT    NOT NULL,
                created_at  REAL    DEFAULT (strftime('%s','now')),
                credited_at REAL    DEFAULT NULL
            )
        ''')

        await conn.commit()

# database.py
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

DATABASE_NAME = "bot.db"


def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            registered_at TIMESTAMP
        )
    ''')
    
    # Таблица заданий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            reward REAL NOT NULL,
            require_photo INTEGER DEFAULT 0,
            instruction_text TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP
        )
    ''')
    
    # Таблица выполненных заданий
    cursor.execute('''
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
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("База данных инициализирована")


# ========== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========

def add_user(user_id: int, username: str, first_name: str):
    """Добавить пользователя"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, registered_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now()))
    conn.commit()
    conn.close()


def get_user(user_id: int):
    """Получить пользователя"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_balance(user_id: int) -> float:
    """Получить баланс"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0


def update_balance(user_id: int, amount: float):
    """Обновить баланс"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()


# ========== ФУНКЦИИ ДЛЯ ЗАДАНИЙ ==========

def add_task(title: str, description: str, reward: float, require_photo: bool = False, instruction_text: str = None) -> int:
    """Добавить новое задание"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (title, description, reward, require_photo, instruction_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (title, description, reward, 1 if require_photo else 0, instruction_text, datetime.now()))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_active_tasks() -> List[Dict]:
    """Получить активные задания"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, reward, require_photo, instruction_text 
        FROM tasks WHERE is_active = 1 ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    tasks = []
    for row in rows:
        tasks.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'reward': row[3],
            'require_photo': bool(row[4]),
            'instruction_text': row[5]
        })
    return tasks


def get_all_tasks() -> List[Dict]:
    """Получить все задания"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    
    tasks = []
    for row in rows:
        tasks.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'reward': row[3],
            'require_photo': bool(row[4]),
            'instruction_text': row[5],
            'is_active': bool(row[6]),
            'created_at': row[7]
        })
    return tasks


def get_task_by_id(task_id: int) -> Optional[Dict]:
    """Получить задание по ID"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'reward': row[3],
            'require_photo': bool(row[4]),
            'instruction_text': row[5],
            'is_active': bool(row[6]),
            'created_at': row[7]
        }
    return None


def update_task_status(task_id: int, is_active: bool):
    """Обновить статус задания"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET is_active = ? WHERE id = ?', (1 if is_active else 0, task_id))
    conn.commit()
    conn.close()


def delete_task(task_id: int):
    """Удалить задание"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM completed_tasks WHERE task_id = ?', (task_id,))
    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()


# ========== ФУНКЦИИ ДЛЯ ВЫПОЛНЕНИЯ ЗАДАНИЙ ==========

def is_task_completed(user_id: int, task_id: int) -> bool:
    """Проверить, выполнено ли задание"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 1 FROM completed_tasks 
        WHERE user_id = ? AND task_id = ? AND status = 'completed'
    ''', (user_id, task_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def complete_task_without_photo(user_id: int, task_id: int, reward: float) -> bool:
    """Выполнить задание без фото"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN TRANSACTION')
        
        # Проверяем, не выполнено ли уже
        cursor.execute('''
            SELECT 1 FROM completed_tasks 
            WHERE user_id = ? AND task_id = ? AND status = 'completed'
        ''', (user_id, task_id))
        
        if cursor.fetchone():
            conn.rollback()
            return False
        
        # Добавляем запись о выполнении
        cursor.execute('''
            INSERT INTO completed_tasks (user_id, task_id, status, completed_at, reward_given)
            VALUES (?, ?, 'completed', ?, 1)
        ''', (user_id, task_id, datetime.now()))
        
        # Начисляем награду
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Ошибка: {e}")
        return False
    finally:
        conn.close()


def create_submission(user_id: int, task_id: int, photo_file_id: str, proof_text: str, reward: float) -> int:
    """Создать заявку на выполнение задания (с фото)"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO completed_tasks (user_id, task_id, photo_file_id, proof_text, status, completed_at, reward_given)
        VALUES (?, ?, ?, ?, 'pending', ?, 0)
    ''', (user_id, task_id, photo_file_id, proof_text, datetime.now()))
    
    submission_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return submission_id


def get_pending_submissions() -> List[Dict]:
    """Получить все заявки на проверку"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ct.*, t.title, t.reward 
        FROM completed_tasks ct
        JOIN tasks t ON ct.task_id = t.id
        WHERE ct.status = 'pending'
        ORDER BY ct.completed_at ASC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    submissions = []
    for row in rows:
        submissions.append({
            'id': row[0],
            'user_id': row[1],
            'task_id': row[2],
            'photo_file_id': row[3],
            'proof_text': row[4],
            'status': row[5],
            'completed_at': row[6],
            'task_title': row[9],
            'reward': row[10]
        })
    return submissions


def get_submission_by_id(submission_id: int) -> Optional[Dict]:
    """Получить заявку по ID"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ct.*, t.title, t.reward 
        FROM completed_tasks ct
        JOIN tasks t ON ct.task_id = t.id
        WHERE ct.id = ?
    ''', (submission_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'user_id': row[1],
            'task_id': row[2],
            'photo_file_id': row[3],
            'proof_text': row[4],
            'status': row[5],
            'completed_at': row[6],
            'task_title': row[9],
            'reward': row[10]
        }
    return None


def approve_submission(submission_id: int, admin_id: int) -> bool:
    """Одобрить заявку и выдать награду"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN TRANSACTION')
        
        # Получаем заявку
        cursor.execute('SELECT user_id, reward FROM completed_tasks WHERE id = ? AND status = "pending"', (submission_id,))
        submission = cursor.fetchone()
        
        if not submission:
            conn.rollback()
            return False
        
        user_id, reward = submission
        
        # Обновляем статус заявки
        cursor.execute('''
            UPDATE completed_tasks 
            SET status = 'completed', reviewed_by = ?, reviewed_at = ?, reward_given = 1
            WHERE id = ?
        ''', (admin_id, datetime.now(), submission_id))
        
        # Начисляем награду
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Ошибка: {e}")
        return False
    finally:
        conn.close()


def reject_submission(submission_id: int, admin_id: int, reason: str) -> None:
    """Отклонить заявку"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE completed_tasks 
        SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, proof_text = ?
        WHERE id = ?
    ''', (admin_id, datetime.now(), reason, submission_id))
    
    conn.commit()
    conn.close()


def get_user_completed_tasks(user_id: int) -> List[Dict]:
    """Получить выполненные задания пользователя"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT t.id, t.title, t.description, t.reward, ct.completed_at
        FROM tasks t
        JOIN completed_tasks ct ON t.id = ct.task_id
        WHERE ct.user_id = ? AND ct.status = 'completed'
        ORDER BY ct.completed_at DESC
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    tasks = []
    for row in rows:
        tasks.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'reward': row[3],
            'completed_at': row[4]
        })
    return tasks


# ========== ФУНКЦИИ ДЛЯ СТАТИСТИКИ ==========

def get_tasks_statistics() -> Dict:
    """Получить статистику по заданиям"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Всего заданий
    cursor.execute('SELECT COUNT(*) FROM tasks')
    total_tasks = cursor.fetchone()[0]
    
    # Активных заданий
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE is_active = 1')
    active_tasks = cursor.fetchone()[0]
    
    # Выполненных заданий
    cursor.execute('SELECT COUNT(*) FROM completed_tasks WHERE status = "completed"')
    completed_tasks = cursor.fetchone()[0]
    
    # Всего выдано наград
    cursor.execute('SELECT SUM(reward) FROM completed_tasks WHERE status = "completed" AND reward_given = 1')
    total_rewards = cursor.fetchone()[0] or 0
    
    # Заявок на проверку
    cursor.execute('SELECT COUNT(*) FROM completed_tasks WHERE status = "pending"')
    pending_submissions = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'total_tasks': total_tasks,
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'total_rewards': total_rewards,
        'pending_submissions': pending_submissions
    }


print("Модуль database.py загружен")


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


async def get_franchise_required_channels(franchise_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT channel_id, channel_url, channel_name FROM franchise_required_channels WHERE franchise_id = ? AND is_active = 1',
            (franchise_id,)
        ) as cursor:
            return await cursor.fetchall()


async def add_franchise_required_channel(franchise_id: int, channel_id: str, channel_url: str, channel_name: str = None):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO franchise_required_channels (franchise_id, channel_id, channel_url, channel_name) VALUES (?, ?, ?, ?)',
                (franchise_id, channel_id, channel_url, channel_name)
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def remove_franchise_required_channel(franchise_id: int, channel_id: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'DELETE FROM franchise_required_channels WHERE franchise_id = ? AND channel_id = ?',
            (franchise_id, channel_id)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_uses_promo(code: str) -> int:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT COUNT(*) FROM uses_promocodes WHERE code = ?',
            (code,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]


async def create_promo(code: str, reward: float, max_uses: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'INSERT INTO promocodes (code, reward, max_uses) VALUES (?, ?, ?)',
            (code, reward, max_uses)
        )
        await conn.commit()


async def get_promo(code: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT code, reward, max_uses, is_active FROM promocodes WHERE code = ?',
            (code,)
        ) as cursor:
            return await cursor.fetchone()


async def deactive_promo(code: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE promocodes SET is_active = 0 WHERE code = ?',
            (code,)
        )
        await conn.commit()


async def get_active_promos():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT code, reward, max_uses FROM promocodes WHERE is_active = 1'
        ) as cursor:
            return await cursor.fetchall()


async def use_promo(code: str, user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")

        async with conn.execute(
            'SELECT reward, max_uses, is_active FROM promocodes WHERE code = ?',
            (code,)
        ) as cursor:
            promo = await cursor.fetchone()

        if not promo:
            await conn.rollback()
            return (False, "Промокод не найден")

        reward, max_uses, is_active = promo

        if not is_active:
            await conn.rollback()
            return (False, "Промокод неактивен")

        async with conn.execute(
            'SELECT COUNT(*) FROM uses_promocodes WHERE code = ? AND user_id = ?',
            (code, user_id)
        ) as cursor:
            user_used = (await cursor.fetchone())[0]

        if user_used > 0:
            await conn.rollback()
            return (False, "Вы уже использовали этот промокод")

        async with conn.execute(
            'SELECT COUNT(*) FROM uses_promocodes WHERE code = ?',
            (code,)
        ) as cursor:
            total_uses = (await cursor.fetchone())[0]

        if total_uses >= max_uses:
            await conn.rollback()
            return (False, "Промокод исчерпан")

        await conn.execute(
            'INSERT INTO uses_promocodes (code, user_id) VALUES (?, ?)',
            (code, user_id)
        )

        await conn.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (reward, user_id)
        )

        if total_uses + 1 >= max_uses:
            await conn.execute(
                'UPDATE promocodes SET is_active = 0 WHERE code = ?',
                (code,)
            )

        await conn.commit()
        return (True, reward)


async def add_required_channel(channel_id: str, channel_url: str, channel_name: str = None):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO required_channels (channel_id, channel_url, channel_name) VALUES (?, ?, ?)',
                (channel_id, channel_url, channel_name)
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def get_all_required_channels():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT channel_id, channel_url, channel_name FROM required_channels WHERE is_active = 1'
        ) as cursor:
            return await cursor.fetchall()


async def remove_required_channel(channel_id: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute('DELETE FROM required_channels WHERE channel_id = ?', (channel_id,))
        await conn.commit()
        return cursor.rowcount > 0


async def toggle_channel_status(channel_id: str, is_active: bool):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'UPDATE required_channels SET is_active = ? WHERE channel_id = ?',
            (1 if is_active else 0, channel_id)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_rented_num(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT nft_address, rent_start_time, rent_duration, rent_end_time FROM rented_num WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    'nft_address': row[0],
                    'rent_start_time': row[1],
                    'rent_duration': row[2],
                    'end_time': row[3],
                }
                for row in rows
            ]


async def add_rent_num(user_id: int, nft_address: str, rent_start_time: float, rent_duration: int, rent_end_time: float, nft_name: str = None):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO rented_num (user_id, nft_address, rent_start_time, rent_duration, rent_end_time, nft_name) VALUES (?, ?, ?, ?, ?, ?)',
                (user_id, nft_address, rent_start_time, rent_duration, rent_end_time, nft_name)
            )
            await conn.commit()
            return True
        except Exception:
            print(f"NFT {nft_address} уже арендован пользователем {user_id}.")
            return False


async def get_rented_nft(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT nft_address, rent_start_time, rent_duration, rent_end_time FROM rented WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()


async def add_rent_nft(user_id: int, nft_address: str, rent_start_time: float, rent_duration: int, rent_end_time: float):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO rented (user_id, nft_address, rent_start_time, rent_duration, rent_end_time) VALUES (?, ?, ?, ?, ?)',
                (user_id, nft_address, rent_start_time, rent_duration, rent_end_time)
            )
            await conn.commit()
            return True
        except Exception:
            print(f"NFT {nft_address} уже арендован пользователем {user_id}.")
            return False


async def update_collection_address(collection_name: str, collection_address: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE collections_address SET collection_address = ? WHERE collection_name = ?',
            (collection_address, collection_name)
        )
        await conn.commit()


async def db_get_collection_address(collection_name: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT collection_address FROM collections_address WHERE collection_name = ?',
            (collection_name,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None


async def add_collection_address(collection_name: str, collection_address: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO collections_address (collection_name, collection_address) VALUES (?, ?)',
                (collection_name, collection_address)
            )
            await conn.commit()
        except Exception:
            print(f"Коллекция {collection_name} уже существует.")


async def check_collection_match(collection_name: str, collection_address: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT collection_address FROM collections_address WHERE collection_name = ?',
            (collection_name,)
        ) as cursor:
            result = await cursor.fetchone()

        if result is None:
            return True

        return result[0] == collection_address


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


async def get_user_by_username(username: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT * FROM users WHERE LOWER(username) = LOWER(?)',
            (username,)
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


async def get_count_users():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM users') as cursor:
            return (await cursor.fetchone())[0]


async def get_count_starsbuyed():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT SUM(stars_buyed) FROM users') as cursor:
            return (await cursor.fetchone())[0]


async def add_stars(user_id: int, stars: int) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET stars_buyed = stars_buyed + ? WHERE user_id = ?',
            (stars, user_id)
        )
        await conn.commit()


async def get_users_ids():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            async with conn.execute('SELECT user_id FROM users') as cursor:
                return [row[0] for row in await cursor.fetchall()]
        except Exception:
            return []


async def register_franchise_user(franchise_id: int, user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO franchise_users (franchise_id, user_id) VALUES (?, ?)',
            (franchise_id, user_id)
        )
        await conn.commit()


async def get_franchise_users_ids(franchise_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT user_id FROM franchise_users WHERE franchise_id = ?',
            (franchise_id,)
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def deincrement_balance(user_id: int, balance: float) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?',
            (balance, user_id, balance)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def increment_balance(user_id: int, balance: float) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (balance, user_id)
        )
        await conn.commit()


async def user_exists(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT 1 FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def get_referrer_id(user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT referral_id FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result and result[0] else None


async def get_referrals_count(user_id: int) -> int:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT referrals_count FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0


async def increment_referrals_count(user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?',
            (user_id,)
        )
        await conn.commit()


async def get_top_referrers(limit: int = 3):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT user_id, username, referrals_count FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT ?',
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


async def create_franchise(owner_id: int, bot_token: str, project_name: str = 'MstiStars', markup: float = 0):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO franchises (owner_id, bot_token, project_name, markup, total_earned) VALUES (?, ?, ?, ?, 0)',
                (owner_id, bot_token, project_name, markup)
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def get_franchise_by_owner(owner_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, owner_id, bot_token, project_name, markup, is_active, total_earned, support_url FROM franchises WHERE owner_id = ?',
            (owner_id,)
        ) as cursor:
            return await cursor.fetchone()


async def get_franchise_by_token(bot_token: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, owner_id, bot_token, project_name, markup, is_active, total_earned FROM franchises WHERE bot_token = ?',
            (bot_token,)
        ) as cursor:
            return await cursor.fetchone()


async def update_franchise_name(owner_id: int, project_name: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE franchises SET project_name = ? WHERE owner_id = ?',
            (project_name, owner_id)
        )
        await conn.commit()


async def update_franchise_support_url(owner_id: int, support_url: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE franchises SET support_url = ? WHERE owner_id = ?',
            (support_url, owner_id)
        )
        await conn.commit()


async def update_franchise_markup(owner_id: int, markup: float):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE franchises SET markup = ? WHERE owner_id = ?',
            (markup, owner_id)
        )
        await conn.commit()


async def increment_franchise_earned(owner_id: int, amount: float):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE franchises SET total_earned = total_earned + ? WHERE owner_id = ?',
            (amount, owner_id)
        )
        await conn.commit()


async def set_franchise_photo(franchise_id: int, section: str, file_id: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'INSERT OR REPLACE INTO franchise_photos (franchise_id, section, file_id) VALUES (?, ?, ?)',
            (franchise_id, section, file_id)
        )
        await conn.commit()


async def get_franchise_photo(franchise_id: int, section: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT file_id FROM franchise_photos WHERE franchise_id = ? AND section = ?',
            (franchise_id, section)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def delete_franchise_photo(franchise_id: int, section: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'DELETE FROM franchise_photos WHERE franchise_id = ? AND section = ?',
            (franchise_id, section)
        )
        await conn.commit()


async def get_all_franchises():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, owner_id, bot_token, project_name, markup, is_active, total_earned FROM franchises'
        ) as cursor:
            return await cursor.fetchall()


async def get_franchise_stats():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*), SUM(total_earned) FROM franchises') as cursor:
            row = await cursor.fetchone()
            return row[0] or 0, row[1] or 0.0


async def get_all_franchises_paginated(offset: int = 0, limit: int = 5):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, owner_id, bot_token, project_name, markup, is_active, total_earned FROM franchises ORDER BY id DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ) as cursor:
            return await cursor.fetchall()


async def get_franchises_count():
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute('SELECT COUNT(*) FROM franchises') as cursor:
            return (await cursor.fetchone())[0]


async def get_franchise_by_id(franchise_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, owner_id, bot_token, project_name, markup, is_active, total_earned, support_url FROM franchises WHERE id = ?',
            (franchise_id,)
        ) as cursor:
            return await cursor.fetchone()


async def set_franchise_active(franchise_id: int, is_active: bool):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'UPDATE franchises SET is_active = ? WHERE id = ?',
            (1 if is_active else 0, franchise_id)
        )
        await conn.commit()


async def delete_franchise(franchise_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute('DELETE FROM franchise_photos WHERE franchise_id = ?', (franchise_id,))
        await conn.execute('DELETE FROM franchises WHERE id = ?', (franchise_id,))
        await conn.commit()


async def create_check(check_id: str, creator_id: int, type_: str, amount: float, cost_rub: float) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO checks (check_id, creator_id, type, amount, cost_rub) VALUES (?, ?, ?, ?, ?)',
                (check_id, creator_id, type_, amount, cost_rub)
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def get_check(check_id: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT check_id, creator_id, type, amount, cost_rub, is_active, used_by, created_at FROM checks WHERE check_id = ?',
            (check_id,)
        ) as cursor:
            return await cursor.fetchone()


async def mark_check_used(check_id: str, used_by: int) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute('SELECT is_active FROM checks WHERE check_id = ?', (check_id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]:
            await conn.rollback()
            return False
        await conn.execute('UPDATE checks SET is_active = 0, used_by = ? WHERE check_id = ?', (used_by, check_id))
        await conn.commit()
        return True


async def reactivate_check(check_id: str) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute('UPDATE checks SET is_active = 1, used_by = NULL WHERE check_id = ?', (check_id,))
        await conn.commit()


async def add_transaction(
    user_id: int,
    type_: str,
    amount: float,
    cost_rub: float,
    recipient: str = None,
) -> None:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute(
            'INSERT INTO transactions (user_id, type, amount, cost_rub, recipient) VALUES (?, ?, ?, ?, ?)',
            (user_id, type_, amount, cost_rub, recipient),
        )
        await conn.commit()


async def get_user_transactions(
    user_id: int,
    type_filter: str = 'all',
    limit: int = 5,
    offset: int = 0,
) -> list:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        if type_filter == 'all':
            async with conn.execute(
                'SELECT id, type, amount, cost_rub, recipient, created_at '
                'FROM transactions WHERE user_id = ? '
                'ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (user_id, limit, offset),
            ) as cursor:
                return await cursor.fetchall()
        else:
            async with conn.execute(
                'SELECT id, type, amount, cost_rub, recipient, created_at '
                'FROM transactions WHERE user_id = ? AND type = ? '
                'ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (user_id, type_filter, limit, offset),
            ) as cursor:
                return await cursor.fetchall()


async def get_user_transactions_count(user_id: int, type_filter: str = 'all') -> int:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        if type_filter == 'all':
            async with conn.execute(
                'SELECT COUNT(*) FROM transactions WHERE user_id = ?',
                (user_id,),
            ) as cursor:
                return (await cursor.fetchone())[0]
        else:
            async with conn.execute(
                'SELECT COUNT(*) FROM transactions WHERE user_id = ? AND type = ?',
                (user_id, type_filter),
            ) as cursor:
                return (await cursor.fetchone())[0]


async def get_user_transactions_stats(user_id: int, type_filter: str = 'all') -> tuple[int, float]:
    """Возвращает (count, total_spent_rub) для пользователя."""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        if type_filter == 'all':
            async with conn.execute(
                'SELECT COUNT(*), COALESCE(SUM(cost_rub), 0) FROM transactions WHERE user_id = ?',
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        else:
            async with conn.execute(
                'SELECT COUNT(*), COALESCE(SUM(cost_rub), 0) FROM transactions WHERE user_id = ? AND type = ?',
                (user_id, type_filter),
            ) as cursor:
                row = await cursor.fetchone()
        return row[0], row[1]


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


# ═══════════════════════════════════════════════════════════════════════════
#  WITHDRAW REQUESTS
# ═══════════════════════════════════════════════════════════════════════════

async def create_withdraw_request(franchise_id: int, owner_id: int, amount: float) -> int | None:
    """
    Create a new pending withdraw request.
    Returns the new row id, or None if a pending request already exists.
    """
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        # guard: only one pending request per franchise at a time
        async with conn.execute(
            "SELECT id FROM withdraw_requests WHERE franchise_id = ? AND status = 'pending'",
            (franchise_id,)
        ) as cursor:
            if await cursor.fetchone():
                await conn.rollback()
                return None
        cursor = await conn.execute(
            "INSERT INTO withdraw_requests (franchise_id, owner_id, amount) VALUES (?, ?, ?)",
            (franchise_id, owner_id, amount)
        )
        req_id = cursor.lastrowid
        await conn.commit()
        return req_id


async def get_withdraw_request(req_id: int):
    """Return a single withdraw_request row by id."""
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            "SELECT id, franchise_id, owner_id, amount, status, comment, created_at, resolved_at "
            "FROM withdraw_requests WHERE id = ?",
            (req_id,)
        ) as cursor:
            return await cursor.fetchone()


async def get_pending_withdraw_requests(limit: int = 20, offset: int = 0):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            "SELECT wr.id, wr.franchise_id, wr.owner_id, wr.amount, wr.created_at, f.project_name "
            "FROM withdraw_requests wr "
            "LEFT JOIN franchises f ON f.id = wr.franchise_id "
            "WHERE wr.status = 'pending' "
            "ORDER BY wr.created_at ASC "
            "LIMIT ? OFFSET ?",
            (limit, offset)
        ) as cursor:
            return await cursor.fetchall()


async def get_pending_withdraw_count() -> int:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'"
        ) as cursor:
            return (await cursor.fetchone())[0]


async def get_franchise_withdraw_history(franchise_id: int, limit: int = 10, offset: int = 0):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            "SELECT id, amount, status, comment, created_at, resolved_at "
            "FROM withdraw_requests WHERE franchise_id = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (franchise_id, limit, offset)
        ) as cursor:
            return await cursor.fetchall()


async def get_franchise_pending_request(franchise_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            "SELECT id, amount, created_at "
            "FROM withdraw_requests WHERE franchise_id = ? AND status = 'pending' "
            "LIMIT 1",
            (franchise_id,)
        ) as cursor:
            return await cursor.fetchone()


async def approve_withdraw_request(req_id: int, check_text: str = None) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute(
            "SELECT franchise_id, amount, status FROM withdraw_requests WHERE id = ?",
            (req_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row or row[2] != 'pending':
            await conn.rollback()
            return False
        franchise_id, amount, _ = row
        await conn.execute(
            "UPDATE withdraw_requests SET status = 'paid', comment = ?, resolved_at = strftime('%s','now') WHERE id = ?",
            (check_text, req_id)
        )
        await conn.execute(
            "UPDATE franchises SET total_earned = MAX(0, total_earned - ?) WHERE id = ?",
            (amount, franchise_id)
        )
        await conn.commit()
        return True


async def reject_withdraw_request(req_id: int, comment: str = None) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute(
            "SELECT id, status FROM withdraw_requests WHERE id = ?",
            (req_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row or row[1] != 'pending':
            await conn.rollback()
            return False
        await conn.execute(
            "UPDATE withdraw_requests "
            "SET status = 'rejected', comment = ?, resolved_at = strftime('%s','now') "
            "WHERE id = ?",
            (comment, req_id)
        )
        await conn.commit()
        return True
async def create_deposit_invoice(invoice_id: str, user_id: int, amount: float, provider: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                "INSERT INTO deposit_invoices (invoice_id, user_id, amount, provider) "
                "VALUES (?, ?, ?, ?)",
                (str(invoice_id), user_id, amount, provider)
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def mark_invoice_credited(invoice_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute(
            "SELECT credited_at FROM deposit_invoices WHERE invoice_id = ?",
            (str(invoice_id),)
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            try:
                await conn.execute(
                    "INSERT INTO deposit_invoices (invoice_id, user_id, amount, provider, credited_at) "
                    "VALUES (?, 0, 0, 'unknown', strftime('%s','now'))",
                    (str(invoice_id),)
                )
                await conn.commit()
                return True
            except aiosqlite.IntegrityError:
                await conn.rollback()
                return False

        if row[0] is not None:
            await conn.rollback()
            return False

        await conn.execute(
            "UPDATE deposit_invoices SET credited_at = strftime('%s','now') WHERE invoice_id = ?",
            (str(invoice_id),)
        )
        await conn.commit()
        return True


# ═══════════════════════════════════════════════════════════════════════════
#  GIFTS
# ═══════════════════════════════════════════════════════════════════════════

async def add_gift(key: str, name: str, emoji_id: str, count_stars: int, gift_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        try:
            await conn.execute(
                'INSERT INTO gifts (key, name, emoji_id, count_stars, gift_id) VALUES (?, ?, ?, ?, ?)',
                (key, name, emoji_id, count_stars, gift_id)
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def get_active_gifts() -> list:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, key, name, emoji_id, count_stars, gift_id, is_active, added_time '
            'FROM gifts WHERE is_active = 1 ORDER BY added_time ASC'
        ) as cursor:
            return await cursor.fetchall()


async def get_all_gifts() -> list:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, key, name, emoji_id, count_stars, gift_id, is_active, added_time '
            'FROM gifts ORDER BY added_time ASC'
        ) as cursor:
            return await cursor.fetchall()


async def get_gift_by_key(key: str):
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT id, key, name, emoji_id, count_stars, gift_id, is_active, added_time '
            'FROM gifts WHERE key = ?',
            (key,)
        ) as cursor:
            return await cursor.fetchone()


async def delete_gift(key: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute('DELETE FROM gifts WHERE key = ?', (key,))
        await conn.commit()
        return cursor.rowcount > 0


async def toggle_gift_active(key: str, is_active: bool) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute(
            'UPDATE gifts SET is_active = ? WHERE key = ?',
            (1 if is_active else 0, key)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_user_referral_rank(user_id: int) -> tuple:
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        async with conn.execute(
            'SELECT referrals_count FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if not result or result[0] == 0:
                return (None, 0)

        user_refs = result[0]

        async with conn.execute(
            'SELECT COUNT(*) FROM users WHERE referrals_count > ?',
            (user_refs,)
        ) as cursor:
            rank = (await cursor.fetchone())[0] + 1

        return (rank, user_refs)
