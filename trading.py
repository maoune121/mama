from dotenv import load_dotenv
load_dotenv()
import os
TOKEN = os.getenv("DISCORD_TOKEN")

import re
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
from keep_alive import keep_alive

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Alerts storage:
# alerts = {
#   guild_id: [
#       {
#           "symbol": str,
#           "screener": str,
#           "exchange": str,
#           "target_price": float,
#           "channel_id": int,
#           "message_id": int,
#           "note": str,
#           "mention_user_ids": set([...])
#       },
#       ...
#   ],
#   ...
# }
alerts = {}

# Price check interval (in seconds)
CHECK_INTERVAL = 29

# Set up intents
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="/",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Slash commands synced.")
        check_prices.start()

bot = MyBot()

# Choices for screener in the slash command
SCREENER_CHOICES = [
    app_commands.Choice(name="forex", value="forex"),
    app_commands.Choice(name="crypto", value="crypto"),
    app_commands.Choice(name="cfd", value="cfd"),
    app_commands.Choice(name="indices", value="indices"),
    app_commands.Choice(name="stocks", value="america"),  # American stocks
]

# Choices for exchange in the slash command
EXCHANGE_CHOICES = [
    app_commands.Choice(name="OANDA", value="OANDA"),
    app_commands.Choice(name="BINANCE", value="BINANCE"),
    app_commands.Choice(name="FXCM", value="FXCM"),
    app_commands.Choice(name="PEPPERSTONE", value="PEPPERSTONE"),
    app_commands.Choice(name="FOREXCOM", value="FOREXCOM"),
]

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_prices():
    logger.debug("Checking prices...")
    for guild_id, guild_alerts in list(alerts.items()):
        for alert_obj in guild_alerts.copy():
            symbol = alert_obj["symbol"]
            screener = alert_obj["screener"]
            exchange = alert_obj["exchange"]
            target_price = alert_obj["target_price"]
            channel_id = alert_obj["channel_id"]
            mention_user_ids = alert_obj.get("mention_user_ids", set())
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    screener=screener,
                    exchange=exchange,
                    interval=Interval.INTERVAL_5_MINUTES
                )
                analysis = handler.get_analysis()
                indicators = analysis.indicators
                high_price = float(indicators.get('high', 0))
                low_price = float(indicators.get('low', 0))

                if low_price <= target_price <= high_price:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        mentions_str = " ".join(f"<@{uid}>" for uid in mention_user_ids)
                        await channel.send(
                            f"Alert triggered for symbol {symbol} at target price {target_price}.\n{mentions_str}".strip()
                        )
                    guild_alerts.remove(alert_obj)
                    logger.info(f"Alert triggered for {symbol} at {target_price} in guild {guild_id}")
            except Exception as e:
                logger.error(f"Error fetching data for {symbol} ({screener}, {exchange}): {e}")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    # Scan channels once at startup to restore alerts that have not been triggered.
    await restore_alerts_from_history()

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
    guild_id = payload.guild_id
    if guild_id not in alerts:
        return
    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception as e:
        logger.error(f"Error fetching message for reaction: {e}")
        return
    if message.author.id != bot.user.id:
        return
    for alert_obj in alerts[guild_id]:
        if alert_obj.get("message_id") == payload.message_id:
            user_id = payload.user_id
            if user_id != bot.user.id:
                alert_obj.setdefault("mention_user_ids", set()).add(user_id)
            break

