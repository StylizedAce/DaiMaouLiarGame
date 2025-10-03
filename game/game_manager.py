"""
Core game logic and state management for the Dai Maou Liar Game.
"""

import time
import random
from threading import Lock

from utils.helpers import get_question_pair


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

            # 🔧 CRITICAL: Only show active players in state
            active_players = [p for p in room["players"] if not p.get("disconnected")]
            
            state = {
                "roomId": room_id,
                "phase": room["phase"],
                "players": active_players,  # ✅ Only active
                "hostId": room["host_id"],
                "lobbyEvents": room["lobby_events"],
                "settings": room.get("settings", {}),
                "currentRound": room.get("current_round", 1),
                "totalRounds": room.get("total_rounds", 5),
                "language": room.get("language", "en")
            }

            if room["phase"] == "question":
                state["questionPhaseStartTimestamp"] = room.get("questionPhaseStartTimestamp")
                state["questionPhaseEndTimestamp"] = room.get("questionPhaseEndTimestamp")

                # 🔧 FIX: Only count submissions from ACTIVE players
                active_player_ids = {p["id"] for p in active_players}
                active_answers = {pid: ans for pid, ans in room.get("answers", {}).items() 
                                if pid in active_player_ids}
                
                state["submittedCount"] = len(active_answers)
                
                # Build answers list (only active players)
                answers_list = []
                for player_id, answer in active_answers.items():
                    player = self.get_player_info_by_id(room["players"], player_id)
                    if player and not player.get("disconnected"):
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
                state["votingPhaseEndTimestamp"] = room.get("votingPhaseEndTimestamp")

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
                state["voteSelectionEndTimestamp"] = room.get("voteSelectionEndTimestamp")

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
            room['voteSelectionEndTimestamp'] = int(time.time() * 1000) + 30000  # 30 seconds
            room["lobby_events"].append("Time to vote for the imposter!")
            room["liarVotes"] = {}
            room['ready_to_vote'] = []  # ✅ CLEAR the ready list for vote_selection phase
            
            self.db_manager.update_room(room_id, room)

        self.schedule_phase_transition(room_id, 'vote_selection', 30, 'results')
        self.emit_state_update(room_id)
    
    def handle_round_transition(self, room_id):
        """Handle the transition between rounds or to final results."""
        from utils.helpers import get_question_pair, get_active_players
        
        with self.lock:
            room = self.db_manager.get_room(room_id)
            if not room:
                return
            
            if room.get('phase') == 'question':
                print(f"⚠️ Round transition already processed, ignoring duplicate call")
                return
            
            if room.get('phase') != 'vote_selection':
                print(f"⚠️ Invalid phase for round transition: {room.get('phase')}")
                return
            
            current_round = room.get('current_round', 1)
            total_rounds = room.get('total_rounds', 5)
            
            print(f"🔄 ROUND TRANSITION - current_round: {current_round}, total_rounds: {total_rounds}")
            print(f"ROUND {current_round} COMPLETE!")

            # Calculate scores
            round_scores = self.calculate_round_scores(room)
            
            # Initialize score tracking if not exists
            if "player_scores" not in room:
                room["player_scores"] = {p["id"]: 0 for p in room["players"]}
            
            # Add round scores to total scores
            for player_id, points in round_scores.items():
                if player_id in room["player_scores"]:
                    room["player_scores"][player_id] += points
                else:
                    room["player_scores"][player_id] = points
            
            print(f"   Round {current_round} scores: {round_scores}")
            print(f"   Total scores: {room['player_scores']}")

            if current_round >= total_rounds:
                # Game is over
                print("RESULTS PAGE TIME")
                room['phase'] = 'results'
                room['results'] = {
                    'finalRound': current_round,
                    'gameComplete': True,
                    'playerScores': room["player_scores"]  # ✅ ADD THIS
                }
            else:
                # Start next round
                next_round = current_round + 1
                room['current_round'] = next_round
                print(f"ROUND {next_round}")
                
                # 🆕 Use ACTIVE players only (exclude disconnected)
                active_players = get_active_players(room["players"])
                
                print(f"   Active players for round {next_round}: {[p['name'] for p in active_players]}")
                
                # Check if enough players remain
                if len(active_players) < 2:
                    print("   Not enough active players, ending game")
                    room['phase'] = 'results'
                    room['results'] = {
                        'finalRound': current_round,
                        'gameComplete': True,
                        'reason': 'Not enough players'
                    }
                    self.db_manager.update_room(room_id, room)
                    self.emit_state_update(room_id)
                    return
                
                room_language = room.get("language", "en")
                q_pair = get_question_pair(used_indexes=room.get("used_question_indexes", []), language=room_language)
                room["main_question"] = q_pair[0]

                if "used_question_indexes" not in room:
                    room["used_question_indexes"] = []
                room["used_question_indexes"].append(q_pair[2])


                # Determine impostor count based on game mode
                game_mode = room.get("settings", {}).get("gameMode", "normal")
                if game_mode == "mayhem":
                    impostor_count = self.get_mayhem_impostor_count(len(active_players))
                else:
                    impostor_count = 1

                # 🆕 Select impostors from ACTIVE players only
                impostors = random.sample(active_players, impostor_count) if impostor_count > 0 else []
                impostor_ids = [imp["id"] for imp in impostors]

                print(f"   Selected impostors: {[imp['name'] for imp in impostors]}")

                # Store impostor info
                room["impostor_ids"] = impostor_ids
                room["imposter_id"] = impostor_ids[0] if impostor_ids else None

                # 🆕 Assign roles and questions to ALL players (including disconnected)
                # Disconnected players keep their role/question if they rejoin
                for p in room["players"]:  # Iterate all players
                    is_imposter = p["id"] in impostor_ids
                    room["roles"][p["id"]] = "imposter" if is_imposter else "normal"
                    room["questions"][p["id"]] = q_pair[1] if is_imposter else q_pair[0]
                    
                    status = "DISCONNECTED" if p.get("disconnected") else "active"
                    print(f"   {p['name']} ({status}): {room['roles'][p['id']]} - Q: {room['questions'][p['id']][:50]}...")

                # Clear previous round data
                room["answers"], room["votes"] = {}, {}
                room["liarVotes"] = {}
                room["ready_to_vote"] = []
                room["phase"] = "question"
                room["questionPhaseStartTimestamp"] = int(time.time() * 1000) - 2000 
                answer_time_seconds = room.get("settings", {}).get("answerTime", 60)
                room["questionPhaseEndTimestamp"] = int(time.time() * 1000) + (answer_time_seconds * 1000)
                room["lobby_events"].append(f"Round {next_round} has started!")
                
        # Update room in database
        self.db_manager.update_room(room_id, room)

        if room.get('phase') == 'question':
            answer_time_seconds = room.get("settings", {}).get("answerTime", 60)
            self.schedule_phase_transition(room_id, 'question', answer_time_seconds, 'voting')

        self.emit_state_update(room_id)

    def calculate_round_scores(self, room):
        """Calculate scores for the round based on voting results."""
        game_mode = room.get("settings", {}).get("gameMode", "normal")
        impostor_ids = room.get("impostor_ids", [])
        liar_votes = room.get("liarVotes", {})
        players = room["players"]

        # Safety check
        if not players:
            print("⚠️ No players in room, returning empty scores")
            return {}
        
        from utils.helpers import get_active_players
        active_players = get_active_players(players)
        active_player_ids = [p["id"] for p in active_players]
        
        # FIX: Initialize scores for ALL players (including disconnected)
        scores = {p["id"]: 0 for p in players}  # Changed from active_players to players
        
        # Special case: Zero impostors
        if len(impostor_ids) == 0:
            voters = set()
            for target_id, voter_list in liar_votes.items():
                voters.update(voter_list)
            
            for player_id in active_player_ids:
                if player_id not in voters:
                    scores[player_id] += 2
                else:
                    wrong_votes = sum(1 for target_id, voters_list in liar_votes.items() 
                                    if player_id in voters_list and target_id != player_id)
                    scores[player_id] -= wrong_votes
            
            return scores
        
        # Normal case: Calculate votes per impostor
        total_players = len(active_player_ids)
        
        for impostor_id in impostor_ids:
            # FIX: Only calculate impostor scores if they're still in the game
            if impostor_id not in scores:
                continue  # Skip disconnected/removed impostors
                
            valid_votes = [v for v in liar_votes.get(impostor_id, []) if v != impostor_id]
            votes_received = len(valid_votes)
            vote_percentage = (votes_received / total_players * 100) if total_players > 0 else 0
            
            if votes_received == 0:
                scores[impostor_id] += 2
            elif vote_percentage <= 50:
                scores[impostor_id] += 1
        
        # Award points to voters (only active players can vote)
        if game_mode == "mayhem":
            for player_id in active_player_ids:
                if player_id in impostor_ids:
                    continue
                
                correct_votes = 0
                wrong_votes = 0
                
                for target_id, voter_list in liar_votes.items():
                    if player_id in voter_list and target_id != player_id:
                        if target_id in impostor_ids:
                            correct_votes += 1
                        else:
                            wrong_votes += 1
                
                scores[player_id] += correct_votes - wrong_votes
        else:
            # Normal mode
            for player_id in active_player_ids:
                if player_id in impostor_ids:
                    continue
                
                voted_correctly = False
                for impostor_id in impostor_ids:
                    if player_id in liar_votes.get(impostor_id, []) and player_id != impostor_id:
                        voted_correctly = True
                        break
                
                if voted_correctly:
                    scores[player_id] += 1
        
        return scores

    def get_player_name(self, players, player_id):
        """Helper to get player name by ID."""
        player = next((p for p in players if p["id"] == player_id), None)
        return player["name"] if player else "Unknown"
    
    def schedule_phase_transition(self, room_id, phase_name, duration_seconds, next_phase):
        """Schedule automatic phase transition after duration."""
        import threading
        
        def transition_callback():
            time.sleep(duration_seconds)
            
            with self.lock:
                room = self.db_manager.get_room(room_id)
                if not room or room['phase'] != phase_name:
                    return  # Room gone or phase already changed
                
                print(f"⏱️ SERVER: {phase_name} timer expired, transitioning to {next_phase}")
                
                if next_phase == 'voting':
                    room["phase"] = "voting"
                    room["votingPhaseStartTimestamp"] = int(time.time() * 1000)
                    discuss_time = room.get("settings", {}).get("discussTime", 180)
                    room["votingPhaseEndTimestamp"] = int(time.time() * 1000) + (discuss_time * 1000)
                    room["lobby_events"].append("Time's up! Moving to voting.")
                    room['ready_to_vote'] = []
                    self.db_manager.update_room(room_id, room)
                    self.emit_state_update(room_id, room)
                    # Schedule next transition
                    self.schedule_phase_transition(room_id, 'voting', discuss_time, 'vote_selection')
                    
                elif next_phase == 'vote_selection':
                    self.transition_to_vote_selection(room_id)
                    
                elif next_phase == 'results':
                    self.handle_round_transition(room_id)
        
        threading.Thread(target=transition_callback, daemon=True).start()
        print(f"⏱️ SERVER: Scheduled {phase_name} -> {next_phase} in {duration_seconds}s")