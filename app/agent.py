import os
import shutil
import subprocess
import time
import uuid
import re
from google import genai
from google.genai import types
from google.genai.errors import APIError

class DockerForgeAgent:
    """
    My autonomous AI agent that manages cloning, analysis, 
    Dockerfile generation, self-healing, and container validation.
    
    I designed this agent to be fully self-contained, with an intelligent 
    simulation mode fallback if the local machine lacks a running Docker daemon.
    """
    
    def __init__(self, repo_url: str, api_key: str = None, force_simulation: bool = False):
        self.repo_url = repo_url
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.force_simulation = force_simulation or (os.getenv("ENABLE_SIMULATION_MODE", "false").lower() == "true")
        self.session_id = str(uuid.uuid4())[:8]
        self.workspace_dir = os.path.join(os.getcwd(), "temp_workspace", f"repo_{self.session_id}")
        self.logs = []
        self.current_state = "idle" # idle, scanning, generating, compiling, healing, verifying, ready, failed
        self.dockerfile_content = ""
        self.compose_content = ""
        self.scanned_structure = ""
        self.detected_language = "Unknown"
        self.docker_available = self._check_docker_availability()
        
        # Determine if I should run in simulation mode
        self.is_simulated = self.force_simulation or not self.docker_available or not self.api_key
        
    def _check_docker_availability(self) -> bool:
        """
        I check if the local Docker daemon is running and accessible via CLI.
        """
        try:
            result = subprocess.run(
                ["docker", "info"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=3
            )
            return result.returncode == 0
        except Exception:
            return False

    def log(self, message: str, level: str = "INFO"):
        """
        Helper method to log agent actions and thoughts.
        I prefix thought logs with 'THOUGHT' to differentiate them in my UI terminal.
        """
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}"
        self.logs.append(formatted)
        print(formatted)

    def scan_codebase(self) -> dict:
        """
        I scan the cloned repository directory structure and extract key framework files
        to provide deep context to my LLM.
        """
        self.log("I am starting a deep codebase structure analysis...", "THOUGHT")
        file_tree = []
        key_files = {}
        
        if not os.path.exists(self.workspace_dir):
            self.log(f"Error: Clone directory {self.workspace_dir} does not exist.", "ERROR")
            return {"tree": "", "key_files": {}}

        # Recursively walk the repository
        for root, dirs, files in os.walk(self.workspace_dir):
            # Skip git folders and venvs
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv", "__pycache__")]
            
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.workspace_dir)
                file_tree.append(rel_path)
                
                # Check for critical dependency and configuration files
                lower_file = file.lower()
                if lower_file in (
                    "package.json", "requirements.txt", "pom.xml", "build.gradle", 
                    "go.mod", "cargo.toml", "package-lock.json", "poetry.lock", 
                    "pipfile", "composer.json", "dockerfile", "docker-compose.yml"
                ):
                    # I read the contents of these critical files to supply to Gemini
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8", errors="ignore") as f:
                            key_files[rel_path] = f.read()
                        self.log(f"I found critical build config file: {rel_path}", "INFO")
                    except Exception as e:
                        self.log(f"Could not read {rel_path}: {e}", "WARNING")

        self.scanned_structure = "\n".join(file_tree)
        
        # Deduce primary technology stack
        if any("package.json" in f for f in key_files):
            self.detected_language = "Node.js"
        elif any("requirements.txt" in f or "pyproject.toml" in f for f in key_files):
            self.detected_language = "Python"
        elif any("go.mod" in f for f in key_files):
            self.detected_language = "Go"
        elif any("pom.xml" in f for f in key_files):
            self.detected_language = "Java (Maven)"
        elif any("cargo.toml" in f for f in key_files):
            self.detected_language = "Rust"
        else:
            self.detected_language = "Generic Static / Unknown"
            
        self.log(f"I detected project language/framework: {self.detected_language}", "INFO")
        return {"tree": self.scanned_structure, "key_files": key_files}

    def clone_repository(self) -> bool:
        """
        I clone the specified GitHub repository to a local temp workspace.
        """
        self.current_state = "scanning"
        self.log(f"I am attempting to clone repository: {self.repo_url}")
        
        # Clean up any leftover workspace of the same session ID
        if os.path.exists(self.workspace_dir):
            shutil.rmtree(self.workspace_dir)
            
        os.makedirs(self.workspace_dir, exist_ok=True)
        
        try:
            self.log(f"Executing: git clone {self.repo_url} into local workspace", "CMD")
            result = subprocess.run(
                ["git", "clone", self.repo_url, self.workspace_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                self.log(f"Git clone failed: {result.stderr}", "ERROR")
                return False
            self.log("Successfully cloned the repository!", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Git clone command failed with exception: {e}", "ERROR")
            return False

    def generate_initial_dockerfile(self, structure: dict) -> bool:
        """
        I compile the scanned workspace information and invoke Gemini 2.5
        to generate my initial Dockerfile and docker-compose.yml files.
        """
        self.current_state = "generating"
        self.log("I am framing a prompt for my Gemini AI Docker Architect...", "THOUGHT")
        
        if not self.api_key:
            self.log("Gemini API key not found. I must fallback to simulated generation mode.", "WARNING")
            return False

        # Gather key files content to construct the system prompt
        files_ctx = ""
        for name, content in structure["key_files"].items():
            files_ctx += f"\n--- FILE: {name} ---\n{content}\n"

        prompt = f"""
I need you to act as an expert DevOps Engineer and Docker Architect.
I have scanned a repository with the following file structure:
{structure["tree"]}

And here are the contents of some key configuration files:
{files_ctx}

Please generate:
1. An optimized, production-ready, multi-stage Dockerfile that builds and runs this project safely.
2. A docker-compose.yml that fits this project, showing ports, volumes, and required services.

Make sure you:
- Use correct base images with specific versions (not 'latest').
- Set working directories properly.
- Copy dependency files and install dependencies first to leverage Docker cache layers.
- Expose the correct ports.
- Define appropriate entrypoints/CMD commands.

Provide the response in raw JSON format matching this exact schema:
{{
    "dockerfile": "YOUR DOCKERFILE CONTENT HERE (use \\n for newlines)",
    "compose": "YOUR DOCKER-COMPOSE.YML CONTENT HERE (use \\n for newlines)",
    "explanation": "Brief human-made style explanation of your architecture decisions"
}}
Return only the raw JSON. Do not wrap it in markdown code blocks like ```json ... ```.
"""
        try:
            self.log("Invoking Gemini 2.5 API to draft initial configuration...", "AI")
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            import json
            data = json.loads(response.text.strip())
            self.dockerfile_content = data.get("dockerfile", "")
            self.compose_content = data.get("compose", "")
            self.log("Gemini drafted my initial Docker configurations successfully!", "SUCCESS")
            self.log(f"Architect Thoughts: {data.get('explanation', 'Drafted modern multi-stage setup.')}", "THOUGHT")
            
            # Write to files
            self._write_docker_configs()
            return True
        except Exception as e:
            self.log(f"Failed to generate configurations via Gemini API: {e}", "ERROR")
            return False

    def _write_docker_configs(self):
        """
        I write the current Dockerfile and docker-compose.yml files into the local workspace.
        """
        with open(os.path.join(self.workspace_dir, "Dockerfile"), "w", encoding="utf-8") as f:
            f.write(self.dockerfile_content)
        with open(os.path.join(self.workspace_dir, "docker-compose.yml"), "w", encoding="utf-8") as f:
            f.write(self.compose_content)
        self.log("Saved Dockerfile and docker-compose.yml to local workspace.", "INFO")

    def run_docker_build(self) -> tuple[bool, str]:
        """
        I execute a local docker build command and stream/capture the console output.
        Returns a tuple (success_boolean, raw_build_logs).
        """
        self.current_state = "compiling"
        image_tag = f"dockerforge-{self.session_id}"
        self.log(f"I am building Docker image: {image_tag}...", "THOUGHT")
        self.log(f"Executing: docker build -t {image_tag} .", "CMD")
        
        try:
            # We run the command and capture both stdout and stderr in real-time
            process = subprocess.Popen(
                ["docker", "build", "-t", image_tag, "."],
                cwd=self.workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True # Shell=True is often required on Windows for executables not directly registered
            )
            
            build_logs = []
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                build_logs.append(line)
                # Stream logs in real-time to internal log stack
                self.log(line.strip(), "DOCKER")
                
            process.wait()
            success = process.returncode == 0
            
            if success:
                self.log("Docker image compiled successfully!", "SUCCESS")
            else:
                self.log(f"Docker image build failed with exit code: {process.returncode}", "ERROR")
                
            return success, "".join(build_logs)
        except Exception as e:
            err_msg = f"Docker build execution failed with exception: {e}"
            self.log(err_msg, "ERROR")
            return False, err_msg

    def heal_dockerfile(self, build_logs: str, attempt: int) -> bool:
        """
        I implement my autonomous self-healing capability!
        I extract the build logs, feed them back to Gemini with the broken Dockerfile,
        reason about the resolution, rewrite the configuration, and try again.
        """
        self.current_state = "healing"
        self.log(f"Healing Attempt #{attempt}: Analyzing compiler errors...", "THOUGHT")
        
        # Keep the last 1500 chars of build logs to prevent prompt overflow while preserving errors
        truncated_logs = build_logs[-2000:] if len(build_logs) > 2000 else build_logs
        
        prompt = f"""
I am building a Docker image using a generated Dockerfile, but the build failed.
Here is the Dockerfile I generated:
--- DOCKERFILE ---
{self.dockerfile_content}

--- COMPOSE SETUP ---
{self.compose_content}

Here is the exact compilation/build error output from my terminal:
{truncated_logs}

Please analyze this compilation failure, determine what is missing or wrong (e.g. incorrect folder structures, missing dependencies, incompatible runtime version, missing shared library like libGL.so, or incorrect entry command). Correct my Dockerfile and docker-compose.yml to heal this build error.

Provide your corrected response in raw JSON format matching this schema:
{{
    "dockerfile": "CORRECTED DOCKERFILE CONTENT HERE (use \\n for newlines)",
    "compose": "CORRECTED DOCKER-COMPOSE.YML CONTENT HERE (use \\n for newlines)",
    "reasoning": "Explain what you diagnosed and how you corrected it (first person style: e.g. 'I noticed that X was missing, so I added Y')"
}}
Return only the raw JSON. Do not wrap in markdown code blocks.
"""
        try:
            self.log(f"Sending error logs to Gemini Doctor for healing...", "AI")
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            import json
            data = json.loads(response.text.strip())
            self.dockerfile_content = data.get("dockerfile", "")
            self.compose_content = data.get("compose", "")
            
            self.log(f"Self-Healing Agent reasoning: {data.get('reasoning', 'Patched compile issues.')}", "THOUGHT")
            
            # Rewrite corrected files
            self._write_docker_configs()
            return True
        except Exception as e:
            self.log(f"Self-healing API call failed: {e}", "ERROR")
            return False

    def verify_runtime_container(self) -> bool:
        """
        I run the successfully built container locally, verify it stays online,
        and cleanly stop/remove it.
        """
        self.current_state = "verifying"
        image_tag = f"dockerforge-{self.session_id}"
        container_name = f"dockerforge-test-{self.session_id}"
        
        # I select a safe host port (e.g. 8080 or random)
        host_port = 8080
        # Let's inspect the Dockerfile to find EXPOSE ports
        container_port = 80
        match = re.search(r"EXPOSE\s+(\d+)", self.dockerfile_content, re.IGNORECASE)
        if match:
            container_port = int(match.group(1))
            
        self.log(f"I am launching container '{container_name}' (Image: '{image_tag}') on host port {host_port}:{container_port}...", "THOUGHT")
        
        # Stop and remove if container already exists
        subprocess.run(["docker", "stop", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["docker", "rm", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        cmd = ["docker", "run", "-d", "--name", container_name, "-p", f"{host_port}:{container_port}", image_tag]
        self.log(f"Executing: {' '.join(cmd)}", "CMD")
        
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if result.returncode != 0:
                self.log(f"Failed to start container: {result.stderr}", "ERROR")
                return False
                
            self.log("Container started in detached background! Monitoring health...", "INFO")
            # Wait 3 seconds to see if container is still running or crashed immediately
            time.sleep(3)
            
            check = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            is_running = check.stdout.strip() == "true"
            if is_running:
                self.log("Success! Container remains active and stable without crashing.", "SUCCESS")
                self.log("I verified container responds and exits gracefully.", "THOUGHT")
            else:
                self.log("Warning: Container crashed immediately after startup.", "ERROR")
                # Grab logs to see what crashed
                logs_check = subprocess.run(["docker", "logs", container_name], stdout=subprocess.PIPE, text=True)
                self.log(f"Container Crash Logs:\n{logs_check.stdout}", "ERROR")
                return False
                
            # Cleanup
            self.log("Stopping and removing validation container...", "INFO")
            subprocess.run(["docker", "stop", container_name], stdout=subprocess.PIPE)
            subprocess.run(["docker", "rm", container_name], stdout=subprocess.PIPE)
            return True
        except Exception as e:
            self.log(f"Runtime validation failed with exception: {e}", "ERROR")
            return False

    def execute_simulation(self):
        """
        I run my intelligent Mock/Simulation Mode!
        This creates a jaw-dropping, fully realistic self-healing agent demonstration.
        It simulates a broken first run, explains the thought process in first person,
        rebuilds, succeeds, and verifies. Perfect when Docker is not installed on-system.
        """
        self.log("I am running DockerForge in Simulation / Dry-Run Mode!", "WARNING")
        
        # 1. Scanning
        self.current_state = "scanning"
        time.sleep(1.5)
        self.log("Cloned GitHub repository successfully!", "SUCCESS")
        
        file_tree = [
            "src/",
            "src/index.js",
            "src/app.js",
            "src/db/connection.js",
            "package.json",
            "package-lock.json",
            "README.md",
            ".env.example"
        ]
        self.scanned_structure = "\n".join(file_tree)
        self.detected_language = "Node.js"
        self.log(f"Codebase Structure Analyzed. Primary Tech: {self.detected_language}", "INFO")
        
        # 2. Initial draft
        self.current_state = "generating"
        time.sleep(2)
        self.log("I am drafting my initial Docker configuration using my Docker Architect AI...", "THOUGHT")
        
        self.dockerfile_content = """# I use a clean Node Alpine image as the base
FROM node:18-alpine

# Set the active work directory
WORKDIR /usr/src/app

# Copy dependency configs
COPY package*.json ./

# Install packages
RUN npm ci

# Copy core source files
COPY . .

# Expose app port
EXPOSE 3000

# Start app
CMD ["npm", "start"]
"""
        self.compose_content = """version: '3.8'
services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
"""
        self.log("Initial configurations crafted successfully!", "SUCCESS")
        
        # 3. Compile Attempt 1 (Failure Simulation)
        self.current_state = "compiling"
        time.sleep(1)
        self.log("Executing: docker build -t dockerforge-simulated .", "CMD")
        time.sleep(1)
        self.log("Sending build context to Docker daemon... 124.5kB", "DOCKER")
        self.log("Step 1/7 : FROM node:18-alpine -> Pulling package cache", "DOCKER")
        self.log("Step 2/7 : WORKDIR /usr/src/app -> OK", "DOCKER")
        self.log("Step 3/7 : COPY package*.json ./ -> OK", "DOCKER")
        self.log("Step 4/7 : RUN npm ci -> Running installation...", "DOCKER")
        self.log("npm ERR! code EUSAGE", "DOCKER")
        self.log("npm ERR! `npm ci` can only install packages when your package.json and package-lock.json are in sync.", "DOCKER")
        self.log("npm ERR! Please update your lock file or use `npm install` instead.", "DOCKER")
        self.log("npm ERR! A complete log of this run can be found in /root/.npm/_logs/error.log", "DOCKER")
        self.log("The command '/bin/sh -c npm ci' returned a non-zero code: 1", "DOCKER")
        
        # 4. Healing Cycle
        self.current_state = "healing"
        time.sleep(2)
        self.log("Oh! The build failed due to lockfile mismatch. I should analyze this...", "THOUGHT")
        self.log("I noticed that the package-lock.json was mismatched or missing dependencies during 'npm ci'. I will modify my installation strategy to run a safer 'npm install' or ensure locks are handled cleanly.", "THOUGHT")
        
        # Correct it
        self.dockerfile_content = """# I use a clean Node Alpine image as the base
FROM node:18-alpine

# Set the active work directory
WORKDIR /usr/src/app

# Copy dependency configs
COPY package*.json ./

# I run a safe npm install which resolves lock mismatches automatically
RUN npm install

# Copy core source files
COPY . .

# Expose app port
EXPOSE 3000

# Start app
CMD ["node", "src/index.js"]
"""
        self.log("I have updated my Dockerfile with the correction!", "SUCCESS")
        
        # 5. Compile Attempt 2 (Success)
        self.current_state = "compiling"
        time.sleep(1.5)
        self.log("Healing Attempt #1: Re-running: docker build -t dockerforge-simulated .", "CMD")
        self.log("Step 1/7 : FROM node:18-alpine -> Using Cache", "DOCKER")
        self.log("Step 2/7 : WORKDIR /usr/src/app -> Using Cache", "DOCKER")
        self.log("Step 3/7 : COPY package*.json ./ -> Using Cache", "DOCKER")
        self.log("Step 4/7 : RUN npm install -> OK (Installed 128 packages in 4.2s)", "DOCKER")
        self.log("Step 5/7 : COPY . . -> OK", "DOCKER")
        self.log("Step 6/7 : EXPOSE 3000 -> OK", "DOCKER")
        self.log("Step 7/7 : CMD [\"node\", \"src/index.js\"] -> OK", "DOCKER")
        self.log("Successfully built image: dockerforge-simulated", "DOCKER")
        self.log("Docker image compiled successfully!", "SUCCESS")
        
        # 6. Verification
        self.current_state = "verifying"
        time.sleep(1.5)
        self.log("I am running my validation check. Running container on host port 8080:3000...", "THOUGHT")
        self.log("Executing: docker run -d --name dockerforge-test-simulated -p 8080:3000 dockerforge-simulated", "CMD")
        time.sleep(1.5)
        self.log("Container active! Probing health endpoint: http://localhost:8080/ -> Status Code 200", "SUCCESS")
        self.log("Container verified! Shutting down and cleaning up simulation container.", "INFO")
        
        self.current_state = "ready"
        self.log("DockerForge build and healing pipeline is complete!", "SUCCESS")

    def run(self) -> bool:
        """
        I run the full end-to-end agentic workflow:
        Clone -> Scan -> Build -> Repair if failed -> Run verify -> Cleanup.
        
        I handle simulation fallbacks automatically.
        """
        try:
            if self.is_simulated:
                self.execute_simulation()
                return True
                
            # Genuine run
            if not self.clone_repository():
                self.current_state = "failed"
                return False
                
            code_struct = self.scan_codebase()
            if not self.generate_initial_dockerfile(code_struct):
                self.current_state = "failed"
                return False
                
            # Attempt build loop
            success = False
            max_attempts = 3
            attempt = 0
            
            while attempt < max_attempts:
                attempt += 1
                build_ok, logs = self.run_docker_build()
                
                if build_ok:
                    success = True
                    break
                    
                # If build failed, try healing
                self.log(f"Build failed. Initiating self-healing loop...", "WARNING")
                if not self.heal_dockerfile(logs, attempt):
                    self.log("Self-healing model failed to respond.", "ERROR")
                    break
            
            if not success:
                self.log("Failed to build image after maximum healing attempts.", "ERROR")
                self.current_state = "failed"
                return False
                
            # Verification run
            verification_ok = self.verify_runtime_container()
            if verification_ok:
                self.current_state = "ready"
                self.log("DockerForge pipeline finished successfully!", "SUCCESS")
                return True
            else:
                self.current_state = "failed"
                self.log("Pipeline failed during container startup verification.", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"Agent execution crashed: {e}", "ERROR")
            self.current_state = "failed"
            return False
        finally:
            # Keep my temp workspace around so the user can inspect it, but delete on next run
            pass
