# main.py
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from threading import Lock
import uuid
import random
import os
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

lock = Lock()
rooms = {}  # In-memory storage for game rooms

QUESTION_PAIRS = [
    ("What's your favorite type of food?", "What was the last thing you ate?"),
    ("What's your dream vacation?", "What's your next planned trip?"),
    ("What's your biggest fear?", "What's something you dislike?"),
    ("What's your favorite movie?", "What's the last movie you watched?"),
    ("What’s your favorite animal?", "What pet do you have?")
]

def get_room_state(room_id):
    """Constructs the complete state payload for a room."""
    with lock:
        room = rooms.get(room_id)
        if not room:
            return None

        # Base state visible to everyone
        state = {
            "roomId": room_id,
            "phase": room["phase"],
            "players": room["players"],
            "hostId": room["host_id"],
            "lobbyEvents": room["lobby_events"],
            "settings": room.get("settings", {})
        }

        if room["phase"] == "question":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["answers"] = room.get("answers", {})

        # Add phase-specific data
        if room["phase"] == "voting":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["votingPhaseStartTimestamp"] = room.get("votingPhaseStartTimestamp")  # NEW LINE
            state["answers"] = [
                {"playerId": p["id"], "name": p["name"], "answer": room["answers"].get(p["id"], "No answer")}
                for p in room["players"]
            ]
            
            state["mainQuestion"] = room["main_question"] # Add the main question here
        elif room["phase"] == "results":
            state["results"] = room["results"]
            # Also reveal the imposter's question
            state["questions"] = room["questions"]


        return state

def emit_state_update(room_id):
    """Emits the full game state to all clients in a room."""
    room_state = get_room_state(room_id)
    if room_state:
        # Emit general state to the room
        socketio.emit('update_game_state', room_state, room=room_id)

        # Emit personal info (role, question) to each player individually
        room = rooms.get(room_id)
        if room and room["phase"] == "question":
            for p in room["players"]:
                personal_info = {
                    "role": room["roles"].get(p["id"]),
                    "question": room["questions"].get(p["id"])
                }
                socketio.emit('personal_game_info', personal_info, room=p["socket_id"])

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect(reason=None):
    print(f"Client disconnected: {request.sid} (reason: {reason})")
    with lock:
        room_to_update = None
        for room_id, room in list(rooms.items()):
            player_to_remove = next((p for p in room["players"] if p.get("socket_id") == request.sid), None)

            if player_to_remove:
                player_id = player_to_remove["id"]
                player_name = player_to_remove["name"]
                
                room["players"] = [p for p in room["players"] if p["id"] != player_id]
                room["lobby_events"].append(f"{player_name} has left the game.")
                
                if not room["players"]:
                    del rooms[room_id]
                    print(f"Room {room_id} is empty and has been removed.")
                    return
                
                # If the host disconnected, assign a new host
                if player_id == room["host_id"]:
                    room["host_id"] = room["players"][0]["id"]
                    new_host_name = room["players"][0]["name"]
                    room["lobby_events"].append(f"{new_host_name} is the new host.")

                # If game was in progress and now has too few players, reset it
                if len(room["players"]) < 2 and room["phase"] != "waiting":
                    room["phase"] = "waiting"
                    # Reset game-specific fields
                    room["roles"], room["questions"], room["answers"], room["votes"], room["results"] = {}, {}, {}, {}, {}
                    room["readyToVote"] = [] # NEW LINE
                    room["readyToVote"] = []
                    room["imposter_id"] = None
                    room["lobby_events"].append("Not enough players. Returning to lobby.")

                room_to_update = room_id
                break
    
    if room_to_update:
        emit_state_update(room_to_update)

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
        room = rooms.get(room_id)
        if not room:
            # Create a new room if it doesn't exist
            player_id = str(uuid.uuid4())
            rooms[room_id] = {
                "players": [{"id": player_id, "name": name, "avatar": userAvatar, "socket_id": request.sid}],
                "host_id": player_id,  # First player is the host
                "phase": "waiting",
                "imposter_id": None,
                "roles": {}, "questions": {}, "answers": {}, "votes": {}, "results": {},
                "lobby_events": [f"{name} created the room and is the host."],
                "main_question": None # Initialize main_question
            }
        else:
            # Join an existing room
            if room["phase"] != "waiting":
                emit('error_event', {'message': 'Game is already in progress.'}, room=request.sid)
                return
            if any(p["name"] == name for p in room["players"]):
                emit('error_event', {'message': 'That name is already taken.'}, room=request.sid)
                return

            player_id = str(uuid.uuid4())
            room["players"].append({"id": player_id, "name": name, "avatar": userAvatar, "socket_id": request.sid})
            room["lobby_events"].append(f"{name} has joined the game.")

        join_room(room_id)
        # Send confirmation with their new ID
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
        room = rooms.get(room_id)
        if not room:
            emit('error_event', {'message': 'Room not found.'}, room=request.sid)
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
            del rooms[room_id]
            print(f"Room {room_id} is empty and has been removed.")
            return
        
        # If the host left, assign a new host
        if player_id == room["host_id"]:
            room["host_id"] = room["players"][0]["id"]
            new_host_name = room["players"][0]["name"]
            room["lobby_events"].append(f"{new_host_name} is the new host.")
        
        # If game was in progress and now has too few players, reset it
        if len(room["players"]) < 2 and room["phase"] != "waiting":
            room["phase"] = "waiting"
            # Reset game-specific fields
            room["roles"], room["questions"], room["answers"], room["votes"], room["results"] = {}, {}, {}, {}, {}
            room["readyToVote"] = [] # NEW LINE
            room["imposter_id"] = None
            room["lobby_events"].append("Not enough players. Returning to lobby.")
    
    # Update all remaining players in the room
    emit_state_update(room_id)

