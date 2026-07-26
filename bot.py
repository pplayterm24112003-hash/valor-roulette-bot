import time
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# =========================================================
# 1. БАЗА ДАННЫХ (В памяти)
# =========================================================
user_db = {}

def get_user_data(user_id: int):
    """Возвращает данные пользователя или создает новые."""
    if user_id not in user_db:
        user_db[user_id] = {
            "balance": 1000,
            "bank": 0,
            "last_bonus": 0
        }
    return user_db[user_id]

def update_user_data(user_id: int, data: dict):
    """Обновляет данные пользователя."""
    user_db[user_id] = data


# =========================================================
# 2. ОСНОВНЫЕ КОМАНДЫ ( /start, /deposit, /withdraw, /roulette, /calc )
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и выдача клавиатуры с кнопками."""
    keyboard = [
        ["💰 Кошелек", "🎁 Ежечасовой подарок"],
        ["🎰 Рулетка", "🏦 Банк"],
        ["🧮 Калькулятор"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_msg = (
        "👋 <b>Добро пожаловать в игрового бота Valor!</b>\n\n"
        "Используй меню ниже или быстрые команды для игры и управления балансом!"
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="HTML")


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Положить средства в банк."""
    user_id = update.effective_user.id
    user = get_user_data(user_id)

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Укажите сумму! Пример: <code>/deposit 500</code> или <code>б 500</code>", parse_mode="HTML")
        return

    amount = int(context.args[0])
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0!")
        return

    if user["balance"] < amount:
        await update.message.reply_text(f"❌ Недостаточно средств на руках! Ваш баланс: {user['balance']} Valor")
        return

    user["balance"] -= amount
    user["bank"] += amount
    update_user_data(user_id, user)

    await update.message.reply_text(
        f"🏦 <b>Депозит успешный!</b>\n"
        f"• Переведено в банк: {amount} Valor\n"
        f"• На руках: {user['balance']} Valor\n"
        f"• В банке: {user['bank']} Valor",
        parse_mode="HTML"
    )


async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Снять средства из банка."""
    user_id = update.effective_user.id
    user = get_user_data(user_id)

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Укажите сумму! Пример: <code>/withdraw 500</code> или <code>б -500</code>", parse_mode="HTML")
        return

    amount = int(context.args[0])
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0!")
        return

    if user["bank"] < amount:
        await update.message.reply_text(f"❌ Недостаточно средств в банке! В банке лежит: {user['bank']} Valor")
        return

    user["bank"] -= amount
    user["balance"] += amount
    update_user_data(user_id, user)

    await update.message.reply_text(
        f"💸 <b>Снятие успешно!</b>\n"
        f"• Переведено на руки: {amount} Valor\n"
        f"• На руках: {user['balance']} Valor\n"
        f"• В банке: {user['bank']} Valor",
        parse_mode="HTML"
    )


async def roulette_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Игра в рулетку."""
    import random

    user_id = update.effective_user.id
    user = get_user_data(user_id)
    if len(context.args) < 2 or not context.args[0].isdigit():
          await update.message.reply_text("❌ Ошибка! Формат: <code>/roulette 100 красное</code> или <code>100 к</code>", parse_mode="HTML")
          return

    bet = int(context.args[0])
    choice = context.args[1].lower()

    if bet <= 0:
        await update.message.reply_text("❌ Ставка должна быть больше 0!")
        return

    if user["balance"] < bet:
        await update.message.reply_text(f"❌ Недостаточно средств! На руках: {user['balance']} Valor")
        return

    # Выпадение случайного числа (0..36)
    winning_number = random.randint(0, 36)
    
    # Определение цвета
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    if winning_number == 0:
        winning_color = "зеленое"
    elif winning_number in red_numbers:
        winning_color = "красное"
    else:
        winning_color = "черное"

    # Проверка выигрыша
    won = False
    multiplier = 2

    if choice in ["красное", "черное"] and choice == winning_color:
        won = True
        multiplier = 2
    elif choice.isdigit() and int(choice) == winning_number:
        won = True
        multiplier = 36

    if won:
        win_amount = bet * multiplier
        user["balance"] += (win_amount - bet)
        result_text = f"🎉 <b>Вы выиграли {win_amount} Valor!</b>"
    else:
        user["balance"] -= bet
        result_text = f"🪦 <b>Вы проиграли {bet} Valor.</b>"

    update_user_data(user_id, user)

    await update.message.reply_text(
        f"🎰 <b>Рулетка крутится...</b>\n\n"
        f"🎯 Выпало: <b>{winning_number} ({winning_color.upper()})</b>\n"
        f"{result_text}\n"
        f"💳 Ваш кошелек: {user['balance']} Valor",
        parse_mode="HTML"
    )


