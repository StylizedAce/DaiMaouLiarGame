from flask import Flask, request, jsonify
from threading import Lock, Thread
import uuid
import random
import time

app = Flask(__name__)
lock = Lock()

rooms = {}

QUESTION_PAIRS = [
    ("What's your favorite type of food?", "What was the last thing you ate?"),
    ("What's your dream vacation?", "What's your next planned trip?"),
    ("What's your biggest fear?", "What's something you dislike?"),
    ("What's your favorite movie?", "What's the last movie you watched?"),
    ("What’s your favorite animal?", "What pet do you have?")
]

def start_game_after_countdown(room_id):
    time.sleep(5)
    with lock:
        room = rooms.get(room_id)
        if not room or room["state"] != "countdown":
            return

        players = room["players"]
        imposter = random.choice(players)
        q_pair = random.choice(QUESTION_PAIRS)

        for p in players:
            role = "imposter" if p == imposter else "normal"
            room["roles"][p["id"]] = role
            room["questions"][p["id"]] = q_pair[1] if role == "imposter" else q_pair[0]

        room["answers"].clear()
        room["votes"].clear()
        room["state"] = "question"

@app.route("/<room_id>/join", methods=["POST"])
def join_room(room_id):
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400

    with lock:
        room = rooms.setdefault(room_id, {
            "players": [],
            "roles": {},
            "questions": {},
            "answers": {},
            "votes": {},
            "ready": {},
            "state": "waiting"
        })

        if room["state"] != "waiting":
            return jsonify({"error": "Game already started"}), 400

        if any(p["name"] == name for p in room["players"]):
            return jsonify({"error": "Name already taken"}), 400

        player_id = str(uuid.uuid4())
        room["players"].append({"id": player_id, "name": name})
        room["ready"][player_id] = False
        return jsonify({"player_id": player_id})

@app.route("/<room_id>/ready", methods=["POST"])
def mark_ready(room_id):
    data = request.json
    player_id = data.get("player_id")

    with lock:
        room = rooms.get(room_id)
        if not room or room["state"] != "waiting":
            return jsonify({"error": "Invalid room state"}), 400

        room["ready"][player_id] = True

        if all(room["ready"].values()) and len(room["players"]) >= 3:
            room["state"] = "countdown"
            Thread(target=start_game_after_countdown, args=(room_id,), daemon=True).start()

    return jsonify({"message": "Ready!"})

@app.route("/<room_id>/cancel", methods=["POST"])
def cancel_ready(room_id):
    data = request.json
    player_id = data.get("player_id")

    with lock:
        room = rooms.get(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404

        room["players"] = [p for p in room["players"] if p["id"] != player_id]
        room["ready"].pop(player_id, None)

        # Reset state if not enough players
        if len(room["players"]) < 3:
            room["state"] = "waiting"
            for pid in room["ready"]:
                room["ready"][pid] = False

    return jsonify({"message": "Cancelled and removed"})

@app.route("/<room_id>/state", methods=["GET"])
def get_state(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    return jsonify({"state": room["state"]})

@app.route("/<room_id>/role/<player_id>", methods=["GET"])
def get_role(room_id, player_id):
    room = rooms.get(room_id)
    return jsonify({"role": room["roles"].get(player_id, "unknown")})

@app.route("/<room_id>/question/<player_id>", methods=["GET"])
def get_question(room_id, player_id):
    room = rooms.get(room_id)
    return jsonify({"question": room["questions"].get(player_id, "Unknown")})

@app.route("/<room_id>/answer", methods=["POST"])
def submit_answer(room_id):
    data = request.json
    player_id = data.get("player_id")
    answer = data.get("answer")

    with lock:
        room = rooms.get(room_id)
        if room["state"] != "question":
            return jsonify({"error": "Game not accepting answers"}), 400

        room["answers"][player_id] = answer

        if len(room["answers"]) == len(room["players"]):
            room["state"] = "voting"

    return jsonify({"message": "Answer submitted"})

@app.route("/<room_id>/answers", methods=["GET"])
def get_answers(room_id):
    room = rooms.get(room_id)
    return jsonify({
        "answers": [
            {"name": p["name"], "answer": room["answers"].get(p["id"], "")}
            for p in room["players"]
        ]
    })

@app.route("/<room_id>/vote", methods=["POST"])
def submit_vote(room_id):
    data = request.json
    voter_id = data.get("player_id")
    vote_for = data.get("vote_for")

    with lock:
        room = rooms.get(room_id)
        if room["state"] != "voting":
            return jsonify({"error": "Not in voting phase"}), 400

        room["votes"][voter_id] = vote_for

        if len(room["votes"]) == len(room["players"]):
            room["state"] = "results"

    return jsonify({"message": "Vote submitted"})

@app.route("/<room_id>/results", methods=["GET"])
def get_results(room_id):
    room = rooms.get(room_id)
    vote_counts = {}
    for vote in room["votes"].values():
        vote_counts[vote] = vote_counts.get(vote, 0) + 1

    max_votes = max(vote_counts.values())
    candidates = [pid for pid, count in vote_counts.items() if count == max_votes]
    chosen = candidates[0] if candidates else None

    result = {
        "votes": {p["name"]: room["votes"].get(p["id"]) for p in room["players"]},
        "imposter": next((p["name"] for p in room["players"] if room["roles"][p["id"]] == "imposter"), None),
        "you_got_it": any(chosen == pid and room["roles"][pid] == "imposter" for pid in room["roles"])
    }

    return jsonify(result)

if __name__ == "__main__":
    app.run(port=5000)
