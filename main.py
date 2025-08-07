# main.py
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from threading import Lock
import uuid
import random
import os
import time
import pandas as pd

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

lock = Lock()
rooms = {}  # In-memory storage for game rooms

""" QUESTION_PAIRS = [
    ("What's your favorite type of food?", "What was the last thing you ate?"),
    ("What's your dream vacation?", "What's your next planned trip?"),
    ("What's your biggest fear?", "What's something you dislike?"),
    ("What's your favorite movie?", "What's the last movie you watched?"),
    ("What’s your favorite animal?", "What pet do you have?")
] """

def get_question_pair(used_indexes=None):
    """
    Returns a single random question pair (normal, imposter) and its index.
    Avoids previously used indexes for the current room session.
    
    Args:
        used_indexes (list): List of question indexes already used in this room session
        
    Returns:
        tuple: ((normal_question, imposter_question), selected_index)
    """
    if used_indexes is None:
        used_indexes = []
    
    try:
        df = pd.read_csv('question_pairs.csv')
        if df.empty:
            raise ValueError("CSV file is empty.")
        
        # Get available indexes (excluding used ones)
        all_indexes = list(range(len(df)))
        available_indexes = [i for i in all_indexes if i not in used_indexes]
        
        if not available_indexes:
            print("WARNING: All questions have been used. Resetting question pool.")
            available_indexes = all_indexes  # Reset if all questions used
        
        # Pick random available index
        selected_index = random.choice(available_indexes)
        
        # Get the question pair
        row = df.iloc[selected_index]
        question_pair = (row['Normal_Question'], row['Imposter_Question'])
        
        print(f"DEBUG: Selected question index {selected_index}: {question_pair[0]}")
        return question_pair
        
    except Exception as e:
        print(f"DEBUG: Could not load question_pairs.csv ({e}). Using default pairs.")
        emit('error_event', {'message': 'Could not load question pairs. Please try again later.'}, room=request.sid)


def get_room_state(room_id):
    """ This function given a room ID can fetch the roomdata from the currently running rooms. It is used in every state emission"""
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
            state["submittedCount"] = len(room.get("answers", {}))
            state["answers"] = [
                {"playerId": p["id"], "name": p["name"], "answer": room["answers"].get(p["id"], "")}
                for p in room["players"] if p["id"] in room.get("answers", {})
            ]

        # Add phase-specific data
        if room["phase"] == "voting":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["votingPhaseStartTimestamp"] = room.get("votingPhaseStartTimestamp")  # NEW LINE
            state["answers"] = [
                {"playerId": p["id"], "name": p["name"], "answer": room["answers"].get(p["id"], "No answer")}
                for p in room["players"]
            ]
            
            state["mainQuestion"] = room["main_question"] # Add the main question here
            state["ready_to_vote"] = room.get("ready_to_vote", [])

        elif room["phase"] == "vote_selection":
            state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
            state["votingPhaseStartTimestamp"] = room.get("votingPhaseStartTimestamp")
            state["voteSelectionStartTimestamp"] = room.get("voteSelectionStartTimestamp")
            state["answers"] = [
                {"playerId": p["id"], "name": p["name"], "answer": room["answers"].get(p["id"], "No answer")}
                for p in room["players"]
            ]   
            state["mainQuestion"] = room["main_question"]
            state["ready_to_vote"] = room.get("ready_to_vote", [])
            state["liarVotes"] = room.get("liarVotes", {})
            state["imposterId"] = room.get("imposter_id")



        elif room["phase"] == "results":
            state["results"] = room["results"]
            # Also reveal the imposter's question
            state["questions"] = room["questions"]


        return state

