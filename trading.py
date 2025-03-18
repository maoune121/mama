import discord
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
import logging
import os  # لإدارة متغيرات البيئة

# إعداد سجل التصحيح
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# تفعيل الـ Intents مع تفعيل صلاحية قراءة محتوى الرسائل
intents = discord.Intents.default()
intents.message_content = True

# إنشاء البوت مع تعيين بادئة الأوامر (prefix="/")
bot = commands.Bot(command_prefix="/", intents=intents)

# قائمة التنبيهات: تحتوي على تنبيه لكل طلب يشمل رمز العملة/المؤشر، السعر المستهدف، ومعرف القناة
alerts = []

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert usdcad 1.427822
    حيث يتم حفظ التنبيه مع معرف القناة التي كتب فيها الأمر.
    """
    alert_data = {
        "symbol": symbol.upper(),
        "target_price": target_price,
        "channel_id": ctx.channel.id
    }
    alerts.append(alert_data)
    await ctx.send(f"تم ضبط تنبيه لـ **{alert_data['symbol']}** عند السعر **{alert_data['target_price']}**.")
    logger.debug(f"تنبيه جديد مضاف: {alert_data}")

@tasks.loop(seconds=30)  # فحص كل 30 ثانية للتجربة
async def check_prices():
    logger.debug("بدء فحص الأسعار...")
    alerts_to_remove = []
    
    for alert_data in alerts:
        symbol = alert_data["symbol"]
        target_price = alert_data["target_price"]
        channel_id = alert_data["channel_id"]
        
        try:
            logger.debug(f"فحص {symbol} مع السعر المستهدف {target_price}")
            handler = TA_Handler(
                symbol=symbol,
                screener="forex",     # بيانات الفوركس لجميع أزواج العملات
                exchange="OANDA",     # استخدام منصة OANDA
                interval=Interval.INTERVAL_1_MINUTE  # إطار زمني لمدة دقيقة واحدة للتجربة
            )
            analysis = handler.get_analysis().indicators
            high_price = float(analysis.get('high', 0))
            low_price = float(analysis.get('low', 0))
            logger.debug(f"الشمعة الحالية لـ {symbol}: High={high_price} و Low={low_price}")
            
            # تحقق ما إذا كان السعر المستهدف يقع ضمن نطاق الشمعة (بين low و high)
            if low_price <= target_price <= high_price:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(
                        f"🚨 تنبيه: **{symbol}** لمس السعر المطلوب **{target_price}** خلال آخر دقيقة!"
                    )
                    logger.debug(f"تم إرسال التنبيه لـ {symbol} إلى القناة {channel_id}")
                alerts_to_remove.append(alert_data)
            else:
                logger.debug(f"السعر المستهدف {target_price} ليس ضمن نطاق الشمعة ({low_price} - {high_price}) لـ {symbol}")
        except Exception as e:
            logger.error(f"خطأ في جلب البيانات لـ {symbol}: {e}")
    
    # إزالة التنبيهات التي تم إرسال الإشعار لها
    for alert_data in alerts_to_remove:
        if alert_data in alerts:
            alerts.remove(alert_data)
            logger.debug(f"تم إزالة التنبيه: {alert_data}")

@bot.event
async def on_ready():
    logger.info(f"تم تسجيل الدخول كـ {bot.user}")
    check_prices.start()

# قراءة التوكن من متغير البيئة DISCORD_BOT_TOKEN
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not TOKEN:
    logger.error("لم يتم العثور على توكن البوت! تأكد من إضافة DISCORD_BOT_TOKEN في المتغيرات.")
else:
    bot.run(TOKEN)
