from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import redis
import random
import os
import uuid
import json

app = Flask(__name__, static_folder="static", template_folder="templates")
socketio = SocketIO(app, cors_allowed_origins="*")

# Secure Redis Connection
redis_client = redis.StrictRedis(
    host="mint-alien-56744.upstash.io",
    port=6379,
    password="Ad2oAAIjcDFhZjkyNTcyYWQ1ODM0MTkzODBkMWUzMDA4NGQwZDA4M3AxMA",  # Store this in env variables
    ssl=True,
    decode_responses=True
)

GRID_SIZE = 30  # Game Grid Size

# --- Utility Functions ---
def spawn_food(existing_food):
    """Ensure 5 food pods exist in unique locations."""
    while len(existing_food) < 5:
        new_food = (random.randint(0, GRID_SIZE - 1), random.randint(0, GRID_SIZE - 1))
        if new_food not in existing_food:
            existing_food.append(new_food)
    return existing_food

def save_session(session_id, data):
    """Store session data in Redis."""
    redis_client.set(f"session:{session_id}", json.dumps(data))

def load_session(session_id):
    """Load session data from Redis."""
    session_data = redis_client.get(f"session:{session_id}")
    return json.loads(session_data) if session_data else None

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

# --- Game Logic ---
@socketio.on("start_game")
def start_game():
    session_id = str(uuid.uuid4())  # Unique session ID per user
    deployment_name = f"snake-deploy-{session_id[:8]}"

    session_data = {
        "snake": [(GRID_SIZE // 2, GRID_SIZE // 2)],  
        "food": spawn_food([]),  
        "direction": "RIGHT",
        "running": True,
        "score": 0,
        "deployment": deployment_name
    }

    save_session(session_id, session_data)
    redis_client.set(f"deployment:{session_id}", deployment_name)

    create_deployment(deployment_name, replicas=1)

    join_room(session_id)  # Make user join their own room

    emit("session_started", {
        "session_id": session_id,
        "deployment": deployment_name,
        "snake": session_data["snake"], 
        "food": session_data["food"],
        "score": 0
    }, room=session_id)  # Send only to this user

@socketio.on("change_direction")
def change_direction(data):
    session_id = data.get("session_id")
    new_direction = data.get("direction")

    session_data = load_session(session_id)
    if session_data and new_direction:
        session_data["direction"] = new_direction
        save_session(session_id, session_data)

@socketio.on("game_loop")
def game_loop(data):
    session_id = data.get("session_id")
    session_data = load_session(session_id)

    if not session_data or not session_data["running"]:
        return

    head_x, head_y = session_data["snake"][-1]

    if session_data["direction"] == "UP": head_y -= 1
    elif session_data["direction"] == "DOWN": head_y += 1
    elif session_data["direction"] == "LEFT": head_x -= 1
    elif session_data["direction"] == "RIGHT": head_x += 1

    # Check for collisions
    if head_x < 0 or head_x >= GRID_SIZE or head_y < 0 or head_y >= GRID_SIZE or (head_x, head_y) in session_data["snake"]:
        session_data["running"] = False
        save_session(session_id, session_data)
        emit("game_over", {"session_id": session_id}, room=session_id)  # Send to this user only
        return

    session_data["snake"].append((head_x, head_y))

    # Check if snake eats food
    if (head_x, head_y) in session_data["food"]:
        session_data["food"].remove((head_x, head_y))
        session_data["food"] = spawn_food(session_data["food"])  
        session_data["score"] += 1

        deployment_name = redis_client.get(f"deployment:{session_id}")
        if deployment_name:
            new_replicas = session_data["score"]
            scale_deployment(deployment_name, new_replicas)
    else:
        session_data["snake"].pop(0)  # Move forward

    save_session(session_id, session_data)

    emit("update", {
        "session_id": session_id, 
        "snake": session_data["snake"], 
        "food": session_data["food"],
        "score": session_data["score"],
        "deployment": session_data["deployment"]
    }, room=session_id)  # Send only to this session

@socketio.on("disconnect")
def handle_disconnect():
    session_id = request.sid  # Use user socket ID
    leave_room(session_id)  # Remove user from room

    deployment_name = redis_client.get(f"deployment:{session_id}")
    if deployment_name:
        os.system(f"kubectl delete deployment {deployment_name} --force --grace-period=0")
        redis_client.delete(f"deployment:{session_id}")

    redis_client.delete(f"session:{session_id}")

# --- Deployment Management ---
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
