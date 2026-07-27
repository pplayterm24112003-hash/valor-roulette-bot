import logging
from multiprocessing import context
import random
import sqlite3
import time
from tracemalloc import start
from turtle import update
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================================================
# ⚙️ 1. НАСТРОЙКИ ДОНАТА (НАСТРАИВАЙ РАСЦЕНКИ ЗДЕСЬ)
# =========================================================
DONATE_PACKAGES = {
    "pack_5": {
        "title": "2 500 Valor",
        "description": "Пакет «Новичок»",
        "stars": 5,
        "valor": 2500,
    },
    "pack_15": {
        "title": "8 500 Valor",
        "description": "Пакет «Игрок» (+13% бонусом)",
        "stars": 15,
        "valor": 8500,
    },
    "pack_35": {
        "title": "22 000 Valor",
        "description": "Пакет «Хайроллер» (+25% бонусом)",
        "stars": 35,
        "valor": 22000,
    },
    "pack_75": {
        "title": "50 000 Valor",
        "description": "Пакет «Магнат» (+33% бонусом)",
        "stars": 75,
        "valor": 50000,
    },
    "pack_150": {
        "title": "115 000 Valor",
        "description": "Пакет «Кит» (Максимальная выгода 💥)",
        "stars": 150,
        "valor": 115000,
    },
}

# =========================================================
# 2. БАЗА ДАННЫХ SQLITE
# =========================================================
DB_NAME = "database.db"


def init_db():
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 1000,
            bank INTEGER DEFAULT 0,
            last_bonus REAL DEFAULT 0,
            last_bank_interest REAL DEFAULT 0
        )
    """)
  conn.commit()
  conn.close()


def get_user_data(user_id: int) -> dict:
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT balance, bank, last_bonus, last_bank_interest FROM users WHERE"
      " user_id = ?",
      (user_id,),
  )
  row = cursor.fetchone()

  if row is None:
    now = time.time()
    cursor.execute(
        "INSERT INTO users (user_id, balance, bank, last_bonus,"
        " last_bank_interest) VALUES (?, ?, ?, ?, ?)",
        (user_id, 1000, 0, 0, now),
    )
    conn.commit()
    balance, bank, last_bonus, last_bank_interest = 1000, 0, 0, now
  else:
    balance, bank, last_bonus, last_bank_interest = row

  conn.close()
  return {
      "balance": balance,
      "bank": bank,
      "last_bonus": last_bonus,
      "last_bank_interest": last_bank_interest,
  }


def update_user_data(user_id: int, data: dict):
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      """
        UPDATE users 
        SET balance = ?, bank = ?, last_bonus = ?, last_bank_interest = ?
        WHERE user_id = ?
    """,
      (
          data["balance"],
          data["bank"],
          data["last_bonus"],
          data["last_bank_interest"],
          user_id,
      ),
  )
  conn.commit()
  conn.close()


def apply_bank_interest(user_id: int, user_data: dict) -> tuple[dict, int]:
  """Начисляет 1% раз в 12 часов (43200 секунд)."""
  now = time.time()
  interval = 12 * 3600
  earned = 0

  if user_data["bank"] > 0 and (
      now - user_data.get("last_bank_interest", 0)
  ) >= interval:
    earned = int(user_data["bank"] * 0.01)
    if earned < 1:
      earned = 1
    user_data["bank"] += earned
    user_data["last_bank_interest"] = now
    update_user_data(user_id, user_data)

  return user_data, earned


# Глобальные переменные
active_bets = []
cooldown_start_time = 0
ROULETTE_COOLDOWN = 7
active_mines_games = {}
MINES_MULTIPLIERS = [
    1.09,
    1.18,
    1.29,
    1.42,
    1.57,
    1.74,
    2.01,
    2.35,
    2.5,
    2.73,
    3.15,
    3.75,
    4.5,
    6.0,
    10.0,
    17.0,
    25.0,
    35.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
    250.0,
    300.0,
    350.0,
    400.0,
    500.0,
]

# =========================================================
# 3. ОСНОВНЫЕ КОМАНДЫ
# =========================================================


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  keyboard = [
      ["💰 Кошелек", "🎁 Подарок"],
      ["🎰 Рулетка", "💣 Мины"],
      ["🏦 Банк", "💎 Магазин"],
  ]
  reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
  welcome_msg = (
      "👋 <b>Добро пожаловать в игрового бота Valor!</b>\n\n"
      "Используй меню ниже или быстрые команды для игры и управления балансом!"
  )
  await update.message.reply_text(
      welcome_msg, reply_markup=reply_markup, parse_mode="HTML"
  )


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  user = get_user_data(user_id)
  user, earned = apply_bank_interest(user_id, user)

  if not context.args or not context.args[0].isdigit():
    await update.message.reply_text(
        "❌ Укажите сумму! Пример: <code>б 500</code>", parse_mode="HTML"
    )
    return

  amount = int(context.args[0])
  if amount <= 0 or user["balance"] < amount:
    await update.message.reply_text(
        "❌ Некорректная сумма или недостаточно средств!"
    )
    return

  user["balance"] -= amount
  user["bank"] += amount
  update_user_data(user_id, user)

  msg = (
      f"🏦 <b>Депозит успешный!</b>\n• На руках: {user['balance']} Valor\n• В"
      f" банке: {user['bank']} Valor"
  )
  if earned > 0:
    msg += f"\n\n📈 <i>Вам начислено +{earned} Valor (1% за 12 часов)!</i>"
  await update.message.reply_text(msg, parse_mode="HTML")


async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  user = get_user_data(user_id)
  user, earned = apply_bank_interest(user_id, user)

  if not context.args or not context.args[0].isdigit():
    await update.message.reply_text(
        "❌ Укажите сумму! Пример: <code>б -500</code>", parse_mode="HTML"
    )
    return

  amount = int(context.args[0])
  if amount <= 0 or user["bank"] < amount:
    await update.message.reply_text(
        "❌ Недостаточно средств в банке!"
    )
    return

  user["bank"] -= amount
  user["balance"] += amount
  update_user_data(user_id, user)

  msg = (
      f"💸 <b>Снятие успешно!</b>\n• На руках: {user['balance']} Valor\n• В"
      f" банке: {user['bank']} Valor"
  )
  if earned > 0:
    msg += f"\n\n📈 <i>Вам начислено +{earned} Valor (1% за 12 часов)!</i>"
  await update.message.reply_text(msg, parse_mode="HTML")


async def give_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  sender = update.effective_user
  reply_msg = update.message.reply_to_message

  if not reply_msg:
    await update.message.reply_text(
        "❌ Ответьте на сообщение игрока командой <code>о <сумма></code>!",
        parse_mode="HTML",
    )
    return

  target_user = reply_msg.from_user
  if target_user.id == sender.id or target_user.is_bot:
    await update.message.reply_text(
        "❌ Нельзя передать Valor самому себе или ботам!"
    )
    return

  if not context.args or not context.args[0].isdigit():
    await update.message.reply_text(
        "❌ Укажите сумму! Пример: <code>о 200</code>", parse_mode="HTML"
    )
    return

  amount = int(context.args[0])
  sender_data = get_user_data(sender.id)
  target_data = get_user_data(target_user.id)

  if amount <= 0 or sender_data["balance"] < amount:
    await update.message.reply_text("❌ Недостаточно средств на руках!")
    return

  sender_data["balance"] -= amount
  target_data["balance"] += amount

  update_user_data(sender.id, sender_data)
  update_user_data(target_user.id, target_data)
  sender_mention = (
      f'<a href="tg://user?id={sender.id}">{sender.first_name}</a>'
  )
  target_mention = (
      f'<a href="tg://user?id={target_user.id}">{target_user.first_name}</a>'
  )

  await update.message.reply_text(
      f"🤝 {sender_mention} передал(а) <b>{amount} Valor</b> игроку"
      f" {target_mention}!",
      parse_mode="HTML",
  )


# =========================================================
# 4. МАГАЗИН ДОНАТА (TELEGRAM STARS)
# =========================================================


async def open_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
  keyboard = []
  for key, pack in DONATE_PACKAGES.items():
    button_text = f"🔹 {pack['title']} — {pack['stars']} ⭐"
    keyboard.append(
        [InlineKeyboardButton(button_text, callback_data=f"buy_{key}")]
    )

  reply_markup = InlineKeyboardMarkup(keyboard)
  shop_text = (
      "🛒 <b>Магазин Валоров (Telegram Stars)</b>\n\n"
      "Пополняйте баланс быстро и безопасно с помощью Stars!\n"
      "Выберите желаемый пакет:"
  )
  if update.message:
    await update.message.reply_text(
        shop_text, reply_markup=reply_markup, parse_mode="HTML"
    )
  elif update.callback_query:
    await update.callback_query.message.reply_text(
        shop_text, reply_markup=reply_markup, parse_mode="HTML"
    )


async def buy_package_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  await query.answer()

  pack_key = query.data.replace("buy_", "")
  pack = DONATE_PACKAGES.get(pack_key)

  if not pack:
    await query.message.reply_text("❌ Ошибка: пакет не найден.")
    return

  await context.bot.send_invoice(
      chat_id=query.from_user.id,
      title=f"Покупка {pack['title']}",
      description=pack["description"],
      payload=f"donate_{pack_key}",
      provider_token="",
      currency="XTR",
      prices=[LabeledPrice(pack["title"], pack["stars"])],
  )


async def precheckout_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.pre_checkout_query
  await query.answer(ok=True)


async def successful_payment_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  payment = update.message.successful_payment
  payload = payment.invoice_payload

  pack_key = payload.replace("donate_", "")
  pack = DONATE_PACKAGES.get(pack_key)

  if pack:
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    added_valor = pack["valor"]
    user_data["balance"] += added_valor
    update_user_data(user_id, user_data)

    await update.message.reply_text(
        f"🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Вам зачислено: <b>+{added_valor} Valor</b>\n"
        f"Текущий баланс: <b>{user_data['balance']} Valor</b>",
        parse_mode="HTML",
    )


# =========================================================
# 5. МИНИ-ИГРА "МИНЫ"
# =========================================================


def build_mines_keyboard(game: dict, reveal_all: bool = False):
  keyboard = []
  opened = game["opened"]
  mines = game["mines"]

  for row in range(6):
    keyboard_row = []
    for col in range(6):
      idx = row * 6 + col
      if reveal_all:
        if idx in mines:
          text = "💥" if idx in opened else "💣"
        elif idx in opened:
          text = "💎"
        else:
          text = "⬛"
      else:
        text = "💎" if idx in opened else "🟦"

      keyboard_row.append(
          InlineKeyboardButton(text, callback_data=f"mine_{idx}")
      )
    keyboard.append(keyboard_row)

  if not reveal_all and len(opened) > 0:
    current_step = len(opened)
    mult = MINES_MULTIPLIERS[current_step - 1]
    cashout_amount = int(game["bet"] * mult)
    keyboard.append([
        InlineKeyboardButton(
            f"💰 Забрать {cashout_amount} Valor (x{mult})",
            callback_data="mine_cashout",
        )
    ])

  return InlineKeyboardMarkup(keyboard)


async def start_mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  user_id = user.id
  if user_id in active_mines_games:
    await update.message.reply_text("❌ У вас уже есть активная игра!")
    return

  if not context.args or not context.args[0].isdigit():
    await update.message.reply_text(
        "❌ Формат: <code>мины 500</code>", parse_mode="HTML"
    )
    return

  bet = int(context.args[0])
  user_data = get_user_data(user_id)

  if bet <= 0 or user_data["balance"] < bet:
    await update.message.reply_text("❌ Недостаточно средств!")
    return

  user_data["balance"] -= bet
  update_user_data(user_id, user_data)

  mines_locations = set(random.sample(range(36), 8))
  game_state = {
      "bet": bet,
      "mines": mines_locations,
      "opened": set(),
      "step": 0,
  }
  active_mines_games[user_id] = game_state

  reply_markup = build_mines_keyboard(game_state)
  await update.message.reply_text(
      f"💣 <b>Игра «Мины» началась!</b>\n\n• Ставка: <b>{bet} Valor</b>\n•"
      " Поле: <b>36 клеток (8 мин)</b>",
      reply_markup=reply_markup,
      parse_mode="HTML",
  )


async def mines_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  query = update.callback_query
  user_id = query.from_user.id

  if user_id not in active_mines_games:
    await query.answer("❌ Игра завершена!", show_alert=True)
    return

  game = active_mines_games[user_id]
  data = query.data

  if data == "mine_cashout":
    step = len(game["opened"])
    if step == 0:
      await query.answer("Откройте хотя бы одну клетку!", show_alert=True)
      return

    mult = MINES_MULTIPLIERS[step - 1]
    win_amount = int(game["bet"] * mult)

    user_data = get_user_data(user_id)
    user_data["balance"] += win_amount
    update_user_data(user_id, user_data)

    reply_markup = build_mines_keyboard(game, reveal_all=True)
    del active_mines_games[user_id]

    await query.edit_message_text(
        f"🎉 <b>Вы забрали выигрыш!</b>\n\n• Множитель: <b>x{mult}</b>\n• Итого:"
        f" <b>+{win_amount} Valor</b>",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return

  idx = int(data.split("_")[1])
  if idx in game["opened"]:
    await query.answer("Клетка уже открыта!")
    return

  if idx in game["mines"]:
    game["opened"].add(idx)
    reply_markup = build_mines_keyboard(game, reveal_all=True)
    del active_mines_games[user_id]

    await query.edit_message_text(
        f"💥 <b>БУМ! Вы попали на мину!</b>\n\n• Ставка <b>{game['bet']}"
        " Valor</b> сгорела.",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return

  game["opened"].add(idx)
  step = len(game["opened"])
  mult = MINES_MULTIPLIERS[step - 1]
  current_win = int(game["bet"] * mult)

  if step == 28:
    user_data = get_user_data(user_id)
    user_data["balance"] += current_win
    update_user_data(user_id, user_data)

    reply_markup = build_mines_keyboard(game, reveal_all=True)
    del active_mines_games[user_id]

    await query.edit_message_text(
        "👑 <b>НЕВЕРОЯТНО! Вы очистили все поле!</b>\n\n• Выигрыш:"
        f" <b>{current_win} Valor (x{mult})</b>!",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return

  reply_markup = build_mines_keyboard(game)
  await query.answer(f"💎 Безопасно! x{mult}")
  await query.edit_message_text(
      f"💣 <b>Игра «Мины»</b>\n\n• Открыто: <b>{step}/28</b>\n• Множитель:"
      f" <b>x{mult}</b>\n• Выигрыш: <b>{current_win} Valor</b>",
      reply_markup=reply_markup,
      parse_mode="HTML",
  )

# =========================================================
# 6. РУЛЕТКА (С ПОДДЕРЖКОЙ ДИАПАЗОНОВ ЧИСЕЛ)
# =========================================================


async def roulette_bet_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  global active_bets, cooldown_start_time
  user = update.effective_user
  user_data = get_user_data(user.id)

  if len(context.args) < 2:
    await update.message.reply_text(
        "❌ Формат: <code>500 ч</code> или <code>500 10-20</code>",
        parse_mode="HTML",
    )
    return

  bet_str = context.args[0]
  raw_choice = context.args[1].lower()

  if not bet_str.isdigit():
    await update.message.reply_text(
        "❌ Сумма ставки должна быть числом!", parse_mode="HTML"
    )
    return

  bet = int(bet_str)

  if bet <= 0 or user_data["balance"] < bet:
    await update.message.reply_text("❌ Недостаточно средств!")
    return

  # Проверяем вариант ставки: цвет, конкретное число или диапазон
  choice = None
  if raw_choice in ["ч", "чёрное", "черное", "black"]:
    choice = "черное"
  elif raw_choice in ["к", "красное", "red"]:
    choice = "красное"
  elif "-" in raw_choice:
    parts = raw_choice.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
      start, end = int(parts[0]), int(parts[1])
      if 0 <= start <= 36 and 0 <= end <= 36 and start <= end:
        choice = f"{start}-{end}"
  elif raw_choice.isdigit() and 0 <= int(raw_choice) <= 36:
    choice = raw_choice

  if not choice:
    await update.message.reply_text(
        "❌ Неверная ставка! Укажите цвет (к/ч), число (0-36) или диапазон"
        " (например, 10-20).",
        parse_mode="HTML",
    )
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
      "choice": choice,
  })

  if is_first_bet:
    await update.message.reply_text(
        f"✅ <b>{user.first_name}</b> сделал(а) ставку <b>{bet} Valor</b> на"
        f" <code>{choice}</code>!\n⏳ Кулдаун <b>7 сек</b>. Старт:"
        " <code>го</code>.",
        parse_mode="HTML",
    )
  else:
    await update.message.reply_text(
        f"✅ Ставка на <code>{choice}</code> принята! Всего ставок:"
        f" <b>{len(active_bets)}</b>.",
        parse_mode="HTML",
    )


async def spin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  global active_bets, cooldown_start_time

  if not active_bets:
    await update.message.reply_text("❌ Ставок еще нет!", parse_mode="HTML")
    return

  elapsed = time.time() - cooldown_start_time
  if elapsed < ROULETTE_COOLDOWN:
    remaining = int(ROULETTE_COOLDOWN - elapsed) + 1
    await update.message.reply_text(
        f"❌ До запуска осталось <b>{remaining} сек.</b>", parse_mode="HTML"
    )
    return

  winning_number = random.randint(0, 36)
  red_numbers = [
      1,
      3,
      5,
      7,
      9,
      12,
      14,
      16,
      18,
      19,
      21,
      23,
      25,
      27,
      30,
      32,
      34,
      36,
  ]

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
    win_amount = 0

    if choice in ["красное", "черное"]:
      if choice == winning_color.split()[0]:
        won = True
        win_amount = bet * 2
    elif "-" in choice:
      start_str, end_str = choice.split("-")
      start, end = int(start_str), int(end_str)
    if start <= winning_number <= end:
        won = True
        total_numbers_in_range = (end - start) + 1
        multiplier = 36 / total_numbers_in_range
        win_amount = int(bet * multiplier)
    elif choice.isdigit():
      if int(choice) == winning_number:
        won = True
        win_amount = bet * 36

    if won:
      u_data["balance"] += win_amount
      results_summary.append(
          f"🟢 <b>{name}</b> ({choice}): +{win_amount} Valor 🎉"
      )
    else:
      results_summary.append(f"🔴 <b>{name}</b> ({choice}): -{bet} Valor")

    update_user_data(u_id, u_data)

  active_bets.clear()
  cooldown_start_time = 0

  res_text = "\n".join(results_summary)
  await update.message.reply_text(
      f"🎰 Выпало: <b>{winning_number} ({winning_color.upper()})</b>\n\n<b>Результаты:</b>\n{res_text}",
      parse_mode="HTML",
  )

# =========================================================
# 7. ОБРАБОТЧИК СООБЩЕНИЙ И ТРИГГЕРОВ
# =========================================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not update.message or not update.message.text:
    return

  user = update.effective_user
  user_data = get_user_data(user.id)
  raw_text = update.message.text.strip()
  text = raw_text.lower()

  if text in ["го", "крутить", "погнали", "пуск"]:
    await spin_command(update, context)
    return

  if text == "к":
    user_data, earned = apply_bank_interest(user.id, user_data)
    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    msg = (
        f"💳 <b>Кошелек {user_mention}:</b>\n• На руках: {user_data['balance']}"
        f" Valor\n• В банке: {user_data['bank']} Valor"
    )
    if earned > 0:
      msg += f"\n\n📈 <i>Вам начислено +{earned} Valor (1% за 12ч в банке)!</i>"
    await update.message.reply_text(msg, parse_mode="HTML")
    return

  parts = text.split()

  if len(parts) == 2 and parts[0] in ["мины", "мина", "mines"]:
    if parts[1].isdigit():
      context.args = [parts[1]]
      await start_mines_game(update, context)
      return

  if len(parts) == 2 and parts[0] in ["о", "отдать", "передать"]:
    if parts[1].isdigit():
      context.args = [parts[1]]
      await give_command(update, context)
      return

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

  # Проверка ставки рулетки (например, "500 ч", "1000 10-20", "200 5")
  if len(parts) == 2 and parts[0].isdigit():
    context.args = [parts[0], parts[1]]
    await roulette_bet_command(update, context)
    return

  # Обработка кнопок из клавиатуры
  if raw_text in ["💰 Кошелек", "💰 Баланс"]:
    user_data, earned = apply_bank_interest(user.id, user_data)
    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    msg = (
        f"💳 <b>Кошелек {user_mention}:</b>\n• На руках: {user_data['balance']}"
        f" Valor\n• В банке: {user_data['bank']} Valor"
    )
    if earned > 0:
      msg += f"\n\n📈 <i>Вам начислено +{earned} Valor (1% за 12ч в банке)!</i>"
    await update.message.reply_text(msg, parse_mode="HTML")

  elif raw_text in ["🎁 Подарок", "🎁 Бонус (1000 Valor)"]:
    now = time.time()
    cooldown = 1 * 3600
    if now - user_data.get("last_bonus", 0) >= cooldown:
      user_data["balance"] += 1000
      user_data["last_bonus"] = now
      update_user_data(user.id, user_data)
      await update.message.reply_text("🎉 Вы получили подарок: 1000 Valor!")
    else:
      remaining = int(cooldown - (now - user_data["last_bonus"]))
      mins, secs = divmod(remaining, 60)
      await update.message.reply_text(
          f"⏳ Подождите еще {mins} мин. {secs} сек."
      )

  elif raw_text.startswith("💣 Мины"):
    await update.message.reply_text(
        "💣 <b>Мини-игра «Мины»:</b>\n\n• Начните игру: <code>мины 500</code>\n•"
        " Нажимайте кнопки под сообщением.\n• Заберите выигрыш кнопкой <b>💰"
        " Забрать</b>!",
        parse_mode="HTML",
    )

  elif raw_text.startswith("🏦 Банк"):
    user_data, earned = apply_bank_interest(user.id, user_data)
    msg = (
        "🏦 <b>Управление банком:</b>\n\n"
        "• <code>б 1000</code> — положить в банк\n"
        "• <code>б -400</code> — снять из банка\n\n"
        "💡 <i>Банк приносит 1% каждые 12 часов от суммы на счету!</i>"
    )
    if earned > 0:
      msg += f"\n\n📈 <i>Вам начислено +{earned} Valor!</i>"
    await update.message.reply_text(msg, parse_mode="HTML")

  elif raw_text in ["💎 Магазин", "💎 Донат"]:
    await open_shop(update, context)

# =========================================================
# 8. ЗАПУСК БОТА
# =========================================================

BOT_TOKEN = "8869539861:AAE8vdxDT3y6kZU-kSHTFRl7TL-nBMlsG5I"


def main():
  init_db()
  app = Application.builder().token(BOT_TOKEN).build()

  # Команды
  app.add_handler(CommandHandler("start", start_command))
  app.add_handler(CommandHandler("deposit", deposit_command))
  app.add_handler(CommandHandler("withdraw", withdraw_command))
  app.add_handler(CommandHandler("give", give_command))
  app.add_handler(CommandHandler("roulette", roulette_bet_command))
  app.add_handler(CommandHandler("spin", spin_command))
  app.add_handler(CommandHandler("mines", start_mines_game))
  app.add_handler(CommandHandler("shop", open_shop))

  # Обработчики доната (Telegram Stars)
  app.add_handler(CallbackQueryHandler(buy_package_callback, pattern="^buy_"))
  app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
  app.add_handler(
      MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback)
  )

  # Обработчики инлайн-кнопок игры "Мины"
  app.add_handler(CallbackQueryHandler(mines_callback_handler, pattern="^mine_"))

  # Обработчик обычных текстовых сообщений
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

  print("Бот успешно запущен!")
  app.run_polling()


if __name__ == "__main__":
  main()