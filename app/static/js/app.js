/*
   My DockerForge SPA Interface Manager
   I built this script to manage UI bindings, stream terminal logs, and coordinate state flows.
*/

document.addEventListener("DOMContentLoaded", () => {
    // UI Elements
    const repoInput = document.getElementById("repo-url");
    const apiKeyInput = document.getElementById("api-key");
    const modeRealBtn = document.getElementById("mode-real");
    const modeSimBtn = document.getElementById("mode-sim");
    const btnForge = document.getElementById("btn-forge");
    
    const dockerStatusBadge = document.getElementById("docker-status");
    const geminiStatusBadge = document.getElementById("gemini-status");
    const techBadge = document.getElementById("tech-badge");
    
    const pipelineNodes = {
        idle: document.getElementById("node-idle"),
        scanning: document.getElementById("node-scanning"),
        generating: document.getElementById("node-generating"),
        compiling: document.getElementById("node-compiling"),
        healing: document.getElementById("node-healing"),
        verifying: document.getElementById("node-verifying"),
        ready: document.getElementById("node-ready")
    };
    
    const codeDockerfile = document.getElementById("code-dockerfile");
    const codeCompose = document.getElementById("code-compose");
    const codeExplorer = document.getElementById("code-explorer");
    const codeActions = document.getElementById("code-actions");
    
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    const terminalScreen = document.getElementById("terminal-screen");
    const btnClearTerminal = document.getElementById("btn-clear-terminal");
    const btnCopy = document.getElementById("btn-copy");
    const btnDownload = document.getElementById("btn-download");
    
    // Application State Variables
    let selectedMode = "simulation"; // default
    let activeSessionSource = null;
    let currentActiveTab = "dockerfile";
    
    // I check server environment features on initialization
    async function checkSystemHealth() {
        try {
            const res = await fetch("/api/health");
            const data = await res.json();
            
            // Set Docker Badge
            if (data.docker_available) {
                dockerStatusBadge.classList.add("active");
                dockerStatusBadge.querySelector(".label").textContent = "My Docker Daemon: ACTIVE";
            } else {
                dockerStatusBadge.classList.add("warning");
                dockerStatusBadge.querySelector(".label").textContent = "My Docker Daemon: OFFLINE";
                appendTerminalLine("[12:00:00] [WARNING] I detected Docker is not running locally. I will fallback to simulation mode automatically.", "WARNING");
            }
            
            // Set Gemini API Key Badge
            if (data.api_key_configured) {
                geminiStatusBadge.classList.add("active");
                geminiStatusBadge.querySelector(".label").textContent = "My Gemini Key: CONFIGURED";
            } else {
                geminiStatusBadge.classList.add("warning");
                geminiStatusBadge.querySelector(".label").textContent = "My Gemini Key: NOT CONFIGURED";
            }
            
            // Select default mode button based on config
            if (data.default_simulation_mode || !data.docker_available) {
                setRunningMode("simulation");
            } else {
                setRunningMode("real");
            }
        } catch (e) {
            console.error("Could not fetch backend health", e);
            dockerStatusBadge.classList.add("error");
            dockerStatusBadge.querySelector(".label").textContent = "My Backend: ERROR";
        }
    }
    
    // Helper to toggle switch modes
    function setRunningMode(mode) {
        selectedMode = mode;
        if (mode === "simulation") {
            modeSimBtn.classList.add("active");
            modeRealBtn.classList.remove("active");
        } else {
            modeRealBtn.classList.add("active");
            modeSimBtn.classList.remove("active");
        }
    }
    
    modeSimBtn.addEventListener("click", () => setRunningMode("simulation"));
    modeRealBtn.addEventListener("click", () => {
        // Warning if Docker is not active
        if (!dockerStatusBadge.classList.contains("active")) {
            alert("I noticed Docker is offline on your system. Please install/start Docker to run in Genuine mode!");
            return;
        }
        setRunningMode("real");
    });
    
    // Clear terminal screen logs
    btnClearTerminal.addEventListener("click", () => {
        terminalScreen.innerHTML = '<div class="terminal-line system-welcome">Logs cleared by user. Waiting for next forge...</div>';
    });
    
    // Main trigger to forge dockerfile configurations
    btnForge.addEventListener("click", async () => {
        const repoUrl = repoInput.value.trim();
        if (!repoUrl) {
            alert("Please enter a valid GitHub Repository URL to scan!");
            return;
        }
        
        // Disable forms
        btnForge.disabled = true;
        repoInput.disabled = true;
        apiKeyInput.disabled = true;
        modeSimBtn.disabled = true;
        modeRealBtn.disabled = true;
        
        // Reset code panel visibility
        codeActions.style.display = "none";
        
        // Reset pipeline visual node items
        Object.values(pipelineNodes).forEach(node => {
            node.classList.remove("active", "completed", "failed");
        });
        pipelineNodes.idle.classList.add("active");
        
        appendTerminalLine(`[CMD] Triggering codebase scanner on: ${repoUrl}`, "CMD");
        
        try {
            const response = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    repo_url: repoUrl,
                    api_key: apiKeyInput.value.trim() || null,
                    force_simulation: selectedMode === "simulation"
                })
            });
            
            if (!response.ok) {
                const err = await response.json();
                let errMsg = "Build request failed";
                if (err && err.detail) {
                    if (typeof err.detail === "string") {
                        errMsg = err.detail;
                    } else if (Array.isArray(err.detail)) {
                        errMsg = err.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ');
                    }
                }
                throw new Error(errMsg);
            }
            
            const data = await response.json();
            const sessionId = data.session_id;
            
            appendTerminalLine(`[INFO] Created background task worker session: ${sessionId}`, "INFO");
            
            // Connect to server stream
            connectStream(sessionId);
        } catch (err) {
            appendTerminalLine(`[ERROR] Generation setup failed: ${err.message}`, "ERROR");
            resetInterfaceState();
        }
    });
    
    // Connect Server Sent Events stream
    function connectStream(sessionId) {
        if (activeSessionSource) {
            activeSessionSource.close();
        }
        
        activeSessionSource = new EventSource(`/api/stream/${sessionId}`);
        
        activeSessionSource.addEventListener("log", (e) => {
            const data = JSON.parse(e.data);
            parseAndAppendLog(data.line);
        });
        
        activeSessionSource.addEventListener("state", (e) => {
            const data = JSON.parse(e.data);
            updatePipelineTracker(data.state);
            
            if (data.detected_language && data.detected_language !== "Unknown") {
                techBadge.textContent = `Primary: ${data.detected_language}`;
            }
            
            // Pop code frames
            if (data.dockerfile) {
                codeDockerfile.textContent = data.dockerfile;
            }
            if (data.compose) {
                codeCompose.textContent = data.compose;
            }
            if (data.state === "ready" && data.dockerfile) {
                // Preload structure tree if scanned
                if (data.dockerfile && codeExplorer.textContent.includes("waiting")) {
                    codeExplorer.textContent = "Scanned files found:\n" + (data.dockerfile.length > 50 ? "- Dockerfile\n- docker-compose.yml\n" : "");
                }
                
                // Show actions pane
                codeActions.style.display = "flex";
                configureFileExportControls();
            }
            
            if (data.state === "ready" || data.state === "failed") {
                activeSessionSource.close();
                resetInterfaceState();
            }
        });
        
        activeSessionSource.onerror = (err) => {
            console.error("SSE Stream connection error", err);
            appendTerminalLine("[ERROR] Connection to my logger stream was interrupted.", "ERROR");
            activeSessionSource.close();
            resetInterfaceState();
        };
    }
    
    // Parse log lines and map levels to CSS selectors
    function parseAndAppendLog(log) {
        // Format example: [HH:MM:SS] [LEVEL] Message
        const match = log.match(/^\[\d{2}:\d{2}:\d{2}\]\s+\[(\w+)\]\s+(.*)$/);
        let level = "INFO";
        let message = log;
        
        if (match) {
            level = match[1];
            message = match[2];
        }
        
        appendTerminalLine(message, level);
    }
    
    // Core terminal render engine
    function appendTerminalLine(message, level) {
        const div = document.createElement("div");
        div.className = `terminal-line level-${level.toLowerCase()}`;
        div.textContent = message;
        terminalScreen.appendChild(div);
        
        // Dynamic scroll behavior
        terminalScreen.scrollTop = terminalScreen.scrollHeight;
    }
    
    // Map backend state loops to pipeline tracker cards
    function updatePipelineTracker(state) {
        // States: idle, scanning, generating, compiling, healing, verifying, ready, failed
        const steps = ["idle", "scanning", "generating", "compiling", "healing", "verifying", "ready"];
        const curIdx = steps.indexOf(state);
        
        if (curIdx === -1) {
            if (state === "failed") {
                // Trigger fail style on whatever was last active
                Object.values(pipelineNodes).forEach(node => {
                    if (node.classList.contains("active")) {
                        node.classList.add("failed");
                    }
                });
            }
            return;
        }
        
        // Reset actives
        Object.values(pipelineNodes).forEach(node => node.classList.remove("active"));
        
        // Highlight active and mark previous completed
        steps.forEach((step, idx) => {
            const node = pipelineNodes[step];
            if (idx < curIdx) {
                node.classList.add("completed");
                node.classList.remove("active");
            } else if (idx === curIdx) {
                node.classList.add("active");
                node.classList.remove("completed");
            } else {
                node.classList.remove("completed", "active");
            }
        });
    }
    
    // Reset forms after execution
    function resetInterfaceState() {
        btnForge.disabled = false;
        repoInput.disabled = false;
        apiKeyInput.disabled = false;
        modeSimBtn.disabled = false;
        modeRealBtn.disabled = false;
    }
    
    // Code tabs visual selector
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabName = btn.dataset.tab;
            currentActiveTab = tabName;
            
            tabButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            tabContents.forEach(tc => {
                if (tc.id === `tab-${tabName}`) {
                    tc.classList.add("active");
                } else {
                    tc.classList.remove("active");
                }
            });
            
            // Reconfigure export controls to point to active files
            configureFileExportControls();
        });
    });
    
    // Clipboard copy controls
    btnCopy.addEventListener("click", () => {
        let codeText = "";
        if (currentActiveTab === "dockerfile") {
            codeText = codeDockerfile.textContent;
        } else if (currentActiveTab === "compose") {
            codeText = codeCompose.textContent;
        } else {
            codeText = codeExplorer.textContent;
        }
        
        navigator.clipboard.writeText(codeText)
            .then(() => {
                const oldText = btnCopy.textContent;
                btnCopy.textContent = "Copied! ✓";
                setTimeout(() => btnCopy.textContent = oldText, 2000);
            })
            .catch(err => {
                alert("Failed to copy code to clipboard: " + err);
            });
    });
    
    // File download generator
    function configureFileExportControls() {
        let filename = "Dockerfile";
        let content = "";
        
        if (currentActiveTab === "dockerfile") {
            filename = "Dockerfile";
            content = codeDockerfile.textContent;
            btnCopy.style.display = "inline-block";
            btnDownload.style.display = "inline-block";
        } else if (currentActiveTab === "compose") {
            filename = "docker-compose.yml";
            content = codeCompose.textContent;
            btnCopy.style.display = "inline-block";
            btnDownload.style.display = "inline-block";
        } else {
            // Hide for file explorer
            btnDownload.style.display = "none";
        }
        
        // Build raw blob
        const blob = new Blob([content], { type: "text/plain" });
        btnDownload.href = URL.createObjectURL(blob);
        btnDownload.download = filename;
    }
    
    // Initialize system checks
    checkSystemHealth();
});
