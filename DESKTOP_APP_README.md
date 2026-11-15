# Jarvis Desktop Screen Assistant (GUI)

A modern dark graphical interface for the OpenJarvis screen-seeing and PC control assistant.

---

## 🚀 How to Run

### Method 1: Double-Click Desktop Shortcut
- Double-click **`Jarvis_Desktop_App.bat`** on your desktop.

### Method 2: Command Line
```powershell
cd C:\Users\ASC\.gemini\antigravity\scratch\OpenJarvis
python ui.py
```

### Fallback: Working Console Version
If you ever want the original console mode, it is kept safe:
```powershell
python screen_assistant.py
# or with voice:
python screen_assistant.py --voice
```

---

## 🎛️ App Features & Buttons

| Control / Area | Description |
|---|---|
| **Chat Area** | Shows user commands and Jarvis responses in conversational bubbles. |
| **Input Bar & Send** | Type any request and press Enter or click Send. |
| **🎙️ Mic Button** | Push-to-talk voice input with pulsing animation while listening. |
| **Status Badge** | Real-time state: `Idle` (Green), `Looking at screen` (Cyan), `Thinking` (Yellow), `Waiting for your approval` (Orange), `Acting` (Orange-Red), `Stopped` (Red). |
| **📋 Plan Card** | Appears when Jarvis proposes steps. Features large **[APPROVE & EXECUTE]** and **[CANCEL]** buttons. Risky actions (send/delete/pay) are highlighted in red. |
| **Screen Preview** | Displays a live thumbnail of the last screen captured and active window title. |
| **👀 What's on my screen?** | Instant 1-click screen analysis using local vision model (`moondream`). |
| **🚨 Emergency STOP Button** | Always visible in red at the top right. Instantly halts all mouse and keyboard actions (same as pressing **Ctrl + Alt + Q**). |
| **Pin on Top** | Keeps the Jarvis window floating above other applications. |
| **System Tray** | Minimizes to system tray on close; right-click tray icon to Restore or Quit. |
| **Action Log Tab** | Complete chronological audit log of every step, tool, and result. |
| **Settings Tab** | Configure model, Ollama endpoint, timeout (default 120s), voice on/off, dry-run on/off. |

---

## 💡 5 Example Commands to Try

1. **`what is on my screen`**  
   *(Jarvis takes a screenshot, passes it to moondream, and describes all open windows and content)*
2. **`summarise this page`**  
   *(Jarvis analyzes your active document or browser page and summarizes it)*
3. **`open notepad and type meeting notes`**  
   *(Jarvis formulates a plan, waits for your click on [APPROVE], opens Notepad, and types the text)*
4. **`open chrome and go to youtube.com`**  
   *(Jarvis proposes opening YouTube, waits for your approval, and navigates there)*
5. **`scroll down and check what changed`**  
   *(Jarvis scrolls the active window, takes another screenshot, and reports)*

---

## 📦 How to Package into a Single .EXE (PyInstaller)

To bundle Jarvis into a standalone Windows `.exe` application:

1. Install PyInstaller:
   ```powershell
   pip install pyinstaller
   ```
2. Build the `.exe` from the OpenJarvis directory:
   ```powershell
   cd C:\Users\ASC\.gemini\antigravity\scratch\OpenJarvis
   pyinstaller --noconsole --onefile --name "Jarvis" --collect-all customtkinter ui.py
   ```
3. Your standalone executable will be generated in `C:\Users\ASC\.gemini\antigravity\scratch\OpenJarvis\dist\Jarvis.exe`.
