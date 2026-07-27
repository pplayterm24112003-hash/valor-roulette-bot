import time
import sqlite3
import logging
import random
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
# 1. БАЗА ДАННЫХ (С сохранением в файл users.json)
# =========================================================

DB_NAME = "database.db"  # Если на Render с Persistent Disk, укажите путь: "/var/data/database.db"

def init_db():
    """Создает таблицу пользователей, если ее еще нет."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 1000,
            bank INTEGER DEFAULT 0,
            last_bonus REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user_data(user_id: int) -> dict:
    """Получает данные пользователя или регистрирует нового с балансом 1000."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance, bank, last_bonus FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        # Новый игрок — выдаем стартовый баланс
        cursor.execute(
            "INSERT INTO users (user_id, balance, bank, last_bonus) VALUES (?, ?, ?, ?)",
            (user_id, 1000, 0, 0)
        )
        conn.commit()
        balance, bank, last_bonus = 1000, 0, 0
    else:
        balance, bank, last_bonus = row
        
    conn.close()
    return {
        "balance": balance,
        "bank": bank,
        "last_bonus": last_bonus
    }

def update_user_data(user_id: int, data: dict):
    """Обновляет баланс и данные пользователя в базе данных."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users 
        SET balance = ?, bank = ?, last_bonus = ?
        WHERE user_id = ?
    """, (data["balance"], data["bank"], data["last_bonus"], user_id))
    
    conn.commit()
    conn.close()

# =========================================================
# 2. ОСНОВНЫЕ КОМАНДЫ ( /start, /deposit, /withdraw, /give, /calc )
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и выдача клавиатуры с кнопками."""
    keyboard = [
        ["💰 Кошелек", "🎁 Подарок"],
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


async def give_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Передача Valor другому игроку при ответе на его сообщение."""
    sender = update.effective_user
    reply_msg = update.message.reply_to_message

    # 1. Проверяем, сделан ли ответ на сообщение
    if not reply_msg:
        await update.message.reply_text("❌ Чтобы передать Valor, ответьте на сообщение игрока комендой <code>о <сумма></code>!", parse_mode="HTML")
        return

    target_user = reply_msg.from_user

    # 2. Нельзя передавать самому себе или ботам
    if target_user.id == sender.id:
        await update.message.reply_text("❌ Вы не можете передать Valor самому себе!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ Нельзя передавать Valor ботам!")
        return

    # 3. Проверяем сумму
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Укажите сумму для передачи! Пример: <code>о 200</code>", parse_mode="HTML")
        return

    amount = int(context.args[0])
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0!")
        return

    sender_data = get_user_data(sender.id)
    target_data = get_user_data(target_user.id)

    if sender_data["balance"] < amount:
        await update.message.reply_text(f"❌ Недостаточно средств на руках! Ваш баланс: {sender_data['balance']} Valor")
        return

    # 4. Производим транзакцию
    sender_data["balance"] -= amount
    target_data["balance"] += amount

    update_user_data(sender.id, sender_data)
    update_user_data(target_user.id, target_data)

    # Красиво тегаем обоих игроков
    sender_mention = f'<a href="tg://user?id={sender.id}">{sender.first_name}</a>'
    target_mention = f'<a href="tg://user?id={target_user.id}">{target_user.first_name}</a>'

    await update.message.reply_text(
        f"🤝 {sender_mention} передал(а) <b>{amount} Valor</b> игроку {target_mention}!",
        parse_mode="HTML"
    )


