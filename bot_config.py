# bot_config.py - Konfigurasi bot
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Pastikan .env terbaca
load_dotenv()

class BotConfig:
    """Configuration class untuk bot"""
    
    # Bot settings
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    API_KEY = os.getenv("MYXL_API_KEY", "")
    
    # Session settings
    SESSION_TIMEOUT = 3600  # 1 hour
    MAX_SESSIONS_PER_USER = 1
    
    # Rate limiting
    MAX_REQUESTS_PER_MINUTE = 30
    MAX_OTP_REQUESTS_PER_HOUR = 5
    
    # Messages
    MESSAGES = {
        "welcome": """
🤖 **Selamat datang di MyXL Bot!**

Bot ini membantu Anda mengelola paket XL dengan mudah.

**Fitur yang tersedia:**
• Login ke akun MyXL
• Cek saldo dan masa aktif  
• Beli paket XUT (Xtra Unlimited Turbo)

Ketik /help untuk bantuan lebih lanjut.
        """,
        
        "help": """
🔧 **Bantuan MyXL Bot**

**Perintah:**
/start - Mulai menggunakan bot
/login - Login dengan nomor XL
/balance - Lihat saldo dan masa aktif
/packages - Beli paket XUT
/help - Tampilkan bantuan ini

**Tips:**
• Pastikan nomor XL aktif dan prabayar
• Format nomor: 6281234567890
• Bot hanya support paket XUT
        """,
        
        "not_logged_in": "❌ Anda belum login!\nSilakan login terlebih dahulu dengan /login",
        
        "login_prompt": """
📱 **Login ke MyXL**

Silakan masukkan nomor XL Prabayar Anda:
Format: 6281234567890

Ketik /cancel untuk membatalkan
        """,
        
        "otp_sent": """
✅ **OTP berhasil dikirim!**

📱 Silakan masukkan kode OTP 6 digit yang diterima via SMS:

Ketik /cancel untuk membatalkan
        """,
        
        "login_success": """
✅ **Login berhasil!**

Sekarang Anda dapat:
• /balance - Cek saldo
• /packages - Beli paket XUT
• /help - Bantuan
        """,
        
        "purchase_success": """
✅ **Paket berhasil dibeli!**

Silakan cek aplikasi MyXL untuk konfirmasi.
Paket akan aktif dalam beberapa menit.
        """,
        
        "errors": {
            "invalid_phone": "❌ Nomor tidak valid!\nPastikan format: 6281234567890",
            "invalid_otp": "❌ Kode OTP tidak valid!\nMasukkan 6 digit angka",
            "otp_failed": "❌ OTP salah atau expired!\nSilakan login ulang dengan /login",
            "network_error": "❌ Terjadi kesalahan jaringan. Coba lagi nanti.",
            "api_error": "❌ Terjadi kesalahan pada server. Coba lagi nanti.",
            "purchase_failed": "❌ Pembelian gagal! Pastikan saldo mencukupi."
        }
    }
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration"""
        if not cls.BOT_TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN tidak diset")
            return False
            
        if not cls.API_KEY:
            print("❌ MYXL_API_KEY tidak diset")
            return False
            
        return True