@socketio.on('start_game')
def on_start_game(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    settings = data.get("settings")

    with lock:
        room = rooms.get(room_id)
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
        imposter = random.choice(players)
        q_pair = random.choice(QUESTION_PAIRS)
        
        room["imposter_id"] = imposter["id"]
        for p in players:
            is_imposter = p["id"] == room["imposter_id"]
            room["roles"][p["id"]] = "imposter" if is_imposter else "normal"
            room["questions"][p["id"]] = q_pair[1] if is_imposter else q_pair[0]
        room["main_question"] = q_pair[0] # Store the main question

        room["answers"], room["votes"], room["results"] = {}, {}, {}
        room["phase"] = "question"
        room["questionPhaseStartTimestamp"] = int(time.time() * 1000) - 2000 # subtract 1.5 seconds
        room["lobby_events"].append("The game has started!")

    emit_state_update(room_id)


@socketio.on('submit_answer')
def on_submit_answer(data):
    room_id = data.get("roomId")
    player_id = data.get("playerId")
    answer = data.get("answer")

    with lock:
        room = rooms.get(room_id)
        if not room or room["phase"] != "question": return
        if player_id in room["answers"]: return # Prevent re-submission

        room["answers"][player_id] = answer
        player_name = next((p["name"] for p in room["players"] if p["id"] == player_id), "Someone")
        room["lobby_events"].append(f"{player_name} submitted their answer.")

        emit_state_update(room_id)
        
        
        # Check if all players have answered
        if len(room["answers"]) == len(room["players"]):
            room["phase"] = "voting"
            room["votingPhaseStartTimestamp"] = int(time.time() * 1000) - 2000  # NEW LINE
            room["lobby_events"].append("All answers are in! Time to vote.")

        emit_state_update(room_id)


@socketio.on('submit_vote')
def on_submit_vote(data):
    room_id = data.get("roomId")
    voter_id = data.get("playerId")
    voted_for_id = data.get("votedForId")

    with lock:
        room = rooms.get(room_id)
        if not room or room["phase"] != "voting": return
        if voter_id in room["votes"]: return # Prevent re-submission

        room["votes"][voter_id] = voted_for_id
        voter_name = next((p["name"] for p in room["players"] if p["id"] == voter_id), "Someone")
        room["lobby_events"].append(f"{voter_name} has cast their vote.")
        
        # Check if all players have voted
        if len(room["votes"]) == len(room["players"]):
            room["phase"] = "results"
            room["lobby_events"].append("The votes are in! Here are the results.")

            # --- Calculate Results ---
            vote_counts = {p["id"]: 0 for p in room["players"]}
            for voted_id in room["votes"].values():
                if voted_id in vote_counts:
                    vote_counts[voted_id] += 1
            
            imposter_id = room["imposter_id"]
            imposter_name = next((p["name"] for p in room["players"] if p["id"] == imposter_id), "N/A")

            # Determine who was voted out
            max_votes = -1
            voted_out_id = None
            if vote_counts:
                max_votes = max(vote_counts.values())
                # Note: This simple logic picks the first player in case of a tie.
                voted_out_id = next((pid for pid, count in vote_counts.items() if count == max_votes), None)
            
            voted_out_name = next((p["name"] for p in room["players"] if p["id"] == voted_out_id), "No one")

            # Determine the winner
            imposter_found = voted_out_id == imposter_id
            winner_message = f"You got it! {imposter_name} was the imposter." if imposter_found else f"The imposter got away! It was {imposter_name}."

            room["results"] = {
                "imposterId": imposter_id,
                "imposterName": imposter_name,
                "votedOutName": voted_out_name,
                "imposterFound": imposter_found,
                "winnerMessage": winner_message,
                "votes": [
                    {
                        "voterName": next((p["name"] for p in room["players"] if p["id"] == vid), "N/A"),
                        "votedForName": next((p["name"] for p in room["players"] if p["id"] == vfid), "N/A")
                    } for vid, vfid in room["votes"].items()
                ]
            }

    emit_state_update(room_id)

@app.route('/', methods=['GET'])
def index():
    return "Welcome to the Dai Maou Liar Game!"

if __name__ == "__main__":
    DEVELOPMENT = False
    if not DEVELOPMENT:
        port = int(os.environ.get("PORT", 5000))
        socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

    else:
        socketio.run(app, port=5000, debug=True, allow_unsafe_werkzeug=True) # debug=True for development