async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Калькулятор."""
    if not context.args:
        await update.message.reply_text("❌ Напишите выражение! Пример: <code>/calc 25 * 4 + 10</code>", parse_mode="HTML")
        return

    expression = "".join(context.args)
    try:
        # Простая фильтрация от опасного кода
        allowed = "0123456789+-*/(). "
        if not all(c in allowed for c in expression):
            raise ValueError()
        
        result = eval(expression)
        await update.message.reply_text(f"🧮 <b>Результат:</b> {expression} = <b>{result}</b>", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("❌ Некорректное математическое выражение!")


# =========================================================
# 3. ОБРАБОТЧИК СООБЩЕНИЙ И ТРИГГЕРОВ (HANDLE_MESSAGE)
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    user = get_user_data(user_id)
    raw_text = update.message.text.strip()
    text = raw_text.lower()

    # --- 1. ТРИГГЕР ДЛЯ КОШЕЛЬКА (Короткая буква "к") ---
    if text == "к":
        msg = f"💳 <b>Ваш кошелек:</b>\n• На руках: {user['balance']} Valor\n• В банке: {user['bank']} Valor"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # --- 2. ТРИГГЕРЫ ДЛЯ БАНКА (б 1000, б +150, б -400, банк 500) ---
    parts = text.split()

    if len(parts) == 2 and parts[0] in ["б", "банк"]:
        val_str = parts[1]
        
        # Пополнение банка (например: б 1000, б +150)
        if val_str.startswith("+") or val_str.isdigit():
            amount_str = val_str.replace("+", "")
            if amount_str.isdigit():
                context.args = [amount_str]
                await deposit_command(update, context)
                return

        # Снятие из банка (например: б -400, банк -200)
        elif val_str.startswith("-"):
            amount_str = val_str.replace("-", "")
            if amount_str.isdigit():
                context.args = [amount_str]
                await withdraw_command(update, context)
                return
# --- 3. ТРИГГЕРЫ ДЛЯ РУЛЕТКИ (500 ч, 100 к, 1000 7) ---
    if len(parts) == 2 and parts[0].isdigit():
        bet = int(parts[0])
        raw_choice = parts[1]

        choice = None
        if raw_choice in ["ч", "чёрное", "черное", "black"]:
            choice = "черное"
        elif raw_choice in ["к", "красное", "red"]:
            choice = "красное"
        elif raw_choice.isdigit() and 0 <= int(raw_choice) <= 36:
            choice = raw_choice

        if choice:
            context.args = [str(bet), choice]
            await roulette_command(update, context)
            return

    # --- 4. ОБРАБОТКА КНОПОК МЕНЮ И ДРУГОГО ТЕКСТА ---

    if raw_text in ["💰 Кошелек", "💰 Баланс"]:
        msg = f"💳 <b>Ваш кошелек:</b>\n• На руках: {user['balance']} Valor\n• В банке: {user['bank']} Valor"
        await update.message.reply_text(msg, parse_mode="HTML")

    elif raw_text in ["🎁 Ежечасовой подарок", "🎁 Бонус (1000 Valor)"]:
        now = time.time()
        cooldown = 1 * 3600  # 1 час (3600 секунд)
        
        if now - user.get("last_bonus", 0) >= cooldown:
            user["balance"] += 1000
            user["last_bonus"] = now
            update_user_data(user_id, user)
            await update.message.reply_text("🎉 Вы получили ваш ежечасовой подарок: 1000 Valor!")
        else:
            remaining = int(cooldown - (now - user["last_bonus"]))
            mins, secs = divmod(remaining, 60)
            await update.message.reply_text(f"⏳ Ежечасовой подарок пока недоступен!\nПодождите еще {mins} мин. {secs} сек.")

    elif raw_text.startswith("🎰 Рулетка"):
        await update.message.reply_text(
            "🎰 <b>Как играть в рулетку:</b>\n\n"
            "Напиши сумму и цвет через пробел:\n"
            "• <code>500 ч</code> — ставка 500 на чёрное\n"
            "• <code>500 к</code> — ставка 500 на красное\n"
            "• <code>1000 7</code> — ставка 1000 на число 7",
            parse_mode="HTML"
        )

    elif raw_text.startswith("🏦 Банк"):
        await update.message.reply_text(
            "🏦 <b>Управление банком:</b>\n\n"
            "<b>Быстрые команды (на любую сумму):</b>\n"
            "• <code>б 1000</code> или <code>б +1000</code> — положить в банк\n"
            "• <code>б -400</code> — снять из банка\n\n"
            "<b>Полные команды:</b>\n"
            "• /deposit 500\n"
            "• /withdraw 500",
            parse_mode="HTML"
        )

    elif raw_text.startswith("🧮 Калькулятор"):
        await update.message.reply_text(
            "Отправь математическое выражение для расчета:\n"
            "Пример: /calc 25 * 4 + 10"
        )


# =========================================================
# 4. ЗАПУСК БОТА
# =========================================================

BOT_TOKEN = "8869539861:AAEhpB4TBy7g0VvplY2ST0e-XuBIb1mtWKc"  # 👈 Вставь сюда токен от BotFather!

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("deposit", deposit_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("roulette", roulette_command))
    app.add_handler(CommandHandler("calc", calc_command))

    # Регистрация обработчика текста
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот успешно запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()