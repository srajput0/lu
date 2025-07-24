
#!/usr/bin/env python3
"""
Ludo Game Telegram Bot with Comprehensive Logging
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass
import uuid

# Telegram Bot imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================================
# TELEGRAM BOT LOGGER
# ================================

class TelegramBotLogger:
    def __init__(self):
        self.setup_logging()
        self.bot_stats = {
            'total_commands': 0,
            'successful_commands': 0,
            'failed_commands': 0,
            'total_users': set(),
            'active_games': 0,
            'invitations_sent': 0
        }

    def setup_logging(self):
        # Create logs directory
        os.makedirs('logs', exist_ok=True)
        
        # Setup formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )

        # File handlers
        bot_handler = logging.FileHandler('logs/telegram_bot.log')
        bot_handler.setLevel(logging.DEBUG)
        bot_handler.setFormatter(detailed_formatter)

        error_handler = logging.FileHandler('logs/bot_errors.log')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)

        # Setup logger
        self.logger = logging.getLogger('TelegramBot')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(bot_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(console_handler)

        self.logger.info("🤖 Telegram Bot Logger Initialized")

    def log_structured(self, level: str, event_type: str, data: Dict[str, Any]):
        """Log structured data for analytics"""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'component': 'telegram-bot',
            'data': data,
            'stats': {
                'total_commands': self.bot_stats['total_commands'],
                'successful_commands': self.bot_stats['successful_commands'],
                'failed_commands': self.bot_stats['failed_commands'],
                'total_users': len(self.bot_stats['total_users']),
                'active_games': self.bot_stats['active_games'],
                'invitations_sent': self.bot_stats['invitations_sent']
            }
        }
        
        log_message = f"🤖 {event_type.upper()}: {json.dumps(log_entry, default=str)}"
        getattr(self.logger, level.lower())(log_message)

    def log_command(self, update: Update, command: str, success: bool = True, additional_data: Dict = None):
        """Log bot commands"""
        self.bot_stats['total_commands'] += 1
        self.bot_stats['total_users'].add(update.effective_user.id)
        
        if success:
            self.bot_stats['successful_commands'] += 1
        else:
            self.bot_stats['failed_commands'] += 1

        user_info = {
            'user_id': update.effective_user.id,
            'username': update.effective_user.username,
            'first_name': update.effective_user.first_name,
            'command': command,
            'success': success,
            'chat_id': update.effective_chat.id,
            'chat_type': update.effective_chat.type,
            'additional_data': additional_data or {}
        }
        
        level = 'info' if success else 'error'
        self.log_structured(level, 'bot_command', user_info)

    def log_game_invitation(self, from_user_id: int, to_user_id: int, game_id: str):
        """Log game invitations"""
        self.bot_stats['invitations_sent'] += 1
        
        invitation_data = {
            'from_user_id': from_user_id,
            'to_user_id': to_user_id,
            'game_id': game_id,
            'invitation_id': str(uuid.uuid4())
        }
        
        self.log_structured('info', 'game_invitation', invitation_data)

    def log_webhook_event(self, update: Update):
        """Log webhook events"""
        webhook_data = {
            'update_id': update.update_id,
            'message_type': type(update.message).__name__ if update.message else 'None',
            'user_id': update.effective_user.id if update.effective_user else None,
            'chat_id': update.effective_chat.id if update.effective_chat else None,
            'has_callback_query': bool(update.callback_query)
        }
        
        self.log_structured('debug', 'webhook_event', webhook_data)

    def log_error(self, error: Exception, context: str, additional_data: Dict = None):
        """Log errors with context"""
        error_data = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context,
            'additional_data': additional_data or {}
        }
        
        self.log_structured('error', 'bot_error', error_data)
        self.logger.error(f"❌ ERROR in {context}: {error}", exc_info=True)

    def get_stats(self) -> Dict:
        """Get bot statistics"""
        return {
            'total_commands': self.bot_stats['total_commands'],
            'successful_commands': self.bot_stats['successful_commands'],
            'failed_commands': self.bot_stats['failed_commands'],
            'success_rate': (
                self.bot_stats['successful_commands'] / max(self.bot_stats['total_commands'], 1) * 100
            ),
            'total_users': len(self.bot_stats['total_users']),
            'active_games': self.bot_stats['active_games'],
            'invitations_sent': self.bot_stats['invitations_sent']
        }

# Initialize logger
bot_logger = TelegramBotLogger()

# ================================
# GAME DATA MODELS
# ================================

@dataclass
class GameInvitation:
    id: str
    from_user_id: int
    to_user_id: int
    game_url: str
    created_at: datetime
    expires_at: datetime
    status: str = "pending"  # pending, accepted, declined, expired

@dataclass
class UserProfile:
    user_id: int
    username: str
    first_name: str
    games_played: int = 0
    games_won: int = 0
    last_active: datetime = None
    
    def __post_init__(self):
        if self.last_active is None:
            self.last_active = datetime.utcnow()

# ================================
# GAME MANAGER FOR BOT
# ================================

class BotGameManager:
    def __init__(self):
        self.game_invitations: Dict[str, GameInvitation] = {}
        self.user_profiles: Dict[int, UserProfile] = {}
        self.active_games: Dict[str, Dict] = {}
        
    def create_game_invitation(self, from_user_id: int, to_user_id: int) -> GameInvitation:
        """Create a new game invitation"""
        invitation_id = str(uuid.uuid4())
        game_url = f"https://yourdomain.com/game/{invitation_id}"  # Replace with your domain
        
        invitation = GameInvitation(
            id=invitation_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            game_url=game_url,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24)  # 24 hour expiry
        )
        
        self.game_invitations[invitation_id] = invitation
        bot_logger.log_game_invitation(from_user_id, to_user_id, invitation_id)
        
        return invitation
    
    def get_user_profile(self, user_id: int, username: str = None, first_name: str = None) -> UserProfile:
        """Get or create user profile"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserProfile(
                user_id=user_id,
                username=username or "Unknown",
                first_name=first_name or "User"
            )
        else:
            # Update last active
            self.user_profiles[user_id].last_active = datetime.utcnow()
        
        return self.user_profiles[user_id]
    
    def accept_invitation(self, invitation_id: str) -> bool:
        """Accept game invitation"""
        if invitation_id in self.game_invitations:
            invitation = self.game_invitations[invitation_id]
            if invitation.status == "pending" and datetime.utcnow() < invitation.expires_at:
                invitation.status = "accepted"
                return True
        return False
    
    def cleanup_expired_invitations(self):
        """Remove expired invitations"""
        current_time = datetime.utcnow()
        expired_ids = [
            inv_id for inv_id, inv in self.game_invitations.items()
            if current_time > inv.expires_at and inv.status == "pending"
        ]
        
        for inv_id in expired_ids:
            self.game_invitations[inv_id].status = "expired"
            bot_logger.log_structured('info', 'invitation_expired', {'invitation_id': inv_id})

