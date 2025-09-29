"""
Core game logic and state management for the Dai Maou Liar Game.
"""

import time
import random
from threading import Lock


class GameManager:
    """Manages core game logic and state transitions."""
    
    def __init__(self, db_manager, socketio):
        self.db_manager = db_manager
        self.socketio = socketio
        self.lock = Lock()
    
    def get_player_info_by_id(self, players_list, player_id):
        """Helper function to find a player dictionary in a list by their ID."""
        return next((p for p in players_list if p["id"] == player_id), None)
    
    def get_room_state(self, room_id, room=None):
        """
        This function given a room ID can fetch the roomdata from the currently running rooms.
        It is used in every state emission.
        Accepts an optional 'room' dictionary to avoid redundant database reads.
        """
        with self.lock:
            if room is None:
                room = self.db_manager.get_room(room_id)
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
                "settings": room.get("settings", {}),
                "currentRound": room.get("current_round", 1),
                "totalRounds": room.get("total_rounds", 5)
            }

            if room["phase"] == "question":
                state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
                state["submittedCount"] = len(room.get("answers", {}))
                
                # Build the answers list
                answers_list = []
                for player_id, answer in room.get("answers", {}).items():
                    player = self.get_player_info_by_id(room["players"], player_id)
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
                    player = self.get_player_info_by_id(room["players"], player_id)
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
                    player = self.get_player_info_by_id(room["players"], player_id)
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
    
    def emit_state_update(self, room_id, room=None):
        """Emits the full game state to all clients in a room."""
        room_state = self.get_room_state(room_id, room)
        if room_state:
            print(f"DEBUG: Emitting state update for room {room_id}. Phase: {room_state.get('phase')}")
            
            # Emit general state to the room
            self.socketio.emit('update_game_state', room_state, room=room_id)

            # Emit personal info (role, question) to each player individually
            if room is None:  # Fetch if not already provided
                room = self.db_manager.get_room(room_id)
            if room and room["phase"] == "question":
                for p in room["players"]:
                    personal_info = {
                        "role": room["roles"].get(p["id"]),
                        "question": room["questions"].get(p["id"])
                    }
                    target_sid = p.get("socket_id")
                    if target_sid:
                        self.socketio.emit('personal_game_info', personal_info, room=target_sid)
        else:
            print(f"DEBUG: No room state found for room {room_id}")
    
    def get_mayhem_impostor_count(self, player_count):
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
    
    def transition_to_vote_selection(self, room_id):
        """Transition a room from voting phase to vote selection phase."""
        with self.lock:
            room = self.db_manager.get_room(room_id)
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
            self.db_manager.update_room(room_id, room)

        # Emit outside the lock to avoid deadlock
        self.emit_state_update(room_id)
    
    def handle_round_transition(self, room_id):
        """Handle the transition between rounds or to final results."""
        from utils.helpers import get_question_pair
        import time
        import random
        
        with self.lock:
            room = self.db_manager.get_room(room_id)
            if not room:
                return
            
            current_round = room.get('current_round', 1)
            total_rounds = room.get('total_rounds', 5)
            
            print(f"ROUND {current_round} COMPLETE!")
            
            if current_round > total_rounds:
                # Game is over, go to final results
                print("RESULTS PAGE TIME")
                room['phase'] = 'results'
                # Set some basic results data
                room['results'] = {
                    'finalRound': current_round,
                    'gameComplete': True
                }
            else:
                # Start next round
                next_round = current_round + 1
                room['current_round'] = next_round
                print(f"ROUND {next_round}")
                
                # Reset game state for new round
                players = room["players"]
                q_pair = get_question_pair(used_indexes=room.get("used_question_indexes", []))
                room["main_question"] = q_pair[0]

                # Determine impostor count based on game mode
                game_mode = room.get("settings", {}).get("gameMode", "normal")
                if game_mode == "mayhem":
                    impostor_count = self.get_mayhem_impostor_count(len(players))
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

                # Clear previous round data
                room["answers"], room["votes"] = {}, {}
                room["liarVotes"] = {}
                room["ready_to_vote"] = []
                room["phase"] = "question"
                room["questionPhaseStartTimestamp"] = int(time.time() * 1000) - 2000
                room["lobby_events"].append(f"Round {next_round} has started!")
                
            # Update room in database
            self.db_manager.update_room(room_id, room)

        self.emit_state_update(room_id)
