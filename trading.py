import os
import re
import discord
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
import logging
from keep_alive import keep_alive
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

# قائمة التنبيهات المخزنة: 
# alerts[guild_id] = list of alert dicts, each dict has keys: "symbol", "target_price", "channel_id"
alerts = {}

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    أمر يتم استدعاؤه بالشكل:
    /alert GBPUSD 1.2999
    حيث يتم حفظ التنبيه مع معرف القناة التي تم فيها ضبط الأمر.
    """
    guild_id = ctx.guild.id
    channel_id = ctx.channel.id
    alert_obj = {"symbol": symbol.upper(), "target_price": target_price, "channel_id": channel_id}
    if guild_id not in alerts:
        alerts[guild_id] = []
    # إضافة التنبيه حتى وإن كان هناك تنبيه سابق لنفس العملة والسعر
    alerts[guild_id].append(alert_obj)
    
    await ctx.send(f"✅ تم ضبط تنبيه لـ **{symbol.upper()}** عند السعر **{target_price}** في هذه القناة.")
    logger.debug(f"New alert added: {symbol.upper()} at {target_price} in guild {guild_id}")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_prices():
    logger.debug("🔎 Checking prices...")
    # Iterate over each guild's alerts
    for guild_id, guild_alerts in list(alerts.items()):
        # Create a copy of the list to iterate over while possibly removing items
        for alert_obj in guild_alerts.copy():
            symbol = alert_obj["symbol"]
            target_price = alert_obj["target_price"]
            channel_id = alert_obj["channel_id"]
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    screener="forex",
                    exchange="OANDA",
                    interval=Interval.INTERVAL_5_MINUTES  # Using 5-minute candlesticks
                )
                analysis = handler.get_analysis()
                indicators = analysis.indicators
                high_price = float(indicators.get('high', 0))
                low_price = float(indicators.get('low', 0))
                logger.debug(f"{symbol}: High={high_price}, Low={low_price}, Target={target_price}")
                
                channel = bot.get_channel(channel_id)
                if channel:
                    if low_price <= target_price <= high_price:
                        await channel.send(
                            f"🚨 **تنبيه:** {symbol} وصل إلى السعر المطلوب **{target_price}** خلال آخر 5 دقائق!"
                        )
                        logger.info(f"Alert triggered for {symbol} at {target_price} in channel {channel_id}")
                        guild_alerts.remove(alert_obj)
                    else:
                        await channel.send(f"🔄 **{symbol}**: لم يصل إلى **{target_price}** بعد.")
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")
    # On startup, scan each text channel in every guild for untriggered alerts
    for guild in bot.guilds:
        if guild.id not in alerts:
            alerts[guild.id] = []
        for channel in guild.text_channels:
            try:
                # Get the last 50 messages from the channel
                messages = [msg async for msg in channel.history(limit=50)]
                for msg in messages:
                    # Only consider messages sent by this bot (Trading Alert)
                    if msg.author.id == bot.user.id:
                        content = msg.content
                        # If message contains "تم ضبط تنبيه" and does NOT contain "تنبيه:" (i.e. not triggered)
                        if "تم ضبط تنبيه" in content and "تنبيه:" not in content:
                            pattern = r"تم ضبط تنبيه لـ \*\*(.+?)\*\* عند السعر \*\*(.+?)\*\* في هذه القناة\."
                            match = re.search(pattern, content)
                            if match:
                                symbol_found = match.group(1).upper()
                                try:
                                    target_price_found = float(match.group(2))
                                except ValueError:
                                    continue
                                # Check if a triggered alert message already exists for this alert in the channel
                                alert_already_sent = False
                                for m in messages:
                                    if m.author.id == bot.user.id and "تنبيه:" in m.content:
                                        if symbol_found in m.content and str(target_price_found) in m.content:
                                            alert_already_sent = True
                                            break
                                if not alert_already_sent:
                                    # Before adding, check if this same alert is already in our list
                                    exists = any(
                                        a["symbol"] == symbol_found and a["target_price"] == target_price_found
                                        for a in alerts[guild.id]
                                    )
                                    if not exists:
                                        alerts[guild.id].append({
                                            "symbol": symbol_found,
                                            "target_price": target_price_found,
                                            "channel_id": channel.id
                                        })
                                        logger.debug(f"Restored alert: {symbol_found} at {target_price_found} in channel {channel.id}")
            except Exception as e:
                logger.error(f"Error reading channel {channel.name}: {e}")
    check_prices.start()

# Start keep_alive server and run the bot
keep_alive()
bot.run(TOKEN)
