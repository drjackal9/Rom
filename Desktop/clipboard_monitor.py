import pyperclip
import time
from datetime import datetime
import os
import subprocess

# File to save the clipboard contents
output_file = "clipboard_history.log"

# Keep track of the last copied content
last_content = ""

def get_active_app():
    try:
        # This works on macOS to get the active application name
        return subprocess.check_output(["osascript", 
            "-e", "tell application \"System Events\"",
            "-e", "set frontApp to name of first application process whose frontmost is true",
            "-e", "end tell"
        ]).decode().strip()
    except:
        return "Unknown"

def get_current_directory():
    return os.getcwd()

print("Clipboard monitoring started. Press Ctrl+C to stop.")

try:
    while True:
        # Get current clipboard content
        current_content = pyperclip.paste()

        # If the content has changed, save it
        if current_content != last_content:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            active_app = get_active_app()
            current_dir = get_current_directory()

            with open(output_file, "a") as f:
                f.write(f"\n--- Copied at {timestamp} ---\n")
                f.write(f"Active Application: {active_app}\n")
                f.write(f"Current Directory: {current_dir}\n")
                f.write("Copied Content:\n")
                f.write(current_content)
                f.write("\n\n")
            
            last_content = current_content
            print(f"New content saved at {timestamp} from {active_app}")

        # Wait for a short time before checking again
        time.sleep(1)

except KeyboardInterrupt:
    print("\nClipboard monitoring stopped.")