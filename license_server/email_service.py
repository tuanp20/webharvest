import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import asyncio
from license_server.config import Settings

logger = logging.getLogger("webharvest.email")

_APP_DOWNLOAD_URL = os.getenv("APP_DOWNLOAD_URL", "https://webharvest.twentypi.com/#download")


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;"))


def _send_email_sync(settings: Settings, to_email: str, subject: str, html_content: str):
    """Synchronous function to connect and send email via SMTP."""
    if not settings.smtp_username or not settings.smtp_password:
        logger.warning("SMTP credentials not configured. Skipping email dispatch.")
        return False

    from_addr = settings.smtp_from_email or settings.smtp_username
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("WebHarvest", from_addr))
    msg["To"] = to_email

    # Plain text fallback
    text_content = f"Cảm ơn bạn đã mua WebHarvest!\n\nLicense Key của bạn: {html_content}\n\nTải ứng dụng:\n- Windows: /download/win\n- macOS: /download/mac"
    
    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        # Check if port is SSL or STARTTLS
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()
        
        server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(from_addr, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Successfully sent license email to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

async def send_license_email(settings: Settings, to_email: str, name: str, key: str, tier_name: str, duration_months: int):
    """Asynchronously sends the license email on a background thread."""
    # Escape all user-provided values before inserting into HTML
    safe_name = _escape_html(name)
    safe_key = _escape_html(key)
    safe_tier = _escape_html(tier_name)
    download_url = _escape_html(_APP_DOWNLOAD_URL)

    subject = f"[WebHarvest] Kích hoạt bản quyền gói {tier_name} thành công"
    
    # Elegant HTML design for the email
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Kích hoạt bản quyền WebHarvest</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #0f172a;
                color: #f1f5f9;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background: #1e293b;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
                border: 1px solid #334155;
            }}
            .header {{
                background: linear-gradient(135deg, #a855f7 0%, #3b82f6 100%);
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                color: #ffffff;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px;
                line-height: 1.6;
            }}
            .greeting {{
                font-size: 18px;
                margin-bottom: 20px;
                font-weight: 600;
                color: #ffffff;
            }}
            .license-box {{
                background: #0f172a;
                border: 1px dashed #6366f1;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin: 25px 0;
            }}
            .license-key {{
                font-family: 'Courier New', Courier, monospace;
                font-size: 20px;
                font-weight: bold;
                color: #38bdf8;
                letter-spacing: 1px;
                word-break: break-all;
            }}
            .details-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 25px;
            }}
            .details-table td {{
                padding: 10px 0;
                border-bottom: 1px solid #334155;
            }}
            .details-label {{
                color: #94a3b8;
                width: 40%;
            }}
            .details-value {{
                color: #ffffff;
                font-weight: 600;
                text-align: right;
            }}
            .btn-group {{
                display: flex;
                gap: 15px;
                margin-top: 30px;
                justify-content: center;
            }}
            .btn {{
                display: inline-block;
                padding: 12px 24px;
                border-radius: 6px;
                text-decoration: none;
                font-weight: 600;
                text-align: center;
                transition: opacity 0.2s;
            }}
            .btn-primary {{
                background: #6366f1;
                color: #ffffff !important;
            }}
            .btn-secondary {{
                background: #475569;
                color: #ffffff !important;
            }}
            .footer {{
                background: #0f172a;
                padding: 20px;
                text-align: center;
                font-size: 12px;
                color: #64748b;
                border-top: 1px solid #334155;
            }}
            a {{
                color: #38bdf8;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WEBHARVEST LICENSE</h1>
            </div>
            <div class="content">
                <div class="greeting">Xin chào {safe_name},</div>
                <p>Cảm ơn bạn đã tin dùng dịch vụ và sản phẩm <strong>WebHarvest</strong>. Đơn thanh toán của bạn đã được xác nhận thành công.</p>
                <p>Dưới đây là thông tin bản quyền (License Key) và liên kết tải phần mềm của bạn:</p>
                
                <div class="license-box">
                    <div style="font-size: 12px; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase;">Mã bản quyền của bạn</div>
                    <div class="license-key">{safe_key}</div>
                </div>

                <table class="details-table">
                    <tr>
                        <td class="details-label">Gói bản quyền</td>
                        <td class="details-value">{safe_tier}</td>
                    </tr>
                    <tr>
                        <td class="details-label">Thời hạn</td>
                        <td class="details-value">{duration_months} tháng</td>
                    </tr>
                    <tr>
                        <td class="details-label">Ràng buộc thiết bị</td>
                        <td class="details-value">Có (Hỗ trợ tự đổi máy)</td>
                    </tr>
                </table>

                <p><strong>Hướng dẫn kích hoạt:</strong> Mở ứng dụng WebHarvest trên máy tính của bạn, nhập mã bản quyền trên vào khung kích hoạt để bắt đầu sử dụng.</p>
                
                <div class="btn-group">
                    <a href="{download_url}" class="btn btn-primary">Tải cho Windows (EXE)</a>
                    <a href="{download_url}" class="btn btn-secondary">Tải cho macOS (DMG)</a>
                </div>
            </div>
            <div class="footer">
                <p>Nếu bạn gặp bất kỳ sự cố nào trong quá trình kích hoạt, vui lòng liên hệ admin qua email hoặc telegram support.</p>
                <p>&copy; 2026 WebHarvest. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Run SMTP client in background thread
    await asyncio.to_thread(_send_email_sync, settings, to_email, subject, html_content)

