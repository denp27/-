# tasks.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from app.database import (
    get_active_tasks, get_task_by_id, complete_task,
    is_task_completed, get_user_completed_tasks,
    create_user_task_submission, get_pending_submissions,
    approve_submission, reject_submission
)
from app.config import ADMIN_IDS

router = Router()


# FSM состояния для выполнения задания с фото
class CompleteTaskStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_proof_text = State()


# Проверка админа
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ========== ПОЛЬЗОВАТЕЛЬСКИЕ ФУНКЦИИ ==========

@router.callback_query(F.data == "tasks")
async def show_tasks(callback: CallbackQuery):
    """Показать список доступных заданий"""
    user_id = callback.from_user.id
    tasks = await get_active_tasks()
    
    if not tasks:
        from app.keyboards import get_back_keyboard
        await callback.message.edit_text(
            "📋 <b>Доступные задания</b>\n\n"
            "😕 Пока нет доступных заданий.\n"
            "Загляните позже!",
            reply_markup=await get_back_keyboard(user_id),
            parse_mode="HTML"
        )
    else:
        text = "📋 <b>Доступные задания</b>\n\n"
        available_tasks = []
        
        for task in tasks:
            is_completed = await is_task_completed(user_id, task['id'])
            
            if not is_completed:
                available_tasks.append(task)
                text += f"📌 <b>{task['title']}</b>\n"
                text += f"   📝 {task['description']}\n"
                text += f"   ⭐ Награда: +{task['reward']} Stars\n"
                if task.get('require_photo'):
                    text += f"   📸 Требуется фото подтверждение\n"
                text += "\n"
        
        if not available_tasks:
            text = "✅ <b>Отлично!</b>\n\nВы выполнили все доступные задания!\nСкоро появятся новые."
        
        from app.keyboards import get_tasks_keyboard
        await callback.message.edit_text(
            text,
            reply_markup=await get_tasks_keyboard(available_tasks, user_id),
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("complete_task_"))
async def start_task_completion(callback: CallbackQuery, state: FSMContext):
    """Начать выполнение задания"""
    user_id = callback.from_user.id
    task_id = int(callback.data.split("_")[2])
    
    # Получаем информацию о задании
    task = await get_task_by_id(task_id)
    
    if not task:
        await callback.answer("❌ Задание не найдено!", show_alert=True)
        return
    
    # Проверяем, не выполнено ли уже
    if await is_task_completed(user_id, task_id):
        await callback.answer("❌ Вы уже выполнили это задание!", show_alert=True)
        return
    
    # Сохраняем task_id в состояние
    await state.update_data(task_id=task_id, task_reward=task['reward'])
    
    # Проверяем, требуется ли фото
    if task.get('require_photo', False):
        keyboard = None
        if task.get('instruction_text'):
            text = f"📸 <b>{task['title']}</b>\n\n"
            text += f"{task['instruction_text']}\n\n"
            text += f"Пожалуйста, отправьте фото в подтверждение выполнения задания.\n"
            text += f"Награда: +{task['reward']} ⭐"
        else:
            text = f"📸 <b>{task['title']}</b>\n\n"
            text += f"Отправьте фото в подтверждение выполнения задания.\n"
            text += f"Награда: +{task['reward']} ⭐"
        
        await callback.message.edit_text(
            text,
            parse_mode="HTML"
        )
        await state.set_state(CompleteTaskStates.waiting_for_photo)
    else:
        # Если фото не требуется, сразу выполняем задание
        success = await complete_task(user_id, task_id, task['reward'])
        
        if success:
            from app.keyboards import get_task_completed_keyboard
            await callback.message.edit_text(
                f"✅ <b>Задание выполнено!</b>\n\n"
                f"📋 {task['title']}\n"
                f"⭐ Получено: +{task['reward']} Stars\n\n"
                f"Баланс пополнен! Продолжайте выполнять задания!",
                reply_markup=await get_task_completed_keyboard(user_id),
                parse_mode="HTML"
            )
            await callback.answer(f"✅ Получено {task['reward']} Stars!")
        else:
            await callback.answer("❌ Ошибка при выполнении задания!", show_alert=True)
    
    await callback.answer()


