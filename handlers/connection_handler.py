"""
Socket event handlers for connection management operations.
"""

import time
from flask import request
from flask_socketio import emit, join_room
from utils.helpers import get_active_players


class ConnectionHandler:
    """Handles connection-related socket events."""
    
    def __init__(self, db_manager, game_manager, socketio):
        self.db_manager = db_manager
        self.game_manager = game_manager
        self.socketio = socketio
    
    def handle_connect(self):
        """Handle client connection."""
        print(f"Client connected: {request.sid}")
    
    def handle_disconnect(self, reason=None):
        """Handle client disconnection."""
        print(f"Client disconnected: {request.sid} (reason: {reason})")
        
        with self.game_manager.lock:
            room_to_update = None
            for room_id in self.db_manager.get_all_room_ids():
                room = self.db_manager.get_room(room_id)
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
                    active_players = get_active_players(room["players"])

                    # Check if only 1 active player remains AND game has started
                    if len(active_players) == 1 and room["phase"] != "waiting":
                        # Kick the last player with a message
                        last_player = active_players[0]
                        last_player_sid = last_player.get("socket_id")
                        if last_player_sid:
                            self.socketio.emit('solo_player_kick', {
                                'message': 'You were the only player left in the game.'
                            }, room=last_player_sid)
                        
                        # Delete the room
                        self.db_manager.delete_room(room_id)
                        print(f"Room {room_id} had only 1 active player and was deleted.")
                        return
                    
                    # Check if no active players
                    if not active_players:
                        self.db_manager.delete_room(room_id)
                        print(f"Room {room_id} has no active players and has been removed.")
                        return

                    # If the disconnected player was the host, assign a new host from active players
                    if player_id == room["host_id"] and active_players:
                        room["host_id"] = active_players[0]["id"]
                        new_host_name = active_players[0]["name"]
                        room["lobby_events"].append(f"{new_host_name} is the new host.")

                    # Update the room in database
                    self.db_manager.update_room(room_id, room)
                    room_to_update = room_id
                    break
        
        if room_to_update:
            self.game_manager.emit_state_update(room_to_update)
    
    def handle_rejoin_game(self, data):
        """Handle player rejoin request."""
        room_id = data.get("roomId")
        player_id = data.get("playerId")
        timestamp = data.get("timeStamp")

        print(f"🔄 Rejoin request: SID={request.sid}, Room={room_id}, Player={player_id}")

        if not room_id or not player_id:
            emit('error', {"message": "Room ID and Player ID are required."})
            return

        try:
            with self.game_manager.lock:
                room = self.db_manager.get_room(room_id)
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
                self.db_manager.update_room(room_id, room)

            # Emissions must happen after the room data is fully updated
            room_state = self.game_manager.get_room_state(room_id)
            
            # We need to manually emit to the reconnected player first to prevent race conditions.
            player = self.game_manager.get_player_info_by_id(room_state["players"], player_id)
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
            self.game_manager.emit_state_update(room_id)
            print(f"✅ Rejoin process completed for player {player_id}")
            
        except Exception as e:
            print(f"❌ Error in rejoin_game: {e}")
            import traceback
            traceback.print_exc()
            emit('error', {"message": "An error occurred during rejoin."})
