import time
import json
import os
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
DB_FILE = "users.json"

def load_db():
    """Загружает базу данных из файла."""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                # json хранит ключи как строки, переводим обратно в int (user_id)
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки базы: {e}")
    return {}

def save_db():
    """Сохраняет текущую базу данных в файл."""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(user_db, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Ошибка сохранения базы: {e}")

# Инициализируем базу данных из файла при запуске
user_db = load_db()
active_bets = []          # Список текущих ставок
cooldown_start_time = 0   # Время первой ставки
ROULETTE_COOLDOWN = 7     # Кулдаун в секундах

def get_user_data(user_id: int):
    """Возвращает данные пользователя или создает новые."""
    if user_id not in user_db:
        user_db[user_id] = {
            "balance": 1000,
            "bank": 0,
            "last_bonus": 0
        }
        save_db()  # Сохраняем нового пользователя
    return user_db[user_id]

def update_user_data(user_id: int, data: dict):
    """Обновляет данные пользователя и сразу сохраняет в файл."""
    user_db[user_id] = data
    save_db()  # Автоматически сохраняем изменения на диск

# =========================================================
# 2. ОСНОВНЫЕ КОМАНДЫ ( /start, /deposit, /withdraw, /calc )
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

    # Замораживаем ставку с баланса
    user_data["balance"] -= bet
    update_user_data(user.id, user_data)

    is_first_bet = len(active_bets) == 0

    # Если это самая первая ставка в раунде — заново засекаем 7 секунд
    if is_first_bet:
        cooldown_start_time = time.time()

    # Сохраняем ставку в общий стол
    active_bets.append({
        "user_id": user.id,
        "name": user.first_name,
        "bet": bet,
        "choice": choice
    })

    if is_first_bet:
        await update.message.reply_text(
            f"✅ <b>{user.first_name}</b> сделал(а) первую ставку <b>{bet} Valor</b> на <b>{choice.upper()}</b>!\n"
            f"⏳ Кулдаун <b>7 секунд</b> начался!\n📊 Всего ставок: <b>{len(active_bets)}</b>.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"✅ <b>{user.first_name}</b> добавил(а) ставку <b>{bet} Valor</b> на <b>{choice.upper()}</b>!\n"
            f"📊 Всего ставок: <b>{len(active_bets)}</b>.",
            parse_mode="HTML"
        )


async def spin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск рулетки по команде пользователя с проверкой КД."""
    global active_bets, cooldown_start_time

    if not active_bets:
        await update.message.reply_text("❌ Ставок еще нет! Сделайте ставку (например: <code>100 ч</code>)", parse_mode="HTML")
        return

    # Проверяем, прошло ли 7 секунд с момента первой ставки
    elapsed = time.time() - cooldown_start_time
    if elapsed < ROULETTE_COOLDOWN:
        remaining = int(ROULETTE_COOLDOWN - elapsed) + 1
        await update.message.reply_text(
            f"❌ <b>Слишком рано!</b> До запуска осталось <b>{remaining} сек.</b>",
            parse_mode="HTML"
        )
        return

    # Выпадение случайного числа
    winning_number = random.randint(0, 36)
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    
    if winning_number == 0:
        winning_color = "зеленое 🟢"
    elif winning_number in red_numbers:
        winning_color = "красное 🔴"
    else:
        winning_color = "черное ⬛"

    results_summary = []
# Расчет результатов для каждого игрока
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

    # Очищаем пул ставок после вращения
    active_bets.clear()
    cooldown_start_time = 0

    res_text = "\n".join(results_summary)
    await update.message.reply_text(
        f"🎰 <b>Рулетка закрутилась!</b>\n\n"
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

    user_id = update.effective_user.id
    user = get_user_data(user_id)
    raw_text = update.message.text.strip()
    text = raw_text.lower()

    # --- 1. ТРИГГЕР ДЛЯ ЗАПУСКА РУЛЕТКИ (го, крутить, spin, погнали) ---
    if text in ["го", "крутить", "погнали", "пуск"]:
        await spin_command(update, context)
        return

    # --- 2. ТРИГГЕР ДЛЯ КОШЕЛЬКА (буква "к") ---
    if text == "к":
        msg = f"💳 <b>Ваш кошелек:</b>\n• На руках: {user['balance']} Valor\n• В банке: {user['bank']} Valor"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # --- 3. ТРИГГЕРЫ ДЛЯ БАНКА (б 1000, б +150, б -400) ---
    parts = text.split()

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

    # --- 4. ТРИГГЕРЫ ДЛЯ СТАВОК В РУЛЕТКУ (500 ч, 100 к, 1000 7) ---
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
        msg = f"💳 <b>Ваш кошелек:</b>\n• На руках: {user['balance']} Valor\n• В банке: {user['bank']} Valor"
        await update.message.reply_text(msg, parse_mode="HTML")

    elif raw_text in ["🎁 Подарок", "🎁 Бонус (1000 Valor)"]:
        now = time.time()
        cooldown = 1 * 3600  # 1 час
        if now - user.get("last_bonus", 0) >= cooldown:
            user["balance"] += 1000
            user["last_bonus"] = now
            update_user_data(user_id, user)
            await update.message.reply_text("🎉 Вы получили ваш Подарок: 1000 Valor!")
        else:
            remaining = int(cooldown - (now - user["last_bonus"]))
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
            "🏦 <b>Управление банком:</b>\n\n"
            "• <code>б 1000</code> — положить в банк\n"
            "• <code>б -1000</code> — снять из банка",
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

BOT_TOKEN = "8869539861:AAEhpB4TBy7g0VvplY2ST0e-XuBIb1mtWKc"  # 👈 Вставь токен от BotFather!

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("deposit", deposit_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("roulette", roulette_bet_command))
    app.add_handler(CommandHandler("spin", spin_command))
    app.add_handler(CommandHandler("calc", calc_command))

    # Регистрация обработчика текста
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот успешно запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()