# Initialize game manager
game_manager = BotGameManager()

# ================================
# BOT COMMAND HANDLERS
# ================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        profile = game_manager.get_user_profile(user.id, user.username, user.first_name)
        
        welcome_message = f"""
🎲 **Welcome to Ludo Game, {user.first_name}!** 🎲

I'm your Ludo game bot! Here's what I can help you with:

🎮 **Commands:**
/play - Start a new game or join existing one
/invite @username - Invite someone to play
/stats - View your game statistics
/help - Show this help message

🏆 **Your Stats:**
• Games Played: {profile.games_played}
• Games Won: {profile.games_won}
• Win Rate: {(profile.games_won / max(profile.games_played, 1) * 100):.1f}%

Ready to play? Use /play to get started!
        """
        
        await update.message.reply_text(
            welcome_message,
            parse_mode='Markdown'
        )
        
        bot_logger.log_command(update, '/start', True, {
            'is_new_user': user.id not in game_manager.user_profiles,
            'user_stats': {
                'games_played': profile.games_played,
                'games_won': profile.games_won
            }
        })
        
    except Exception as e:
        bot_logger.log_error(e, 'start_command', {'user_id': update.effective_user.id})
        bot_logger.log_command(update, '/start', False)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /play command"""
    try:
        user = update.effective_user
        profile = game_manager.get_user_profile(user.id, user.username, user.first_name)
        
        # Create inline keyboard with game options
        keyboard = [
            [InlineKeyboardButton("🎮 Quick Play", callback_data="quick_play")],
            [InlineKeyboardButton("👥 Create Private Game", callback_data="create_private")],
            [InlineKeyboardButton("🔗 Join Game with Code", callback_data="join_with_code")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎲 **Choose your game mode:**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        bot_logger.log_command(update, '/play', True)
        
    except Exception as e:
        bot_logger.log_error(e, 'play_command', {'user_id': update.effective_user.id})
        bot_logger.log_command(update, '/play', False)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /invite command"""
    try:
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_text(
                "❌ Please specify a username to invite!\n"
                "Usage: `/invite @username`",
                parse_mode='Markdown'
            )
            bot_logger.log_command(update, '/invite', False, {'error': 'no_username_provided'})
            return
        
        target_username = context.args[0].replace('@', '')
        
        # Create game invitation
        # Note: In a real implementation, you'd need to resolve the username to user_id
        # For now, we'll create a placeholder invitation
        invitation = game_manager.create_game_invitation(user.id, 0)  # 0 as placeholder
        
        invite_message = f"""
🎮 **Game Invitation Created!**

Hey @{target_username}! {user.first_name} has invited you to play Ludo!

🔗 **Game Link:** {invitation.game_url}
⏰ **Expires:** {invitation.expires_at.strftime('%Y-%m-%d %H:%M UTC')}

Click the link to join the game!
        """
        
        await update.message.reply_text(invite_message, parse_mode='Markdown')
        
        bot_logger.log_command(update, '/invite', True, {
            'target_username': target_username,
            'invitation_id': invitation.id
        })
        
    except Exception as e:
        bot_logger.log_error(e, 'invite_command', {
            'user_id': update.effective_user.id,
            'args': context.args
        })
        bot_logger.log_command(update, '/invite', False)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    try:
        user = update.effective_user
        profile = game_manager.get_user_profile(user.id, user.username, user.first_name)
        
        win_rate = (profile.games_won / max(profile.games_played, 1)) * 100
        
        stats_message = f"""
📊 **Your Ludo Statistics**

👤 **Player:** {user.first_name} (@{user.username or 'No username'})
🎮 **Games Played:** {profile.games_played}
🏆 **Games Won:** {profile.games_won}
📈 **Win Rate:** {win_rate:.1f}%
📅 **Last Active:** {profile.last_active.strftime('%Y-%m-%d %H:%M UTC')}

🎯 Keep playing to improve your stats!
        """
        
        await update.message.reply_text(stats_message, parse_mode='Markdown')
        
        bot_logger.log_command(update, '/stats', True, {
            'user_stats': {
                'games_played': profile.games_played,
                'games_won': profile.games_won,
                'win_rate': win_rate
            }
        })
        
    except Exception as e:
        bot_logger.log_error(e, 'stats_command', {'user_id': update.effective_user.id})
        bot_logger.log_command(update, '/stats', False)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    try:
        help_message = """
🎲 **Ludo Game Bot Help** 🎲

**Available Commands:**
/start - Welcome message and quick overview
/play - Start playing Ludo (various game modes)
/invite @username - Invite someone to play
/stats - View your game statistics
/help - Show this help message

**Game Modes:**
🎮 **Quick Play** - Get matched with random players
👥 **Private Game** - Create a game for friends only
🔗 **Join with Code** - Join a specific game room

**How to Play:**
1. Use /play to choose your game mode
2. Wait for other players to join
3. Click the game link when ready
4. Play Ludo in your browser!

**Tips:**
• Invite friends with /invite for more fun
• Check your progress with /stats
• Games expire after 24 hours

Need more help? Contact @yourusername
        """
        
        await update.message.reply_text(help_message, parse_mode='Markdown')
        
        bot_logger.log_command(update, '/help', True)
        
    except Exception as e:
        bot_logger.log_error(e, 'help_command', {'user_id': update.effective_user.id})
        bot_logger.log_command(update, '/help', False)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