async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Калькулятор."""
    if not context.args:
        await update.message.reply_text("❌ Напишите выражение! Пример: <code>/calc 25 * 4 + 10</code>", parse_mode="HTML")
        return

    expression = "".join(context.args)
    try:
        allowed = "0123456789+-*/(). "
        if not all(c in allowed for c in expression):
            raise ValueError()
        
        result = eval(expression)
        await update.message.reply_text(f"🧮 <b>Результат:</b> {expression} = <b>{result}</b>", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("❌ Некорректное математическое выражение!")


# =========================================================
# 3. МНОГОПОЛЬЗОВАТЕЛЬСКАЯ РУЛЕТКА (Прием ставок + Ручной запуск)
# =========================================================

async def roulette_bet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сделать ставку в общий стол."""
    global active_bets, cooldown_start_time
    user = update.effective_user
    user_data = get_user_data(user.id)

    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("❌ Формат ставки: <code>500 ч</code> или <code>/roulette 100 красное</code>", parse_mode="HTML")
        return

    bet = int(context.args[0])
    choice = context.args[1].lower()
    if bet <= 0:
        await update.message.reply_text("❌ Ставка должна быть больше 0!")
        return

    if user_data["balance"] < bet:
        await update.message.reply_text(f"❌ Недостаточно средств! На руках: {user_data['balance']} Valor")
        return

    user_data["balance"] -= bet
    update_user_data(user.id, user_data)

    is_first_bet = len(active_bets) == 0

    if is_first_bet:
        cooldown_start_time = time.time()

    active_bets.append({
        "user_id": user.id,
        "name": user.first_name,
        "bet": bet,
        "choice": choice
    })

    if is_first_bet:
        await update.message.reply_text(
            f"✅ <b>{user.first_name}</b> ставит ставку <b>{bet} Valor</b> на <b>{choice.upper()}</b>!\n"
            f"📊 Всего ставок: <b>{len(active_bets)}</b>.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"✅ <b>{user.first_name}</b> ставит <b>{bet} Valor</b> на <b>{choice.upper()}</b>!\n"
            f"📊 Всего ставок: <b>{len(active_bets)}</b>.",
            parse_mode="HTML"
        )