async def restore_alerts_from_history():
    """
    On startup, scan the last 50 messages in each text channel of each guild to restore alerts
    that have not been triggered. For each alert set message, check if there exists a triggered alert 
    message (starting with "Alert triggered for symbol") for the same symbol and target price. 
    If one is found, skip restoration.
    """
    for guild in bot.guilds:
        if guild.id not in alerts:
            alerts[guild.id] = []
        for channel in guild.text_channels:
            try:
                messages = [msg async for msg in channel.history(limit=50)]
            except Exception as e:
                logger.error(f"Error reading channel {channel.name}: {e}")
                continue

            for msg in messages:
                # Process only bot alert set messages
                if msg.author.id == bot.user.id and "Alert set for symbol" in msg.content:
                    # Expected format:
                    # "Alert set for symbol {symbol} at target price {target_price} using screener: {screener} and exchange: {exchange}. Note: {note}"
                    pattern = r"Alert set for symbol\s+(.+?)\s+at target price\s+([\d\.]+)\s+using screener:\s+(\w+)\s+and exchange:\s+(\w+)\.?(?:\s+Note:\s+(.*))?"
                    match = re.search(pattern, msg.content)
                    if not match:
                        continue
                    symbol_found = match.group(1).strip()
                    target_price_str = match.group(2).strip()
                    screener_found = match.group(3).strip()
                    exchange_found = match.group(4).strip()
                    note_found = match.group(5).strip() if match.group(5) else ""
                    try:
                        target_price_found = float(target_price_str)
                    except ValueError:
                        continue

                    # Check if there is a triggered alert message in the same channel history
                    triggered_exists = any(
                        m.author.id == bot.user.id and 
                        m.content.startswith("Alert triggered for symbol") and 
                        symbol_found in m.content and 
                        target_price_str in m.content
                        for m in messages
                    )
                    if triggered_exists:
                        continue

                    # Also, skip if the alert is already restored (matching symbol, price, and channel)
                    if any(a["symbol"] == symbol_found and a["target_price"] == target_price_found and a["channel_id"] == msg.channel.id 
                           for a in alerts[guild.id]):
                        continue

                    # Re-fetch the message to update reaction data
                    try:
                        fresh_msg = await channel.fetch_message(msg.id)
                    except Exception as e:
                        logger.error(f"Error re-fetching message {msg.id}: {e}")
                        fresh_msg = msg
                    mention_user_ids = set()
                    try:
                        for reaction in fresh_msg.reactions:
                            users = [user async for user in reaction.users()]
                            for u in users:
                                if u.id != bot.user.id:
                                    mention_user_ids.add(u.id)
                    except Exception as e:
                        logger.error(f"Error fetching reactions: {e}")

                    alerts[guild.id].append({
                        "symbol": symbol_found,
                        "screener": screener_found.lower(),
                        "exchange": exchange_found.upper(),
                        "target_price": target_price_found,
                        "channel_id": msg.channel.id,
                        "message_id": msg.id,
                        "note": note_found,
                        "mention_user_ids": mention_user_ids
                    })
                    logger.info(f"Restored alert for {symbol_found} at {target_price_found} in {channel.name}")

@bot.tree.command(name="alert", description="Set an alert for a specific symbol")
@app_commands.describe(
    screener="Choose the screener type (e.g., forex, crypto, cfd, indices, stocks)",
    exchange="Choose the exchange/platform (e.g., OANDA, BINANCE, ...)",
    symbol="Symbol name (e.g., XAUUSD, BTCUSDT, etc.)",
    target_price="The target price for the alert",
    note="An additional note (optional)"
)
@app_commands.choices(screener=SCREENER_CHOICES, exchange=EXCHANGE_CHOICES)
async def alert(interaction: discord.Interaction, screener: str, exchange: str, symbol: str, target_price: float, note: str = ""):
    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if guild_id not in alerts:
        alerts[guild_id] = []

    # Compose the alert message with all necessary data for restoration
    content = (f"Alert set for symbol {symbol.upper()} at target price {target_price} using screener: {screener} "
               f"and exchange: {exchange}.")
    if note:
        content += f" Note: {note}"
    
    await interaction.response.send_message(content)
    sent_msg = await interaction.original_response()

    alert_obj = {
        "symbol": symbol.upper(),
        "screener": screener.lower(),
        "exchange": exchange.upper(),
        "target_price": target_price,
        "channel_id": channel_id,
        "note": note,
        "message_id": sent_msg.id,
        "mention_user_ids": set()
    }
    alerts[guild_id].append(alert_obj)
    logger.info(f"New alert added: {symbol.upper()} at {target_price} (screener={screener}, exchange={exchange}) in guild {guild_id}")

# Start the keep_alive server if you use it
keep_alive()

# Run the bot
bot.run(TOKEN)
