# Max Bot Integration Guide

This document contains information for connecting and configuring the Max bot for the elevator repair ticket system.

## Bot Token
```
MAX_BOT_TOKEN=f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l
```

## API Endpoints
- Base URL: `https://platform-api.max.ru`
- Webhook endpoint: `/max/webhook` (on your server)
- Messages API: `https://platform-api.max.ru/messages?user_id={USER_ID}`
- Get bot info: `https://platform-api.max.ru/me`

## Message Format

### Sending a Text Message
```json
POST https://platform-api.max.ru/messages?user_id={USER_ID}
Headers:
  Authorization: {MAX_BOT_TOKEN}
  Content-Type: application/json

Body:
{
  "text": "Your message here"
}
```

### Sending a Message with Inline Keyboard
```json
POST https://platform-api.max.ru/messages?user_id={USER_ID}
Headers:
  Authorization: {MAX_BOT_TOKEN}
  Content-Type: application/json

Body:
{
  "text": "Choose an option:",
  "attachments": [
    {
      "type": "inline_keyboard",
      "payload": {
        "buttons": [
          [
            {"type": "callback", "text": "🛗 Мои лифты", "payload": "my_elevators"},
            {"type": "callback", "text": "📋 Мои заявки", "payload": "my_tickets"}
          ],
          [
            {"type": "callback", "text": "❓ Помощь", "payload": "help"},
            {"type": "callback", "text": "✅ Завершить заявку", "payload": "complete_ticket"}
          ]
        ]
      }
    }
  ]
}
```

## Webhook Handling

The server expects updates in the following format:

### Message Received
```json
{
  "update_type": "message_created",
  "message": {
    "sender": {
      "user_id": 123456789
    },
    "body": {
      "text": "User message text"
    }
  }
}
```

### Button Press (Callback Query)
```json
{
  "update_type": "callback_query",
  "callback": {
    "user_id": 123456789,
    "payload": "button_payload_from_keyboard"
  }
}
```

### Bot Started
```json
{
  "update_type": "bot_started",
  "user": {
    "user_id": 123456789
  },
  "payload": "optional_payload"
}
```

## Response Types

The bot can send:
1. Plain text messages
2. Messages with inline keyboards (buttons)
3. Callback responses for button presses

## Button Payloads Used in This System

- `my_elevators` - Show user's elevators
- `my_tickets` - Show user's tickets
- `help` - Show help information
- `complete_ticket` - Complete a ticket
- `accept_{ticket_id}` - Accept ticket for work
- `complete_{ticket_id}` - Mark ticket as completed

## Environment Variables

Set these environment variables for the bot to work:

```
MAX_BOT_TOKEN=f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l
```

## Quick Test

To test the bot API directly:

```bash
# Send a simple text message
curl -X POST "https://platform-api.max.ru/messages?user_id=YOUR_USER_ID" \
  -H "Authorization: f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Привет! Это тестовое сообщение."
  }'

# Send a message with keyboard
curl -X POST "https://platform-api.max.ru/messages?user_id=YOUR_USER_ID" \
  -H "Authorization: f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Выберите действие:",
    "attachments": [
      {
        "type": "inline_keyboard",
        "payload": {
          "buttons": [
            [
              {"type": "callback", "text": "Кнопка 1", "payload": "btn1"},
              {"type": "callback", "text": "Кнопка 2", "payload": "btn2"}
            ]
          ]
        }
      }
    ]
  }'
```

Replace `YOUR_USER_ID` with the actual Max user ID you want to send messages to.

## Troubleshooting

1. **401 Unauthorized**: Check that the MAX_BOT_TOKEN is correct and has the right permissions
2. **400 Bad Request**: Verify the JSON format is correct and all required fields are present
3. **Messages not delivered**: Ensure the user_id is correct and the user has started the bot
4. **Buttons not showing**: Check that the inline keyboard format matches the Max API specification exactly
5. **Callback queries not received**: Make sure your webhook endpoint is correctly configured to receive POST requests and return 200 OK

## Notes

- The Max API uses `user_id` as a query parameter for sending messages, not in the JSON body
- Inline keyboards must be sent as attachments with type `inline_keyboard`
- Callback payloads are strings that you define and receive back when buttons are pressed
- The bot token should be kept secure and not exposed in client-side code
