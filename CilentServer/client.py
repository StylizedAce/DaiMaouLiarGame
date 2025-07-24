import socketio
import threading
import time
import os
import sys

BASE = "https://daimaouliargame.onrender.com"

sio = socketio.Client()
player_id = None   # Will be set upon joining
room_id = None     # Will be set upon joining
player_name_global = None # Store player's name globally for use in handlers

# Global variable to manage the current state reported by the server
current_game_state = "unknown"

# A threading.Event to signal when the initial lobby list has been displayed
initial_lobby_displayed = threading.Event()

# --- SocketIO Event Handlers ---

@sio.event
def connect():
    print("Connected to server!")

@sio.event
def disconnect():
    print("Disconnected from server.")
    # Exit the client application cleanly after disconnect
    os._exit(0) # Force exit all threads, as main loop might be waiting for input

@sio.on('error')
def on_error(data):
    print(f"Server Error: {data.get('message', 'Unknown error')}")
    if data.get('message') == 'Game already started in this room.':
        print("Please try another room or wait for the current game to finish.")
        sio.disconnect()
        # No need for os._exit(1) here, disconnect handler will take care of it

@sio.on('joined_confirmation')
def on_joined_confirmation(data):
    global player_id, room_id
    player_id = data["player_id"]
    room_id = data["room_id"]
    # Print a confirmation, but rely on 'player_list_update' for the actual lobby view
    print(f"Successfully joined room '{room_id}' as {player_name_global}. Your ID: {player_id}")


@sio.on('player_list_update')
def on_player_list_update(data):
    # Clear console for a fresh display of the lobby
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("\n--- Lobby Players ---")
    for p in data["players"]:
        ready_status = "READY" if p["ready"] else "NOT READY"
        you_tag = "(You)" if p["id"] == player_id else ""
        print(f"- {p['name']} {you_tag} [{ready_status}]")
    
    print(f"\n--- Game State: {current_game_state.upper()} ---") # Show current state
    
    # Signal that the initial lobby view has been rendered
    initial_lobby_displayed.set()


@sio.on('lobby_event')
def on_lobby_event(data):
    # This will print additional messages like "Ace has joined"
    # This prints *after* the player list update in a separate line
    print(f"*** LOBBY UPDATE: {data['message']} ***")

@sio.on('game_countdown')
def on_game_countdown(data):
    print(f"Game starting in {data['seconds']} seconds...")

@sio.on('game_state_change')
def on_game_state_change(data):
    global current_game_state
    current_game_state = data["state"]
    print(f"\n--- Game State: {current_game_state.upper()} ---")
    print(f"*** GAME UPDATE: {data['message']} ***")

    if current_game_state == "question":
        # The game has officially started. Role and question received via 'your_game_info'
        pass # The specific info is handled by another event

    elif current_game_state == "voting":
        # When entering voting, the server sends all answers with the state change
        print("\n--- Answers ---")
        for a in data.get('answers', []):
            print(f"{a['name']}: {a['answer']}")
        # Now prompt for vote in the main thread

    elif current_game_state == "results":
        # When entering results, the server sends all results with the state change
        results = data.get('results', {})
        print("\n--- Voting Results ---")
        for name_voter, voted_for_name in results["votes"].items():
            print(f"{name_voter} voted for {voted_for_name}")
        print(f"\nThe imposter was: {results['imposter']}")
        print(f"Voted imposter: {results['chosen_by_vote']}")
        print("🎉 YOU GOT IT RIGHT!" if results["you_got_it"] else "❌ WRONG GUESS!")
        # Game finished, disconnect
        sio.disconnect()


@sio.on('your_game_info')
def on_your_game_info(data):
    # This event is sent only to the specific player getting their role/question
    print(f"\nYour role is: {data['role'].upper()}")
    print(f"QUESTION: {data['question']}")
    # Now prompt for answer in main thread


@sio.on('cancelled_confirmation')
def on_cancelled_confirmation(data):
    print(data['message'])
    sio.disconnect() # Disconnect after confirming cancellation


# --- Main Client Logic ---

player_name_global = input("Enter your name: ").strip()
target_room_id = input("Enter room ID: ").strip()

# Connect to the server
sio.connect(BASE)

# Wait for 'connect' event to ensure socket is ready
# sio.wait() # This can block, better to rely on events

# Emit join_room event to the server
sio.emit('join_room', {'room_id': target_room_id, 'name': player_name_global})

# Wait for player_id to be set by 'joined_confirmation' event AND for the initial lobby to be drawn
# This loop prevents the "Ready up?" prompt from appearing before the lobby is shown
while player_id is None or not initial_lobby_displayed.is_set():
    sio.sleep(0.1) # Use sio.sleep for compatibility with SocketIO's internal event loop

# Now that lobby is displayed and player_id is set, proceed with readying up
# Loop for readying up. This will be an interactive loop
while current_game_state == "waiting":
    ready_input = input("Ready up? [y/n]: ").strip().lower()
    if ready_input == "n":
        sio.emit('cancel_ready', {'room_id': room_id, 'player_id': player_id})
        # The 'cancelled_confirmation' event handler will disconnect, and os._exit(0) will clean up
        sio.wait() # Wait for disconnect before exiting
    elif ready_input == "y":
        sio.emit('ready_up', {'room_id': room_id, 'player_id': player_id})
        # Break from this loop and wait for game state changes via events
        break
    else:
        print("Invalid input. Please type 'y' or 'n'.")


# Game flow after readying up - these blocks wait for server-pushed state changes
while True:
    if current_game_state == "question":
        answer = input("Your answer: ")
        sio.emit('submit_answer', {'room_id': room_id, 'player_id': player_id, 'answer': answer})
        print("Answer submitted. Waiting for others...")
        current_game_state = "answered" # Client-side temporary state to prevent re-prompting
    elif current_game_state == "voting":
        vote = input("Who do you think is the imposter? Type their name: ").strip()
        sio.emit('submit_vote', {'room_id': room_id, 'player_id': player_id, 'vote_for': vote})
        print("Vote submitted. Waiting for results...")
        current_game_state = "voted" # Client-side temporary state
    elif current_game_state == "results" or current_game_state == "unknown":
        # Game finished or not in an active phase for user input.
        # The 'game_state_change' handler for 'results' will disconnect.
        pass
    
    # Keep the client alive to receive server events
    sio.sleep(0.1) # Small sleep to prevent busy-waiting, allows event loop to run