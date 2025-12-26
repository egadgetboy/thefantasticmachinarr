"""
Email notifications for The Fantastic Machinarr.
Handles batched find notifications and individual alerts.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import threading


@dataclass
class FindNotification:
    """A successful find to be notified."""
    title: str
    source: str
    tier: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class EmailNotifier:
    """Email notification manager."""
    
    def __init__(self, config, logger):
        self.config = config
        self.log = logger.get_logger('notifier')
        self._lock = threading.Lock()
        
        # Batched finds
        self.pending_finds: List[FindNotification] = []
        self.last_batch_sent = datetime.utcnow()
    
    def _send_email(self, subject: str, body: str, html: bool = True) -> bool:
        """Send an email."""
        email_cfg = self.config.email
        
        if not email_cfg.enabled:
            return False
        
        if not all([email_cfg.smtp_host, email_cfg.from_address, email_cfg.to_address]):
            self.log.warning("Email not configured properly")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = email_cfg.from_address
            msg['To'] = email_cfg.to_address
            
            if html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port) as server:
                if email_cfg.smtp_tls:
                    server.starttls()
                if email_cfg.smtp_user and email_cfg.smtp_password:
                    server.login(email_cfg.smtp_user, email_cfg.smtp_password)
                server.send_message(msg)
            
            self.log.info(f"Email sent: {subject}")
            return True
            
        except Exception as e:
            self.log.error(f"Failed to send email: {e}")
            return False
    
    def notify_find(self, title: str, source: str, tier: str):
        """Add a find to the batch queue."""
        with self._lock:
            self.pending_finds.append(FindNotification(
                title=title,
                source=source,
                tier=tier,
            ))
    
    def flush_finds(self, force: bool = False) -> bool:
        """Send batched find notifications if due."""
        email_cfg = self.config.email
        
        if not email_cfg.enabled or not email_cfg.batch_finds:
            return False
        
        with self._lock:
            if not self.pending_finds:
                return False
            
            # Check if enough time has passed
            time_since_last = datetime.utcnow() - self.last_batch_sent
            if not force and time_since_last < timedelta(minutes=email_cfg.batch_interval_minutes):
                return False
            
            finds = self.pending_finds.copy()
            self.pending_finds.clear()
            self.last_batch_sent = datetime.utcnow()
        
        # Build email
        subject = f"🎬 Machinarr: {len(finds)} new finds!"
        
        items_html = ""
        for find in finds:
            tier_emoji = {"hot": "🔥", "warm": "☀️", "cool": "❄️", "cold": "🧊"}.get(find.tier, "")
            items_html += f"<li>{tier_emoji} <b>{find.title}</b> ({find.source})</li>\n"
        
        body = f"""
        <html>
        <body style="font-family: sans-serif;">
        <h2>🎬 The Fantastic Machinarr - New Finds</h2>
        <p>Found {len(finds)} new items:</p>
        <ul>
        {items_html}
        </ul>
        <p style="color: #666; font-size: 12px;">
        Sent at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
        </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, body)
    
    def notify_intervention_needed(self, title: str, reason: str, 
                                   details: str, link: str) -> bool:
        """Send immediate notification for manual intervention."""
        if not self.config.email.enabled:
            return False
        
        subject = f"⚠️ Machinarr: Manual intervention needed"
        
        body = f"""
        <html>
        <body style="font-family: sans-serif;">
        <h2>⚠️ Manual Intervention Required</h2>
        <p><b>Item:</b> {title}</p>
        <p><b>Reason:</b> {reason}</p>
        <p><b>Details:</b> {details}</p>
        <p><a href="{link}" style="background: #3b82f6; color: white; padding: 10px 20px; 
           text-decoration: none; border-radius: 5px;">View in Machinarr</a></p>
        </body>
        </html>
        """
        
        return self._send_email(subject, body)
    
    def notify_storage_warning(self, path: str, used_percent: float, 
                               free_gb: float) -> bool:
        """Send storage warning notification."""
        if not self.config.email.enabled:
            return False
        
        level = "🚨 CRITICAL" if used_percent >= 95 else "⚠️ WARNING"
        subject = f"{level}: Storage space low on {path}"
        
        body = f"""
        <html>
        <body style="font-family: sans-serif;">
        <h2>{level}: Low Storage Space</h2>
        <p><b>Path:</b> {path}</p>
        <p><b>Used:</b> {used_percent:.1f}%</p>
        <p><b>Free:</b> {free_gb:.1f} GB</p>
        <p>Please free up space to avoid download failures.</p>
        </body>
        </html>
        """
        
        return self._send_email(subject, body)
    
    def notify_connection_error(self, service: str, error: str) -> bool:
        """Send connection error notification."""
        if not self.config.email.enabled:
            return False
        
        subject = f"🔴 Machinarr: Cannot connect to {service}"
        
        body = f"""
        <html>
        <body style="font-family: sans-serif;">
        <h2>🔴 Connection Error</h2>
        <p><b>Service:</b> {service}</p>
        <p><b>Error:</b> {error}</p>
        <p>Please check the service is running and accessible.</p>
        </body>
        </html>
        """
        
        return self._send_email(subject, body)
    
    def test_connection(self) -> Dict[str, Any]:
        """Test email configuration."""
        subject = "✅ Machinarr: Test Email"
        body = """
        <html>
        <body style="font-family: sans-serif;">
        <h2>✅ Email Test Successful</h2>
        <p>Your email notifications are configured correctly!</p>
        </body>
        </html>
        """
        
        success = self._send_email(subject, body)
        return {
            'success': success,
            'message': 'Test email sent' if success else 'Failed to send test email'
        }
