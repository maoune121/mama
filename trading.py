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
CHECK_INTERVAL = 29  # فحص الأسعار كل 29 ثانية

# إعداد سجل التصحيح
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# تفعيل الـ Intents المطلوبة
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# إنشاء البوت مع بادئة الأوامر "/"
bot = commands.Bot(command_prefix="/", intents=intents)

# قائمة التنبيهات المخزنة: مفهرسة حسب معرف السيرفر ثم حسب العملة.
# كل تنبيه يحتوي على:
# - target_price: السعر الهدف
# - channel_id: معرف القناة
alerts = {}

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert GBPUSD 1.2999
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
                    interval=Interval.INTERVAL_5_MINUTES  # استخدام شمعة 5 دقائق
                )
                analysis = handler.get_analysis()
                indicators = analysis.indicators
                high_price = float(indicators.get('high', 0))
                low_price = float(indicators.get('low', 0))
                logger.debug(f"🔹 {symbol}: High={high_price}, Low={low_price}, Target={target_price}")
                
                # التحقق مما إذا كان السعر الهدف ضمن نطاق الشمعة الحالية
                if low_price <= target_price <= high_price:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(
                            f"🚨 تنبيه: {symbol} لمس السعر المطلوب {target_price} خلال آخر 5 دقائق!"
                        )
                        logger.debug(f"✅ تم إرسال التنبيه لـ {symbol} إلى القناة {channel_id}")
                    # حذف التنبيه بعد إرساله لمنع التكرار
                    del alerts[guild_id][symbol]
            except Exception as e:
                logger.error(f"⚠️ خطأ أثناء جلب بيانات {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ تم تسجيل الدخول كـ {bot.user}")
    
    # عند بدء التشغيل، نقوم بفحص الرسائل في كل قناة نصية لكل سيرفر لاستعادة التنبيهات غير المنفذة
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                # جلب آخر 50 رسالة من القناة
                messages = [msg async for msg in channel.history(limit=50)]
                for msg in messages:
                    # نبحث فقط عن رسائل البوت (Trading Alert #0520)
                    if msg.author.id == bot.user.id:
                        content = msg.content
                        # إذا كانت الرسالة تحتوي على "تم ضبط تنبيه" ولا تحتوي على "تنبيه:"
                        if "تم ضبط تنبيه" in content and "تنبيه:" not in content:
                            # استخراج العملة والسعر باستخدام تعبير منتظم
                            pattern = r"تم ضبط تنبيه لـ \*\*(.+?)\*\* عند السعر \*\*(.+?)\*\* في هذه القناة\."
                            match = re.search(pattern, content)
                            if match:
                                symbol_found = match.group(1).upper()
                                try:
                                    target_price_found = float(match.group(2))
                                except ValueError:
                                    continue
                                # التأكد من عدم وجود رسالة تنبيه (🚨 تنبيه:) لنفس العملة والسعر في نفس مجموعة الرسائل
                                alert_already_sent = False
                                for m in messages:
                                    if m.author.id == bot.user.id and "تنبيه:" in m.content:
                                        if symbol_found in m.content and str(target_price_found) in m.content:
                                            alert_already_sent = True
                                            break
                                if not alert_already_sent:
                                    if guild.id not in alerts:
                                        alerts[guild.id] = {}
                                    if symbol_found not in alerts[guild.id]:
                                        alerts[guild.id][symbol_found] = {
                                            "target_price": target_price_found,
                                            "channel_id": channel.id
                                        }
                                        logger.debug(f"↻ إعادة ضبط تنبيه: {symbol_found} عند {target_price_found} في القناة {channel.id}")
            except Exception as e:
                logger.error(f"❌ خطأ في قراءة قناة {channel.name}: {e}")
    
    # بدء مهمة فحص الأسعار
    check_prices.start()

# بدء خادم keep_alive ثم تشغيل البوت
keep_alive()
bot.run(TOKEN)
