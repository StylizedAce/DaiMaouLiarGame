import requests
import time

BASE = "http://localhost:5000"

room_id = input("Enter room ID: ").strip()
name = input("Enter your name: ").strip()

res = requests.post(f"{BASE}/{room_id}/join", json={"name": name})
if res.status_code != 200:
    print(res.json())
    exit()

player_id = res.json()["player_id"]
print(f"Joined room as {name}.")

ready = input("Ready up? [y/n]: ").strip().lower()
if ready == "n":
    requests.post(f"{BASE}/{room_id}/cancel", json={"player_id": player_id})
    print("Canceled.")
    exit()

requests.post(f"{BASE}/{room_id}/ready", json={"player_id": player_id})
print("Waiting for all players to ready up...")

# Wait for countdown
while True:
    state = requests.get(f"{BASE}/{room_id}/state").json()["state"]
    if state == "countdown":
        print("All players ready! Game starting in 5 seconds...")
        break
    time.sleep(0.2)

# Wait for question phase
while True:
    state = requests.get(f"{BASE}/{room_id}/state").json()["state"]
    if state == "question":
        break
    time.sleep(0.2)

# Game begins
role = requests.get(f"{BASE}/{room_id}/role/{player_id}").json()["role"]
question = requests.get(f"{BASE}/{room_id}/question/{player_id}").json()["question"]

print(f"\nYour role is: {role.upper()}")
print(f"QUESTION: {question}")
answer = input("Your answer: ")

requests.post(f"{BASE}/{room_id}/answer", json={"player_id": player_id, "answer": answer})
print("Answer submitted. Waiting for others...")

# Voting
while True:
    state = requests.get(f"{BASE}/{room_id}/state").json()["state"]
    if state == "voting":
        break
    time.sleep(0.2)

answers = requests.get(f"{BASE}/{room_id}/answers").json()["answers"]
print("\n--- Answers ---")
for a in answers:
    print(f"{a['name']}: {a['answer']}")

vote = input("Who do you think is the imposter? Type their name: ").strip()
requests.post(f"{BASE}/{room_id}/vote", json={"player_id": player_id, "vote_for": vote})

# Results
while True:
    state = requests.get(f"{BASE}/{room_id}/state").json()["state"]
    if state == "results":
        break
    time.sleep(0.2)

result = requests.get(f"{BASE}/{room_id}/results").json()
print("\n--- Voting Results ---")
for name, voted_for in result["votes"].items():
    print(f"{name} voted for {voted_for}")

print(f"\nThe imposter was: {result['imposter']}")
print("🎉 YOU GOT IT RIGHT!" if result["you_got_it"] else "❌ WRONG GUESS!")
