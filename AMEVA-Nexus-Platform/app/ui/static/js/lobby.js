// lobby.js - AMEVA Battle.net Lobby Actions

let wsConn = null;
let currentSelectedBot = null;
let activeNodesData = [];

// Initialize
document.addEventListener("DOMContentLoaded", () => {
    loadChatHistory();
    fetchActiveNodes();
    initWebSocket();

    // Set up polling for active nodes (every 3 seconds)
    setInterval(fetchActiveNodes, 3000);

    // Event listeners
    document.getElementById("chat-send").addEventListener("click", sendChatMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            sendChatMessage();
        }
    });

    // SRE Buttons actions
    document.getElementById("btn-chaos-halt").addEventListener("click", () => {
        if (confirm("🚨 EMERGENCY CHAOS HALT: Are you sure you want to halt the system?")) {
            fetch("/api/v1/sre/chaos", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ drop_rate: 1.0 })
            }).then(() => alert("Chaos Injector activated: Platform requests are now blocked."));
        }
    });

    document.getElementById("btn-chaos-bench").addEventListener("click", () => {
        alert("Running system hardware audit and latency checks across all active nodes...");
    });
});

// Fetch historical lobby chats
async function loadChatHistory() {
    try {
        const res = await fetch("/api/v1/lobby/chat");
        const data = await res.json();
        const chatMessages = document.getElementById("chat-messages");
        
        // Clear previous messages except welcome
        const welcome = chatMessages.querySelector(".terminal-welcome");
        chatMessages.innerHTML = "";
        if (welcome) chatMessages.appendChild(welcome);

        if (data.chats && data.chats.length > 0) {
            data.chats.forEach(msg => {
                appendChatMessage(msg.bot_name, msg.content, msg.created_at);
            });
            scrollToBottom();
        }
    } catch (err) {
        console.error("Failed to load chat history:", err);
    }
}

// Fetch active nodes and hardware specs
async function fetchActiveNodes() {
    try {
        const res = await fetch("/api/v1/lobby/nodes");
        const data = await res.json();
        
        activeNodesData = data.nodes || [];
        document.getElementById("node-count").innerText = activeNodesData.length;
        
        renderNodesList();
        renderSelectedBotDetail();
    } catch (err) {
        console.error("Failed to fetch active nodes:", err);
    }
}

// Render nodes list in left panel
function renderNodesList() {
    const list = document.getElementById("agents-list");
    list.innerHTML = "";

    if (activeNodesData.length === 0) {
        list.innerHTML = `<li class="placeholder-text">No active nodes connected...</li>`;
        return;
    }

    activeNodesData.forEach(node => {
        const li = document.createElement("li");
        li.dataset.botName = node.bot_name;
        if (currentSelectedBot === node.bot_name) {
            li.classList.add("selected-bot");
        }

        // Status class mapping
        let statusClass = "status-offline";
        if (node.status === "ACTIVE") statusClass = "status-active";
        else if (node.status === "LOBBY_WAITING") statusClass = "status-lobby-waiting";

        // Bot name styling class
        const nameClass = `bot-name-${node.bot_name}`;

        li.innerHTML = `
            <div class="bot-name-wrapper">
                <span class="bot-status-dot ${statusClass}"></span>
                <span class="bot-name ${nameClass}">${node.bot_name}</span>
            </div>
            <span class="bot-hw-badge" style="font-size:10px; color:#4b5a7a;">[${node.hardware_mode}]</span>
        `;

        li.addEventListener("click", () => {
            document.querySelectorAll("#agents-list li").forEach(item => {
                item.classList.remove("selected-bot");
            });
            li.classList.add("selected-bot");
            currentSelectedBot = node.bot_name;
            renderSelectedBotDetail();
        });

        list.appendChild(li);
    });
}

// Render specifications of the selected bot
function renderSelectedBotDetail() {
    const content = document.getElementById("bot-detail-content");
    if (!currentSelectedBot) {
        content.innerHTML = `<p class="placeholder-text">Select an agent to query hardware specs...</p>`;
        return;
    }

    const node = activeNodesData.find(n => n.bot_name === currentSelectedBot);
    if (!node) {
        content.innerHTML = `<p class="placeholder-text">Agent '${currentSelectedBot}' went offline.</p>`;
        currentSelectedBot = null;
        return;
    }

    // Parse models list
    let modelsHtml = "";
    if (node.available_models && node.available_models.length > 0) {
        node.available_models.forEach(m => {
            modelsHtml += `<span style="display:inline-block; background:#1b2a4a; padding:1px 5px; margin:2px; border-radius:3px; font-size:10px;">${m}</span>`;
        });
    } else {
        modelsHtml = "None";
    }

    content.innerHTML = `
        <div class="spec-row"><span class="spec-label">Agent ID:</span><span class="spec-value">${node.bot_name}</span></div>
        <div class="spec-row"><span class="spec-label">Status:</span><span class="spec-value" style="color:${node.status === 'ACTIVE' ? 'var(--neon-green)' : 'var(--neon-cyan)'}">${node.status}</span></div>
        <div class="spec-row"><span class="spec-label">CPU Info:</span><span class="spec-value">${node.cpu_info}</span></div>
        <div class="spec-row"><span class="spec-label">System RAM:</span><span class="spec-value">${node.ram_gb} GB</span></div>
        <div class="spec-row"><span class="spec-label">GPU Model:</span><span class="spec-value">${node.gpu_model}</span></div>
        <div class="spec-row"><span class="spec-label">VRAM Size:</span><span class="spec-value">${node.vram_gb} GB</span></div>
        <div class="spec-row" style="margin-top:6px;"><span class="spec-label">Last Seen:</span><span class="spec-value">${node.last_seen || 'N/A'}</span></div>
        <div style="margin-top:8px;">
            <div class="spec-label" style="margin-bottom:3px;">Ollama Local Models:</div>
            <div>${modelsHtml}</div>
        </div>
    `;
}

