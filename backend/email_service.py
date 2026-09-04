"""
Email service module for sending emails.
Supports forgot password and other email notifications.
"""
import logging
import ssl
import aiosmtplib
import certifi
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from config.environments import get_environment_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmailService:
    """Email service for sending various types of emails."""

    def __init__(self):
        settings = get_environment_config()
        self.smtp_host = settings.email.smtp_host
        self.smtp_port = settings.email.smtp_port
        self.smtp_username = settings.email.smtp_username
        self.smtp_password = settings.email.smtp_password
        self.email_from = settings.email.email_from
        self.email_from_name = settings.email.email_from_name
        self.frontend_url = settings.security.frontend_url
        # Some minimal Docker images don't ship an OS CA trust store. Use certifi to validate STARTTLS.
        self._tls_context = ssl.create_default_context(cafile=certifi.where())

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """
        Send an email using SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML content of the email
            text_content: Plain text content (optional)

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Check if email is configured
            if not self.smtp_username or not self.smtp_password:
                logger.error("SMTP credentials not configured")
                return False

            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.email_from_name} <{self.email_from}>"
            message["To"] = to_email

            # Add text content if provided
            if text_content:
                text_part = MIMEText(text_content, "plain")
                message.attach(text_part)

            # Add HTML content
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)

            # Explicit SMTP envelope sender/recipients avoids relying on header parsing and helps with Gmail.
            sender = self.smtp_username
            recipients = [to_email]

            use_tls = self.smtp_port == 465
            start_tls = not use_tls

            # Send email using aiosmtplib for async support
            await aiosmtplib.send(
                message,
                sender=sender,
                recipients=recipients,
                hostname=self.smtp_host,
                port=self.smtp_port,
                use_tls=use_tls,
                start_tls=start_tls,
                username=self.smtp_username,
                password=self.smtp_password,
                tls_context=self._tls_context,
            )

            logger.info("Email sent successfully")
            return True

        except Exception as e:
            hint = None
            if isinstance(e, aiosmtplib.errors.SMTPAuthenticationError):
                hint = (
                    "SMTP authentication failed. If you're using Gmail, SMTP_PASSWORD must be an App Password "
                    "(requires 2-Step Verification) or you need OAuth2; regular account passwords won't work."
                )
            elif isinstance(e, ssl.SSLCertVerificationError):
                hint = (
                    "TLS certificate verification failed. This is commonly caused by missing CA certificates in the "
                    "runtime image."
                )
            elif isinstance(e, (aiosmtplib.errors.SMTPConnectError, TimeoutError, ConnectionError, OSError)):
                hint = (
                    "SMTP connection failed. Verify outbound connectivity and SMTP configuration."
                )

            logger.error("Email delivery failed: %s", type(e).__name__)
            if hint:
                logger.error(hint)
            return False

    async def send_password_reset_email(self, to_email: str, full_name: str, reset_token: str) -> bool:
        """
        Send password reset email.

        Args:
            to_email: Recipient email address
            full_name: User's full name
            reset_token: Password reset token

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        reset_url = f"{self.frontend_url}/reset-password?token={reset_token}"

        # HTML content for password reset email
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Password Reset - ClauseIQ</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background-color: #2563eb;
                    color: white;
                    padding: 20px;
                    text-align: center;
                    border-radius: 8px 8px 0 0;
                }}
                .content {{
                    background-color: #f8fafc;
                    padding: 30px;
                    border-radius: 0 0 8px 8px;
                    border: 1px solid #e2e8f0;
                }}
                .button {{
                    display: inline-block;
                    background-color: #2563eb;
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 6px;
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .button:hover {{
                    background-color: #1d4ed8;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    font-size: 12px;
                    color: #64748b;
                }}
                .warning {{
                    background-color: #fef2f2;
                    border: 1px solid #fecaca;
                    border-radius: 6px;
                    padding: 15px;
                    margin: 20px 0;
                    color: #dc2626;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🔒 Password Reset Request</h1>
            </div>
            <div class="content">
                <h2>Hello {full_name},</h2>
                <p>We received a request to reset your password for your ClauseIQ account.</p>
                <p>Click the button below to reset your password:</p>

                <div style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset My Password</a>
                </div>

                <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                <p style="word-break: break-all; background-color: #f1f5f9; padding: 10px; border-radius: 4px; font-family: monospace;">
                    {reset_url}
                </p>

                <div class="warning">
                    <strong>⚠️ Important:</strong>
                    <ul>
                        <li>This reset link will expire in 30 minutes</li>
                        <li>If you didn't request this reset, please ignore this email</li>
                        <li>Never share this link with anyone</li>
                    </ul>
                </div>

                <p>If you continue to have problems, please contact our support team.</p>

                <p>Best regards,<br>
                The ClauseIQ Team</p>
            </div>
            <div class="footer">
                <p>This email was sent to {to_email}</p>
                <p>© 2024 ClauseIQ. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        # Plain text version
        text_content = f"""
        Password Reset Request - ClauseIQ

        Hello {full_name},

        We received a request to reset your password for your ClauseIQ account.

        Please click on the following link to reset your password:
        {reset_url}

        Important:
        - This reset link will expire in 30 minutes
        - If you didn't request this reset, please ignore this email
        - Never share this link with anyone

        If you continue to have problems, please contact our support team.

        Best regards,
        The ClauseIQ Team

        This email was sent to {to_email}
        """

        # Send email
        return await self.send_email(
            to_email=to_email,
            subject="Reset Your ClauseIQ Password",
            html_content=html_content,
            text_content=text_content
        )

    async def send_verification_email(self, to_email: str, full_name: str, verification_token: str) -> bool:
        """
        Send email verification email.

        Args:
            to_email: Recipient email address
            full_name: User's full name
            verification_token: Email verification token

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        verify_url = f"{self.frontend_url}/verify-email?token={verification_token}"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Verify Your Email - ClauseIQ</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background-color: #2563eb;
                    color: white;
                    padding: 20px;
                    text-align: center;
                    border-radius: 8px 8px 0 0;
                }}
                .content {{
                    background-color: #f8fafc;
                    padding: 30px;
                    border-radius: 0 0 8px 8px;
                    border: 1px solid #e2e8f0;
                }}
                .button {{
                    display: inline-block;
                    background-color: #2563eb;
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 6px;
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .button:hover {{
                    background-color: #1d4ed8;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    font-size: 12px;
                    color: #64748b;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>✉️ Verify Your Email</h1>
            </div>
            <div class="content">
                <h2>Welcome, {full_name}!</h2>
                <p>Thanks for signing up for ClauseIQ. Please verify your email address to unlock all features.</p>
                <p>Click the button below to verify your email:</p>

                <div style="text-align: center;">
                    <a href="{verify_url}" class="button">Verify My Email</a>
                </div>

                <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                <p style="word-break: break-all; background-color: #f1f5f9; padding: 10px; border-radius: 4px; font-family: monospace;">
                    {verify_url}
                </p>

                <p style="margin-top: 20px; font-size: 14px; color: #64748b;">
                    This verification link will expire in 24 hours. If you didn't create a ClauseIQ account, you can safely ignore this email.
                </p>

                <p>Best regards,<br>
                The ClauseIQ Team</p>
            </div>
            <div class="footer">
                <p>This email was sent to {to_email}</p>
                <p>&copy; 2024 ClauseIQ. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Verify Your Email - ClauseIQ

        Welcome, {full_name}!

        Thanks for signing up for ClauseIQ. Please verify your email address to unlock all features.

        Click the following link to verify your email:
        {verify_url}

        This verification link will expire in 24 hours.
        If you didn't create a ClauseIQ account, you can safely ignore this email.

        Best regards,
        The ClauseIQ Team

        This email was sent to {to_email}
        """

        return await self.send_email(
            to_email=to_email,
            subject="Verify Your Email - ClauseIQ",
            html_content=html_content,
            text_content=text_content
        )

# Global email service instance
email_service = EmailService()

async def send_password_reset_email(to_email: str, full_name: str, reset_token: str) -> bool:
    """Convenience function to send password reset email."""
    return await email_service.send_password_reset_email(to_email, full_name, reset_token)

async def send_verification_email(to_email: str, full_name: str, verification_token: str) -> bool:
    """Convenience function to send email verification email."""
    return await email_service.send_verification_email(to_email, full_name, verification_token)
