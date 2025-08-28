import os
import logging
from datetime import datetime
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Import dari modul lokal
# get_profile, get_balance, get_new_token, get_otp, submit_otp, get_package, purchase_package, send_api_request, validate_contact
from api_request import *
from paket_xut import get_package_xut
from util import verify_api_key
from dotenv import load_dotenv

# ------------------------------------------------------------
# Logging Utama (error/debugging)
# ------------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Logging Aktivitas (login & pembelian paket)
# ------------------------------------------------------------
activity_logger = logging.getLogger("activity")
activity_logger.setLevel(logging.INFO)

fh = logging.FileHandler("activity.log", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(message)s")
fh.setFormatter(formatter)
activity_logger.addHandler(fh)

ADMIN_ID = os.getenv("ADMIN_TELEGRAM_ID")  # isi di .env
bot_notifier = None  # akan diisi setelah bot jalan


async def log_activity(user, action: str):
    """Log aktivitas ke file + kirim ke admin telegram"""
    tg_user = f"{user.full_name} (id={user.id}, username=@{user.username})"
    msg = f"[{action}] {tg_user}"

    # tulis ke file
    activity_logger.info(msg)

    # kirim ke admin telegram (jika bot sudah siap)
    if bot_notifier and ADMIN_ID:
        try:
            await bot_notifier.send_message(chat_id=ADMIN_ID, text=msg)
        except Exception as e:
            activity_logger.error(f"Gagal kirim log ke admin: {e}")


# ------------------------------------------------------------
# Global session (untuk demo; production sebaiknya pakai DB)
# ------------------------------------------------------------
user_sessions: Dict[int, Dict[str, Any]] = {}


# ------------------------------------------------------------
# Bot Class
# ------------------------------------------------------------
class MyXLTelegramBot:

    def __init__(self, bot_token: str, api_key: str):
        self.bot_token = bot_token
        self.api_key = api_key
        self.application = Application.builder().token(bot_token).build()

        # isi bot_notifier global agar bisa dipakai log_activity()
        global bot_notifier
        bot_notifier = self.application.bot

        # mapping callback_data pendek -> package_option_code (UUID)
        self.package_map: Dict[str, str] = {}
        self.setup_handlers()

    # -------------------- helper --------------------
    def _prefer_edit(self, update: Update) -> bool:
        """True bila datang dari tombol (CallbackQuery) dan ada message yang bisa diedit."""
        return bool(update.callback_query and update.callback_query.message)

    async def _send(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup=None,
        prefer_edit: bool | None = None,
    ):
        """
        Kirim respons aman: edit pesan jika dari callback, atau reply bila dari command.
        Fallback ke bot.send_message bila objek message tidak tersedia.
        """
        if prefer_edit is None:
            prefer_edit = self._prefer_edit(update)

        try:
            if prefer_edit and update.callback_query and update.callback_query.message:
                await update.callback_query.message.edit_text(
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup)
                return

            if update.message:
                await update.message.reply_text(text,
                                                parse_mode=parse_mode,
                                                reply_markup=reply_markup)
                return

            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(
                    text, parse_mode=parse_mode, reply_markup=reply_markup)
                return

            # Fallback terakhir
            chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
            await context.bot.send_message(chat_id=chat_id,
                                           text=text,
                                           parse_mode=parse_mode,
                                           reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"_send failed: {e}")
            # Fallback terakhir2
            try:
                chat_id = update.effective_chat.id if update.effective_chat else update.effective_user.id
                await context.bot.send_message(chat_id=chat_id,
                                               text=text,
                                               parse_mode=parse_mode,
                                               reply_markup=reply_markup)
            except Exception as e2:
                logger.error(f"_send fallback failed: {e2}")

    # -------------------- handlers setup --------------------
    def setup_handlers(self):
        self.application.add_handler(
            CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(
            CommandHandler("login", self.login_command))
        self.application.add_handler(
            CommandHandler("kuota", self.kuota_command))
        self.application.add_handler(
            CommandHandler("packages", self.packages_command))
        self.application.add_handler(CommandHandler("menu", self.menu_command))

        self.application.add_handler(CallbackQueryHandler(
            self.button_callback))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND,
                           self.handle_message))

        # Error handler global
        self.application.add_error_handler(self.error_handler)

    # -------------------- error handler --------------------
    async def error_handler(self, update: object,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled exception", exc_info=context.error)

    # -------------------- commands --------------------
    async def start_command(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                "state": "idle",
                "is_logged_in": False,
                "phone_number": None,
                "tokens": None,
                "waiting_for": None,
            }

        welcome_text = ("🤖 **Selamat datang di DoyStore DorXL Bot!**\n\n"
                        "Fitur:\n"
                        "• Login MyXL\n"
                        "• Cek saldo & masa aktif\n"
                        "• Beli paket\n\n"
                        "Perintah:\n"
                        "/login - Login ke MyXL\n"
                        "/menu  - Buka menu utama\n"
                        "/help  - Bantuan\n\n"
                        "Untuk mulai, silakan login dengan /login")
        await self._send(update, context, welcome_text)

    async def help_command(self, update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
        help_text = ("🔧 **Bantuan Bot**\n\n"
                     "1) /login kemudian masukkan nomor XL\n"
                     "2) Masukkan OTP dari SMS\n"
                     "3) Setelah login, gunakan /menu untuk akses fitur\n\n"
                     "👉 Gunakan tombol untuk navigasi.")
        keyboard = [[
            InlineKeyboardButton("⬅️ Kembali ke Menu",
                                 callback_data="menu_back")
        ]]
        await self._send(update,
                         context,
                         help_text,
                         reply_markup=InlineKeyboardMarkup(keyboard))

    async def login_command(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                "state": "idle",
                "is_logged_in": False,
                "phone_number": None,
                "tokens": None,
                "waiting_for": None,
            }

        if user_sessions[user_id]["is_logged_in"]:
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Login Ulang",
                                         callback_data="relogin")
                ],
                [InlineKeyboardButton("❌ Batal", callback_data="cancel")],
            ]
            await self._send(
                update,
                context,
                f"Anda sudah login sebagai {user_sessions[user_id]['phone_number']}\n\nIngin login ulang?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        user_sessions[user_id]["state"] = "waiting_phone"
        user_sessions[user_id]["waiting_for"] = "phone_number"
        await self._send(
            update,
            context,
            "📱 **Login ke MyXL**\n\nMasukkan nomor XL prabayar Anda (format: 6281234567890)\n\nKetik /cancel untuk batal",
        )

    async def menu_command(self, update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in user_sessions or not user_sessions[user_id][
                "is_logged_in"]:
            await self._send(update, context,
                             "❌ Anda belum login!\nSilakan /login")
            return

        session = user_sessions[user_id]
        tokens = session.get("tokens")
        try:
            profile = get_profile(self.api_key, tokens["access_token"],
                                  tokens["id_token"])
            balance = get_balance(self.api_key, tokens["id_token"])

            if profile and balance:
                phone_number = profile["profile"]["msisdn"]
                balance_remaining = balance["remaining"]
                balance_expired = datetime.fromtimestamp(
                    balance["expired_at"]).strftime("%Y-%m-%d %H:%M:%S")

                account_text = ("🏠 **Menu Utama**\n\n"
                                "💰 **Informasi Akun**\n"
                                f"📱 Nomor: `{phone_number}`\n"
                                f"💵 Pulsa: Rp {balance_remaining:,}\n"
                                f"⏰ Masa Aktif: {balance_expired}\n\n"
                                "👉 Pilih menu di bawah:")

                keyboard = [
                    [
                        InlineKeyboardButton("📊 Cek Kuota",
                                             callback_data="menu_kuota")
                    ],
                    [
                        InlineKeyboardButton("📦 Lihat Paket",
                                             callback_data="menu_packages")
                    ],
                    [
                        InlineKeyboardButton("ℹ️ Bantuan",
                                             callback_data="menu_help")
                    ],
                    [
                        InlineKeyboardButton("🚪 Logout",
                                             callback_data="menu_logout")
                    ],
                ]
                await self._send(update,
                                 context,
                                 account_text,
                                 reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await self._send(
                    update, context,
                    "❌ Gagal mengambil data akun. Silakan /login ulang.")

        except Exception as e:
            logger.error(f"Error in menu_command: {e}")
            await self._send(update, context,
                             "❌ Terjadi kesalahan saat mengambil menu akun.")

    async def kuota_command(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in user_sessions or not user_sessions[user_id][
                "is_logged_in"]:
            await self._send(update, context,
                             "❌ Anda belum login!\nSilakan /login")
            return

        # progress
        await self._send(update,
                         context,
                         "⏳ Mengambil data kuota...",
                         prefer_edit=True)

        try:
            session = user_sessions[user_id]
            tokens = get_new_token(session["tokens"]["refresh_token"]
                                   ) if session.get("tokens") else None
            if tokens:
                session["tokens"] = tokens
            else:
                await self._send(update,
                                 context,
                                 "❌ Sesi kadaluarsa. Silakan /login ulang.",
                                 prefer_edit=True)
                return

            path = "api/v8/packages/quota-details"
            payload = {
                "is_enterprise": False,
                "lang": "en",
                "family_member_id": ""
            }
            res = send_api_request(self.api_key, path, payload,
                                   tokens["id_token"], "POST")

            if res.get("status") != "SUCCESS":
                await self._send(update,
                                 context,
                                 "❌ Gagal mengambil kuota.",
                                 prefer_edit=True)
                return

            quotas = res["data"]["quotas"]
            if not quotas:
                text = "ℹ️ Tidak ada kuota aktif."
            else:
                text_lines = ["📊 **Kuota Aktif:**\n"]
                for idx, quota in enumerate(quotas, start=1):
                    name = quota.get("name", "N/A")
                    remaining = quota.get("remaining", "-")
                    total = quota.get("total", "-")
                    text_lines.append(
                        f"{idx}. {name}\n   ➡️ {remaining} / {total}")
                text = "\n".join(text_lines)

            keyboard = [[
                InlineKeyboardButton("⬅️ Kembali ke Menu",
                                     callback_data="menu_back")
            ]]
            await self._send(update,
                             context,
                             text,
                             reply_markup=InlineKeyboardMarkup(keyboard),
                             prefer_edit=True)

        except Exception as e:
            logger.error(f"Error getting quota: {e}")
            await self._send(update,
                             context,
                             "❌ Terjadi kesalahan saat mengambil data kuota",
                             prefer_edit=True)

    async def packages_command(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in user_sessions or not user_sessions[user_id][
                "is_logged_in"]:
            await self._send(update, context,
                             "❌ Anda belum login!\nSilakan /login")
            return

        # progress
        await self._send(update,
                         context,
                         "⏳ Mengambil data paket...",
                         prefer_edit=True)

        try:
            session = user_sessions[user_id]
            new_tokens = get_new_token(session["tokens"]["refresh_token"]
                                       ) if session.get("tokens") else None
            if new_tokens:
                session["tokens"] = new_tokens
            else:
                await self._send(update,
                                 context,
                                 "❌ Sesi kadaluarsa. Silakan /login ulang.",
                                 prefer_edit=True)
                return

            packages = get_package_xut(self.api_key, session["tokens"])
            if not packages:
                await self._send(update,
                                 context,
                                 "❌ Tidak ada paket tersedia",
                                 prefer_edit=True)
                return

            # reset mapping setiap buka menu packages
            self.package_map.clear()

            keyboard = []
            for idx, pkg in enumerate(packages, start=1):
                short_code = f"pkg{idx}"
                self.package_map[short_code] = pkg['code']  # simpan UUID asli
                label = f"📦 {pkg['name']} - Rp {pkg['price']:,}"
                keyboard.append(
                    [InlineKeyboardButton(label, callback_data=short_code)])

            keyboard.append([
                InlineKeyboardButton("⬅️ Kembali ke Menu",
                                     callback_data="menu_back")
            ])
            await self._send(
                update,
                context,
                "📦 **Paket Tersedia:**\n\nPilih paket:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                prefer_edit=True,
            )
        except Exception as e:
            logger.error(f"Error getting packages: {e}")
            await self._send(update,
                             context,
                             "❌ Terjadi kesalahan saat mengambil data paket",
                             prefer_edit=True)

    # -------------------- callbacks --------------------
    async def button_callback(self, update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        data = query.data

        if data == "cancel":
            if user_id in user_sessions:
                user_sessions[user_id]["state"] = "idle"
                user_sessions[user_id]["waiting_for"] = None
            await self._send(update, context, "❌ Dibatalkan", prefer_edit=True)
            return

        if data == "relogin":
            user_sessions[user_id] = {
                "state": "waiting_phone",
                "is_logged_in": False,
                "phone_number": None,
                "tokens": None,
                "waiting_for": "phone_number",
            }
            await self._send(
                update,
                context,
                "📱 **Login ke MyXL**\n\nSilakan masukkan nomor XL Prabayar Anda:\nFormat: 6281234567890",
                prefer_edit=True,
            )
            return

        # Navigasi menu
        if data == "menu_kuota":
            await self.kuota_command(update, context)
            return
        if data == "menu_packages":
            await self.packages_command(update, context)
            return
        if data == "menu_help":
            await self.help_command(update, context)
            return
        if data == "menu_back":
            await self.menu_command(update, context)
            return
        if data == "menu_logout":
            user_sessions[user_id] = {
                "state": "idle",
                "is_logged_in": False,
                "phone_number": None,
                "tokens": None,
                "waiting_for": None,
            }
            await self._send(update,
                             context,
                             "✅ Anda telah logout.",
                             prefer_edit=True)
            return

        # Alur pilih paket → detail → konfirmasi → proses beli
        if data.startswith("pkg"):
            package_code = self.package_map.get(data)
            if package_code:
                await self.handle_package_purchase(update, context, user_id,
                                                   package_code)
            else:
                await self._send(update,
                                 context,
                                 "❌ Paket tidak ditemukan",
                                 prefer_edit=True)
            return

        if data.startswith("confirm"):
            package_code = self.package_map.get(data)
            if package_code:
                await self.process_package_purchase(update, context, user_id,
                                                    package_code)
            else:
                await self._send(update,
                                 context,
                                 "❌ Paket tidak ditemukan",
                                 prefer_edit=True)
            return

    # -------------------- purchase flow (AMAN dari NoneType) --------------------
    async def handle_package_purchase(self, update: Update,
                                      context: ContextTypes.DEFAULT_TYPE,
                                      user_id: int, package_code: str):
        """
        Tampilkan detail paket & tombol konfirmasi.
        Menggunakan _send(prefer_edit=True) agar aman untuk callback & tidak spam pesan.
        """
        try:
            session = user_sessions[user_id]
            package_details = get_package(self.api_key, session["tokens"],
                                          package_code)
            if not package_details:
                await self._send(update,
                                 context,
                                 "❌ Gagal mengambil detail paket",
                                 prefer_edit=True)
                return

            name1 = package_details.get("package_family", {}).get("name", "")
            name2 = package_details.get("package_detail_variant",
                                        {}).get("name", "")
            name3 = package_details.get("package_option", {}).get("name", "")
            price = package_details["package_option"]["price"]
            title = f"{name1} {name2} {name3}".strip()

            detail_text = ("📦 **Detail Paket**\n\n"
                           f"📋 Nama: {title}\n"
                           f"💰 Harga: Rp {price:,}\n\n"
                           "⚠️ Pastikan pulsa mencukupi sebelum membeli!\n\n"
                           "Lanjutkan pembelian?")

            confirm_code = f"confirm_{user_id}_{package_code[:8]}"
            self.package_map[confirm_code] = package_code
            keyboard = [
                [
                    InlineKeyboardButton("✅ Ya, Beli",
                                         callback_data=confirm_code)
                ],
                [
                    InlineKeyboardButton("⬅️ Kembali ke Menu",
                                         callback_data="menu_back")
                ],
            ]
            await self._send(update,
                             context,
                             detail_text,
                             reply_markup=InlineKeyboardMarkup(keyboard),
                             prefer_edit=True)

        except Exception as e:
            logger.error(f"Error handling package purchase: {e}")
            await self._send(update,
                             context,
                             "❌ Terjadi kesalahan saat memproses paket",
                             prefer_edit=True)

    async def process_package_purchase(self, update: Update,
                                       context: ContextTypes.DEFAULT_TYPE,
                                       user_id: int, package_code: str):
        """Proses beli paket. Aman untuk callback. Token direfresh dulu untuk menghindari gagal."""
        # progress
        await self._send(update,
                         context,
                         "⏳ Memproses pembelian paket...",
                         prefer_edit=True)

        try:
            session = user_sessions[user_id]

            # Refresh token sebelum beli (lebih andal)
            try:
                new_tokens = get_new_token(session["tokens"]["refresh_token"]
                                           ) if session.get("tokens") else None
                if new_tokens:
                    session["tokens"] = new_tokens
            except Exception as e:
                logger.warning(
                    f"Token refresh sebelum beli gagal (lanjut pakai token lama): {e}"
                )

            # Call purchase
            try:
                result = purchase_package(self.api_key, session["tokens"],
                                          package_code)
            except Exception as e:
                logger.error(f"purchase_package raised: {e}")
                result = {"status": "FAILED", "message": "Terjadi kesalahan"}

            # Hasil
            if result and result.get("status") == "SUCCESS":
                # Ambil detail paket
                try:
                    pkg = get_package(self.api_key, session["tokens"],
                                      package_code)
                    pkg_name = pkg.get("package_option",
                                       {}).get("name", "Unknown")
                    pkg_price = pkg.get("package_option", {}).get("price", 0)
                except Exception:
                    pkg_name, pkg_price = "Unknown", 0

                msg = f"✅ **Paket berhasil dibeli!**\n\n📦 {pkg_name}\n💰 Rp {pkg_price:,}\n\nSilakan cek aplikasi MyXL."

                # 🔥 Log aktivitas
                await log_activity(
                    update.effective_user,
                    f"Pembelian paket sukses | Nomor: {session.get('phone_number')} | Paket: {pkg_name} | Harga: Rp {pkg_price:,}"
                )

            else:
                error_code = result.get("message") if result else None
                if error_code == "BALANCE_INSUFFICIENT":
                    human_msg = "Pulsa tidak cukup untuk membeli paket ini."
                else:
                    human_msg = error_code or "Pembelian gagal"

                msg = f"❌ **Pembelian gagal!**\n\n{human_msg}"

                # 🔥 Log aktivitas gagal
                await log_activity(
                    update.effective_user,
                    f"Pembelian paket GAGAL | Nomor: {session.get('phone_number')} | PaketCode: {package_code} | Alasan: {human_msg}"
                )

            # Tombol kembali ke menu
            keyboard = [[
                InlineKeyboardButton("⬅️ Kembali ke Menu",
                                     callback_data="menu_back")
            ]]
            await self._send(update,
                             context,
                             msg,
                             reply_markup=InlineKeyboardMarkup(keyboard),
                             prefer_edit=True)

        except Exception as e:
            logger.error(f"Error processing purchase: {e}")
            await self._send(update,
                             context,
                             "❌ Terjadi kesalahan saat pembelian paket",
                             prefer_edit=True)

            # 🔥 Log error umum
            await log_activity(
                update.effective_user,
                f"ERROR saat pembelian | Nomor: {session.get('phone_number')} | PackageCode: {package_code} | Error: {e}"
            )

    # -------------------- text messages --------------------
    async def handle_message(self, update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        message_text = (update.message.text or "").strip()

        if message_text == "/cancel":
            if user_id in user_sessions:
                user_sessions[user_id]["state"] = "idle"
                user_sessions[user_id]["waiting_for"] = None
            await self._send(update, context, "❌ Dibatalkan")
            return

        if user_id not in user_sessions:
            await self._send(update, context,
                             "Silakan mulai dengan /start terlebih dahulu")
            return

        session = user_sessions[user_id]
        if session.get("waiting_for") == "phone_number":
            await self.handle_phone_number(update, context, user_id,
                                           message_text)
        elif session.get("waiting_for") == "otp":
            await self.handle_otp(update, context, user_id, message_text)
        else:
            await self._send(update, context, "Gunakan /menu untuk navigasi")

    # -------------------- phone & otp --------------------
    async def handle_phone_number(self, update: Update,
                                  context: ContextTypes.DEFAULT_TYPE,
                                  user_id: int, phone_number: str):
        if not validate_contact(phone_number):
            await self._send(update, context,
                             "❌ Nomor tidak valid! Format: 6281234567890")
            return

        await self._send(update, context, "⏳ Mengirim OTP...")
        try:
            subscriber_id = get_otp(phone_number)
            if not subscriber_id:
                await self._send(update, context,
                                 "❌ Gagal mengirim OTP.\nCoba /login lagi")
                user_sessions[user_id]["state"] = "idle"
                user_sessions[user_id]["waiting_for"] = None
                return

            user_sessions[user_id]["phone_number"] = phone_number
            user_sessions[user_id]["waiting_for"] = "otp"
            await self._send(update, context,
                             "✅ OTP dikirim!\n\nMasukkan kode OTP 6 digit:")
        except Exception as e:
            logger.error(f"Error sending OTP: {e}")
            await self._send(update, context,
                             "❌ Terjadi kesalahan saat mengirim OTP")

    async def handle_otp(self, update: Update,
                         context: ContextTypes.DEFAULT_TYPE, user_id: int,
                         otp_code: str):
        if not otp_code.isdigit() or len(otp_code) != 6:
            await self._send(
                update, context,
                "❌ Kode OTP tidak valid! Masukkan 6 digit angka:")
            return

        await self._send(update, context, "⏳ Memverifikasi OTP...")
        try:
            session = user_sessions[user_id]
            phone_number = session.get("phone_number")
            tokens = submit_otp(phone_number, otp_code)
            if not tokens:
                await self._send(update, context,
                                 "❌ OTP salah/expired. /login ulang")
                user_sessions[user_id]["state"] = "idle"
                user_sessions[user_id]["waiting_for"] = None
                return

            user_sessions[user_id].update({
                "is_logged_in": True,
                "tokens": tokens,
                "state": "idle",
                "waiting_for": None,
            })

            # 🔥 Log login sukses
            await log_activity(update.effective_user,
                               f"Login berhasil | Nomor: {phone_number}")

            # ✅ Setelah login sukses → langsung ke menu utama
            await self.menu_command(update, context)

        except Exception as e:
            logger.error(f"Error verifying OTP: {e}")
            await self._send(update, context,
                             "❌ Terjadi kesalahan saat verifikasi OTP")

            # 🔥 Log error login
            await log_activity(
                update.effective_user,
                f"Login ERROR | Nomor: {session.get('phone_number')} | Error: {e}"
            )

    # -------------------- run --------------------
    def run(self):
        logger.info("Starting Doy Telegram Bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


# -------------------- entrypoint --------------------
def main():
    load_dotenv()


    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("MYXL_API_KEY")

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN tidak ditemukan di environment variables")
        return
    if not api_key:
        print("❌ MYXL_API_KEY tidak ditemukan di environment variables")
        return

    if not verify_api_key(api_key):
        print("❌ API key tidak valid")
        return

    bot = MyXLTelegramBot(bot_token, api_key)
    bot.run()


if __name__ == "__main__":
    main()

