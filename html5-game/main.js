// ================================
// GAME LOGGER CLASS
// ================================

class GameLogger {
    constructor() {
        this.logLevel = 'INFO';
        this.sessionId = this.generateSessionId();
        this.wsConnection = null;
        this.localLogs = [];
    }

    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    setWebSocketConnection(ws) {
        this.wsConnection = ws;
    }

    log(level, message, data = {}) {
        const logEntry = {
            timestamp: new Date().toISOString(),
            level,
            component: 'game-client',
            sessionId: this.sessionId,
            message,
            data: {
                ...data,
                gameState: this.getCurrentGameState(),
                playerId: this.getPlayerId(),
                url: window.location.href,
                userAgent: navigator.userAgent
            }
        };

        // Store locally
        this.localLogs.push(logEntry);
        if (this.localLogs.length > 1000) {
            this.localLogs.shift(); // Keep only last 1000 logs
        }

        // Send to server if WebSocket is available
        if (this.wsConnection?.readyState === WebSocket.OPEN) {
            this.wsConnection.send(JSON.stringify({
                type: 'log',
                payload: logEntry
            }));
        }

        // Console logging with colors
        const colors = {
            ERROR: 'color: #ef4444; font-weight: bold;',
            WARN: 'color: #f59e0b; font-weight: bold;',
            INFO: 'color: #3b82f6;',
            DEBUG: 'color: #6b7280;'
        };

        console.log(
            `%c[${level}] ${message}`,
            colors[level] || '',
            logEntry.data
        );
    }

    getCurrentGameState() {
        if (typeof game !== 'undefined' && game) {
            return {
                currentPlayer: game.currentPlayer,
                gamePhase: game.gamePhase,
                playersCount: game.players?.length || 0,
                diceValue: game.lastDiceRoll
            };
        }
        return null;
    }

    getPlayerId() {
        try {
            return localStorage.getItem('playerId') || 'anonymous';
        } catch (e) {
            return 'anonymous';
        }
    }

    // Specific logging methods
    logPlayerAction(action, details = {}) {
        this.log('INFO', `Player action: ${action}`, {
            action,
            ...details,
            timestamp: Date.now()
        });
    }

    logGameEvent(event, details = {}) {
        this.log('INFO', `Game event: ${event}`, {
            event,
            ...details
        });
    }

    logError(error, context = '') {
        this.log('ERROR', `Error: ${error.message}`, {
            error: error.message,
            stack: error.stack,
            context,
            timestamp: Date.now()
        });
    }

    logPerformance(metric, value, context = '') {
        this.log('INFO', `Performance: ${metric}`, {
            metric,
            value,
            context,
            timestamp: Date.now()
        });
    }

    log3DEvent(event, details = {}) {
        this.log('DEBUG', `3D Event: ${event}`, {
            event,
            ...details,
            renderInfo: this.getRenderInfo()
        });
    }

    getRenderInfo() {
        if (typeof renderer !== 'undefined' && renderer) {
            return {
                drawCalls: renderer.info.render.calls,
                triangles: renderer.info.render.triangles,
                geometries: renderer.info.memory.geometries,
                textures: renderer.info.memory.textures
            };
        }
        return null;
    }

    exportLogs() {
        return {
            sessionId: this.sessionId,
            logs: this.localLogs,
            exportTime: new Date().toISOString()
        };
    }
}

// Initialize logger
const logger = new GameLogger();

// ================================
// GAME CLASS
// ================================

class LudoGame {
    constructor() {
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.gameBoard = null;
        this.players = [];
        this.currentPlayer = 0;
        this.gamePhase = 'waiting'; // waiting, playing, finished
        this.lastDiceRoll = 0;
        this.pieces = {};
        this.websocket = null;
        this.gameId = null;
        this.playerId = this.generatePlayerId();
        
        this.init();
        logger.logGameEvent('game_initialized');
    }

