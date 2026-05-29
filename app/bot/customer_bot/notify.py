from app.bot.customer_bot.queries import fmt_money


def msg_order_confirmed(order):
    return (
        f"✅ Buyurtmangiz qabul qilindi\n"
        f"№ {order.number}\n"
        f"Summa: <b>{fmt_money(order.total)}</b> so'm"
    )


def msg_order_dispatched(order):
    return (
        f"🚚 Buyurtmangiz yo'lda\n"
        f"№ {order.number}\n"
        f"Tez orada yetkaziladi."
    )


def msg_order_delivered(order, balance):
    return (
        f"📦 Buyurtma yetkazildi\n"
        f"№ {order.number}\n"
        f"To'langan: <b>{fmt_money(order.paid)}</b> so'm\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )


def msg_agent_payment(agent_code, agent_name, amount, balance):
    return (
        f"💰 To'lov qabul qilindi\n"
        f"Agent {agent_code} {agent_name} <b>{fmt_money(amount)}</b> so'm to'lov qabul qildi.\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )
