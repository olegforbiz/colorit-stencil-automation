import os
import telebot
from orchestrator import run_stencil_automation

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("Помилка: TELEGRAM_BOT_TOKEN не знайдено в змінних середовища!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Зберігаємо вибраний рівень складності для кожного користувача
user_levels = {}

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "Привіт! Я бот для створення трафаретів Colorit. 🎨\n\n"
        "1. Надішли мені зображення (як фото).\n"
        "2. За замовчуванням рівень складності M.\n"
        "3. Щоб змінити рівень, напиши /level S, /level M або /level H.\n\n"
        "Чекаю на твоє зображення!"
    )

@bot.message_handler(commands=['level'])
def set_level(message):
    parts = message.text.split()
    if len(parts) > 1 and parts[1].upper() in ['S', 'M', 'H']:
        level = parts[1].upper()
        user_levels[message.chat.id] = level
        bot.reply_to(message, f"Рівень складності встановлено на {level}!")
    else:
        bot.reply_to(message, "Будь ласка, вкажіть рівень: /level S, /level M або /level H")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    level = user_levels.get(chat_id, "M")
    
    msg = bot.reply_to(message, f"Отримав фото! Починаю конвеєр генерації (Складність: {level}). Це може зайняти хвилину-дві...")
    
    try:
        # Завантажуємо фото з Telegram
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        input_image_path = f"input_{chat_id}.jpg"
        with open(input_image_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Запускаємо нашу автоматизацію
        result_path = run_stencil_automation(input_image_path, level)
        
        if result_path and os.path.exists(result_path):
            with open(result_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=f"Ваш трафарет готовий! (Рівень: {level})")
        else:
            bot.send_message(chat_id, "Вибачте, не вдалося згенерувати якісний трафарет після 3 ітерацій або сталася помилка.")
            
    except Exception as e:
        bot.send_message(chat_id, f"Сталася помилка при обробці: {e}")

if __name__ == "__main__":
    print("Бот запущено. Очікування повідомлень...")
    bot.infinity_polling()