    generatePlayerId() {
        const id = 'player_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        try {
            localStorage.setItem('playerId', id);
        } catch (e) {
            logger.logError(e, 'localStorage_save');
        }
        return id;
    }

    async init() {
        try {
            logger.logGameEvent('initialization_started');
            
            await this.initThreeJS();
            await this.setupWebSocket();
            this.setupEventListeners();
            this.setupUI();
            this.animate();
            
            logger.logGameEvent('initialization_completed');
            this.hideLoadingScreen();
        } catch (error) {
            logger.logError(error, 'game_initialization');
            this.showError('Failed to initialize game: ' + error.message);
        }
    }

    async initThreeJS() {
        const startTime = performance.now();
        
        try {
            // Setup Three.js scene
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(0x87CEEB);

            // Setup camera
            this.camera = new THREE.PerspectiveCamera(
                75, 
                window.innerWidth / window.innerHeight, 
                0.1, 
                1000
            );
            this.camera.position.set(0, 15, 15);
            this.camera.lookAt(0, 0, 0);

            // Setup renderer
            const canvas = document.getElementById('game-canvas');
            this.renderer = new THREE.WebGLRenderer({ 
                canvas: canvas,
                antialias: true 
            });
            this.renderer.setSize(
                canvas.parentElement.clientWidth, 
                canvas.parentElement.clientHeight
            );
            this.renderer.shadowMap.enabled = true;
            this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

            // Setup lighting
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
            this.scene.add(ambientLight);

            const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
            directionalLight.position.set(10, 10, 5);
            directionalLight.castShadow = true;
            this.scene.add(directionalLight);

            // Create game board
            await this.createGameBoard();
            
            // Create dice
            this.createDice();

            const initTime = performance.now() - startTime;
            logger.logPerformance('threejs_initialization', initTime, 'milliseconds');
            logger.log3DEvent('scene_created', {
                objects_count: this.scene.children.length,
                renderer_info: logger.getRenderInfo()
            });

        } catch (error) {
            logger.logError(error, 'threejs_initialization');
            throw error;
        }
    }

    async createGameBoard() {
        try {
            // Create board base
            const boardGeometry = new THREE.BoxGeometry(12, 0.5, 12);
            const boardMaterial = new THREE.MeshLambertMaterial({ color: 0xF5DEB3 });
            this.gameBoard = new THREE.Mesh(boardGeometry, boardMaterial);
            this.gameBoard.receiveShadow = true;
            this.scene.add(this.gameBoard);

            // Create player home areas
            const colors = [0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00];
            const positions = [
                { x: -4, z: -4 }, // Red
                { x: 4, z: -4 },  // Green
                { x: 4, z: 4 },   // Blue
                { x: -4, z: 4 }   // Yellow
            ];

            for (let i = 0; i < 4; i++) {
                const homeGeometry = new THREE.BoxGeometry(3, 0.6, 3);
                const homeMaterial = new THREE.MeshLambertMaterial({ color: colors[i] });
                const home = new THREE.Mesh(homeGeometry, homeMaterial);
                home.position.set(positions[i].x, 0.3, positions[i].z);
                this.scene.add(home);
            }

            // Create path squares
            this.createPathSquares();

            logger.log3DEvent('board_created', {
                board_size: '12x12',
                player_homes: 4,
                path_squares: 52
            });

        } catch (error) {
            logger.logError(error, 'board_creation');
            throw error;
        }
    }

    createPathSquares() {
        // Create the main path around the board
        const pathPositions = this.generatePathPositions();
        
        pathPositions.forEach((pos, index) => {
            const squareGeometry = new THREE.BoxGeometry(0.8, 0.1, 0.8);
            const squareMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFFFF });
            const square = new THREE.Mesh(squareGeometry, squareMaterial);
            square.position.set(pos.x, 0.35, pos.z);
            square.userData = { pathIndex: index };
            this.scene.add(square);
        });
    }

    generatePathPositions() {
        // Generate positions for the 52 squares around the board
        const positions = [];
        const radius = 5;
        
        for (let i = 0; i < 52; i++) {
            const angle = (i / 52) * Math.PI * 2;
            positions.push({
                x: Math.cos(angle) * radius,
                z: Math.sin(angle) * radius
            });
        }
        
        return positions;
    }

    createDice() {
        const diceGeometry = new THREE.BoxGeometry(1, 1, 1);
        const diceMaterial = new THREE.MeshLambertMaterial({ color: 0xFFFFFF });
        this.dice = new THREE.Mesh(diceGeometry, diceMaterial);
        this.dice.position.set(0, 2, 0);
        this.dice.castShadow = true;
        this.scene.add(this.dice);

        logger.log3DEvent('dice_created');
    }

    setupWebSocket() {
        return new Promise((resolve, reject) => {
            try {
                // Mock WebSocket for demo - replace with actual server URL
                const wsUrl = `ws://localhost:8765`;
                logger.logGameEvent('websocket_connection_attempt', { url: wsUrl });
                
                // For demo purposes, we'll simulate WebSocket behavior
                this.simulateWebSocketConnection();
                resolve();
                
                /* Uncomment this when you have a real WebSocket server:
                this.websocket = new WebSocket(wsUrl);
                
                // Set logger WebSocket connection
                logger.setWebSocketConnection(this.websocket);

                this.websocket.onopen = () => {
                    logger.logGameEvent('websocket_connected', { url: wsUrl });
                    
                    // Join game or create new one
                    this.websocket.send(JSON.stringify({
                        type: 'join_game',
                        payload: {
                            playerId: this.playerId,
                            playerName: 'Player ' + this.playerId.slice(-4)
                        }
                    }));
                    
                    resolve();
                };

                this.websocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        this.handleWebSocketMessage(data);
                    } catch (error) {
                        logger.logError(error, 'websocket_message_parsing');
                    }
                };

                this.websocket.onerror = (error) => {
                    logger.logError(new Error('WebSocket error'), 'websocket_connection');
                    reject(error);
                };

                this.websocket.onclose = () => {
                    logger.logGameEvent('websocket_disconnected');
                    this.showError('Connection lost. Please refresh the page.');
                };
                */

            } catch (error) {
                logger.logError(error, 'websocket_setup');
                reject(error);
            }
        });
    }

    // Simulate WebSocket for demo purposes
    simulateWebSocketConnection() {
        logger.logGameEvent('demo_mode_activated');
        
        // Simulate joining a game
        setTimeout(() => {
            this.handleGameJoined({
                gameId: 'demo_game_123',
                players: [
                    { id: this.playerId, name: 'You' },
                    { id: 'bot_1', name: 'Bot 1' },
                    { id: 'bot_2', name: 'Bot 2' },
                    { id: 'bot_3', name: 'Bot 3' }
                ]
            });
        }, 1000);

        // Simulate game starting
        setTimeout(() => {
            this.handleGameStateUpdate({
                currentPlayer: 0,
                gamePhase: 'playing'
            });
        }, 2000);
    }

    handleWebSocketMessage(data) {
        logger.logGameEvent('websocket_message_received', { type: data.type });

        switch (data.type) {
            case 'game_joined':
                this.handleGameJoined(data.payload);
                break;
            case 'game_state_update':
                this.handleGameStateUpdate(data.payload);
                break;
            case 'player_moved':
                this.handlePlayerMoved(data.payload);
                break;
            case 'dice_rolled':
                this.handleDiceRolled(data.payload);
                break;
            case 'game_finished':
                this.handleGameFinished(data.payload);
                break;
            case 'chat_message':
                this.handleChatMessage(data.payload);
                break;
            case 'error':
                this.handleServerError(data.payload);
                break;
            default:
                logger.logGameEvent('unknown_message_type', { type: data.type });
        }
    }

    handleGameJoined(payload) {
        this.gameId = payload.gameId;
        this.players = payload.players;
        this.updatePlayersUI();
        logger.logGameEvent('game_joined', { gameId: this.gameId, playersCount: this.players.length });
    }

    handleGameStateUpdate(payload) {
        this.currentPlayer = payload.currentPlayer;
        this.gamePhase = payload.gamePhase;
        this.updateGameUI();
        logger.logGameEvent('game_state_updated', payload);
    }

    handlePlayerMoved(payload) {
        this.animatePlayerMove(payload.playerId, payload.fromPosition, payload.toPosition);
        logger.logPlayerAction('player_moved', payload);
    }

    handleDiceRolled(payload) {
        this.lastDiceRoll = payload.value;
        this.animateDiceRoll(payload.value);
        logger.logPlayerAction('dice_rolled', { value: payload.value, playerId: payload.playerId });
    }

    handleGameFinished(payload) {
        this.gamePhase = 'finished';
        this.showGameResult(payload.winner);
        logger.logGameEvent('game_finished', payload);
    }

    handleChatMessage(payload) {
        this.addChatMessage(payload.playerName, payload.message);
        logger.logGameEvent('chat_message', payload);
    }

    handleServerError(payload) {
        this.showError(payload.message);
        logger.logError(new Error(payload.message), 'server_error');
    }

    setupEventListeners() {
        // Roll dice button
        document.getElementById('roll-dice').addEventListener('click', () => {
            this.rollDice();
        });

        // Leave game button
        document.getElementById('leave-game').addEventListener('click', () => {
            this.leaveGame();
        });

        // Chat
        document.getElementById('send-message').addEventListener('click', () => {
            this.sendChatMessage();
        });

        document.getElementById('chat-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.sendChatMessage();
            }
        });

        // Window resize
        window.addEventListener('resize', () => {
            this.onWindowResize();
        });

        // Error handling
        window.addEventListener('error', (event) => {
            logger.logError(event.error, 'global_error');
        });

        logger.logGameEvent('event_listeners_setup');
    }

    rollDice() {
        if (this.gamePhase !== 'playing' || this.currentPlayer !== this.getPlayerIndex()) {
            logger.logPlayerAction('roll_dice_blocked', { reason: 'not_player_turn' });
            return;
        }

        logger.logPlayerAction('roll_dice_clicked');

        // For demo, generate random dice value
        const diceValue = Math.floor(Math.random() * 6) + 1;
        this.handleDiceRolled({ value: diceValue, playerId: this.playerId });

        /* Uncomment for real WebSocket:
        this.websocket.send(JSON.stringify({
            type: 'roll_dice',
            payload: {
                playerId: this.playerId,
                gameId: this.gameId
            }
        }));
        */

        document.getElementById('roll-dice').disabled = true;
    }

    animateDiceRoll(value) {
        const startTime = performance.now();
        
        // Animate dice spinning
        const spinDuration = 1000; // 1 second
        const startRotation = { x: this.dice.rotation.x, y: this.dice.rotation.y, z: this.dice.rotation.z };
        
        const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / spinDuration, 1);
            
            if (progress < 1) {
                this.dice.rotation.x = startRotation.x + (Math.PI * 4 * progress);
                this.dice.rotation.y = startRotation.y + (Math.PI * 3 * progress);
                this.dice.rotation.z = startRotation.z + (Math.PI * 2 * progress);
                
                requestAnimationFrame(animate);
            } else {
                // Final position based on dice value
                this.dice.rotation.x = 0;
                this.dice.rotation.y = 0;
                this.dice.rotation.z = 0;
                
                // Update UI
                document.getElementById('dice-value').textContent = value;
                
                // Enable dice for next turn (simulate turn progression)
                setTimeout(() => {
                    document.getElementById('roll-dice').disabled = false;
                }, 2000);
                
                logger.logPerformance('dice_animation', performance.now() - startTime, 'milliseconds');
                logger.log3DEvent('dice_animation_completed', { value, duration: elapsed });
            }
        };
        
        requestAnimationFrame(animate);
    }

    animatePlayerMove(playerId, fromPos, toPos) {
        logger.log3DEvent('player_move_animation', { playerId, fromPos, toPos });
        // Animation logic would go here
    }

    setupUI() {
        this.updatePlayersUI();
        this.updateGameUI();
        logger.logGameEvent('ui_setup_completed');
    }

    updatePlayersUI() {
        const playersList = document.getElementById('players');
        playersList.innerHTML = '';
        
        this.players.forEach((player, index) => {
            const li = document.createElement('li');
            li.innerHTML = `
                <span>${player.name}</span>
                <span class="player-color" style="background-color: ${this.getPlayerColor(index)};"></span>
            `;
            playersList.appendChild(li);
        });
    }

    updateGameUI() {
        const currentPlayerName = this.players[this.currentPlayer]?.name || 'Unknown';
        document.getElementById('player-name').textContent = currentPlayerName;
        document.getElementById('status-text').textContent = this.gamePhase;
        
        // Enable/disable roll dice button
        const rollButton = document.getElementById('roll-dice');
        rollButton.disabled = this.gamePhase !== 'playing' || this.currentPlayer !== this.getPlayerIndex();
    }

    getPlayerColor(index) {
        const colors = ['#FF0000', '#00FF00', '#0000FF', '#FFFF00'];
        return colors[index] || '#FFFFFF';
    }

    getPlayerIndex() {
        return this.players.findIndex(p => p.id === this.playerId);
    }

    sendChatMessage() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        
        if (message) {
            // For demo, add message locally
            this.addChatMessage('You', message);
            
            /* Uncomment for real WebSocket:
            if (this.websocket) {
                this.websocket.send(JSON.stringify({
                    type: 'chat_message',
                    payload: {
                        gameId: this.gameId,
                        playerId: this.playerId,
                        message: message
                    }
                }));
            }
            */
            
            input.value = '';
            logger.logPlayerAction('chat_message_sent', { messageLength: message.length });
        }
    }

    addChatMessage(playerName, message) {
        const chatMessages = document.getElementById('chat-messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message';
        messageDiv.innerHTML = `<span class="player">${playerName}:</span> ${message}`;
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    leaveGame() {
        logger.logPlayerAction('leave_game');
        
        if (this.websocket) {
            this.websocket.close();
        }
        
        // Reset game state
        this.gamePhase = 'waiting';
        this.updateGameUI();
        
        this.showError('You left the game. Refresh to play again.');
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    }

    onWindowResize() {
        const canvas = document.getElementById('game-canvas');
        const container = canvas.parentElement;
        
        this.camera.aspect = container.clientWidth / container.clientHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(container.clientWidth, container.clientHeight);
        
        logger.logGameEvent('window_resized', {
            width: container.clientWidth,
            height: container.clientHeight
        });
    }

    hideLoadingScreen() {
        const loadingScreen = document.getElementById('loading-screen');
        loadingScreen.style.display = 'none';
        logger.logGameEvent('loading_screen_hidden');
    }

    showError(message) {
        alert('Error: ' + message);
        logger.logError(new Error(message), 'user_facing_error');
    }

    showGameResult(winner) {
        alert(`Game finished! Winner: ${winner}`);
        logger.logGameEvent('game_result_shown', { winner });
    }
}

// Global game instance
let game;

// Initialize game when page loads
window.addEventListener('load', () => {
    try {
        game = new LudoGame();
        logger.logGameEvent('page_loaded');
    } catch (error) {
        logger.logError(error, 'game_startup');
        console.error('Failed to start game:', error);
    }
});

// Export logger for debugging
window.gameLogger = logger;
