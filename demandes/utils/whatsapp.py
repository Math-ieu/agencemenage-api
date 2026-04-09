import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

logger = logging.getLogger(__name__)

class WhatsAppService:
    @staticmethod
    def send_template_message(to: str, template_name: str, media_url: str = None, media_type: str = 'document', variables: list = None):
        """
        Sends a WhatsApp template message via 360 Dialog using urllib.
        """
        if not settings.D360_API_KEY:
            logger.error("WhatsApp Error: D360_API_KEY is not configured.")
            return None

        to = to.replace('+', '').replace(' ', '')

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": "fr"
                },
                "components": []
            }
        }

        if media_url:
            filename = media_url.split('/')[-1]
            header_param = {
                "type": media_type,
                media_type: {
                    "link": media_url
                }
            }
            if media_type == 'document':
                header_param['document']['filename'] = filename

            payload["template"]["components"].append({
                "type": "header",
                "parameters": [header_param]
            })

        if variables:
            body_params = [{"type": "text", "text": str(v)} for v in variables]
            payload["template"]["components"].append({
                "type": "body",
                "parameters": body_params
            })

        data = json.dumps(payload).encode('utf-8')
        headers = {
            "D360-API-KEY": settings.D360_API_KEY,
            "Content-Type": "application/json"
        }

        req = urllib.request.Request(settings.D360_API_URL, data=data, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = response.read().decode('utf-8')
                logger.info(f"WhatsApp Success: Message sent to {to} using template {template_name}")
                return json.loads(res_data)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            logger.error(f"WhatsApp API HTTP Error: {e.code} - {error_body}")
            return None
        except Exception as e:
            logger.error(f"WhatsApp API Error: {str(e)}")
            return None
