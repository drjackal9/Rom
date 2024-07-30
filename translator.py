import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from deep_translator import GoogleTranslator
import requests
import threading

def translate_text():
    source_lang = source_lang_var.get()
    target_lang = target_lang_var.get()
    input_text = input_text_area.get("1.0", tk.END).strip()
    
    if not input_text:
        messagebox.showwarning("Attenzione", "Per favore, inserisci del testo da tradurre.")
        return
    
    translate_button.config(state=tk.DISABLED)
    status_label.config(text="Traduzione in corso...")
    
    def translate_thread():
        try:
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            translated_lines = []
            
            for line in input_text.split('\n'):
                if line.strip():
                    try:
                        translated_line = translator.translate(line)
                        translated_lines.append(translated_line)
                    except requests.exceptions.RequestException as e:
                        translated_lines.append(f"[Errore di traduzione: {str(e)}]")
                else:
                    translated_lines.append('')
            
            translated_text = '\n'.join(translated_lines)
            
            root.after(0, lambda: update_output(translated_text))
        except Exception as e:
            root.after(0, lambda: show_error(str(e)))
        finally:
            root.after(0, lambda: reset_ui())
    
    threading.Thread(target=translate_thread, daemon=True).start()

def update_output(text):
    output_text_area.delete("1.0", tk.END)
    output_text_area.insert(tk.END, text)

def show_error(message):
    messagebox.showerror("Errore", f"Si è verificato un errore durante la traduzione:\n{message}")

def reset_ui():
    translate_button.config(state=tk.NORMAL)
    status_label.config(text="")

# Creazione della finestra principale
root = tk.Tk()
root.title("Traduttore di Canzoni")
root.geometry("800x600")

# Frame principale
main_frame = ttk.Frame(root, padding="10")
main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# Selezione lingua
source_lang_var = tk.StringVar(value="auto")
target_lang_var = tk.StringVar(value="it")

ttk.Label(main_frame, text="Lingua sorgente:").grid(row=0, column=0, sticky=tk.W)
ttk.Combobox(main_frame, textvariable=source_lang_var, values=["auto", "it", "en", "es", "fr", "de"]).grid(row=0, column=1, sticky=tk.W)

ttk.Label(main_frame, text="Lingua di destinazione:").grid(row=0, column=2, sticky=tk.W)
ttk.Combobox(main_frame, textvariable=target_lang_var, values=["it", "en", "es", "fr", "de"]).grid(row=0, column=3, sticky=tk.W)

# Area di input
ttk.Label(main_frame, text="Testo originale:").grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))
input_text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=80, height=10)
input_text_area.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S))

# Pulsante di traduzione
translate_button = ttk.Button(main_frame, text="Traduci", command=translate_text)
translate_button.grid(row=3, column=0, columnspan=2, pady=10)

# Etichetta di stato
status_label = ttk.Label(main_frame, text="")
status_label.grid(row=3, column=2, columnspan=2, pady=10)

# Area di output
ttk.Label(main_frame, text="Testo tradotto:").grid(row=4, column=0, columnspan=4, sticky=tk.W)
output_text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=80, height=10)
output_text_area.grid(row=5, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S))

# Configurazione del grid
main_frame.columnconfigure(tuple(range(4)), weight=1)
main_frame.rowconfigure(2, weight=1)
main_frame.rowconfigure(5, weight=1)

root.mainloop()