# ================================
# CALLBACK QUERY HANDLERS
# ================================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callback queries"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        data = query.data
        
        if data == "quick_play":
            game_url = f"https://yourdomain.com/game/quick_{uuid.uuid4().hex[:8]}"
            
            await query.edit_message_text(
                f"🎮 **Quick Play Game Created!**\n\n"
                f"🔗 **Game Link:** {game_url}\n"
                f"👥 **Waiting for players...**\n\n"
                f"Share this link with friends or wait for random players to join!",
                parse_mode='Markdown'
            )
            
            bot_logger.log_structured('info', 'quick_play_created', {
                'user_id': user.id,
                'game_url': game_url
            })
        
        elif data == "create_private":
            game_code = uuid.uuid4().hex[:6].upper()
            game_url = f"https://yourdomain.com/game/private_{game_code}"
            
            await query.edit_message_text(
                f"👥 **Private Game Created!**\n\n"
                f"🔗 **Game Link:** {game_url}\n"
                f"🔑 **Game Code:** `{game_code}`\n\n"
                f"Share the link or code with your friends!",
                parse_mode='Markdown'
            )
            
            bot_logger.log_structured('info', 'private_game_created', {
                'user_id': user.id,
                'game_code': game_code,
                'game_url': game_url
            })
        
        elif data == "join_with_code":
            await query.edit_message_text(
                "🔗 **Join Game with Code**\n\n"
                "Please send me the game code to join an existing game.\n"
                "Game codes are 6-character strings like: `ABC123`",
                parse_mode='Markdown'
            )
            
            # Set user state to waiting for game code
            context.user_data['waiting_for_code'] = True
            
            bot_logger.log_structured('info', 'join_code_requested', {
                'user_id': user.id
            })
        
        bot_logger.log_structured('info', 'button_callback', {
            'user_id': user.id,
            'callback_data': data
        })
        
    except Exception as e:
        bot_logger.log_error(e, 'button_callback', {
            'user_id': update.effective_user.id,
            'callback_data': update.callback_query.data if update.callback_query else None
        })
        await update.callback_query.answer("❌ Something went wrong. Please try again.")

