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
CHECK_INTERVAL = 27  # فحص كل 27 ثانية

# إعداد سجل التصحيح
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# تفعيل Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# إنشاء البوت مع بادئة الأوامر "/"
bot = commands.Bot(command_prefix="/", intents=intents)

# قائمة التنبيهات المخزنة: مفهرسة حسب معرف السيرفر ثم حسب العملة.
# كل تنبيه يحتوي على:
# - target_price: السعر الهدف
# - channel_id: معرف القناة
# - candle_buffer: قائمة (list) لتخزين بيانات آخر شمعتين؛ كل شمعة عبارة عن dict يحتوي على "time", "high", "low"
alerts = {}

def update_candle_buffer(buffer, new_candle):
    """
    يحدث المخزن (buffer) بحيث يحتوي فقط على آخر شمعتين.
    """
    if len(buffer) == 2:
        buffer.pop(0)
    buffer.append(new_candle)
    return buffer

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert GBPUSD 1.29963
    حيث يتم حفظ التنبيه مع معرف القناة التي تم فيها ضبط الأمر.
    """
    if ctx.guild.id not in alerts:
        alerts[ctx.guild.id] = {}
    
    alerts[ctx.guild.id][symbol.upper()] = {
        "target_price": target_price,
        "channel_id": ctx.channel.id,
        "candle_buffer": []  # يبدأ المخزن فارغاً
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
                current_time = analysis.time  # نفترض أن analysis.time يحتوي على توقيت الشمعة الحالية

                # إنشاء بيانات الشمعة الجديدة
                new_candle = {"time": current_time, "high": high_price, "low": low_price}
                # تحديث المخزن الخاص بهذا التنبيه
                alert_data["candle_buffer"] = update_candle_buffer(alert_data["candle_buffer"], new_candle)

                # إذا كانت لدينا بيانات الشمعتين، نقوم بفحص كل شمعة على حدة
                if len(alert_data["candle_buffer"]) >= 1:
                    alert_triggered = False
                    for candle in alert_data["candle_buffer"]:
                        c_high = candle["high"]
                        c_low = candle["low"]
                        if c_low <= target_price <= c_high:
                            alert_triggered = True
                            break
                    if alert_triggered:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send(
                                f"🚨 تنبيه: **{symbol}** لمس السعر المطلوب **{target_price}** خلال آخر 5 دقائق!"
                            )
                            logger.debug(f"✅ تم إرسال التنبيه لـ {symbol} إلى القناة {channel_id}")
                        # حذف التنبيه بعد إرساله لمنع التكرار
                        del alerts[guild_id][symbol]
            except Exception as e:
                logger.error(f"⚠️ خطأ أثناء جلب بيانات {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ تم تسجيل الدخول كـ {bot.user}")
    
    # عند بدء التشغيل، فحص آخر رسالة مرسلة من البوت في كل قناة بالنصوص في جميع السيرفرات
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=1):
                    if msg.author == bot.user:
                        content = msg.content
                        # إذا كانت الرسالة تتبع تنسيق ضبط التنبيه وليس التنبيه الفعلي
                        if "تم ضبط تنبيه" in content and "تنبيه:" not in content:
                            pattern = r"تم ضبط تنبيه لـ \*\*(.+?)\*\* عند السعر \*\*(.+?)\*\* في هذه القناة\."
                            match = re.search(pattern, content)
                            if match:
                                symbol_found = match.group(1)
                                try:
                                    target_price_found = float(match.group(2))
                                except ValueError:
                                    continue
                                if guild.id not in alerts:
                                    alerts[guild.id] = {}
                                if symbol_found.upper() not in alerts[guild.id]:
                                    alerts[guild.id][symbol_found.upper()] = {
                                        "target_price": target_price_found,
                                        "channel_id": channel.id,
                                        "candle_buffer": []  # يبدأ المخزن فارغاً
                                    }
                                    logger.debug(f"↻ إعادة ضبط تنبيه: {symbol_found.upper()} عند {target_price_found} في القناة {channel.id}")
                        # إذا كانت الرسالة تحتوي على تنبيه مفعل (مثال: "🚨 تنبيه: ...") فلا نقوم بأي إجراء
            except Exception as e:
                logger.error(f"❌ خطأ في قراءة قناة {channel.name}: {e}")
    
    # بدء مهمة فحص الأسعار
    check_prices.start()

# بدء خادم keep_alive ثم تشغيل البوت
keep_alive()
bot.run(TOKEN)
