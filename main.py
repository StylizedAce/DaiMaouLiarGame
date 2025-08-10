# main.py
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from threading import Lock
import uuid
import random
import os
import time
import pandas as pd
import sqlite3
import json
import atexit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

lock = Lock()

# SQLite database setup
DB_PATH = 'game_rooms.db'

def init_database():
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create rooms table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            room_id TEXT PRIMARY KEY,
            players TEXT NOT NULL,  -- JSON string
            host_id TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'waiting',
            imposter_id TEXT,
            roles TEXT,  -- JSON string
            questions TEXT,  -- JSON string
            answers TEXT,  -- JSON string
            votes TEXT,  -- JSON string
            results TEXT,  -- JSON string
            lobby_events TEXT,  -- JSON string
            main_question TEXT,
            ready_to_vote TEXT,  -- JSON string
            settings TEXT,  -- JSON string
            question_phase_start_timestamp INTEGER,
            voting_phase_start_timestamp INTEGER,
            vote_selection_start_timestamp INTEGER,
            liar_votes TEXT,  -- JSON string
            used_question_indexes TEXT  -- JSON string
        )
    ''')

    # Create questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normal_question TEXT NOT NULL,
            imposter_question TEXT NOT NULL
        )
    ''')

    # Check if questions table is empty before importing
    cursor.execute('SELECT COUNT(*) FROM questions')
    question_count = cursor.fetchone()[0]
    
    if question_count == 0:
        # import all the questions from the question_pairs.csv into the database
        try:
            questions_df = pd.read_csv('question_pairs.csv')
            for _, row in questions_df.iterrows():
                cursor.execute('''
                    INSERT INTO questions (normal_question, imposter_question) VALUES (?, ?)
                ''', (row['Normal_Question'], row['Imposter_Question']))
            print(f"Imported {len(questions_df)} questions from CSV into database.")
        except Exception as e:
            print(f"Error importing questions from CSV: {e}")

    conn.commit()
    conn.close()

def cleanup_database():
    """Remove the database file on shutdown for fresh slate."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Database cleaned up for fresh slate.")

# Initialize database on startup
init_database()

# Register cleanup function to run on shutdown
atexit.register(cleanup_database)

def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    return conn

def create_room_in_db(room_id, room_data):
    """Create a new room in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO rooms (
            room_id, players, host_id, phase, imposter_id, roles, questions,
            answers, votes, results, lobby_events, main_question, ready_to_vote,
            settings, question_phase_start_timestamp, voting_phase_start_timestamp,
            vote_selection_start_timestamp, liar_votes, used_question_indexes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        room_id,
        json.dumps(room_data.get('players', [])),
        room_data.get('host_id', ''),
        room_data.get('phase', 'waiting'),
        room_data.get('imposter_id'),
        json.dumps(room_data.get('roles', {})),
        json.dumps(room_data.get('questions', {})),
        json.dumps(room_data.get('answers', {})),
        json.dumps(room_data.get('votes', {})),
        json.dumps(room_data.get('results', {})),
        json.dumps(room_data.get('lobby_events', [])),
        room_data.get('main_question'),
        json.dumps(room_data.get('ready_to_vote', [])),
        json.dumps(room_data.get('settings', {})),
        room_data.get('questionPhaseStartTimestamp'),
        room_data.get('votingPhaseStartTimestamp'),
        room_data.get('voteSelectionStartTimestamp'),
        json.dumps(room_data.get('liarVotes', {})),
        json.dumps(room_data.get('used_question_indexes', []))
    ))
    
    conn.commit()
    conn.close()

