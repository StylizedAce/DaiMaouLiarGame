"""
Socket event handlers for game-related operations.
"""

import time
import random
import uuid
import threading
from flask import request
from flask_socketio import emit
from utils.helpers import get_question_pair


class GameHandler:
    """Handles game-related socket events."""
    
    def __init__(self, db_manager, game_manager, socketio):
        self.db_manager = db_manager
        self.game_manager = game_manager
        self.socketio = socketio
    
    def handle_start_game(self, data):
        """Handle game start request."""
        room_id = data.get("roomId")
        player_id = data.get("playerId")
        settings = data.get("settings")

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
            if not room: 
                return
            
            room["settings"] = settings 

            # Validation: Only the host can start, and only with enough players
            if room["host_id"] != player_id:
                emit('error_event', {'message': 'Only the host can start the game.'}, room=request.sid)
                return
            if len(room["players"]) < 2:  # Min 2 players
                emit('error_event', {'message': 'You need at least 2 players to start.'}, room=request.sid)
                return
            
            # --- Start Game Logic ---
            players = room["players"]
            q_pair = get_question_pair(used_indexes=room.get("used_question_indexes", []))
            room["main_question"] = q_pair[0]

            # Initialize round data
            total_rounds = settings.get("totalRounds", 5) if settings else 5
            room['current_round'] = 1
            room['total_rounds'] = total_rounds

            # Determine impostor count based on game mode
            game_mode = room.get("settings", {}).get("gameMode", "normal")
            if game_mode == "mayhem":
                impostor_count = self.game_manager.get_mayhem_impostor_count(len(players))
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
            
            # Emit game_starting event to trigger animation for all players FIRST
            self.socketio.emit('game_starting', room=room_id)
            
            # Immediately proceed with normal game transition
            room["phase"] = "question"
            room["questionPhaseStartTimestamp"] = int(time.time() * 1000) - 2000
            room["lobby_events"].append("The game has started!")
            
            # Update room in database
            self.db_manager.update_room(room_id, room)

        self.game_manager.emit_state_update(room_id, room)
    
    def handle_submit_answer(self, data):
        """Handle answer submission."""
        room_id = data.get("roomId")
        player_id = data.get("playerId")
        answer = data.get("answer")

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
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
            self.db_manager.update_room(room_id, room)
        
        # We pass the updated 'room' object directly to prevent a race condition.
        self.game_manager.emit_state_update(room_id, room)
    
    def handle_remove_answer(self, data):
        """Handle answer removal (editing)."""
        room_id = data.get("roomId")
        player_id = data.get("playerId")

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
            if not room or room["phase"] != "question": 
                return

            # Remove the player's answer
            if player_id in room["answers"]:
                del room["answers"][player_id]
                
                player_name = next((p["name"] for p in room["players"] if p["id"] == player_id), "Someone")
                room["lobby_events"].append(f"{player_name} is editing their answer.")
                
                # Update room in database
                self.db_manager.update_room(room_id, room)

        self.game_manager.emit_state_update(room_id)
    
    def handle_submit_vote(self, data):
        """Handle vote submission."""
        room_id = data.get("roomId")
        voter_id = data.get("playerId")
        voted_for_id = data.get("votedForId")

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
            if not room or room["phase"] != "voting": 
                return
            if voter_id in room["votes"]: 
                return  # Prevent re-submission

            room["votes"][voter_id] = voted_for_id
            voter_name = next((p["name"] for p in room["players"] if p["id"] == voter_id), "Someone")
            room["lobby_events"].append(f"{voter_name} has cast their vote.")
            
            # Update room in database
            self.db_manager.update_room(room_id, room)
        
        self.game_manager.emit_state_update(room_id, room)
    
    def handle_ready_to_vote(self, data):
        """Handle ready to vote signal."""
        room_id = data.get('roomId')
        player_id = data.get('playerId')

        if not room_id or not player_id:
            return

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
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
                self.db_manager.update_room(room_id, room)

        # Emit state update first
        self.game_manager.emit_state_update(room_id)
        
        # Then check if we need to transition
        room = self.db_manager.get_room(room_id)
        if room and len(room.get('ready_to_vote', [])) == len(room['players']):
            self.game_manager.transition_to_vote_selection(room_id)
    
    def handle_liar_vote(self, data):
        """Handle liar vote submission."""
        room_id = data.get('roomId')
        voter_id = data.get('playerId')
        target_id = data.get('targetId')

        if not room_id or not voter_id or not target_id:
            return

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
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
            self.db_manager.update_room(room_id, room)

        self.game_manager.emit_state_update(room_id)
    
    def handle_voting_timer_expired(self, data):
        """Handle voting phase timer expiration."""
        room_id = data['roomId']
        print(f"🟡 Event received: voting_timer_expired for room {room_id}")

        if self.db_manager.room_exists(room_id):
            print(f"✅ Timer expired in voting phase — transitioning room {room_id}")
            with self.game_manager.lock:
                room = self.db_manager.get_room(room_id)
                if room:
                    room['phase'] = 'vote_selection'
                    room['voteSelectionStartTimestamp'] = time.time()
                    self.db_manager.update_room(room_id, room)

            self.game_manager.emit_state_update(room_id)
    
    def handle_update_settings(self, data):
        """Handle game settings update."""
        room_id = data.get("roomId")
        new_settings = data.get("settings")

        with self.game_manager.lock:
            room = self.db_manager.get_room(room_id)
            if not room:
                return

            room["settings"] = new_settings
            room["lobby_events"].append("Host updated the game settings.")
            
            # Update room in database
            self.db_manager.update_room(room_id, room)

        self.game_manager.emit_state_update(room_id, room)

    def handle_round_transition(self, data):
        """Handle round transition request."""
        room_id = data.get("roomId")
        player_id = data.get("playerId")
        
        if not room_id or not player_id:
            return
        
        print(f"Round transition request from player {player_id} in room {room_id}")
        self.game_manager.handle_round_transition(room_id)