@router.message(CompleteTaskStates.waiting_for_photo)
async def process_task_photo(message: Message, state: FSMContext):
    """Обработка фото для задания"""
    user_id = message.from_user.id
    data = await state.get_data()
    task_id = data.get('task_id')
    
    if not message.photo:
        await message.answer(
            "📸 Пожалуйста, отправьте <b>фото</b> в подтверждение выполнения задания.\n\n"
            "Если хотите отменить выполнение, отправьте /cancel",
            parse_mode="HTML"
        )
        return
    
    # Получаем file_id самого большого фото
    photo = message.photo[-1]
    file_id = photo.file_id
    
    await state.update_data(photo_file_id=file_id)
    
    # Запрашиваем текстовое пояснение
    await message.answer(
        "📝 Теперь отправьте <b>текстовое пояснение</b> к выполненному заданию:\n"
        "Опишите, что вы сделали для выполнения задания.\n\n"
        "Или отправьте 'пропустить' если пояснение не требуется",
        parse_mode="HTML"
    )
    await state.set_state(CompleteTaskStates.waiting_for_proof_text)


@router.message(CompleteTaskStates.waiting_for_proof_text)
async def process_task_proof(message: Message, state: FSMContext):
    """Обработка текстового подтверждения и отправка на модерацию"""
    user_id = message.from_user.id
    data = await state.get_data()
    task_id = data.get('task_id')
    task_reward = data.get('task_reward')
    photo_file_id = data.get('photo_file_id')
    
    proof_text = message.text if message.text.lower() != "пропустить" else None
    
    # Создаем заявку на модерацию
    submission_id = await create_user_task_submission(
        user_id=user_id,
        task_id=task_id,
        photo_file_id=photo_file_id,
        proof_text=proof_text
    )
    
    # Уведомляем админов
    for admin_id in ADMIN_IDS:
        try:
            from app.keyboards import get_moderation_keyboard
            await message.bot.send_photo(
                admin_id,
                photo=photo_file_id,
                caption=f"🆕 <b>Новая заявка на задание!</b>\n\n"
                       f"👤 Пользователь: @{message.from_user.username or 'Неизвестно'}\n"
                       f"🆔 ID: {user_id}\n"
                       f"📋 Задание ID: {task_id}\n"
                       f"📝 Пояснение: {proof_text or 'Нет пояснения'}\n"
                       f"⭐ Награда: {task_reward} Stars",
                reply_markup=await get_moderation_keyboard(submission_id, user_id, task_reward),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление админу {admin_id}: {e}")
    
    await message.answer(
        "✅ <b>Ваше задание отправлено на проверку!</b>\n\n"
        "Модератор проверит ваше выполнение в ближайшее время.\n"
        "Вы получите уведомление о результате проверки.\n\n"
        "Спасибо за ожидание!",
        parse_mode="HTML"
    )
    
    # Возвращаемся в главное меню
    from app.keyboards import main_menu
    await message.answer(
        "🌟 Главное меню:",
        reply_markup=main_menu(user_id, is_admin(user_id))
    )
    
    await state.clear()


@router.callback_query(F.data == "my_completed_tasks")
async def show_completed_tasks(callback: CallbackQuery):
    """Показать выполненные задания пользователя"""
    user_id = callback.from_user.id
    completed_tasks = await get_user_completed_tasks(user_id)
    
    if not completed_tasks:
        text = "📋 <b>Выполненные задания</b>\n\n"
        text += "😕 Вы еще не выполнили ни одного задания.\n"
        text += "Перейдите в раздел 'Задания' чтобы начать!"
    else:
        text = "✅ <b>Ваши выполненные задания</b>\n\n"
        total_reward = sum(task['reward'] for task in completed_tasks)
        
        for task in completed_tasks:
            text += f"• <b>{task['title']}</b>\n"
            text += f"  ⭐ +{task['reward']} Stars\n"
            text += f"  📅 {task['completed_at']}\n\n"
        
        text += f"📊 <b>Всего получено:</b> {total_reward} Stars"
    
    from app.keyboards import get_completed_tasks_keyboard
    await callback.message.edit_text(
        text,
        reply_markup=await get_completed_tasks_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "/cancel")
async def cancel_task(message: Message, state: FSMContext):
    """Отмена выполнения задания"""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer(
            "❌ Выполнение задания отменено.\n"
            "Вы можете начать заново через раздел 'Задания'"
        )
    else:
        await message.answer("Нет активных действий для отмены")
