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

# Start the keep-alive server
keep_alive()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# Enable intents with message content
intents = discord.Intents.default()
intents.message_content = True

# Create the bot with the command prefix "/"
bot = commands.Bot(command_prefix="/", intents=intents)

# Alerts list: stores an alert for each request (symbol, target price, channel id)
alerts = []

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    Command format:
    /alert usdcad 1.427822
    Stores an alert with the channel id where the command was issued.
    """
    alert_data = {
        "symbol": symbol.upper(),
        "target_price": target_price,
        "channel_id": ctx.channel.id
    }
    alerts.append(alert_data)
    await ctx.send(f"تم ضبط تنبيه لـ **{alert_data['symbol']}** عند السعر **{alert_data['target_price']}** في هذه القناة.")
    logger.debug(f"تنبيه جديد مضاف: {alert_data}")

@tasks.loop(seconds=30)  # Check every 30 seconds for testing
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
                screener="forex",     # Forex data for all currency pairs
                exchange="OANDA",     # Using OANDA platform
                interval=Interval.INTERVAL_1_MINUTE  # 1-minute interval for testing
            )
            analysis = handler.get_analysis().indicators
            high_price = float(analysis.get('high', 0))
            low_price = float(analysis.get('low', 0))
            logger.debug(f"الشمعة الحالية لـ {symbol}: High={high_price} و Low={low_price}")
            
            # Check if the target price falls within the candle's range (between low and high)
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
    
    # Remove alerts that have been notified
    for alert_data in alerts_to_remove:
        if alert_data in alerts:
            alerts.remove(alert_data)
            logger.debug(f"تم إزالة التنبيه: {alert_data}")

@bot.event
async def on_ready():
    logger.info(f"تم تسجيل الدخول كـ {bot.user}")
    check_prices.start()

bot.run(TOKEN)