// Establish real-time websocket
function initWebSocket() {
    const loc = window.location;
    const wsProto = loc.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${loc.host}/ws/v1/experiments/LOBBY?agent_id=LOBBY_UI`;

    console.log("Connecting to Platform Websocket:", wsUrl);
    wsConn = new WebSocket(wsUrl);

    wsConn.onopen = () => {
        console.log("WebSocket connected to AMEVA Platform Hub.");
        document.getElementById("sys-status").innerText = "CONNECTED";
        document.getElementById("sys-status").className = "neon-green";
    };

    wsConn.onmessage = (event) => {
        try {
            const envelope = JSON.parse(event.data);
            if (envelope.event_type === "lobby.chat.message") {
                const botName = envelope.agent_id || "Unknown";
                const content = envelope.payload ? envelope.payload.content : "";
                const timeStr = new Date(envelope.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                appendChatMessage(botName, content, timeStr);
                scrollToBottom();
            }
        } catch (err) {
            console.error("Failed to parse websocket message:", err);
        }
    };

    wsConn.onclose = () => {
        console.log("WebSocket connection closed. Reconnecting in 3 seconds...");
        document.getElementById("sys-status").innerText = "OFFLINE (RECONNECTING)";
        document.getElementById("sys-status").className = "neon-pink";
        setTimeout(initWebSocket, 3000);
    };

    wsConn.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

// Format and append chat messages to terminal window
function appendChatMessage(botName, text, timeStr) {
    const chatLog = document.getElementById("chat-messages");
    const msgDiv = document.createElement("div");
    msgDiv.className = "chat-msg";

    // Set time
    const timeSpan = document.createElement("span");
    timeSpan.className = "chat-time";
    timeSpan.innerText = `[${timeStr}]`;
    msgDiv.appendChild(timeSpan);

    // Set author
    const authorSpan = document.createElement("span");
    authorSpan.className = "chat-author";
    
    // Add css coloring depending on author name
    if (botName === "RESEARCHER") {
        authorSpan.classList.add("chat-author-researcher");
        authorSpan.innerText = "RESEARCHER";
    } else if (botName === "SYSTEM") {
        authorSpan.classList.add("chat-author-system");
        authorSpan.innerText = "SYSTEM";
    } else {
        authorSpan.classList.add(`bot-name-${botName}`);
        authorSpan.innerText = botName;
    }
    msgDiv.appendChild(authorSpan);

    // Separator
    const sep = document.createTextNode(": ");
    msgDiv.appendChild(sep);

    // Set text with highlighted mentions (e.g. @bot_1)
    const textSpan = document.createElement("span");
    textSpan.className = "chat-text";
    
    // Simple regex to colorize @bot_x mentions
    const mentionRegex = /(@[a-zA-Z0-9_]+)/g;
    const parts = text.split(mentionRegex);
    parts.forEach(part => {
        if (part.startsWith("@")) {
            const mentionSpan = document.createElement("span");
            mentionSpan.className = "chat-mention";
            mentionSpan.innerText = part;
            textSpan.appendChild(mentionSpan);
        } else {
            textSpan.appendChild(document.createTextNode(part));
        }
    });

    msgDiv.appendChild(textSpan);
    chatLog.appendChild(msgDiv);
}

// Send chat message as researcher
function sendChatMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    if (!wsConn || wsConn.readyState !== WebSocket.OPEN) {
        alert("WebSocket is not connected. Can't send message.");
        return;
    }

    const envelope = {
        version: "1.0.0",
        event_id: "evt_" + Math.random().toString(36).substr(2, 9),
        event_type: "lobby.chat.message",
        idempotency_key: "idem_" + Math.random().toString(36).substr(2, 9) + Date.now(),
        timestamp: Math.floor(Date.now() / 1000),
        agent_id: "RESEARCHER",
        payload: {
            content: text
        }
    };

    wsConn.send(JSON.stringify(envelope));
    input.value = "";
}

function scrollToBottom() {
    const container = document.getElementById("chat-container");
    container.scrollTop = container.scrollHeight;
}