def get_room_from_db(room_id):
    """Get a room from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM rooms WHERE room_id = ?', (room_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    # Convert back to dictionary format
    room_data = {
        'players': json.loads(row['players']),
        'host_id': row['host_id'],
        'phase': row['phase'],
        'imposter_id': row['imposter_id'],
        'roles': json.loads(row['roles']),
        'questions': json.loads(row['questions']),
        'answers': json.loads(row['answers']),
        'votes': json.loads(row['votes']),
        'results': json.loads(row['results']),
        'lobby_events': json.loads(row['lobby_events']),
        'main_question': row['main_question'],
        'ready_to_vote': json.loads(row['ready_to_vote']),
        'settings': json.loads(row['settings']),
        'questionPhaseStartTimestamp': row['question_phase_start_timestamp'],
        'votingPhaseStartTimestamp': row['voting_phase_start_timestamp'],
        'voteSelectionStartTimestamp': row['vote_selection_start_timestamp'],
        'liarVotes': json.loads(row['liar_votes']),
        'used_question_indexes': json.loads(row['used_question_indexes'])
    }
    
    return room_data

def update_room_in_db(room_id, room_data):
    """Update a room in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE rooms SET
            players = ?, host_id = ?, phase = ?, imposter_id = ?, roles = ?,
            questions = ?, answers = ?, votes = ?, results = ?, lobby_events = ?,
            main_question = ?, ready_to_vote = ?, settings = ?,
            question_phase_start_timestamp = ?, voting_phase_start_timestamp = ?,
            vote_selection_start_timestamp = ?, liar_votes = ?, used_question_indexes = ?
        WHERE room_id = ?
    ''', (
        json.dumps(room_data.get('players', [])),
        room_data.get('host_id', ''),
        room_data.get('phase', 'waiting'),
        room_data.get('imposter_id'),
        json.dumps(room_data.get('roles', {})),
        json.dumps(room_data.get('questions', {})),
        json.dumps(room_data.get('answers', {})),
        json.dumps(room_data.get('votes', {})),
        json.dumps(room_data.get('results', {})),
        json.dumps(room_data.get('lobby_events', [])),
        room_data.get('main_question'),
        json.dumps(room_data.get('ready_to_vote', [])),
        json.dumps(room_data.get('settings', {})),
        room_data.get('questionPhaseStartTimestamp'),  # Fixed missing parenthesis
        room_data.get('votingPhaseStartTimestamp'),
        room_data.get('voteSelectionStartTimestamp'),
        json.dumps(room_data.get('liarVotes', {})),
        json.dumps(room_data.get('used_question_indexes', [])),
        room_id
    ))
    
    conn.commit()
    conn.close()

def delete_room_from_db(room_id):
    """Delete a room from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM rooms WHERE room_id = ?', (room_id,))
    
    conn.commit()
    conn.close()

def get_all_room_ids():
    """Get all room IDs from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT room_id FROM rooms')
    rows = cursor.fetchall()
    conn.close()
    
    return [row['room_id'] for row in rows]

def room_exists_in_db(room_id):
    """Check if a room exists in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT 1 FROM rooms WHERE room_id = ?', (room_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    
    return exists

""" QUESTION_PAIRS = [
    ("What's your favorite type of food?", "What was the last thing you ate?"),
    ("What's your dream vacation?", "What's your next planned trip?"),
    ("What's your biggest fear?", "What's something you dislike?"),
    ("What's your favorite movie?", "What's the last movie you watched?"),
    ("What's your favorite animal?", "What pet do you have?")
] """

def get_question_pair(used_indexes=None):
    """
    Returns a single random question pair (normal, imposter) from the database.
    Avoids previously used indexes for the current room session.
    
    Args:
        used_indexes (list): List of question indexes already used in this room session
        
    Returns:
        tuple: (normal_question, imposter_question) or None if error
    """
    if used_indexes is None:
        used_indexes = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, normal_question, imposter_question FROM questions')
        questions = cursor.fetchall()
        conn.close()
        
        if not questions:
            print("DEBUG: No questions found in database.")
            return None
        
        # Get available indexes (excluding used ones)
        all_indexes = [q['id'] for q in questions]
        available_indexes = [idx for idx in all_indexes if idx not in used_indexes]
        
        if not available_indexes:
            print("WARNING: All questions have been used. Resetting question pool.")
            available_indexes = all_indexes  # Reset if all questions used
        
        # Pick random available index
        selected_id = random.choice(available_indexes)
        
        # Get the question pair
        selected_question = next(q for q in questions if q['id'] == selected_id)
        question_pair = (selected_question['normal_question'], selected_question['imposter_question'])
        
        print(f"DEBUG: Selected question ID {selected_id}: {question_pair[0]}")
        return question_pair
        
    except Exception as e:
        print(f"DEBUG: Could not load questions from database ({e}).")
        return None


def get_player_info_by_id(players_list, player_id):
    """Helper function to find a player dictionary in a list by their ID."""
    return next((p for p in players_list if p["id"] == player_id), None)

def get_room_state(room_id, room=None):
    """ This function given a room ID can fetch the roomdata from the currently running rooms.
    It is used in every state emission.
    Accepts an optional 'room' dictionary to avoid redundant database reads.
    """
    with lock:
        if room is None:
            room = get_room_from_db(room_id)
        if not room:
            return None

        # Base state visible to everyone
        active_players = [p for p in room["players"] if not p.get("disconnected")]
        
        state = {
            "roomId": room_id,
            "phase": room["phase"],
            "players": active_players,
            "hostId": room["host_id"],
            "lobbyEvents": room["lobby_events"],
            "settings": room.get("settings", {})
        }

        if room["phase"] == "question":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["submittedCount"] = len(room.get("answers", {}))
            
            # Build the answers list
            answers_list = []
            for player_id, answer in room.get("answers", {}).items():
                player = get_player_info_by_id(room["players"], player_id)
                if player:
                    answers_list.append({
                        "playerId": player_id,
                        "name": player["name"],
                        "answer": answer
                    })
            state["answers"] = answers_list

        # Add phase-specific data
        if room["phase"] == "voting":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["votingPhaseStartTimestamp"] = room.get("votingPhaseStartTimestamp")

            answers_list = []
            for player_id, answer in room.get("answers", {}).items():
                player = get_player_info_by_id(room["players"], player_id)
                if player:
                    answers_list.append({
                        "playerId": player_id,
                        "name": player["name"],
                        "answer": answer
                    })
            state["answers"] = answers_list
            
            state["mainQuestion"] = room["main_question"]
            state["ready_to_vote"] = room.get("ready_to_vote", [])

        elif room["phase"] == "vote_selection":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["votingPhaseStartTimestamp"] = room.get("votingPhaseStartTimestamp")
            state["voteSelectionStartTimestamp"] = room.get("voteSelectionStartTimestamp")
            
            answers_list = []
            for player_id, answer in room.get("answers", {}).items():
                player = get_player_info_by_id(room["players"], player_id)
                if player:
                    answers_list.append({
                        "playerId": player_id,
                        "name": player["name"],
                        "answer": answer
                    })
            state["answers"] = answers_list
            
            state["mainQuestion"] = room["main_question"]
            state["ready_to_vote"] = room.get("ready_to_vote", [])
            state["liarVotes"] = room.get("liarVotes", {})
            state["impostorIds"] = room.get("impostor_ids", [room.get("imposter_id")] if room.get("imposter_id") else [])
            state["imposterId"] = room.get("imposter_id")

        elif room["phase"] == "results":
            state["results"] = room["results"]
            state["questions"] = room["questions"]

    return state

def emit_state_update(room_id, room=None):
    """Emits the full game state to all clients in a room."""
    room_state = get_room_state(room_id, room)
    if room_state:
        print(f"DEBUG: Emitting state update for room {room_id}. Phase: {room_state.get('phase')}")
        
        # Emit general state to the room
        socketio.emit('update_game_state', room_state, room=room_id)

        # Emit personal info (role, question) to each player individually
        if room is None: # Fetch if not already provided
            room = get_room_from_db(room_id)
        if room and room["phase"] == "question":
            for p in room["players"]:
                personal_info = {
                    "role": room["roles"].get(p["id"]),
                    "question": room["questions"].get(p["id"])
                }
                target_sid = p.get("socket_id")
                if target_sid:
                    socketio.emit('personal_game_info', personal_info, room=target_sid)
    else:
        print(f"DEBUG: No room state found for room {room_id}")

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect(reason=None):
    print(f"Client disconnected: {request.sid} (reason: {reason})")
    with lock:
        room_to_update = None
        for room_id in get_all_room_ids():
            room = get_room_from_db(room_id)
            if not room:
                continue
                
            player_to_update = next((p for p in room["players"] if p.get("socket_id") == request.sid), None)

            if player_to_update:
                player_id = player_to_update["id"]
                player_name = player_to_update["name"]
                
                # Mark player as disconnected instead of removing them
                player_to_update["disconnected"] = True
                player_to_update["disconnect_time"] = time.time()
                player_to_update.pop("socket_id", None)  # Remove socket_id safely
                room["lobby_events"].append(f"{player_name} has disconnected.")
                
                # Check if we need to clean up expired disconnected players
                current_time = time.time()
                expired_players = [p for p in room["players"] if p.get("disconnected") and (current_time - p.get("disconnect_time", 0)) > 60]
                
                # Remove expired disconnected players
                for expired_player in expired_players:
                    room["players"] = [p for p in room["players"] if p["id"] != expired_player["id"]]
                    room["lobby_events"].append(f"{expired_player['name']} has been removed (reconnect timeout).")
                
                # Get active (non-disconnected) players
                active_players = [p for p in room["players"] if not p.get("disconnected")]
                
                if not active_players:
                    delete_room_from_db(room_id)
                    print(f"Room {room_id} has no active players and has been removed.")
                    return
                
                # If the disconnected player was the host, assign a new host from active players
                if player_id == room["host_id"] and active_players:
                    room["host_id"] = active_players[0]["id"]
                    new_host_name = active_players[0]["name"]
                    room["lobby_events"].append(f"{new_host_name} is the new host.")


                # Update the room in database
                update_room_in_db(room_id, room)
                room_to_update = room_id
                break
    
    if room_to_update:
        emit_state_update(room_to_update)

@socketio.on('rejoin_game')
def handle_rejoin_game(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    timestamp = data.get("timeStamp")

    print(f"🔄 Rejoin request: SID={request.sid}, Room={room_id}, Player={player_id}")

    if not room_id or not player_id:
        emit('error', {"message": "Room ID and Player ID are required."})
        return

    try:
        with lock:
            room = get_room_from_db(room_id)
            if not room:
                print(f"❌ Room {room_id} does not exist")
                emit('error', {"message": "Room does not exist."})
                return

            player_to_rejoin = next((p for p in room["players"] if p["id"] == player_id), None)
            
            if not player_to_rejoin:
                print(f"❌ Player {player_id} not found in room {room_id}")
                emit('error', {"message": "Player not found in room."})
                return

            if not player_to_rejoin.get("disconnected"):
                print(f"❌ Player {player_id} is not marked as disconnected")
                emit('error', {"message": "Player is not disconnected."})
                return

            disconnect_time = player_to_rejoin.get("disconnect_time", 0)
            if time.time() - disconnect_time > 60:
                print(f"❌ Reconnection time window expired for player {player_id}")
                emit('error', {"message": "Reconnection time window has expired."})
                return

            print(f"✅ Player {player_id} is eligible to rejoin room {room_id}")

            player_to_rejoin["disconnected"] = False
            player_to_rejoin.pop("disconnect_time", None)
            player_to_rejoin["socket_id"] = request.sid

            print(f"🔗 Joining socket room {room_id}")
            join_room(room_id)
            
            room["lobby_events"].append(f"{player_to_rejoin['name']} has reconnected.")

            print(f"💾 Updating room in database")
            update_room_in_db(room_id, room)

        # Emissions must happen after the room data is fully updated
        room_state = get_room_state(room_id)
        
        # We need to manually emit to the reconnected player first to prevent race conditions.
        # The global emit_state_update call will then catch any other players.
        player = get_player_info_by_id(room_state["players"], player_id)
        if player and room_state["phase"] == "question":
            personal_info = {
                "role": room["roles"].get(player_id),
                "question": room["questions"].get(player_id)
            }
            emit('personal_game_info', personal_info, room=player["socket_id"])

        emit('reconnect_player', {
            'success': True,
            'message': 'Successfully reconnected to the game',
            'gameState': room_state,
            'playerId': player_id
        }, room=request.sid)

        print(f"🌐 Emitting state update to all players in room {room_id}")
        emit_state_update(room_id)
        print(f"✅ Rejoin process completed for player {player_id}")
        
    except Exception as e:
        print(f"❌ Error in rejoin_game: {e}")
        import traceback
        traceback.print_exc()
        emit('error', {"message": "An error occurred during rejoin."})

@socketio.on('join_room')
def on_join_room(data):
    room_id = data.get("roomId")
    name = data.get("name")
    userAvatar = data.get("avatar")
    print(f"Join request: {request.sid} for room {room_id} with name {name} and avatar {userAvatar}")
    if not room_id or not name or not userAvatar:
        emit('error_event', {'message': 'Room ID, name, and user avatar are required.'}, room=request.sid)
        return

    # If validation passes, proceed to join the room
    with lock:
        room = get_room_from_db(room_id)
        if not room:
            emit('error_event', {'message': 'The room you were trying to reach doesn\'t exist anymore.'}, room=request.sid)
            return
            
        else:
            # Join an existing room
            if room["phase"] != "waiting":
                emit('error_event', {'message': 'Game is already in progress.'}, room=request.sid)
                return
            max_players = room.get("settings", {}).get("playerCount", 6)  # default
            if len(room["players"]) >= max_players:
                emit('error_event', {'message': 'The room you were trying to reach seems full.'}, room=request.sid)
                return

            if any(p["name"] == name for p in room["players"]):
                emit('error_event', {'message': 'That name is already taken.'}, room=request.sid)
                return

            player_id = str(uuid.uuid4())
            room["players"].append({"id": player_id, "name": name, "avatar": userAvatar, "socket_id": request.sid})
            room["lobby_events"].append(f"{name} has joined the game.")
            
            # Update room in database
            update_room_in_db(room_id, room)

        join_room(room_id)
        # Send confirmation with their new ID
        emit('join_confirmation', {'playerId': player_id, 'roomId': room_id}, room=request.sid)

    emit_state_update(room_id)

@socketio.on('create_room')
def on_create_room(data):
    room_id = data.get("roomId")
    name = data.get("name")
    userAvatar = data.get("avatar")
    print(f"Create room request: {request.sid} for room {room_id} with name {name} and avatar {userAvatar}")

    if not room_id or not name or not userAvatar:
        emit('error_event', {'message': 'Room ID, name, and user avatar are required.'}, room=request.sid)
        return

    with lock:
        if room_exists_in_db(room_id):
            emit('error_event', {'message': 'Room already exists.'}, room=request.sid)
            return

        player_id = str(uuid.uuid4())
        room_data = {
            "players": [{"id": player_id, "name": name, "avatar": userAvatar, "socket_id": request.sid}],
            "host_id": player_id,  # First player is the host
            "phase": "waiting",
            "imposter_id": None,
            "roles": {},
            "questions": {},
            "answers": {},
            "votes": {},
            "results": {},
            "lobby_events": [f"{name} created the room and is the host."],
            "main_question": None,  # Initialize main_question
            'ready_to_vote': []
        }
        
        # Create room in database
        create_room_in_db(room_id, room_data)

        join_room(room_id)
        emit('join_confirmation', {'playerId': player_id, 'roomId': room_id}, room=request.sid)

    emit_state_update(room_id)


@socketio.on('leave_room')
def on_leave_room(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    
    print(f"Leave request: {request.sid} for room {room_id} with player ID {player_id}")
    
    if not room_id or not player_id:
        emit('error_event', {'message': 'Room ID and player ID are required.'}, room=request.sid)
        return

    with lock:
        room = get_room_from_db(room_id)
        if not room:
            emit('error_event', {'message': 'The room you were trying to reach doesn\'t exist anymore.'}, room=request.sid)
            return
        
        # Find the player in the room
        player_to_remove = next((p for p in room["players"] if p["id"] == player_id), None)
        if not player_to_remove:
            emit('error_event', {'message': 'Player not found in room.'}, room=request.sid)
            return
        
        # Verify the socket ID matches (security check)
        if player_to_remove.get("socket_id") != request.sid:
            emit('error_event', {'message': 'Invalid player credentials.'}, room=request.sid)
            return
        
        player_name = player_to_remove["name"]
        
        # Remove the player from the room
        room["players"] = [p for p in room["players"] if p["id"] != player_id]
        room["lobby_events"].append(f"{player_name} has left the game.")
        
        # Leave the socket room
        leave_room(room_id)
        
        # Send confirmation to the leaving player
        emit('leave_confirmation', {'message': 'Successfully left the room.'}, room=request.sid)
        
        # Check if room is now empty
        if not room["players"]:
            delete_room_from_db(room_id)
            print(f"Room {room_id} is empty and has been removed.")
            return
        
        # If the host left, assign a new host
        if player_id == room["host_id"]:
            room["host_id"] = room["players"][0]["id"]
            new_host_name = room["players"][0]["name"]
            room["lobby_events"].append(f"{new_host_name} is the new host.")
    
        # Update room in database
        update_room_in_db(room_id, room)
    
    # Update all remaining players in the room
    emit_state_update(room_id)


@socketio.on('start_game')
def on_start_game(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    settings = data.get("settings")

    with lock:
        room = get_room_from_db(room_id)
        if not room: return
        
        room["settings"] = settings 

        # Validation: Only the host can start, and only with enough players
        if room["host_id"] != player_id:
            emit('error_event', {'message': 'Only the host can start the game.'}, room=request.sid)
            return
        if len(room["players"]) < 2: # Min 2 players
            emit('error_event', {'message': 'You need at least 2 players to start.'}, room=request.sid)
            return
        
        # --- Start Game Logic ---
        players = room["players"]
        q_pair = get_question_pair(used_indexes=room.get("used_question_indexes", []))
        room["main_question"] = q_pair[0]

        # Determine impostor count based on game mode
        game_mode = room.get("settings", {}).get("gameMode", "normal")
        if game_mode == "mayhem":
            impostor_count = get_mayhem_impostor_count(len(players))
        else:
            impostor_count = 1

        # Select impostors
        impostors = random.sample(players, impostor_count) if impostor_count > 0 else []
        impostor_ids = [imp["id"] for imp in impostors]

        # Store impostor info (update to handle multiple)
        room["impostor_ids"] = impostor_ids
        room["imposter_id"] = impostor_ids[0] if impostor_ids else None

        # Assign roles and questions
        for p in players:
            is_imposter = p["id"] in impostor_ids
            room["roles"][p["id"]] = "imposter" if is_imposter else "normal"
            room["questions"][p["id"]] = q_pair[1] if is_imposter else q_pair[0]


        room["answers"], room["votes"], room["results"] = {}, {}, {}
        room["phase"] = "question"
        room["questionPhaseStartTimestamp"] = int(time.time() * 1000) - 2000
        room["lobby_events"].append("The game has started!")
        
        # Update room in database
        update_room_in_db(room_id, room)

    emit_state_update(room_id, room)


@socketio.on('submit_answer')
def on_submit_answer(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    answer = data.get("answer")

    with lock:
        room = get_room_from_db(room_id)
        if not room or room["phase"] != "question":
            return

        is_new_submission = player_id not in room["answers"]
        room["answers"][player_id] = answer

        player_name = next((p["name"] for p in room["players"] if p["id"] == player_id), "Someone")

        if is_new_submission:
            room["lobby_events"].append(f"{player_name} submitted their answer.")
        else:
            room["lobby_events"].append(f"{player_name} updated their answer.")

        # Check if all players have answered
        if len(room["answers"]) == len(room["players"]):
            room["phase"] = "voting"
            room["votingPhaseStartTimestamp"] = int(time.time() * 1000)
            room["lobby_events"].append("All answers are in! Time to vote.")
            room['ready_to_vote'] = [] 
            
        # Update room in database
        update_room_in_db(room_id, room)
    
    # We pass the updated 'room' object directly to prevent a race condition.
    emit_state_update(room_id, room)


@socketio.on('update_settings')
def on_update_settings(data):
    room_id = data.get("roomId")
    new_settings = data.get("settings")

    with lock:
        room = get_room_from_db(room_id)
        if not room:
            return

        room["settings"] = new_settings
        room["lobby_events"].append("Host updated the game settings.")
        
        # Update room in database
        update_room_in_db(room_id, room)

    emit_state_update(room_id, room)

@socketio.on('submit_vote')
def on_submit_vote(data):
    room_id = data.get("roomId")
    voter_id = data.get("playerId")
    voted_for_id = data.get("votedForId")

    with lock:
        room = get_room_from_db(room_id)
        if not room or room["phase"] != "voting": return
        if voter_id in room["votes"]: return # Prevent re-submission

        room["votes"][voter_id] = voted_for_id
        voter_name = next((p["name"] for p in room["players"] if p["id"] == voter_id), "Someone")
        room["lobby_events"].append(f"{voter_name} has cast their vote.")
        
        # Update room in database
        update_room_in_db(room_id, room)
    
    emit_state_update(room_id, room)

@app.route('/hello', methods=['GET'])
def index():
    # updateing pandas with new data,
    # saving to database
    #database saved.
    return "Welcome to the Dai Maou Liar Game!"


@socketio.on("kick_player")
def handle_kick_player(data):
    room_id = data.get("roomId")
    target_player_id = data.get("targetPlayerId")
    by_player_id = data.get("byPlayerId")

    print(f"KICK request: {by_player_id} is trying to kick {target_player_id} from {room_id}")

    with lock:
        room = get_room_from_db(room_id)
        if not room:
            emit("error_event", {"message": "Room not found."}, room=request.sid)
            return

        if by_player_id != room["host_id"]:
            emit("error_event", {"message": "Only the host can kick players."}, room=request.sid)
            return

        player_to_kick = next((p for p in room["players"] if p["id"] == target_player_id), None)
        if not player_to_kick:
            emit("error_event", {"message": "Player to kick not found."}, room=request.sid)
            return

        target_socket_id = player_to_kick["socket_id"]
        player_name = player_to_kick["name"]

        room["players"] = [p for p in room["players"] if p["id"] != target_player_id]
        room["lobby_events"].append(f"{player_name} was kicked from the game.")
        
        # Update room in database
        update_room_in_db(room_id, room)

    # Alert the kicked player
    emit('kicked_from_room', {"message": "You have been removed from the game."}, to=target_socket_id)

    try:
        socketio.disconnect(target_socket_id)
    except Exception as e:
        print(f"Error disconnecting socket: {e}")

    # Emit full state update using the same logic as leave_room
    emit_state_update(room_id)


@socketio.on('ready_to_vote')
def handle_ready_to_vote(data):
    room_id = data.get('roomId')
    player_id = data.get('playerId')

    if not room_id or not player_id:
        return

    with lock:
        room = get_room_from_db(room_id)
        if not room:
            return

        # Ensure the list exists
        if 'ready_to_vote' not in room:
            room['ready_to_vote'] = []

        # Add player if not already there
        if player_id not in room['ready_to_vote']:
            room['ready_to_vote'].append(player_id)
            player_name = next((p["name"] for p in room["players"] if p["id"] == player_id), "Someone")
            room["lobby_events"].append(f"{player_name} is ready to vote.")
            
            # Update room in database
            update_room_in_db(room_id, room)

    # Emit state update first
    emit_state_update(room_id)
    
    # Then check if we need to transition (do this after emit to avoid race conditions)
    room = get_room_from_db(room_id)
    if room and len(room.get('ready_to_vote', [])) == len(room['players']):
        transition_to_vote_selection(room_id)

def transition_to_vote_selection(room_id):
    with lock:
        room = get_room_from_db(room_id)
        if not room:
            return
        
        # Only transition if we're currently in voting phase
        if room['phase'] != 'voting':
            return
        
        room['phase'] = 'vote_selection'
    room['voteSelectionStartTimestamp'] = int(time.time() * 1000)
    room["lobby_events"].append("Time to vote for the imposter!")
    room["liarVotes"] = {}
    
    # CLEAR the ready_to_vote list for the new phase
    room['ready_to_vote'] = []
    
    # Update room in database
    update_room_in_db(room_id, room)

# Emit outside the lock to avoid deadlock
    emit_state_update(room_id)
    
@socketio.on('voting_timer_expired')
def handle_voting_timer_expired(data):
    room_id = data['roomId']
    print(f"🟡 Event received: voting_timer_expired for room {room_id}")

    if room_exists_in_db(room_id):
        print(f"✅ Timer expired in voting phase — transitioning room {room_id}")
        with lock:
            room = get_room_from_db(room_id)
            if room:
                room['phase'] = 'vote_selection'
                room['voteSelectionStartTimestamp'] = time.time()
                update_room_in_db(room_id, room)

        emit_state_update(room_id)

@socketio.on('liar_vote')
def handle_liar_vote(data):
    room_id = data.get('roomId')
    voter_id = data.get('playerId')
    target_id = data.get('targetId')

    if not room_id or not voter_id or not target_id:
        return

    with lock:
        room = get_room_from_db(room_id)
        if not room or room['phase'] != 'vote_selection':
            return

        if 'liarVotes' not in room:
            room['liarVotes'] = {}

        # Get game mode to determine voting behavior
        game_mode = room.get("settings", {}).get("gameMode", "normal")

        if game_mode != "mayhem":
            # Normal mode: Remove previous vote (only one vote allowed)
            for voters in room['liarVotes'].values():
                if voter_id in voters:
                    voters.remove(voter_id)
        # In mayhem mode: Allow multiple votes, don't remove previous ones

        if target_id not in room['liarVotes']:
            room['liarVotes'][target_id] = []

        # Add the vote (even if duplicate in mayhem mode)
        room['liarVotes'][target_id].append(voter_id)

        voter_name = next((p["name"] for p in room["players"] if p["id"] == voter_id), "Someone")
        target_name = next((p["name"] for p in room["players"] if p["id"] == target_id), "Unknown")
        room["lobby_events"].append(f"{voter_name} voted for {target_name}.")
        
        # Update room in database
        update_room_in_db(room_id, room)

    emit_state_update(room_id)

def get_mayhem_impostor_count(player_count):
    """
    Determines the number of impostors for Mayhem mode based on random chance.
    Scales with player count for more chaos.
    """
    rand = random.random() * 100
    
    if player_count == 4:
        # 4 players
        if rand < 10:  # 10%
            return 0
        elif rand < 30:  # 20%
            return 3  # 3 out of 4
        elif rand < 90:  # 60%
            return 2
        else:  # 10%
            return 1
    
    elif player_count <= 6:
        # 5-6 players: more variety
        if rand < 5:  # 5%
            return 0
        elif rand < 10:  # 5%
            return player_count - 1  # Everyone except 1
        elif rand < 25:  # 15%
            return player_count - 2  # Everyone except 2
        elif rand < 70:  # 45%
            return player_count // 2  # Half the players
        else:  # 30%
            return min(3, player_count - 2)
    
    else:  # 7+ players
        # Big games: maximum chaos potential
        if rand < 3:  # 3%
            return 0
        elif rand < 8:  # 5%
            return player_count - 1  # Everyone except 1 (extreme scenario!)
        elif rand < 18:  # 10%
            return player_count - 2  # Everyone except 2
        elif rand < 40:  # 22%
            return player_count // 2  # Half the players
        elif rand < 70:  # 30%
            return (player_count * 2) // 3  # Two-thirds are impostors
        else:  # 30%
            return player_count // 3  # One-third are impostors

@socketio.on('remove_answer')
def on_remove_answer(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")

    with lock:
        room = get_room_from_db(room_id)
        if not room or room["phase"] != "question": 
            return

        # Remove the player's answer
        if player_id in room["answers"]:
            del room["answers"][player_id]
            
            player_name = next((p["name"] for p in room["players"] if p["id"] == player_id), "Someone")
            room["lobby_events"].append(f"{player_name} is editing their answer.")
            
            # Update room in database
            update_room_in_db(room_id, room)

    emit_state_update(room_id)

if __name__ == "__main__":
    DEVELOPMENT = True
    if not DEVELOPMENT:
        port = int(os.environ.get("PORT", 5000))
        socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

    else:
        socketio.run(app, port=5000, debug=True, allow_unsafe_werkzeug=True) # debug=True for development
