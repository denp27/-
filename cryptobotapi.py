from aiogram.fsm.state import State, StatesGroup


class DepositState(StatesGroup):
    wait_amount = State()


class UserState(StatesGroup):
    wait_username = State()
    wait_stars = State()
    wait_username_premium = State()
    wait_username_ton = State()
    wait_tons = State()
    wait_rent_duration = State()
    wait_bind = State()
    wait_promo_code = State()
    wait_rent_num_duration = State()
    wait_bind_number = State()
    wait_gift_username = State()


class AdminState(StatesGroup):
    wait_user_id = State()
    wait_balance_add = State()
    wait_balance_remove = State()
    wait_new_commission = State()
    wait_new_referral_percent = State()
    wait_mailing_text = State()
    wait_channel_id = State()
    wait_channel_url = State()
    wait_channel_name = State()
    wait_delete_promo = State()
    wait_create_promo = State()
    wait_ban_reason = State()
    wait_withdraw_approve_check = State()
    wait_withdraw_reject_reason = State()
    wait_gift_data = State()


class CheckState(StatesGroup):
    wait_stars_amount = State()
    wait_ton_amount = State()


class FranchiseState(StatesGroup):
    wait_token = State()
    wait_project_name = State()
    wait_markup = State()
    wait_edit_name = State()
    wait_edit_markup = State()
    wait_photo = State()
    wait_edit_support_url = State()
    wait_channel_id = State()
    wait_channel_url = State()
    wait_channel_name = State()
    wait_mailing_text = State()