# ================================
# MESSAGE HANDLERS
# ================================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (like game codes)"""
    try:
        user = update.effective_user
        message_text = update.message.text
        
        # Check if user is waiting for a game code
        if context.user_data.get('waiting_for_code'):
            # Validate game code format (6 characters, alphanumeric)
            if len(message_text) == 6 and message_text.isalnum():
                game_url = f"https://yourdomain.com/game/private_{message_text.upper()}"
                
                await update.message.reply_text(
                    f"✅ **Joining Game!**\n\n"
                    f"🔗 **Game Link:** {game_url}\n"
                    f"🔑 **Code:** `{message_text.upper()}`\n\n"
                    f"Click the link to join the game!",
                    parse_mode='Markdown'
                )
                
                context.user_data['waiting_for_code'] = False
                
                bot_logger.log_structured('info', 'game_joined_with_code', {
                    'user_id': user.id,
                    'game_code': message_text.upper()
                })
            else:
                await update.message.reply_text(
                    "❌ **Invalid Game Code**\n\n"
                    "Game codes should be 6 characters long (letters and numbers only).\n"
                    "Example: `ABC123`\n\n"
                    "Please try again or use /play to create a new game.",
                    parse_mode='Markdown'
                )
                
                bot_logger.log_structured('warning', 'invalid_game_code', {
                    'user_id': user.id,
                    'invalid_code': message_text
                })
        else:
            # Handle other text messages
            await update.message.reply_text(
                "🤔 I didn't understand that command.\n\n"
                "Use /help to see available commands or /play to start a game!",
                parse_mode='Markdown'
            )
            
            bot_logger.log_structured('info', 'unrecognized_message', {
                'user_id': user.id,
                'message_text': message_text[:100]  # First 100 chars
            })
    
    except Exception as e:
        bot_logger.log_error(e, 'handle_text_message', {
            'user_id': update.effective_user.id,
            'message_text': update.message.text[:100] if update.message.text else None
        })
        await update.message.reply_text("❌ Sorry, something went wrong. Please try again.")

# ================================
# ERROR HANDLER
# ================================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    bot_logger.log_error(context.error, 'telegram_error_handler', {
        'update': str(update)[:500] if update else None,
        'context': str(context)[:500] if context else None
    })

# ================================
# WEBHOOK HANDLER
# ================================

