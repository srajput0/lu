#!/usr/bin/env python3
"""
Ludo Game WebSocket Server with Comprehensive Logging
"""

import asyncio
import websockets
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Set, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# ================================
# LOGGING SETUP
# ================================

class GameServerLogger:
    def __init__(self):
        self.setup_logging()
        self.active_games = {}
        self.player_sessions = {}
        self.connection_stats = {
            'total_connections': 0,
            'active_connections': 0,
            'messages_processed': 0,
            'errors_occurred': 0
        }

    def setup_logging(self):
        # Create logs directory if it doesn't exist
        import os
        os.makedirs('logs', exist_ok=True)
        
        # Setup formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )

        # Setup file handlers
        file_handler = logging.FileHandler('logs/game_server.log')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)

        error_handler = logging.FileHandler('logs/server_errors.log')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)

        # Setup console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)

        # Setup logger
        self.logger = logging.getLogger('GameServer')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(console_handler)

        self.logger.info("🎮 Game Server Logger Initialized")

    def log_structured(self, level: str, event_type: str, data: Dict[str, Any]):
        """Log structured data for analytics"""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'component': 'websocket-server',
            'data': data,
            'stats': self.connection_stats.copy()
        }
        
        log_message = f"📊 {event_type.upper()}: {json.dumps(log_entry, default=str)}"
        getattr(self.logger, level.lower())(log_message)

    def log_connection_event(self, websocket, event: str, additional_data: Dict = None):
        """Log WebSocket connection events"""
        client_info = {
            'remote_address': str(websocket.remote_address),
            'user_agent': websocket.request_headers.get('User-Agent', 'Unknown'),
            'origin': websocket.request_headers.get('Origin', 'Unknown'),
            'event': event
        }
        
        if additional_data:
            client_info.update(additional_data)
        
        self.log_structured('info', 'connection_event', client_info)
        
        # Update stats
        if event == 'connected':
            self.connection_stats['total_connections'] += 1
            self.connection_stats['active_connections'] += 1
        elif event == 'disconnected':
            self.connection_stats['active_connections'] = max(0, self.connection_stats['active_connections'] - 1)

    def log_game_event(self, event_type: str, game_id: str, player_id: str = None, data: Dict = None):
        """Log game-specific events"""
        game_data = {
            'game_id': game_id,
            'player_id': player_id,
            'event_details': data or {}
        }
        
        self.log_structured('info', f'game_{event_type}', game_data)

    def log_performance_metric(self, metric_name: str, value: float, context: Dict = None):
        """Log performance metrics"""
        metric_data = {
            'metric_name': metric_name,
            'value': value,
            'context': context or {}
        }
        
        self.log_structured('info', 'performance_metric', metric_data)

    def log_error(self, error: Exception, context: str, additional_data: Dict = None):
        """Log errors with context"""
        error_data = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context,
            'additional_data': additional_data or {}
        }
        
        self.connection_stats['errors_occurred'] += 1
        self.log_structured('error', 'server_error', error_data)
        self.logger.error(f"❌ ERROR in {context}: {error}", exc_info=True)

    def log_message_processed(self, message_type: str, processing_time: float, success: bool = True):
        """Log message processing metrics"""
        self.connection_stats['messages_processed'] += 1
        
        metric_data = {
            'message_type': message_type,
            'processing_time_ms': processing_time * 1000,
            'success': success
        }
        
        self.log_structured('debug', 'message_processed', metric_data)

# Initialize global logger
server_logger = GameServerLogger()

# ================================
# GAME DATA MODELS
# ================================

