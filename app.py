from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import redis
import random
import os
import uuid

app = Flask(__name__, static_folder="static", template_folder="templates")
socketio = SocketIO(app, cors_allowed_origins="*")

# redis_client = redis.StrictRedis(host="mint-alien-56744.upstash.io", port=6379, decode_responses=True)
redis_client = redis.StrictRedis(
    host="mint-alien-56744.upstash.io",
    port=6379,
    password="Ad2oAAIjcDFhZjkyNTcyYWQ1ODM0MTkzODBkMWUzMDA4NGQwZDA4M3AxMA",  # Fetch from environment variables
    ssl=True,  # Enable SSL/TLS
    decode_responses=True
)


sessions = {}

GRID_SIZE = 30  # Bigger game box

def spawn_food(existing_food):
    """Ensure 5 food pods exist in unique locations."""
    while len(existing_food) < 5:
        new_food = (random.randint(0, GRID_SIZE - 1), random.randint(0, GRID_SIZE - 1))
        if new_food not in existing_food:
            existing_food.append(new_food)
    return existing_food

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("start_game")
def start_game():
    session_id = str(uuid.uuid4())
    deployment_name = f"snake-deploy-{session_id[:8]}"
    
    sessions[session_id] = {
        "snake": [(GRID_SIZE // 2, GRID_SIZE // 2)],  
        "food": spawn_food([]),  
        "direction": "RIGHT",  # Default direction
        "running": True,
        "score": 0,
        "deployment": deployment_name
    }

    redis_client.set(f"deployment:{session_id}", deployment_name)
    create_deployment(deployment_name, replicas=1)

    emit("session_started", {
        "session_id": session_id,
        "deployment": deployment_name,
        "snake": sessions[session_id]["snake"], 
        "food": sessions[session_id]["food"],
        "score": 0
    })

@socketio.on("change_direction")  # 🛠 Fix: Handling Direction Change
def change_direction(data):
    session_id = data.get("session_id")
    new_direction = data.get("direction")

    if session_id in sessions and new_direction:
        sessions[session_id]["direction"] = new_direction

@socketio.on("game_loop")
def game_loop(data):
    session_id = data["session_id"]
    if session_id not in sessions:
        return

    game = sessions[session_id]
    if not game["running"]:
        return

    head_x, head_y = game["snake"][-1]

    if game["direction"] == "UP": head_y -= 1
    elif game["direction"] == "DOWN": head_y += 1
    elif game["direction"] == "LEFT": head_x -= 1
    elif game["direction"] == "RIGHT": head_x += 1

    # Check collision with walls or itself
    if head_x < 0 or head_x >= GRID_SIZE or head_y < 0 or head_y >= GRID_SIZE or (head_x, head_y) in game["snake"]:
        game["running"] = False
        emit("game_over", {"session_id": session_id})
        return

    game["snake"].append((head_x, head_y))

    # Check if snake eats food
    if (head_x, head_y) in game["food"]:
        game["food"].remove((head_x, head_y))
        game["food"] = spawn_food(game["food"])  
        game["score"] += 1

        deployment_name = redis_client.get(f"deployment:{session_id}")
        if deployment_name:
            new_replicas = game["score"]
            scale_deployment(deployment_name, new_replicas)
    else:
        game["snake"].pop(0)  # Move forward

    emit("update", {
        "session_id": session_id, 
        "snake": game["snake"], 
        "food": game["food"],
        "score": game["score"],
        "deployment": game["deployment"]
    }, broadcast=True)

@socketio.on("disconnect")
def handle_disconnect():
    for session_id in list(sessions.keys()):
        deployment_name = redis_client.get(f"deployment:{session_id}")
        if deployment_name:
            os.system(f"kubectl delete deployment {deployment_name} --force --grace-period=0")
            redis_client.delete(f"deployment:{session_id}")

        del sessions[session_id]

def create_deployment(deployment_name, replicas):
    deployment_yaml = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {deployment_name}
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: snake-pod
  template:
    metadata:
      labels:
        app: snake-pod
    spec:
      containers:
      - name: busybox
        image: busybox
        command: ["sh", "-c", "sleep 3600"]
"""
    with open("deployment.yaml", "w") as f:
        f.write(deployment_yaml)
    os.system(f"kubectl apply -f deployment.yaml")
    os.remove("deployment.yaml")

def scale_deployment(deployment_name, replicas):
    os.system(f"kubectl scale deployment {deployment_name} --replicas={replicas}")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
