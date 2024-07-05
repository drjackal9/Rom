import subprocess
import time
from datetime import datetime
import os
import tkinter as tk
from tkinter import ttk, scrolledtext
import re
import logging
import threading
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Set up logging
log_file = os.path.join(os.path.expanduser("~"), "clipboard_monitor.log")
logging.basicConfig(filename=log_file, level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration
MIN_CONTENT_LENGTH = 1
MAX_ENTRIES_PER_FILE = 10000
output_directory = os.path.join(os.path.expanduser("~"), "Desktop", "clipboard_logs")
INITIAL_DELAY = 1  # Reduced initial delay

# Ensure the output directory exists
os.makedirs(output_directory, exist_ok=True)

# Global variables
last_content = ""
monitoring = False
entry_count = 0
ignore_initial = True
output_file = ""
avoid_duplicates = True  # New global variable to enable/disable duplicate check
logged_contents = set()  # Set to track logged contents

def get_clipboard_content():
    try:
        process = subprocess.Popen(
            ['osascript', '-e', 'the clipboard as text'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(timeout=0.5)  # Added timeout
        if stderr:
            logging.error(f"Error getting clipboard content: {stderr.decode()}")
            return None
        return stdout.decode().strip()
    except subprocess.TimeoutExpired:
        logging.warning("Clipboard content retrieval timed out")
        return None
    except Exception as e:
        logging.error(f"Failed to get clipboard content: {e}")
        return None

def get_active_app():
    try:
        return subprocess.check_output([
            "osascript",
            "-e", "tell application \"System Events\"",
            "-e", "set frontApp to name of first application process whose frontmost is true",
            "-e", "end tell"
        ], timeout=0.5).decode().strip()  # Added timeout
    except subprocess.TimeoutExpired:
        logging.warning("Active app retrieval timed out")
        return "Unknown"
    except Exception as e:
        logging.error(f"Failed to get active app: {e}")
        return "Unknown"

def get_text_stats(text):
    words = len(re.findall(r'\w+', text))
    chars = len(text)
    lines = text.count('\n') + 1
    return f"Words: {words}, Characters: {chars}, Lines: {lines}"

def log_content(content):
    global entry_count, output_file, logged_contents  # Aggiunto logged_contents
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_app = get_active_app()
    stats = get_text_stats(content)
    
    log_entry = f"[{timestamp}] App: {active_app}\n{stats}\nContent: {content}\n\n"
    
    try:
        with open(output_file, "a", encoding='utf-8') as f:
            f.write(log_entry)
        
        logged_contents.add(content)  # Aggiunta questa riga per aggiornare il set
        entry_count += 1
        if entry_count >= MAX_ENTRIES_PER_FILE:
            rotate_log_file()
        
        logging.info(f"New content logged at {timestamp} from {active_app}")
        return log_entry
    except Exception as e:
        logging.error(f"Failed to log content: {e}")
        return f"Error: {str(e)}"

def rotate_log_file():
    global output_file, entry_count
    new_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_output_file = os.path.join(output_directory, f"clipboard_history_{new_timestamp}.log")
    output_file = new_output_file
    entry_count = 0
    logging.info(f"Created new log file: {new_output_file}")

def monitor_clipboard(app):
    global last_content, monitoring, ignore_initial, avoid_duplicates
    
    if ignore_initial:
        last_content = get_clipboard_content()
        app.update_debug_info(f"Initial clipboard content ignored.")
    
    app.update_debug_info(f"Starting to monitor clipboard...")
    
    while monitoring:
        current_content = get_clipboard_content()
        if current_content is not None and current_content != last_content and len(current_content) >= MIN_CONTENT_LENGTH:
            if not avoid_duplicates or current_content not in logged_contents:  # Controllo per vedere se il contenuto è già loggato
                log_entry = log_content(current_content)
                app.update_debug_info(log_entry)
                last_content = current_content
        time.sleep(0.1)  # Check every 0.1 seconds
    app.update_debug_info("Monitoring stopped.")

class ClipboardMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Clipboard Monitor")
        self.geometry("500x400")
        self.resizable(True, True)

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="20 20 20 20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.toggle_button = ttk.Button(main_frame, text="Start Monitoring", command=self.toggle_monitoring)
        self.toggle_button.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.status_label = ttk.Label(main_frame, text="Status: Stopped", font=("Helvetica", 12))
        self.status_label.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        self.ignore_initial_var = tk.BooleanVar(value=True)
        self.ignore_initial_check = ttk.Checkbutton(main_frame, text="Ignore initial clipboard content", 
                                                    variable=self.ignore_initial_var)
        self.ignore_initial_check.grid(row=2, column=0, sticky="w", padx=5, pady=5)

        self.avoid_duplicates_var = tk.BooleanVar(value=True)  # Variabile per abilitare/disabilitare duplicati
        self.avoid_duplicates_check = ttk.Checkbutton(main_frame, text="Avoid duplicate entries", 
                                                      variable=self.avoid_duplicates_var)
        self.avoid_duplicates_check.grid(row=3, column=0, sticky="w", padx=5, pady=5)

        ttk.Separator(main_frame, orient="horizontal").grid(row=4, column=0, sticky="ew", padx=5, pady=10)

        self.log_location_label = ttk.Label(main_frame, text=f"Logs saved to:\n{output_directory}", font=("Helvetica", 10), wraplength=460)
        self.log_location_label.grid(row=5, column=0, sticky="ew", padx=5, pady=5)

        self.debug_text = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=60, height=15)
        self.debug_text.grid(row=6, column=0, sticky="nsew", padx=5, pady=5)
        main_frame.grid_rowconfigure(6, weight=1)

        self.update_debug_info("Application started. Click 'Start Monitoring' to begin.")

    def toggle_monitoring(self):
        global monitoring, ignore_initial, output_file, avoid_duplicates
        monitoring = not monitoring
        if monitoring:
            ignore_initial = self.ignore_initial_var.get()
            avoid_duplicates = self.avoid_duplicates_var.get()  # Aggiornamento della variabile avoid_duplicates
            self.toggle_button.config(text="Stop Monitoring")
            self.status_label.config(text="Status: Running")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(output_directory, f"clipboard_history_{timestamp}.log")
            logging.info("Monitoring started")
            self.update_debug_info(f"Monitoring started... {'Ignoring initial content.' if ignore_initial else ''}")
            threading.Thread(target=monitor_clipboard, args=(self,), daemon=True).start()
        else:
            self.toggle_button.config(text="Start Monitoring")
            self.status_label.config(text="Status: Stopped")
            logging.info("Monitoring stopped")
            self.update_debug_info("Monitoring stopped.")

    def update_debug_info(self, info):
        self.debug_text.insert(tk.END, f"{info}\n")
        self.debug_text.see(tk.END)

def main():
    try:
        logging.info("Application started")
        app = ClipboardMonitorApp()
        app.mainloop()
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        raise

if __name__ == "__main__":
    main()