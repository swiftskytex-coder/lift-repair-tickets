# Telegram Bot Integration Guide

This document contains information for connecting and configuring the Telegram bot for the elevator repair ticket system.

## Bot Token
```
TELEGRAM_BOT_TOKEN=8262774907:AAH4tYjvPDP3PdZb0iGkxR6ojCp9k68BbHQ
```

## Bot Information
- Bot Username: @lift_repair_bot (to be confirmed with @BotFather)
- Bot URL: https://t.me/lift_repair_bot

## API Endpoints
- Telegram Bot API: `https://api.telegram.org`
- Base URL: `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}`

## Message Format

### Sending a Text Message
```
POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage
Headers:
  Content-Type: application/json

Body:
{
  "chat_id": "USER_ID",
  "text": "Your message here"
}
```

### Sending a Message with Inline Keyboard
```
POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage
Headers:
  Content-Type: application/json

Body:
{
  "chat_id": "USER_ID",
  "text": "Choose an option:",
  "reply_markup": {
    "inline_keyboard": [
      [
        {"text": "🛗 Мои лифты", "callback_data": "my_elevators"},
        {"text": "📋 Мои заявки", "callback_data": "my_tickets"}
      ],
      [
        {"text": "❓ Помощь", "callback_data": "help"},
        {"text": "✅ Завершить заявку", "callback_data": "complete_ticket"}
      ]
    ]
  }
}
```

### Sending a Photo
```
POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto
Headers:
  Content-Type: application/json

Body:
{
  "chat_id": "USER_ID",
  "photo": "PHOTO_FILE_ID or URL",
  "caption": "Photo description"
}
```

### Using Reply Keyboard (Main Menu)
```
POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage
Headers:
  Content-Type: application/json

Body:
{
  "chat_id": "USER_ID",
  "text": "Выберите действие:",
  "reply_markup": {
    "keyboard": [
      [{"text": "🛗 Мои лифты"}, {"text": "📋 Мои заявки"}],
      [{"text": "❓ Помощь"}, {"text": "✅ Завершить заявку"}]
    ],
    "resize_keyboard": true
  }
}
```

## Bot Commands

### Available Commands
- `/start` - Start the bot and get registration prompt
- `/help` - Get help information
- `/my_elevators` - View assigned elevators
- `/my_tickets` - View your tickets
- `/complete` - Complete a ticket

### Keyboard Buttons Used in This System
- `🛗 Мои лифты` - Show user's elevators
- `📋 Мои заявки` - Show user's tickets
- `❓ Помощь` - Show help information
- `✅ Завершить заявку` - Complete a ticket

### Callback Data (Inline Buttons)
- `my_elevators` - Show user's elevators
- `my_tickets` - Show user's tickets
- `help` - Show help information
- `complete_ticket` - Complete a ticket
- `accept_{ticket_id}` - Accept ticket for work
- `complete_{ticket_id}` - Mark ticket as completed

## Environment Variables

Set these environment variables for the bot to work:

```
TELEGRAM_BOT_TOKEN=8262774907:AAH4tYjvPDP3PdZb0iGkxR6ojCp9k68BbHQ
```

## Quick Test

To test the bot API directly:

```bash
# Send a simple text message
curl -X POST "https://api.telegram.org/bot8262774907:AAH4tYjvPDP3PdZb0iGkxR6ojCp9k68BbHQ/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "YOUR_CHAT_ID",
    "text": "Привет! Это тестовое сообщение."
  }'

# Send a message with inline keyboard
curl -X POST "https://api.telegram.org/bot8262774907:AAH4tYjvPDP3PdZb0iGkxR6ojCp9k68BbHQ/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "YOUR_CHAT_ID",
    "text": "Выберите действие:",
    "reply_markup": {
      "inline_keyboard": [
        [
          {"text": "Кнопка 1", "callback_data": "btn1"},
          {"text": "Кнопка 2", "callback_data": "btn2"}
        ]
      ]
    }
  }'

# Send a photo
curl -X POST "https://api.telegram.org/bot8262774907:AAH4tYjvPDP3PdZb0iGkxR6ojCp9k68BbHQ/sendPhoto" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "YOUR_CHAT_ID",
    "photo": "YOUR_PHOTO_FILE_ID",
    "caption": "Описание фото"
  }'
```

Replace `YOUR_CHAT_ID` with the actual Telegram chat ID you want to send messages to.

## Bot Workflow

### Registration Process
1. User starts the bot with `/start`
2. Bot asks for phone number for verification
3. User sends phone number (must match database)
4. Bot validates and registers user
5. Main menu keyboard is shown

### Ticket Workflow
1. Operator creates ticket in web interface
2. Bot sends notification to assigned mechanic
3. Mechanic can accept the ticket with "Принять" button
4. Mechanic completes work and sends report with photos
5. Ticket status is updated in database
6. Operator is notified of completion

### Photo Upload Flow
1. Mechanic sends photo to bot
2. Bot saves photo to uploads directory
3. Photo is linked to the ticket
4. Photo is visible in web interface

## Troubleshooting

1. **401 Unauthorized**: Check that the TELEGRAM_BOT_TOKEN is correct
2. **400 Bad Request**: Verify the JSON format is correct and all required fields are present
3. **Messages not delivered**: Ensure the chat_id is correct and the user has started the bot
4. **Buttons not working**: Check that callback_data matches what your handler expects
5. **Photo upload fails**: Check file size limits and format (JPEG, PNG supported)

## Python Library

The bot uses `python-telegram-bot` library:
```bash
pip install python-telegram-bot
```

## Notes

- The bot uses both inline keyboards (callback buttons) and reply keyboards (menu buttons)
- Photo uploads are limited to 10MB
- Supported photo formats: JPEG, PNG
- The bot maintains conversation state for multi-step workflows
- All ticket operations are logged for audit purposes
- The bot token should be kept secure and not exposed in client-side code
