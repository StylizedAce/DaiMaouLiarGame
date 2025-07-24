from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from threading import Lock, Thread
import uuid
import random
import time

app = Flask(__name__)
# Configure SocketIO to use WebSocket. You might need to install 'eventlet' or 'gevent' for production use,
# but for development, the default (threading) is usually fine.
socketio = SocketIO(app, cors_allowed_origins="*") # Allow all origins for local testing

lock = Lock()

rooms = {}

QUESTION_PAIRS = [
    ("What's your favorite type of food?", "What was the last thing you ate?"),
    ("What's your dream vacation?", "What's your next planned trip?"),
    ("What's your biggest fear?", "What's something you dislike?"),
    ("What's your favorite movie?", "What's the last movie you watched?"),
    ("What’s your favorite animal?", "What pet do you have?")
]

def get_players_info_for_room(room):
    """Helper to get formatted player info for a room."""
    players_info = []
    for p in room["players"]:
        players_info.append({
            "id": p["id"],
            "name": p["name"],
            "ready": room["ready"].get(p["id"], False)
        })
    return players_info

def start_game_logic(room_id):
    """
    Contains the core game start logic, now called directly or via background task.
    This function emits state changes using socketio.emit.
    """
    with lock:
        room = rooms.get(room_id)
        if not room:
            print(f"Error: Room {room_id} not found during game start logic.")
            return

        players = room["players"]
        imposter_player = random.choice(players) # Get the player dictionary
        q_pair = random.choice(QUESTION_PAIRS)

        room["imposter_id"] = imposter_player["id"] # Store imposter's ID
        for p in players:
            role = "imposter" if p["id"] == imposter_player["id"] else "normal"
            room["roles"][p["id"]] = role
            room["questions"][p["id"]] = q_pair[1] if role == "imposter" else q_pair[0]

        room["answers"].clear()
        room["votes"].clear()
        room["state"] = "question"

        # Emit the new state to all players in the room
        socketio.emit('game_state_change', {'state': 'question', 'message': 'Game has started!'}, room=room_id)
        # For each player, also emit their specific role and question
        for p in players:
            socketio.emit('your_game_info', {
                'role': room["roles"][p["id"]],
                'question': room["questions"][p["id"]]
            }, room=p["socket_id"]) # Emit only to that player's socket


# --- SocketIO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    # Find which player/room this disconnected socket belonged to and remove them
    with lock:
        for room_id, room in rooms.items():
            for p_idx, p in enumerate(room["players"]):
                if p.get("socket_id") == request.sid:
                    player_name = p["name"]
                    player_id_to_remove = p["id"]

                    # Remove player from room
                    room["players"].pop(p_idx)
                    room["ready"].pop(player_id_to_remove, None)
                    room["roles"].pop(player_id_to_remove, None)
                    room["questions"].pop(player_id_to_remove, None)
                    room["answers"].pop(player_id_to_remove, None)
                    room["votes"].pop(player_id_to_remove, None)

                    # Notify others in the room
                    emit('player_list_update', {'players': get_players_info_for_room(room)}, room=room_id)
                    emit('lobby_event', {'message': f"{player_name} has left the lobby."}, room=room_id)

                    # If not enough players, reset state
                    if len(room["players"]) < 3 and room["state"] != "waiting":
                        room["state"] = "waiting"
                        emit('game_state_change', {'state': 'waiting', 'message': 'Not enough players, waiting for more...'}, room=room_id)
                        # Ensure any pending game start threads are stopped if applicable
                        # (more complex for threading, but conceptually important)

                    print(f"Player {player_name} ({player_id_to_remove}) removed from room {room_id} due to disconnect.")
                    return # Player found and removed, exit loop

@socketio.on('join_room')
def on_join_room(data):
    room_id = data.get("room_id")
    name = data.get("name")
    if not room_id or not name:
        emit('error', {'message': 'Room ID and name are required.'}, room=request.sid)
        return

    with lock:
        room = rooms.setdefault(room_id, {
            "players": [],
            "roles": {},
            "questions": {},
            "answers": {},
            "votes": {},
            "ready": {},
            "state": "waiting", # Initial state is waiting
            "imposter_id": None
        })

        if room["state"] != "waiting":
            emit('error', {'message': 'Game already started in this room.'}, room=request.sid)
            return

        if any(p["name"] == name for p in room["players"]):
            emit('error', {'message': 'Name already taken in this room.'}, room=request.sid)
            return

        player_id = str(uuid.uuid4())
        room["players"].append({"id": player_id, "name": name, "socket_id": request.sid})
        room["ready"][player_id] = False

        join_room(room_id)

        # Emit confirmation back to the joining client
        emit('joined_confirmation', {'player_id': player_id, 'room_id': room_id}, room=request.sid)

        # --- ADD THIS LINE ---
        # Emit the initial 'waiting' game state to the newly joined client
        emit('game_state_change', {'state': room["state"], 'message': 'Welcome to the lobby! Please ready up.'}, room=request.sid)
        # --- END ADDITION ---

        # Broadcast player list update and event to all clients in the room
        emit('player_list_update', {'players': get_players_info_for_room(room)}, room=room_id)
        emit('lobby_event', {'message': f"{name} has joined the lobby."}, room=room_id)
        print(f"Player {name} ({player_id}) joined room {room_id}")
