"use strict";

// ── Socket.IO connection ─────────────────────────────────────────────────────
// Connect to the SIC Webserver on the same origin. The server is at the same
// host:port the page was loaded from, so the default io() call is correct.
const socket = io();

// ── DOM references ───────────────────────────────────────────────────────────
const displayArea = document.getElementById("display-area");
const transcript  = document.getElementById("transcript");
const inputArea   = document.getElementById("input-area");

// ── Helpers ──────────────────────────────────────────────────────────────────

function clearDisplay() {
  displayArea.innerHTML = "";
}

function clearInput() {
  inputArea.innerHTML = "";
  inputArea.classList.add("hidden");
}

// Emit a web_input event back to the SIC Webserver.
// SICScreenAdapter._on_button_clicked() receives this as a ButtonClicked message
// and forwards it to the NarDialPy EventBus so MoveWaitForWebInput can resolve.
function sendValue(value) {
  socket.emit("sic/button_clicked", { type: "web_input", value: value });
}

// ── Transcript handler ───────────────────────────────────────────────────────

// Append a new line to the conversation log (robot or user side).
// Lines accumulate so the viewer can see the full conversation history.
function handleTranscript(payload) {
  var role = payload.role || "robot";
  var text = payload.text || "";
  if (!text) return;

  transcript.classList.remove("hidden");

  var line = document.createElement("div");
  line.className = "transcript-line transcript-line--" + role;
  line.textContent = text;
  transcript.appendChild(line);

  // Auto-scroll to the latest line.
  transcript.scrollTop = transcript.scrollHeight;
}

// ── Display command handler ──────────────────────────────────────────────────

function handleScreen(payload) {
  var type = payload.type;

  if (type === "black") {
    clearDisplay();
    // displayArea background is already black via CSS; clearing children is enough.
    return;
  }

  if (type === "image") {
    clearDisplay();
    var img = document.createElement("img");
    img.src = payload.src || "";
    img.alt = payload.caption || "";
    displayArea.appendChild(img);
    if (payload.caption) {
      var cap = document.createElement("p");
      cap.className = "caption";
      cap.textContent = payload.caption;
      // Caption is positioned by CSS; append after the image element.
      displayArea.appendChild(cap);
    }
    return;
  }

  if (type === "video") {
    clearDisplay();
    var video = document.createElement("video");
    video.src = payload.src || "";
    video.autoplay = true;
    video.controls = false;
    video.loop = false;
    displayArea.appendChild(video);
    return;
  }

  if (type === "iframe") {
    clearDisplay();
    var frame = document.createElement("iframe");
    frame.src = payload.src || "";
    frame.allowFullscreen = true;
    displayArea.appendChild(frame);
    return;
  }

  if (type === "html") {
    clearDisplay();
    var container = document.createElement("div");
    container.className = "html-container";
    // Dialog authors control this content — it is treated as trusted HTML,
    // consistent with how dialog JSON authors have full authoring access.
    container.innerHTML = payload.content || "";
    displayArea.appendChild(container);
    return;
  }
}

// ── Input command handler ────────────────────────────────────────────────────

function handleInput(payload) {
  var type = payload.type;

  if (type === "none") {
    clearInput();
    return;
  }

  if (type === "buttons") {
    clearInput();
    var options = payload.options || [];
    if (options.length === 0) return;

    inputArea.classList.remove("hidden");
    options.forEach(function (option) {
      var btn = document.createElement("button");
      btn.className = "btn-option";
      btn.textContent = option;
      btn.addEventListener("click", function () {
        // Disable all buttons after the first click to prevent double-submission.
        Array.from(inputArea.querySelectorAll(".btn-option")).forEach(function (b) {
          b.disabled = true;
        });
        sendValue(option);
      });
      inputArea.appendChild(btn);
    });
    return;
  }

  if (type === "text_input") {
    clearInput();
    inputArea.classList.remove("hidden");

    var form   = document.createElement("form");
    form.id    = "text-input-form";

    var field        = document.createElement("input");
    field.type       = "text";
    field.id         = "text-input-field";
    field.placeholder = payload.prompt || "";
    field.autocomplete = "off";
    field.autofocus  = true;

    var submit    = document.createElement("button");
    submit.type   = "submit";
    submit.id     = "text-input-submit";
    submit.textContent = "Send";

    form.appendChild(field);
    form.appendChild(submit);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var value = field.value.trim();
      if (!value) return;
      field.disabled  = true;
      submit.disabled = true;
      sendValue(value);
    });

    inputArea.appendChild(form);
    return;
  }
}

// ── Socket.IO event listeners ────────────────────────────────────────────────

socket.on("connect", function () {
  console.log("[NarDialPy] connected to SIC Webserver");
});

socket.on("disconnect", function () {
  console.log("[NarDialPy] disconnected from SIC Webserver");
});

// sic/transcript is emitted by the legacy TranscriptMessage path.
// SICScreenAdapter.show_transcript() sends it for SIC backward compatibility.
// The frontend ignores it in favour of the role-tagged sic/webinfo messages.
socket.on("sic/transcript", function () {
  // intentionally ignored — handled via sic/webinfo label="transcript"
});

socket.on("sic/webinfo", function (data) {
  // data = { label: string, message: any }
  // (Verify field names against SIC WebserverComponent.on_message() if the
  //  server version is updated, as SIC may rename these keys.)
  var label   = data.label;
  var message = data.message;

  if (label === "transcript") {
    handleTranscript(message);
  } else if (label === "screen") {
    handleScreen(message);
  } else if (label === "input") {
    handleInput(message);
  }
});

socket.on("sic/state", function (data) {
  // Sent by the SIC Webserver on every new connection with the last known
  // transcript and webinfo snapshot. Log for now; future: restore display state.
  console.log("[NarDialPy] sic/state received:", data);
});
