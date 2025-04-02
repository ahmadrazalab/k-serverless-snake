from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import redis
import random
import eventlet
import os
import uuid

app = Flask(__name__, static_folder="static", template_folder="templates")
socketio = SocketIO(app, cors_allowed_origins="*")

# Redis Setup (Store pod names for cleanup)
redis_client = redis.StrictRedis(host="localhost", port=6379, decode_responses=True)

# Game State
snake = []
food = (0, 0)
direction = "RIGHT"
game_running = False
session_id = str(uuid.uuid4())  # Unique session ID for each player


def spawn_food():
    """Generate food at a random location."""
    while True:
        new_food = (random.randint(0, 19), random.randint(0, 19))
        if new_food not in snake:
            return new_food


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/reset", methods=["POST"])
def reset_game():
    """Reset the game state and destroy all pods of this session."""
    global snake, food, direction, game_running
    snake = [(5, 5)]
    food = spawn_food()
    direction = "RIGHT"
    game_running = True

    # Delete all pods created by this session
    session_pods = redis_client.smembers(f"pods:{session_id}")
    for pod in session_pods:
        os.system(f"kubectl delete pod {pod} --force --grace-period=0")
    redis_client.delete(f"pods:{session_id}")

    return jsonify({"message": "Game reset, all pods destroyed!"})


@socketio.on("start_game")
def start_game():
    """Initialize the game when the user clicks Start."""
    global snake, food, direction, game_running
    snake = [(5, 5)]
    food = spawn_food()
    direction = "RIGHT"
    game_running = True
    emit("update", {"snake": snake, "food": food, "pods": list(redis_client.smembers(f"pods:{session_id}"))}, broadcast=True)


@socketio.on("move")
def handle_move(data):
    """Change snake direction based on user input."""
    global direction
    direction = data["direction"]


@socketio.on("game_loop")
def game_loop():
    """Game loop to continuously update snake movement."""
    global snake, food, direction, game_running

    if not game_running:
        return

    head_x, head_y = snake[-1]

    if direction == "UP":
        head_y -= 1
    elif direction == "DOWN":
        head_y += 1
    elif direction == "LEFT":
        head_x -= 1
    elif direction == "RIGHT":
        head_x += 1

    # Collision Check (Wall)
    if head_x < 0 or head_x >= 20 or head_y < 0 or head_y >= 20:
        game_running = False
        emit("game_over")
        return

    # Collision Check (Self)
    if (head_x, head_y) in snake:
        game_running = False
        emit("game_over")
        return

    # Move Snake
    snake.append((head_x, head_y))

    # Food Collision
    if (head_x, head_y) == food:
        food = spawn_food()
        pod_name = f"snake-pod-{uuid.uuid4().hex[:6]}"
        redis_client.sadd(f"pods:{session_id}", pod_name)  # Store pod in Redis
        
        # Create a new pod in the Kubernetes cluster
        create_pod(pod_name)
    else:
        snake.pop(0)  # Remove tail if no food eaten

    game_state = {"snake": snake, "food": food, "pods": list(redis_client.smembers(f"pods:{session_id}"))}
    emit("update", game_state, broadcast=True)


@socketio.on("disconnect")
def handle_disconnect():
    """Destroy all pods when the user disconnects (refreshes page)."""
    session_pods = redis_client.smembers(f"pods:{session_id}")
    for pod in session_pods:
        os.system(f"kubectl delete pod {pod} --force --grace-period=0")
    redis_client.delete(f"pods:{session_id}")


def create_pod(pod_name):
    """Deploys a pod in Kubernetes when the snake eats food."""
    pod_yaml = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
spec:
  containers:
  - name: busybox
    image: busybox
    command: ["sh", "-c", "sleep 3600"]
"""
    with open("pod.yaml", "w") as f:
        f.write(pod_yaml)
    os.system(f"kubectl apply -f pod.yaml")
    os.remove("pod.yaml")


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
