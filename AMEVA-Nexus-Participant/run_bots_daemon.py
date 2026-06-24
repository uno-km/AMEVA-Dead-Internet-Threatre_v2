import subprocess
import os
import sys
import argparse

# Resolve absolute path to the directory containing this script
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Use current virtual environment python path
python_path = sys.executable

# Parse command line arguments
parser = argparse.ArgumentParser(description="AMEVA Bots Daemon Runner")
parser.add_argument(
    "--ollama", 
    type=str, 
    default="https://means-sharing-assure-receptor.trycloudflare.com", 
    help="Ollama API endpoint (Cloudflare tunnel URL)"
)
parser.add_argument(
    "--model",
    type=str,
    default="qwen2.5:3b",
    help="Ollama model to use"
)
args_cli = parser.parse_args()

# Define the 4 bots
bots = ["bot_1", "bot_2", "bot_3", "bot_4"]

print("Killing any existing client_ws.py processes...")
if sys.platform.startswith("win"):
    os.system("wmic process where \"CommandLine like '%client_ws.py%'\" call terminate >nul 2>&1")
else:
    os.system("pkill -f client_ws.py")

for bot_name in bots:
    ollama_url = args_cli.ollama

    args = [
        python_path,
        "-u",
        "client_ws.py",
        "--bot", bot_name,
        "--exp", "EXP_TEST",
        "--server", "ws://localhost:8050",
        "--ollama", ollama_url,
        "--model", args_cli.model
    ]
    
    out_file = f"{bot_name}.log"
    err_file = f"{bot_name}_err.log"
    
    # Open log files
    out_f = open(out_file, "w", encoding="utf-8")
    err_f = open(err_file, "w", encoding="utf-8")
    
    # Spawn the process in a background state
    subprocess.Popen(args, stdout=out_f, stderr=err_f)
        
    print(f"[OK] Spawned {bot_name} -> {ollama_url} (Logs: {out_file})")

print("\nAll bots started successfully! Keeping parent daemon process alive...")
try:
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Exiting daemon...")