async def webhook_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log all incoming webhooks"""
    bot_logger.log_webhook_event(update)

# ================================
# PERIODIC TASKS
# ================================

async def periodic_cleanup():
    """Periodic cleanup of expired invitations and stats logging"""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            # Clean up expired invitations
            game_manager.cleanup_expired_invitations()
            
            # Log bot statistics
            stats = bot_logger.get_stats()
            bot_logger.log_structured('info', 'periodic_stats', stats)
            
            bot_logger.logger.info(f"📊 Bot Stats: {stats}")
            
        except Exception as e:
            bot_logger.log_error(e, 'periodic_cleanup')

async def daily_stats_report():
    """Send daily statistics report"""
    while True:
        try:
            # Wait until midnight UTC
            now = datetime.utcnow()
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            sleep_seconds = (tomorrow - now).total_seconds()
            await asyncio.sleep(sleep_seconds)
            
            # Generate daily report
            stats = bot_logger.get_stats()
            daily_report = {
                'date': (datetime.utcnow() - timedelta(days=1)).date().isoformat(),
                'stats': stats,
                'total_invitations': len(game_manager.game_invitations),
                'active_users': len([
                    p for p in game_manager.user_profiles.values()
                    if (datetime.utcnow() - p.last_active).days < 1
                ])
            }
            
            bot_logger.log_structured('info', 'daily_report', daily_report)
            
        except Exception as e:
            bot_logger.log_error(e, 'daily_stats_report')

# ================================
# ADMIN COMMANDS (Optional)
# ================================

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to get detailed bot statistics"""
    # Check if user is admin (replace with your admin user IDs)
    ADMIN_USER_IDS = [5050578106]  # Replace with actual admin user IDs
    
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ Access denied.")
        return
    
    try:
        stats = bot_logger.get_stats()
        game_stats = {
            'total_invitations': len(game_manager.game_invitations),
            'active_invitations': len([
                inv for inv in game_manager.game_invitations.values()
                if inv.status == 'pending' and datetime.utcnow() < inv.expires_at
            ]),
            'total_user_profiles': len(game_manager.user_profiles),
            'active_users_24h': len([
                p for p in game_manager.user_profiles.values()
                if (datetime.utcnow() - p.last_active).days < 1
            ])
        }
        
        admin_message = f"""
🔧 **Admin Bot Statistics**

**Command Stats:**
• Total Commands: {stats['total_commands']}
• Successful: {stats['successful_commands']}
• Failed: {stats['failed_commands']}
• Success Rate: {stats['success_rate']:.1f}%

**User Stats:**
• Total Users: {stats['total_users']}
• Active (24h): {game_stats['active_users_24h']}
• Total Invitations: {game_stats['total_invitations']}
• Active Invitations: {game_stats['active_invitations']}

**Game Stats:**
• Games Created: {stats['active_games']}
• Invitations Sent: {stats['invitations_sent']}

Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
        """
        
        await update.message.reply_text(admin_message, parse_mode='Markdown')
        
        bot_logger.log_command(update, '/admin_stats', True, {
            'is_admin': True,
            'stats_requested': True
        })
        
    except Exception as e:
        bot_logger.log_error(e, 'admin_stats_command', {
            'user_id': update.effective_user.id
        })
        await update.message.reply_text("❌ Error retrieving statistics.")

# ================================
# BOT SETUP AND MAIN
# ================================

def setup_bot_handlers(application: Application):
    """Setup all bot handlers"""
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("invite", invite_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    bot_logger.logger.info("✅ Bot handlers configured")

async def main():
    """Main bot entry point"""
    # Get bot token from environment variable
    BOT_TOKEN = os.getenv('7922102581:AAF33bRlw2uBdTcoZvSfVI-ReXni_-Ubbig')
    
    if not BOT_TOKEN:
        bot_logger.logger.error("❌ TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    bot_logger.logger.info("🚀 Starting Ludo Game Telegram Bot")
    
    try:
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Setup handlers
        setup_bot_handlers(application)
        
        # Start background tasks
        asyncio.create_task(periodic_cleanup())
        asyncio.create_task(daily_stats_report())
        
        bot_logger.logger.info("🤖 Bot is starting...")
        
        # Start the bot
        await application.initialize()
        await application.start()
        
        # Start polling for updates
        await application.updater.start_polling(
            poll_interval=1.0,
            timeout=10,
            read_timeout=5,
            write_timeout=5
        )
        
        bot_logger.logger.info("✅ Bot is running and polling for updates!")
        bot_logger.logger.info("   🔗 Bot commands: /start, /play, /invite, /stats, /help")
        bot_logger.logger.info("   📊 Admin commands: /admin_stats")
        
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        bot_logger.logger.info("⏹️  Bot shutdown requested")
    
    except Exception as e:
        bot_logger.log_error(e, 'bot_startup')
        raise
    
    finally:
        bot_logger.logger.info("🛑 Bot shutdown complete")

if __name__ == "__main__":
    # Check for required packages
    try:
        import telegram
        from telegram.ext import Application
    except ImportError:
        print("❌ python-telegram-bot package not found.")
        print("Install with: pip install python-telegram-bot")
        exit(1)
    
    # Check for bot token
    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        print("❌ Please set TELEGRAM_BOT_TOKEN environment variable")
        print("Get your bot token from @BotFather on Telegram")
        print("Then run: export TELEGRAM_BOT_TOKEN='7922102581:AAF33bRlw2uBdTcoZvSfVI-ReXni_-Ubbig'")
        exit(1)
    
    # Run the bot
    asyncio.run(main())