@socketio.on('ready_up')
def on_ready_up(data):
    room_id = data.get("room_id")
    player_id = data.get("player_id")

    with lock:
        room = rooms.get(room_id)
        if not room or room["state"] != "waiting":
            emit('error', {'message': 'Invalid room state or room not found.'}, room=request.sid)
            return

        # Basic check to ensure player_id matches current socket, useful for security
        player_in_room = next((p for p in room["players"] if p["id"] == player_id), None)
        if not player_in_room or player_in_room["socket_id"] != request.sid:
            emit('error', {'message': 'Unauthorized ready attempt.'}, room=request.sid)
            return

        room["ready"][player_id] = True
        player_name = player_in_room["name"]

        # Broadcast player list update and event
        emit('player_list_update', {'players': get_players_info_for_room(room)}, room=room_id)
        emit('lobby_event', {'message': f"{player_name} is now ready."}, room=room_id)
        print(f"Player {player_name} is ready in room {room_id}")

        if all(room["ready"].values()) and len(room["players"]) >= 3:
            emit('lobby_event', {'message': "All players ready! Game starting in 5 seconds..."}, room=room_id)
            emit('game_state_change', {'state': 'countdown', 'message': 'Game starting in 5 seconds!'}, room=room_id)
            print(f"Room {room_id}: All players ready, starting countdown.")
            # Use socketio.start_background_task for threading with SocketIO
            socketio.start_background_task(target=countdown_and_start_game, room_id=room_id)

@socketio.on('cancel_ready')
def on_cancel_ready(data):
    room_id = data.get("room_id")
    player_id = data.get("player_id")

    with lock:
        room = rooms.get(room_id)
        if not room:
            emit('error', {'message': 'Room not found.'}, room=request.sid)
            return

        player_in_room = next((p for p in room["players"] if p["id"] == player_id), None)
        if not player_in_room or player_in_room["socket_id"] != request.sid:
            emit('error', {'message': 'Unauthorized cancel attempt.'}, room=request.sid)
            return

        player_name = player_in_room["name"]
        
        # Remove player from room
        room["players"] = [p for p in room["players"] if p["id"] != player_id]
        room["ready"].pop(player_id, None)
        room["roles"].pop(player_id, None)
        room["questions"].pop(player_id, None)
        room["answers"].pop(player_id, None)
        room["votes"].pop(player_id, None)

        # Remove client from SocketIO room
        leave_room(room_id)

        # Broadcast player list update and event
        emit('player_list_update', {'players': get_players_info_for_room(room)}, room=room_id)
        emit('lobby_event', {'message': f"{player_name} has left the lobby."}, room=room_id)
        print(f"Player {player_name} left room {room_id}")

        # Reset state if not enough players or if a player cancelled during countdown
        if len(room["players"]) < 3 and room["state"] != "waiting":
            room["state"] = "waiting"
            for pid in room["ready"]: # Un-ready remaining players
                room["ready"][pid] = False
            emit('game_state_change', {'state': 'waiting', 'message': 'Not enough players, returning to waiting.'}, room=room_id)
            emit('player_list_update', {'players': get_players_info_for_room(room)}, room=room_id) # Update ready status
            print(f"Room {room_id}: Not enough players, returned to waiting state.")

    emit('cancelled_confirmation', {'message': 'You have left the room.'}, room=request.sid)


def countdown_and_start_game(room_id):
    """Handles the 5-second countdown before game start."""
    for i in range(5, 0, -1):
        socketio.emit('game_countdown', {'seconds': i}, room=room_id)
        time.sleep(1)
    
    # After countdown, execute the game start logic
    start_game_logic(room_id)