async def spin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск рулетки по команде пользователя с проверкой КД."""
    global active_bets, cooldown_start_time
    
    # Константы и состояние рулетки
    ROULETTE_COOLDOWN = 7  # В секундах
    active_bets = []
    cooldown_start_time = 0

    if not active_bets:
        await update.message.reply_text("❌ Ставок еще нет! Сделайте ставку (например: <code>100 ч</code>)", parse_mode="HTML")
        return

    elapsed = time.time() - cooldown_start_time
    if elapsed < ROULETTE_COOLDOWN:
        remaining = int(ROULETTE_COOLDOWN - elapsed) + 1
        await update.message.reply_text(
            f"❌ <b>Слишком рано!</b> До запуска осталось <b>{remaining} сек.</b>",
            parse_mode="HTML"
        )
        return

    winning_number = random.randint(0, 36)
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    
    if winning_number == 0:
        winning_color = "зеленое 🟢"
    elif winning_number in red_numbers:
        winning_color = "красное 🔴"
    else:
        winning_color = "черное ⬛"

    results_summary = []

    for b in active_bets:
        u_id = b["user_id"]
        u_data = get_user_data(u_id)
        bet = b["bet"]
        choice = b["choice"]
        name = b["name"]

        won = False
        multiplier = 2

        if choice in ["красное", "черное"] and choice == winning_color.split()[0]:
            won = True
            multiplier = 2
        elif choice.isdigit() and int(choice) == winning_number:
            won = True
            multiplier = 36

        if won:
            win_amount = bet * multiplier
            u_data["balance"] += win_amount
            results_summary.append(f"🟢 <b>{name}</b>: +{win_amount - bet} Valor (Выигрыш!)")
        else:
            results_summary.append(f"🔴 <b>{name}</b>: -{bet} Valor (Проигрыш)")

        update_user_data(u_id, u_data)

    active_bets.clear()
    cooldown_start_time = 0

    res_text = "\n".join(results_summary)
    await update.message.reply_text(
        f"🎯 Выпало: <b>{winning_number} ({winning_color.upper()})</b>\n\n"
        f"<b>Результаты раунда:</b>\n{res_text}",
        parse_mode="HTML"
    )


# =========================================================
# 4. ОБРАБОТЧИК СООБЩЕНИЙ И ТРИГГЕРОВ (HANDLE_MESSAGE)
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_data = get_user_data(user.id)
    raw_text = update.message.text.strip()
    text = raw_text.lower()

    # --- 1. ТРИГГЕР ДЛЯ ЗАПУСКА РУЛЕТКИ ---
    if text in ["го", "крутить", "погнали", "пуск"]:
        await spin_command(update, context)
        return
# --- 2. ТРИГГЕР ДЛЯ КОШЕЛЬКА (буква "к") С ТЕГОМ ПОЛЬЗОВАТЕЛЯ ---
    if text == "к":
        user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
        msg = (
            f"💴 <b>Кошелек пользователя {user_mention}:</b>\n"
            f"• На руках: {user_data['balance']} Valor\n"
            f"• В банке: {user_data['bank']} Valor"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # --- 3. ТРИГГЕРЫ ДЛЯ БАНКА И ОБМЕНА ВАЛОРАМИ ---
    parts = text.split()

    # Быстрый триггер обмена: "о 200" (отдать 200 валоров в ответ на сообщение)
    if len(parts) == 2 and parts[0] in ["о", "отдать", "передать"]:
        amount_str = parts[1]
        if amount_str.isdigit():
            context.args = [amount_str]
            await give_command(update, context)
            return

    # Триггеры для банка
    if len(parts) == 2 and parts[0] in ["б", "банк"]:
        val_str = parts[1]
        
        if val_str.startswith("+") or val_str.isdigit():
            amount_str = val_str.replace("+", "")
            if amount_str.isdigit():
                context.args = [amount_str]
                await deposit_command(update, context)
                return

        elif val_str.startswith("-"):
            amount_str = val_str.replace("-", "")
            if amount_str.isdigit():
                context.args = [amount_str]
                await withdraw_command(update, context)
                return

    # --- 4. ТРИГГЕРЫ ДЛЯ СТАВОК В РУЛЕТКУ ---
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
            await roulette_bet_command(update, context)
            return

    # --- 5. ОБРАБОТКА КНОПОК МЕНЮ ---

    if raw_text in ["💰 Кошелек", "💰 Баланс"]:
        user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
        msg = (
            f"💴 <b>Кошелек пользователя {user_mention}:</b>\n"
            f"• На руках: {user_data['balance']} Valor\n"
            f"• В банке: {user_data['bank']} Valor"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    elif raw_text in ["🎁 Подарок", "🎁 Бонус (1000 Valor)"]:
        now = time.time()
        cooldown = 1 * 3600  # 1 час
        
        if now - user_data.get("last_bonus", 0) >= cooldown:
            user_data["balance"] += 1000
            user_data["last_bonus"] = now
            update_user_data(user.id, user_data)
            await update.message.reply_text("🎉 Вы получили ваш ежечасовой подарок: 1000 Valor!")
        else:
            remaining = int(cooldown - (now - user_data["last_bonus"]))
            mins, secs = divmod(remaining, 60)
            await update.message.reply_text(f"⏳ Подарок пока недоступен!\nПодождите еще {mins} мин. {secs} сек.")

    elif raw_text.startswith("🎰 Рулетка"):
        await update.message.reply_text(
            "🎰 <b>Общая рулетка:</b>\n\n"
            "<b>1. Сделайте ставку:</b>\n"
            "• <code>500 ч</code> — 500 на чёрное\n"
            "• <code>500 к</code> — 500 на красное\n\n"
            "<b>2. Запустите рулетку:</b>\n"
            "• Напишите <code>го</code> (доступно через 7 секунд после 1-й ставки)",
            parse_mode="HTML"
        )

    elif raw_text.startswith("🏦 Банк"):
        await update.message.reply_text(
            "🏦 <b>Управление банком и переводами:</b>\n\n"
            "<b>Банк:</b>\n"
"• <code>б 1000</code> — положить в банк\n"
            "• <code>б -400</code> — снять из банка\n\n"
            "<b>Передать Valor игроку:</b>\n"
            "• Напиши <code>о 200</code> <b>в ответ на сообщение</b> игрока!",
            parse_mode="HTML"
        )

    elif raw_text.startswith("🧮 Калькулятор"):
        await update.message.reply_text(
            "Отправь математическое выражение для расчета:\n"
            "Пример: /calc 25 * 4 + 10"
        )


# =========================================================
# 5. ЗАПУСК БОТА
# =========================================================

BOT_TOKEN = "8869539861:AAE8vdxDT3y6kZU-kSHTFRl7TL-nBMlsG5I"  # 👈 Вставь токен от BotFather!

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("deposit", deposit_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("give", give_command))
    app.add_handler(CommandHandler("roulette", roulette_bet_command))
    app.add_handler(CommandHandler("spin", spin_command))
    app.add_handler(CommandHandler("calc", calc_command))

    # Регистрация обработчика текста
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот успешно запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()