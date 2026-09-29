import json
import urllib3
import logging
import os

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Retrieve secrets and environment configuration from Lambda environment variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise RuntimeError("Missing required environment variables: TELEGRAM_TOKEN or CHAT_ID")

# Initialize HTTP connection pool manager
http = urllib3.PoolManager()

def lambda_handler(event, context):
    logger.info(f"Received SNS Event: {json.dumps(event)}")

    records = event.get('Records', [])
    if not records:
        logger.warning("No Records found in the event.")
        return {"status": "no_records"}

    for record in records:
        # 1. Extract message payload sent by the SNS publisher
        sns_data = record.get('Sns', {})
        message_text = sns_data.get('Message', 'No message content')
        subject = sns_data.get('Subject') or 'AWS Alert'

        # Format message layout for Telegram
        full_message = f"*{subject}*\n\n{message_text}"

        # 2. Prepare request payload for Telegram Bot API
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": full_message,
            "parse_mode": "Markdown"
        }

        try:
            # 3. Dispatch HTTP POST request to Telegram API
            encoded_data = json.dumps(payload).encode('utf-8')
            response = http.request(
                'POST',
                url,
                body=encoded_data,
                headers={'Content-Type': 'application/json'},
                timeout=5.0
            )

            if response.status != 200:
                error_body = response.data.decode('utf-8')
                logger.error(f"Telegram API Error [Status {response.status}]: {error_body}")
                raise RuntimeError(f"Telegram API responded with status {response.status}")

            logger.info(f"Successfully sent message to Telegram. Status: {response.status}")

        except Exception as e:
            logger.error(f"Failed to send notification to Telegram: {str(e)}", exc_info=True)
            raise e

    return {
        'statusCode': 200,
        'body': json.dumps('Notifications sent successfully')
    }

