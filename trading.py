import os
import re
import discord
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
import logging
from keep_alive import keep_alive  # استيراد دالة keep_alive
from dotenv import load_dotenv

# تحميل المتغيرات البيئية من ملف .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHECK_INTERVAL = 30  # ثواني بين كل فحص

# إعداد سجل التصحيح
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# تفعيل Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# إنشاء البوت
bot = commands.Bot(command_prefix="/", intents=intents)

# قائمة التنبيهات المخزنة: مفهرسة حسب معرف السيرفر ثم العملة
alerts = {}

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert USDCAD 1.9
    حيث يتم حفظ التنبيه مع معرف القناة التي تم فيها ضبط الأمر.
    """
    if ctx.guild.id not in alerts:
        alerts[ctx.guild.id] = {}
    
    alerts[ctx.guild.id][symbol.upper()] = {
        "target_price": target_price,
        "channel_id": ctx.channel.id
    }
    
    msg = f"✅ تم ضبط تنبيه لـ **{symbol.upper()}** عند السعر **{target_price}** في هذه القناة."
    await ctx.send(msg)
    logger.debug(f"تنبيه جديد مضاف: {symbol.upper()} عند {target_price} في السيرفر {ctx.guild.id}")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_prices():
    logger.debug("🔎 بدء فحص الأسعار...")
    
    # المرور على التنبيهات لكل سيرفر
    for guild_id, guild_alerts in list(alerts.items()):
        for symbol, alert_data in list(guild_alerts.items()):
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
                
                # تحقق إذا كان السعر المستهدف ضمن نطاق الشمعة
                if low_price <= target_price <= high_price:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(f"🚨 تنبيه: **{symbol}** لمس السعر المطلوب **{target_price}** خلال آخر دقيقة!")
                        logger.debug(f"✅ تم إرسال التنبيه لـ {symbol} إلى القناة {channel_id}")
                    del alerts[guild_id][symbol]
            except Exception as e:
                logger.error(f"⚠️ خطأ أثناء جلب بيانات {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ تم تسجيل الدخول كـ {bot.user}")
    
    # عند بدء التشغيل، فحص آخر رسالة مرسلة من البوت في كل قناة بالنصوص في كل السيرفرات
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=1):
                    if msg.author == bot.user:
                        content = msg.content
                        # إذا كانت الرسالة تحتوي على نص ضبط التنبيه
                        # مثال: "تم ضبط تنبيه لـ USDCAD عند السعر 1.9 في هذه القناة."
                        if "تم ضبط تنبيه" in content and "تنبيه:" not in content:
                            pattern = r"تم ضبط تنبيه لـ \*\*(.+?)\*\* عند السعر \*\*(.+?)\*\* في هذه القناة\."
                            match = re.search(pattern, content)
                            if match:
                                symbol = match.group(1)
                                try:
                                    target_price = float(match.group(2))
                                except ValueError:
                                    continue
                                # إعادة حفظ التنبيه إذا لم يكن موجودًا
                                if guild.id not in alerts:
                                    alerts[guild.id] = {}
                                if symbol.upper() not in alerts[guild.id]:
                                    alerts[guild.id][symbol.upper()] = {
                                        "target_price": target_price,
                                        "channel_id": channel.id
                                    }
                                    logger.debug(f"↻ إعادة ضبط تنبيه: {symbol.upper()} عند {target_price} في القناة {channel.id}")
                        # إذا كانت الرسالة تحتوي على تنبيه مفعل (مثال: "🚨 تنبيه: USDCAD لمس السعر المطلوب ...") فلا نقوم بأي إجراء
            except Exception as e:
                logger.error(f"❌ خطأ في قراءة قناة {channel.name}: {e}")
    
    # بدء مهمة فحص الأسعار
    check_prices.start()

# بدء keep_alive ثم تشغيل البوت
keep_alive()
bot.run(TOKEN)
