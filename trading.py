import os
import discord
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
import logging
from keep_alive import keep_alive  # Import the keep_alive function
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))  # السيرفر ID
CHECK_INTERVAL = 30  # عدد الثواني بين كل فحص

# إعداد سجل التصحيح
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# تفعيل الـ Intents مع تفعيل صلاحية قراءة محتوى الرسائل
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# إنشاء البوت مع تعيين بادئة الأوامر (prefix="/")
bot = commands.Bot(command_prefix="/", intents=intents)

# قائمة التنبيهات المخزنة
alerts = {}

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert usdcad 1.427822
    حيث يتم حفظ التنبيه مع معرف القناة التي كتب فيها الأمر.
    """
    if ctx.guild.id not in alerts:
        alerts[ctx.guild.id] = {}

    alerts[ctx.guild.id][symbol.upper()] = {
        "target_price": target_price,
        "channel_id": ctx.channel.id
    }
    
    await ctx.send(f"✅ تم ضبط تنبيه لـ **{symbol.upper()}** عند السعر **{target_price}** في هذه القناة.")
    logger.debug(f"تنبيه جديد مضاف: {symbol.upper()} عند {target_price} في السيرفر {ctx.guild.id}")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_prices():
    logger.debug("🔎 بدء فحص الأسعار...")

    for guild_id, guild_alerts in alerts.items():
        for symbol, alert_data in guild_alerts.items():
            target_price = alert_data["target_price"]
            channel_id = alert_data["channel_id"]

            try:
                handler = TA_Handler(
                    symbol=symbol,
                    screener="forex",
                    exchange="OANDA",
                    interval=Interval.INTERVAL_1_MINUTE
                )
                analysis = handler.get_analysis().indicators
                high_price = float(analysis.get('high', 0))
                low_price = float(analysis.get('low', 0))
                logger.debug(f"🔹 {symbol}: High={high_price}, Low={low_price}")

                # تحقق من آخر رسالة مرسلة في القناة
                channel = bot.get_channel(channel_id)
                if not channel:
                    logger.error(f"❌ القناة {channel_id} غير موجودة!")
                    continue
                
                async for last_message in channel.history(limit=1):
                    if last_message.author == bot.user and "تم ضبط التنبيه" in last_message.content:
                        # أضف هذا التنبيه للقائمة لأنه لم يصل بعد
                        if guild_id not in alerts:
                            alerts[guild_id] = {}
                        alerts[guild_id][symbol] = alert_data

                # تحقق إذا السعر وصل إلى الهدف
                if low_price <= target_price <= high_price:
                    await channel.send(f"🚨 **{symbol}** لمس السعر المطلوب **{target_price}**!")
                    del alerts[guild_id][symbol]
                    logger.debug(f"✅ تم إرسال التنبيه لـ {symbol} إلى القناة {channel_id}")
            except Exception as e:
                logger.error(f"⚠️ خطأ أثناء جلب بيانات {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ تم تسجيل الدخول كـ {bot.user}")
    check_prices.start()

# تشغيل البوت
keep_alive()
bot.run(TOKEN)