@socketio.on('submit_answer')
def on_submit_answer(data):
    room_id = data.get("room_id")
    player_id = data.get("player_id")
    answer = data.get("answer")

    with lock:
        room = rooms.get(room_id)
        if not room or room["state"] != "question":
            emit('error', {'message': 'Game not in question phase or room not found.'}, room=request.sid)
            return

        player_in_room = next((p for p in room["players"] if p["id"] == player_id), None)
        if not player_in_room or player_in_room["socket_id"] != request.sid:
            emit('error', {'message': 'Unauthorized answer submission.'}, room=request.sid)
            return

        room["answers"][player_id] = answer
        player_name = player_in_room["name"]
        emit('lobby_event', {'message': f"{player_name} has submitted their answer."}, room=room_id) # Notify others

        if len(room["answers"]) == len(room["players"]):
            room["state"] = "voting"
            # Emit all answers for clients to display
            all_answers = [
                {"name": p["name"], "answer": room["answers"].get(p["id"], "")}
                for p in room["players"]
            ]
            emit('game_state_change', {'state': 'voting', 'message': 'All answers submitted! Time to vote.', 'answers': all_answers}, room=room_id)
            print(f"Room {room_id}: All answers received, transitioning to voting.")
        else:
            emit('message', {'message': 'Answer submitted. Waiting for others...'}, room=request.sid)

@socketio.on('submit_vote')
def on_submit_vote(data):
    room_id = data.get("room_id")
    # FIX THIS LINE:
    player_id = data.get("player_id") # Removed the extra 'data = '
    vote_for = data.get("vote_for")    # This will now correctly access the original 'data' dictionary

    with lock:
        room = rooms.get(room_id)
        if not room or room["state"] != "voting":
            emit('error', {'message': 'Game not in voting phase or room not found.'}, room=request.sid)
            return

        player_in_room = next((p for p in room["players"] if p["id"] == player_id), None)
        if not player_in_room or player_in_room["socket_id"] != request.sid:
            emit('error', {'message': 'Unauthorized vote submission.'}, room=request.sid)
            return

        # Validate vote_for: Ensure the voted name exists in the current players
        voted_player = next((p for p in room["players"] if p["name"].lower() == vote_for.lower()), None)
        if not voted_player:
            emit('error', {'message': f"Player '{vote_for}' not found. Please vote for an existing player."}, room=request.sid)
            return

        room["votes"][player_id] = voted_player["id"] # Store ID, not name, for consistency
        player_name = player_in_room["name"]
        emit('lobby_event', {'message': f"{player_name} has cast their vote."}, room=room_id)

        if len(room["votes"]) == len(room["players"]):
            room["state"] = "results"
            
            # Calculate results
            vote_counts = {}
            for voter_pid, voted_pid in room["votes"].items():
                voted_player_name = next((p["name"] for p in room["players"] if p["id"] == voted_pid), "Unknown")
                vote_counts[voted_player_name] = vote_counts.get(voted_player_name, 0) + 1

            max_votes = 0
            if vote_counts: # Avoid error if no votes (shouldn't happen with all players voting)
                max_votes = max(vote_counts.values())
            
            # Get candidates with max votes
            candidates_voted_names = [name for name, count in vote_counts.items() if count == max_votes]
            chosen_name = candidates_voted_names[0] if candidates_voted_names else "No one" # Or handle ties

            # Find the ID of the chosen player
            chosen_id = next((p["id"] for p in room["players"] if p["name"] == chosen_name), None)

            imposter_name = next((p["name"] for p in room["players"] if room["roles"][p["id"]] == "imposter"), "Unknown Imposter")
            
            you_got_it = False
            if chosen_id and room["imposter_id"] == chosen_id:
                you_got_it = True

            results_data = {
                "votes": {next((p["name"] for p in room["players"] if p["id"] == voter_id), "Unknown"):
                          next((p["name"] for p in room["players"] if p["id"] == voted_for_id), "Unknown")
                          for voter_id, voted_for_id in room["votes"].items()},
                "imposter": imposter_name,
                "you_got_it": you_got_it,
                "chosen_by_vote": chosen_name
            }

            emit('game_state_change', {'state': 'results', 'message': 'Voting complete! Revealing results.', 'results': results_data}, room=room_id)
            print(f"Room {room_id}: All votes received, transitioning to results.")
        else:
            emit('message', {'message': 'Vote submitted. Waiting for others...'}, room=request.sid)


# --- Basic HTTP Endpoints (for initial testing, though most interactions are WS) ---
# Keeping these for the current structure, but lobby interactions will shift to WS
@app.route("/<room_id>/state", methods=["GET"])
def get_state(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    return jsonify({"state": room["state"]})

@app.route("/<room_id>/answers", methods=["GET"])
def get_answers_http(room_id): # This can eventually be removed if answers are part of WS state change
    room = rooms.get(room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    return jsonify({
        "answers": [
            {"name": p["name"], "answer": room["answers"].get(p["id"], "")}
            for p in room["players"]
        ]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)