class GamePhase(Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    FINISHED = "finished"

class PlayerColor(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"

@dataclass
class Player:
    id: str
    name: str
    websocket: Any
    color: PlayerColor
    pieces: list
    is_connected: bool = True
    join_time: datetime = None
    
    def __post_init__(self):
        if self.join_time is None:
            self.join_time = datetime.utcnow()

@dataclass
class GameState:
    id: str
    players: Dict[str, Player]
    current_player_index: int
    phase: GamePhase
    board_state: Dict
    last_dice_roll: int
    created_at: datetime
    updated_at: datetime
    
    def to_dict(self):
        return {
            'id': self.id,
            'players': [{
                'id': p.id,
                'name': p.name,
                'color': p.color.value,
                'is_connected': p.is_connected
            } for p in self.players.values()],
            'current_player_index': self.current_player_index,
            'phase': self.phase.value,
            'last_dice_roll': self.last_dice_roll,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

# ================================
# GAME MANAGER
# ================================

class GameManager:
    def __init__(self):
        self.games: Dict[str, GameState] = {}
        self.waiting_players: Set[str] = set()
        self.player_to_game: Dict[str, str] = {}
        
    async def join_game(self, player_id: str, player_name: str, websocket) -> str:
        """Join a player to a game (existing or new)"""
        start_time = time.time()
        
        try:
            # Check if player is already in a game
            if player_id in self.player_to_game:
                existing_game_id = self.player_to_game[player_id]
                if existing_game_id in self.games:
                    game = self.games[existing_game_id]
                    if player_id in game.players:
                        # Reconnect player
                        game.players[player_id].websocket = websocket
                        game.players[player_id].is_connected = True
                        
                        server_logger.log_game_event('player_reconnected', existing_game_id, player_id)
                        return existing_game_id
            
            # Find or create game
            game_id = await self._find_or_create_game(player_id, player_name, websocket)
            
            processing_time = time.time() - start_time
            server_logger.log_performance_metric('join_game_time', processing_time, {
                'player_id': player_id,
                'game_id': game_id
            })
            
            return game_id
            
        except Exception as e:
            server_logger.log_error(e, 'join_game', {'player_id': player_id})
            raise

    async def _find_or_create_game(self, player_id: str, player_name: str, websocket) -> str:
        """Find existing game or create new one"""
        
        # Look for games waiting for players
        for game_id, game in self.games.items():
            if game.phase == GamePhase.WAITING and len(game.players) < 4:
                # Join existing game
                color = self._get_available_color(game)
                player = Player(
                    id=player_id,
                    name=player_name,
                    websocket=websocket,
                    color=color,
                    pieces=[]
                )
                
                game.players[player_id] = player
                self.player_to_game[player_id] = game_id
                game.updated_at = datetime.utcnow()
                
                server_logger.log_game_event('player_joined_existing', game_id, player_id, {
                    'players_count': len(game.players),
                    'player_color': color.value
                })
                
                # Start game if we have enough players
                if len(game.players) >= 2:  # Minimum 2 players to start
                    await self._start_game(game_id)
                
                return game_id
        
        # Create new game
        game_id = str(uuid.uuid4())
        player = Player(
            id=player_id,
            name=player_name,
            websocket=websocket,
            color=PlayerColor.RED,  # First player gets red
            pieces=[]
        )
        
        game = GameState(
            id=game_id,
            players={player_id: player},
            current_player_index=0,
            phase=GamePhase.WAITING,
            board_state={},
            last_dice_roll=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.games[game_id] = game
        self.player_to_game[player_id] = game_id
        
        server_logger.log_game_event('game_created', game_id, player_id, {
            'player_name': player_name
        })
        
        return game_id

    def _get_available_color(self, game: GameState) -> PlayerColor:
        """Get next available player color"""
        used_colors = {player.color for player in game.players.values()}
        available_colors = [color for color in PlayerColor if color not in used_colors]
        return available_colors[0] if available_colors else PlayerColor.RED

    async def _start_game(self, game_id: str):
        """Start the game"""
        game = self.games[game_id]
        game.phase = GamePhase.PLAYING
        game.updated_at = datetime.utcnow()
        
        # Notify all players
        await self._broadcast_to_game(game_id, {
            'type': 'game_state_update',
            'payload': {
                'currentPlayer': game.current_player_index,
                'gamePhase': game.phase.value
            }
        })
        
        server_logger.log_game_event('game_started', game_id, data={
            'players_count': len(game.players),
            'player_ids': list(game.players.keys())
        })

    async def handle_dice_roll(self, game_id: str, player_id: str) -> int:
        """Handle dice roll"""
        start_time = time.time()
        
        try:
            game = self.games[game_id]
            current_player_id = list(game.players.keys())[game.current_player_index]
            
            if player_id != current_player_id:
                raise ValueError("Not your turn")
            
            # Roll dice (1-6)
            import random
            dice_value = random.randint(1, 6)
            game.last_dice_roll = dice_value
            game.updated_at = datetime.utcnow()
            
            # Broadcast to all players
            await self._broadcast_to_game(game_id, {
                'type': 'dice_rolled',
                'payload': {
                    'playerId': player_id,
                    'value': dice_value
                }
            })
            
            processing_time = time.time() - start_time
            server_logger.log_performance_metric('dice_roll_time', processing_time)
            
            server_logger.log_game_event('dice_rolled', game_id, player_id, {
                'dice_value': dice_value,
                'processing_time_ms': processing_time * 1000
            })
            
            return dice_value
            
        except Exception as e:
            server_logger.log_error(e, 'handle_dice_roll', {
                'game_id': game_id,
                'player_id': player_id
            })
            raise

    async def handle_chat_message(self, game_id: str, player_id: str, message: str):
        """Handle chat message"""
        try:
            game = self.games[game_id]
            player = game.players[player_id]
            
            # Broadcast to all players in game
            await self._broadcast_to_game(game_id, {
                'type': 'chat_message',
                'payload': {
                    'playerId': player_id,
                    'playerName': player.name,
                    'message': message,
                    'timestamp': datetime.utcnow().isoformat()
                }
            })
            
            server_logger.log_game_event('chat_message', game_id, player_id, {
                'message_length': len(message),
                'player_name': player.name
            })
            
        except Exception as e:
            server_logger.log_error(e, 'handle_chat_message', {
                'game_id': game_id,
                'player_id': player_id
            })

    async def handle_player_disconnect(self, player_id: str):
        """Handle player disconnection"""
        try:
            if player_id in self.player_to_game:
                game_id = self.player_to_game[player_id]
                game = self.games[game_id]
                
                if player_id in game.players:
                    game.players[player_id].is_connected = False
                    game.updated_at = datetime.utcnow()
                    
                    # Notify other players
                    await self._broadcast_to_game(game_id, {
                        'type': 'player_disconnected',
                        'payload': {
                            'playerId': player_id,
                            'playerName': game.players[player_id].name
                        }
                    }, exclude_player=player_id)
                    
                    server_logger.log_game_event('player_disconnected', game_id, player_id)
                    
                    # Check if game should be paused/ended
                    connected_players = sum(1 for p in game.players.values() if p.is_connected)
                    if connected_players == 0:
                        # Clean up empty game after some time
                        asyncio.create_task(self._cleanup_empty_game(game_id, delay=300))  # 5 minutes
                    
        except Exception as e:
            server_logger.log_error(e, 'handle_player_disconnect', {'player_id': player_id})

    async def _cleanup_empty_game(self, game_id: str, delay: int = 300):
        """Clean up empty games after delay"""
        await asyncio.sleep(delay)
        
        if game_id in self.games:
            game = self.games[game_id]
            connected_players = sum(1 for p in game.players.values() if p.is_connected)
            
            if connected_players == 0:
                # Clean up
                for player_id in game.players:
                    if player_id in self.player_to_game:
                        del self.player_to_game[player_id]
                
                del self.games[game_id]
                
                server_logger.log_game_event('game_cleaned_up', game_id, data={
                    'cleanup_delay_seconds': delay,
                    'reason': 'no_connected_players'
                })

    async def _broadcast_to_game(self, game_id: str, message: dict, exclude_player: str = None):
        """Broadcast message to all players in a game"""
        if game_id not in self.games:
            return
        
        game = self.games[game_id]
        message_json = json.dumps(message)
        
        for player_id, player in game.players.items():
            if exclude_player and player_id == exclude_player:
                continue
                
            if player.is_connected and player.websocket:
                try:
                    await player.websocket.send(message_json)
                except Exception as e:
                    server_logger.log_error(e, 'broadcast_message', {
                        'game_id': game_id,
                        'player_id': player_id,
                        'message_type': message.get('type', 'unknown')
                    })
                    # Mark player as disconnected
                    player.is_connected = False

    def get_game_stats(self) -> Dict:
        """Get current game statistics"""
        stats = {
            'total_games': len(self.games),
            'waiting_games': 0,
            'active_games': 0,
            'finished_games': 0,
            'total_players': 0,
            'connected_players': 0
        }
        
        for game in self.games.values():
            if game.phase == GamePhase.WAITING:
                stats['waiting_games'] += 1
            elif game.phase == GamePhase.PLAYING:
                stats['active_games'] += 1
            else:
                stats['finished_games'] += 1
            
            stats['total_players'] += len(game.players)
            stats['connected_players'] += sum(1 for p in game.players.values() if p.is_connected)
        
        return stats

# ================================
# WEBSOCKET HANDLERS
# ================================

game_manager = GameManager()

async def handle_client_message(websocket, message_data: dict, player_id: str):
    """Handle incoming client messages"""
    start_time = time.time()
    message_type = message_data.get('type', 'unknown')
    
    try:
        if message_type == 'join_game':
            payload = message_data.get('payload', {})
            player_name = payload.get('playerName', f'Player {player_id[:8]}')
            
            game_id = await game_manager.join_game(player_id, player_name, websocket)
            game = game_manager.games[game_id]
            
            # Send game joined confirmation
            await websocket.send(json.dumps({
                'type': 'game_joined',
                'payload': {
                    'gameId': game_id,
                    'playerId': player_id,
                    'players': [
                        {
                            'id': p.id,
                            'name': p.name,
                            'color': p.color.value
                        } for p in game.players.values()
                    ]
                }
            }))
            
            # Send current game state
            await websocket.send(json.dumps({
                'type': 'game_state_update',
                'payload': {
                    'currentPlayer': game.current_player_index,
                    'gamePhase': game.phase.value
                }
            }))
        
        elif message_type == 'roll_dice':
            payload = message_data.get('payload', {})
            game_id = payload.get('gameId')
            
            if game_id:
                dice_value = await game_manager.handle_dice_roll(game_id, player_id)
        
        elif message_type == 'chat_message':
            payload = message_data.get('payload', {})
            game_id = payload.get('gameId')
            message = payload.get('message', '')
            
            if game_id and message:
                await game_manager.handle_chat_message(game_id, player_id, message)
        
        elif message_type == 'leave_game':
            await game_manager.handle_player_disconnect(player_id)
        
        elif message_type == 'log':
            # Handle client-side logs
            log_payload = message_data.get('payload', {})
            server_logger.log_structured('info', 'client_log', {
                'player_id': player_id,
                'client_log': log_payload
            })
        
        else:
            server_logger.logger.warning(f"🔄 Unknown message type: {message_type}")
            await websocket.send(json.dumps({
                'type': 'error',
                'payload': {
                    'message': f'Unknown message type: {message_type}'
                }
            }))
        
        # Log processing time
        processing_time = time.time() - start_time
        server_logger.log_message_processed(message_type, processing_time, True)
        
    except Exception as e:
        processing_time = time.time() - start_time
        server_logger.log_message_processed(message_type, processing_time, False)
        
        server_logger.log_error(e, 'handle_client_message', {
            'message_type': message_type,
            'player_id': player_id
        })
        
        # Send error to client
        await websocket.send(json.dumps({
            'type': 'error',
            'payload': {
                'message': f'Server error: {str(e)}'
            }
        }))

async def handle_websocket_connection(websocket, path):
    """Handle new WebSocket connection"""
    player_id = str(uuid.uuid4())
    
    server_logger.log_connection_event(websocket, 'connected', {
        'player_id': player_id,
        'path': path
    })
    
    try:
        async for message in websocket:
            try:
                message_data = json.loads(message)
                await handle_client_message(websocket, message_data, player_id)
                
            except json.JSONDecodeError as e:
                server_logger.log_error(e, 'json_decode', {
                    'player_id': player_id,
                    'raw_message': message[:200]  # First 200 chars
                })
                
                await websocket.send(json.dumps({
                    'type': 'error',
                    'payload': {
                        'message': 'Invalid JSON format'
                    }
                }))
            
            except Exception as e:
                server_logger.log_error(e, 'message_processing', {
                    'player_id': player_id
                })
    
    except websockets.exceptions.ConnectionClosed:
        server_logger.log_connection_event(websocket, 'disconnected', {
            'player_id': player_id,
            'reason': 'connection_closed'
        })
    
    except Exception as e:
        server_logger.log_error(e, 'websocket_connection', {
            'player_id': player_id
        })
    
    finally:
        # Clean up player
        await game_manager.handle_player_disconnect(player_id)
        server_logger.log_connection_event(websocket, 'cleanup_completed', {
            'player_id': player_id
        })

# ================================
# HEALTH CHECK AND STATS ENDPOINT
# ================================

async def handle_http_request(path, request_headers):
    """Handle HTTP requests for health checks and stats"""
    try:
        if path == '/health':
            stats = game_manager.get_game_stats()
            stats.update(server_logger.connection_stats)
            
            response_body = json.dumps({
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'stats': stats
            }, indent=2)
            
            return websockets.http.Response(
                status=200,
                headers=[('Content-Type', 'application/json')],
                body=response_body
            )
        
        elif path == '/stats':
            stats = {
                'server_stats': server_logger.connection_stats,
                'game_stats': game_manager.get_game_stats(),
                'games_detail': [
                    {
                        'id': game.id,
                        'phase': game.phase.value,
                        'players_count': len(game.players),
                        'connected_players': sum(1 for p in game.players.values() if p.is_connected),
                        'created_at': game.created_at.isoformat(),
                        'updated_at': game.updated_at.isoformat()
                    }
                    for game in game_manager.games.values()
                ]
            }
            
            response_body = json.dumps(stats, indent=2)
            
            return websockets.http.Response(
                status=200,
                headers=[('Content-Type', 'application/json')],
                body=response_body
            )
        
        else:
            return websockets.http.Response(
                status=404,
                headers=[('Content-Type', 'text/plain')],
                body=f"Not Found: {path}"
            )
    
    except Exception as e:
        server_logger.log_error(e, 'http_request_handler', {'path': path})
        
        return websockets.http.Response(
            status=500,
            headers=[('Content-Type', 'application/json')],
            body=json.dumps({'error': 'Internal server error'})
        )

# ================================
# PERIODIC TASKS
# ================================

async def periodic_stats_logger():
    """Log server statistics periodically"""
    while True:
        try:
            await asyncio.sleep(60)  # Log every minute
            
            game_stats = game_manager.get_game_stats()
            server_stats = server_logger.connection_stats
            
            combined_stats = {**game_stats, **server_stats}
            
            server_logger.log_structured('info', 'periodic_stats', combined_stats)
            
            # Log performance metrics
            server_logger.log_performance_metric('active_games_count', game_stats['active_games'])
            server_logger.log_performance_metric('connected_players_count', game_stats['connected_players'])
            server_logger.log_performance_metric('total_connections', server_stats['total_connections'])
            
        except Exception as e:
            server_logger.log_error(e, 'periodic_stats_logger')

async def cleanup_finished_games():
    """Periodically clean up finished games"""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            current_time = datetime.utcnow()
            games_to_remove = []
            
            for game_id, game in game_manager.games.items():
                if game.phase == GamePhase.FINISHED:
                    # Remove games finished more than 24 hours ago
                    if (current_time - game.updated_at).total_seconds() > 86400:
                        games_to_remove.append(game_id)
            
            for game_id in games_to_remove:
                game = game_manager.games[game_id]
                
                # Clean up player mappings
                for player_id in game.players:
                    if player_id in game_manager.player_to_game:
                        del game_manager.player_to_game[player_id]
                
                del game_manager.games[game_id]
                
                server_logger.log_game_event('game_cleaned_up', game_id, data={
                    'reason': 'finished_game_cleanup',
                    'finished_hours_ago': (current_time - game.updated_at).total_seconds() / 3600
                })
            
            if games_to_remove:
                server_logger.logger.info(f"🧹 Cleaned up {len(games_to_remove)} finished games")
        
        except Exception as e:
            server_logger.log_error(e, 'cleanup_finished_games')

# ================================
# MAIN SERVER
# ================================

async def main():
    """Main server entry point"""
    server_logger.logger.info("🚀 Starting Ludo Game WebSocket Server")
    
    # Start background tasks
    asyncio.create_task(periodic_stats_logger())
    asyncio.create_task(cleanup_finished_games())
    
    # Start WebSocket server
    host = "localhost"
    port = 8765
    
    server_logger.logger.info(f"🌐 Server starting on {host}:{port}")
    
    try:
        # Start server with both WebSocket and HTTP support
        async with websockets.serve(
            handle_websocket_connection,
            host,
            port,
            process_request=handle_http_request,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=10,
            max_size=10**6,  # 1MB max message size
            max_queue=32,    # Max queued messages
        ) as server:
            
            server_logger.logger.info("✅ WebSocket Server is running!")
            server_logger.logger.info(f"   🎮 Game WebSocket: ws://{host}:{port}")
            server_logger.logger.info(f"   📊 Health Check: http://{host}:{port}/health")
            server_logger.logger.info(f"   📈 Statistics: http://{host}:{port}/stats")
            
            # Keep server running
            await server.wait_closed()
    
    except KeyboardInterrupt:
        server_logger.logger.info("⏹️  Server shutdown requested")
    
    except Exception as e:
        server_logger.log_error(e, 'server_startup')
        raise
    
    finally:
        server_logger.logger.info("🛑 Server shutdown complete")

if __name__ == "__main__":
    # Install required packages if not available
    try:
        import websockets
    except ImportError:
        print("❌ websockets package not found. Install with: pip install websockets")
        exit(1)
    
    # Run server
    asyncio.run(main())
