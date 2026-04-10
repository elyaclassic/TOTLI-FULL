"""FSM holatlar."""
from aiogram.fsm.state import State, StatesGroup


class CustomerEntryState(StatesGroup):
    waiting_currency = State()
    waiting_amount = State()
    waiting_rate = State()


class NewCustomerState(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_opening_balance_uzs = State()
    waiting_opening_balance_usd = State()


class ReportState(StatesGroup):
    choosing_type = State()
    choosing_period = State()
    choosing_output = State()
