import logging
import random
import time
import sqlite3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- РАБОТА С БАЗОЙ ДАННЫХ (SQLite) ---

def init_db():
    """Создание таблицы пользователей, если её еще нет"""
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 1000,
            bank INTEGER DEFAULT 0,
            last_bonus REAL DEFAULT 0,
            last_deposit_update REAL DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    """Получение данных пользователя из БД или создание нового"""
    now = time.time()
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('SELECT balance, bank, last_bonus, last_deposit_update FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()

    if row is None:
        # Новый пользователь
        balance, bank, last_bonus, last_deposit_update = 1000, 0, 0, now
        cursor.execute(
            'INSERT INTO users (user_id, balance, bank, last_bonus, last_deposit_update) VALUES (?, ?, ?, ?, ?)',
            (user_id, balance, bank, last_bonus, last_deposit_update)
        )
        conn.commit()
    else:
        balance, bank, last_bonus, last_deposit_update = row
        # Проверка процентов в банке (1% каждые 6 часов = 21600 сек)
        time_passed = now - last_deposit_update
        if time_passed >= 21600 and bank > 0:
            periods = int(time_passed // 21600)
            for _ in range(periods):
                bank = int(bank * 1.01)
            last_deposit_update += periods * 21600
            cursor.execute(
                'UPDATE users SET bank = ?, last_deposit_update = ? WHERE user_id = ?',
                (bank, last_deposit_update, user_id)
            )
            conn.commit()

    conn.close()
    return {
        "balance": balance,
        "bank": bank,
        "last_bonus": last_bonus,
        "last_deposit_update": last_deposit_update
    }

def update_user_data(user_id, user_data):
    """Сохранение изменений баланса пользователя в БД"""
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET balance = ?, bank = ?, last_bonus = ?, last_deposit_update = ? 
        WHERE user_id = ?
    ''', (user_data["balance"], user_data["bank"], user_data["last_bonus"], user_data["last_deposit_update"], user_id))
    conn.commit()
    conn.close()


# --- КЛАВИАТУРА И ХЭНДЛЕРЫ ---

main_keyboard = ReplyKeyboardMarkup(
    [["🎰 Рулетка", "💰 Баланс"], ["🎁 Бонус (1000 Valor)", "🏦 Банк"], ["🧮 Калькулятор"]],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user_data(user_id)
    await update.message.reply_text(
        "Привет! Добро пожаловать в бота! Выбери действие на клавиатуре ниже:",
        reply_markup=main_keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    text = update.message.text

    if text == "💰 Баланс":
        msg = f"💳 Ваш счет:\n• На руках: {user['balance']} Valor\n• В банке: {user['bank']} Valor"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "🎁 Бонус (1000 Valor)":
        now = time.time()
        cooldown = 2 * 3600
        if now - user["last_bonus"] >= cooldown:
            user["balance"] += 1000
            user["last_bonus"] = now
            update_user_data(user_id, user)  # Сохраняем в БД
            await update.message.reply_text("🎉 Вы получили 1000 Valor! Возвращайтесь через 2 часа.")
        else:
            remaining = int(cooldown - (now - user["last_bonus"]))
            mins, secs = divmod(remaining, 60)
            hours, mins = divmod(mins, 60)
            await update.message.reply_text(f"⏳ Бонус пока недоступен! Подождите {hours}ч {mins}м {secs}с.")

    elif text.startswith("🎰 Рулетка"):
        await update.message.reply_text(
            "Чтобы сыграть в рулетку, напиши команду:\n/roulette [ставка] [красное/черное/число 0-36]\n\n"
            "Пример: /roulette 100 красное или /roulette 50 7",
            parse_mode="Markdown"
        )

    elif text.startswith("🏦 Банк"):
        await update.message.reply_text(
            "В банке твои деньги растут на 1% каждые 6 часов!\n\n"
            "Команды для банка:\n"
            "/deposit [сумма] — положить на депозит\n"
            "/withdraw [сумма] — снять с депозита",
            parse_mode="Markdown"
        )

    elif text.startswith("🧮 Калькулятор"):
        await update.message.reply_text(
            "Отправь математическое выражение для расчета:\n"
            "Пример: /calc 25 * 4 + 10",
            parse_mode="Markdown"
        )

async def roulette_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)

    if len(context.args) < 2:
        await update.message.reply_text("Использование: /roulette [ставка] [красное/черное/0-36]", parse_mode="Markdown")
        return

    try:
        bet = int(context.args[0])
        choice = context.args[1].lower()
    except ValueError:
        await update.message.reply_text("Ставка должна быть числом!")
        return

    if bet <= 0 or bet > user["balance"]:
        await update.message.reply_text("Недостаточно средств на руках или неверная ставка!")
        return

    number = random.randint(0, 36)
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    
    if number == 0:
        color = "зеленое"
    elif number in red_numbers:
        color = "красное"
    else:
        color = "черное"

    user["balance"] -= bet
    win = False
    payout = 0

    if choice in ["красное", "черное"]:
        if choice == color:
            win = True
            payout = bet * 2
    elif choice.isdigit():
        if int(choice) == number:
            win = True
            payout = bet * 36

    if win:
        user["balance"] += payout
        res_text = f"🎰 Выпало: {number} ({color})\n🎉 Поздравляем! Вы выиграли {payout} Valor!"
    else:
        res_text = f"🎰 Выпало: {number} ({color})\n❌ К сожалению, вы проиграли {bet} Valor."

    update_user_data(user_id, user)  # Сохраняем баланс после игры!
    await update.message.reply_text(res_text, parse_mode="Markdown")

async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    try:
        amount = int(context.args[0])
        if amount > 0 and user["balance"] >= amount:
            user["balance"] -= amount
            user["bank"] += amount
            update_user_data(user_id, user)  # Сохраняем в БД
            await update.message.reply_text(f"Успешно! Вы положили {amount} Valor в банк.")
        else:
            await update.message.reply_text("Недостаточно средств на балансе!")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /deposit [сумма]", parse_mode="Markdown")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    try:
        amount = int(context.args[0])
        if amount > 0 and user["bank"] >= amount:
            user["bank"] -= amount
            user["balance"] += amount
            update_user_data(user_id, user)  # Сохраняем в БД
            await update.message.reply_text(f"Успешно! Вы сняли {amount} Valor из банка.")
        else:
            await update.message.reply_text("Недостаточно средств в банке!")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /withdraw [сумма]", parse_mode="Markdown")

async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expression = " ".join(context.args)
    if not expression:
        await update.message.reply_text("Введите выражение. Пример: /calc (10 + 5) * 2", parse_mode="Markdown")
        return
    
    allowed = "0123456789+-*/(). "
    if any(char not in allowed for char in expression):
        await update.message.reply_text("Ошибка: Разрешены только цифры и знаки +, -, *, /, ()")
        return

    try:
        result = eval(expression)
        await update.message.reply_text(f"🧮 Результат: {result}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Ошибка при вычислении выражения!")

if __name__ == '__main__':
    # ВСТАВЬ СВОЙ ТОКЕН СЮДА 👇
    TOKEN = "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"
    
    # Инициализация базы данных
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("roulette", roulette_command))
    app.add_handler(CommandHandler("deposit", deposit_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("calc", calc_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот с базой данных успешно запущен!")
    app.run_polling()