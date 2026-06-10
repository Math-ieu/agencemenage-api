import os
import json
import urllib.request
import urllib.error
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_resend_email(to_email, subject, html_content):
    """
    Sends an email using Resend API.
    """
    api_key = getattr(settings, 'RESEND_API_KEY', None)
    if not api_key:
        logger.warning("RESEND_API_KEY is not set. Cannot send email.")
        return False

    url = 'https://api.resend.com/emails'
    payload = {
        'from': 'notification@agencemenage.ma',
        'to': to_email,
        'subject': subject,
        'html': html_content
    }

    req_data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            logger.info(f"Resend success: {res_body}")
            return True
    except urllib.error.HTTPError as e:
        logger.error(f"Resend HTTP Error {e.code}: {e.read().decode('utf-8')}")
        return False
    except Exception as e:
        logger.error(f"Resend unexpected error: {str(e)}")
        return False


def get_base_html_template(title, content):
    """
    Generates a beautifully styled, responsive HTML email template using premium design tokens.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #334155;
      margin: 0;
      padding: 0;
      -webkit-font-smoothing: antialiased;
    }}
    .wrapper {{
      width: 100%;
      table-layout: fixed;
      background-color: #f8fafc;
      padding: 40px 0;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      background-color: #ffffff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
      border: 1px solid #e2e8f0;
    }}
    .header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      padding: 40px 30px;
      text-align: center;
      border-bottom: 4px solid #d97706;
    }}
    .header h1 {{
      color: #ffffff;
      font-size: 24px;
      margin: 0;
      font-weight: 700;
      letter-spacing: -0.025em;
    }}
    .header p {{
      color: #94a3b8;
      font-size: 14px;
      margin: 8px 0 0 0;
    }}
    .content {{
      padding: 40px 30px;
      line-height: 1.6;
    }}
    .footer {{
      background-color: #f1f5f9;
      padding: 24px 30px;
      text-align: center;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #e2e8f0;
    }}
    .btn {{
      display: inline-block;
      background-color: #d97706;
      color: #ffffff !important;
      text-decoration: none;
      padding: 12px 30px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 15px;
      margin: 24px 0;
      box-shadow: 0 4px 6px -1px rgba(217, 119, 6, 0.2);
      transition: background-color 0.2s;
    }}
    .btn:hover {{
      background-color: #b45309;
    }}
    .card {{
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 24px;
      margin: 20px 0;
    }}
    .card-title {{
      font-size: 16px;
      font-weight: 600;
      color: #0f172a;
      margin-top: 0;
      margin-bottom: 12px;
    }}
    .info-row {{
      display: flex;
      margin-bottom: 8px;
      font-size: 14px;
    }}
    .info-label {{
      width: 140px;
      color: #64748b;
      font-weight: 500;
    }}
    .info-value {{
      color: #0f172a;
      font-weight: 600;
    }}
    .otp-code {{
      font-size: 32px;
      font-weight: 700;
      letter-spacing: 6px;
      color: #d97706;
      text-align: center;
      margin: 20px 0;
      padding: 12px;
      background-color: #fef3c7;
      border: 1px dashed #f59e0b;
      border-radius: 8px;
    }}
    .divider {{
      height: 1px;
      background-color: #e2e8f0;
      margin: 24px 0;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="header">
        <h1>Agence Ménage</h1>
        <p>Votre partenaire propreté et confort</p>
      </div>
      <div class="content">
        {content}
      </div>
      <div class="footer">
        <p>Cet e-mail a été envoyé automatiquement. Merci de ne pas y répondre.</p>
        <p>&copy; {settings.TIME_ZONE[:4] if hasattr(settings, 'TIME_ZONE') else '2026'} Agence Ménage. Tous droits réservés.</p>
      </div>
    </div>
  </div>
</body>
</html>
"""


def send_account_creation_email(user):
    """
    Sends an email to the user upon account creation containing login credentials (username and email)
    and the application access link.
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.agencemenage.ma')
    
    subject = "Création de votre compte - Agence Ménage"
    
    content = f"""
      <h2 style="margin-top: 0; color: #0f172a; font-size: 20px;">Bienvenue chez Agence Ménage !</h2>
      <p>Bonjour {user.first_name} {user.last_name},</p>
      <p>Votre compte a été créé avec succès par un administrateur. Voici vos informations de connexion pour accéder à la plateforme :</p>
      
      <div class="card">
        <h3 class="card-title">Vos identifiants de connexion</h3>
        <div class="info-row">
          <span class="info-label">Nom d'utilisateur :</span>
          <span class="info-value">{user.username}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Adresse e-mail :</span>
          <span class="info-value">{user.email}</span>
        </div>
      </div>
      
      <p>Vous pouvez vous connecter en utilisant indifféremment votre nom d'utilisateur ou votre adresse e-mail, associés au mot de passe qui vous a été communiqué.</p>
      
      <div style="text-align: center;">
        <a href="{frontend_url}" class="btn">Accéder à l'application</a>
      </div>
      
      <p style="font-size: 13px; color: #64748b; margin-top: 20px;">Si le bouton ci-dessus ne fonctionne pas, copiez et collez le lien suivant dans votre navigateur : <br>
      <a href="{frontend_url}" style="color: #d97706;">{frontend_url}</a></p>
    """
    
    html_content = get_base_html_template(subject, content)
    return send_resend_email(user.email, subject, html_content)


def send_password_reset_email(user, reset_code):
    """
    Sends a password reset email containing a 6-digit OTP code.
    """
    subject = "Réinitialisation de votre mot de passe - Agence Ménage"
    
    content = f"""
      <h2 style="margin-top: 0; color: #0f172a; font-size: 20px;">Demande de réinitialisation de mot de passe</h2>
      <p>Bonjour {user.first_name or user.username},</p>
      <p>Nous avons reçu une demande de réinitialisation de mot de passe pour votre compte.</p>
      
      <div class="card">
        <h3 class="card-title">Votre code de réinitialisation</h3>
        <p style="margin: 0; font-size: 14px; color: #475569;">Saisissez le code de validation à 6 chiffres suivant dans l'application pour modifier votre mot de passe :</p>
        <div class="otp-code">{reset_code}</div>
      </div>
      
      <div class="divider"></div>
      
      <p style="font-size: 13px; color: #ef4444; font-weight: 500;">Attention : Ce code de récupération expirera dans 15 minutes.</p>
      <p style="font-size: 13px; color: #64748b;">Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail en toute sécurité.</p>
    """
    
    html_content = get_base_html_template(subject, content)
    return send_resend_email(user.email, subject, html_content)
