"""FSM holatlar."""
from aiogram.fsm.state import State, StatesGroup


class CustomerEntryState(StatesGroup):
    waiting_amount = State()


class NewCustomerState(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_opening_balance = State()


class ReportState(StatesGroup):
    choosing_type = State()
    choosing_period = State()
    choosing_output = State()