def emit_state_update(room_id):
    """Emits the full game state to all clients in a room."""
    room_state = get_room_state(room_id)
    if room_state:
        print(f"DEBUG: Emitting state update for room {room_id}. Phase: {room_state.get('phase')}")
        
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
            emit('error_event', {'message': 'The room you were trying to reach doesn’t exist anymore.'}, room=request.sid)
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
        if room_id in rooms:
            emit('error_event', {'message': 'Room already exists.'}, room=request.sid)
            return

        player_id = str(uuid.uuid4())
        rooms[room_id] = {
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
        room = rooms.get(room_id)
        if not room:
            emit('error_event', {'message': 'The room you were trying to reach doesn’t exist anymore.'}, room=request.sid)
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
        q_pair = get_question_pair(used_indexes=room.get("used_question_indexes", []))
        
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
            room["votingPhaseStartTimestamp"] = int(time.time() * 1000) - 2000  # NEW LINE
            room["lobby_events"].append("All answers are in! Time to vote.")
            room['ready_to_vote'] = [] 
    
    emit_state_update(room_id)


@socketio.on('update_settings')
def on_update_settings(data):
    room_id = data.get("roomId")
    new_settings = data.get("settings")

    with lock:
        room = rooms.get(room_id)
        if not room:
            return

        room["settings"] = new_settings
        room["lobby_events"].append("Host updated the game settings.")

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


@socketio.on("kick_player")
def handle_kick_player(data):
    room_id = data.get("roomId")
    target_player_id = data.get("targetPlayerId")
    by_player_id = data.get("byPlayerId")

    print(f"KICK request: {by_player_id} is trying to kick {target_player_id} from {room_id}")

    with lock:
        room = rooms.get(room_id)
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
        room = rooms.get(room_id)
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

    # Emit state update first
    emit_state_update(room_id)
    
    # Then check if we need to transition (do this after emit to avoid race conditions)
    room = rooms.get(room_id)
    if room and len(room.get('ready_to_vote', [])) == len(room['players']):
        transition_to_vote_selection(room_id)

def transition_to_vote_selection(room_id):
    with lock:
        room = rooms.get(room_id)
        if not room:
            return
        
        # Only transition if we're currently in voting phase
        if room['phase'] != 'voting':
            return
        
        room['phase'] = 'vote_selection'
        room['voteSelectionStartTimestamp'] = int(time.time() * 1000)
        room["lobby_events"].append("Time to vote for the imposter!")

        room["liarVotes"] = {}

    # Emit outside the lock to avoid deadlock
    emit_state_update(room_id)
    
@socketio.on('voting_timer_expired')
def handle_voting_timer_expired(data):
    room_id = data['roomId']
    print(f"🟡 Event received: voting_timer_expired for room {room_id}")

    if room_id in rooms:
        print(f"✅ Timer expired in voting phase — transitioning room {room_id}")
        rooms[room_id]['phase'] = 'vote_selection'
        rooms[room_id]['voteSelectionStartTimestamp'] = time.time()

    emit_state_update(room_id)

@socketio.on('liar_vote')
def handle_liar_vote(data):
    room_id = data.get('roomId')
    voter_id = data.get('playerId')
    target_id = data.get('targetId')

    if not room_id or not voter_id or not target_id:
        return

    with lock:
        room = rooms.get(room_id)
        if not room or room['phase'] != 'vote_selection':
            return

        # Use liarVotes instead of results
        if 'liarVotes' not in room:
            room['liarVotes'] = {}

        # Remove previous vote by this player (in case of vote switch)
        for voters in room['liarVotes'].values():
            if voter_id in voters:
                voters.remove(voter_id)


        if target_id not in room['liarVotes']:
            room['liarVotes'][target_id] = []

        room['liarVotes'][target_id].append(voter_id)

        voter_name = next((p["name"] for p in room["players"] if p["id"] == voter_id), "Someone")
        target_name = next((p["name"] for p in room["players"] if p["id"] == target_id), "Unknown")
        room["lobby_events"].append(f"{voter_name} voted for {target_name}.")

    emit_state_update(room_id)

if __name__ == "__main__":
    DEVELOPMENT = True
    if not DEVELOPMENT:
        port = int(os.environ.get("PORT", 5000))
        socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

    else:
        socketio.run(app, port=5000, debug=True, allow_unsafe_werkzeug=True) # debug=True for development