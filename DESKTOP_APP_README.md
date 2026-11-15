# J.A.R.V.I.S. — Autonomous Desktop Screen Assistant (GUI)

A high-tech, dark-themed graphical interface for OpenJarvis with 3 distinct operational modes, real-time vision, PC control, and autonomous fast-path execution.

---

## 🚀 3 Separated Modes

The interface has 3 dedicated screens accessible via the top navigation bar:

1. **🎙️ Voice Talking Mode**
   - **Central Hovering Iron Man Arc-Reactor HUD**: Floating, rotating holographic core that reacts visually to speech.
   - **State-Reactive Animations**:
     - 🟣 Cyan / Blue = Standby / Idle
     - 🟣 Magenta Pulsing = Listening to your microphone
     - 🟡 Gold Rotating = Thinking / Processing
     - 🟠 Orange = Autonomous PC action in progress
     - 🔴 Red = Emergency stop
   - **Big Push-to-Talk Button**: Press and speak any command.
   - **Live Dialogue Display**: Real-time transcript of what you said and Jarvis's spoken reply.

2. **💬 Chat Assistant**
   - **Messaging Stream**: Conversational bubble interface with complete chat history.
   - **Plan Approval Card**: Interactive card with large **[APPROVE & EXECUTE]** and **[CANCEL]** buttons for complex multi-step plans. Risky actions (send/delete/pay) are highlighted in red.
   - **Direct Input Bar**: Type any instruction and press Enter or Send.

3. **🖥️ Screen Control & Action Audit**
   - **Live Screen Thumbnail**: Real-time preview of the captured screen and active window title.
   - **👀 "What's on my screen?" Button**: Instant 1-click vision analysis powered by local vision model (`moondream`).
   - **Quick App Shortcuts**: 1-click launch for Notepad, Chrome, Calculator, and Calendar.
   - **Action Audit Log**: Detailed chronological execution log of every step, tool, and outcome.

---

## ⚡ Instant Fast-Path Execution (< 1 Second)

Common tasks bypass slow LLM generation and execute immediately:
- **YouTube Playback**: *"open youtube and play mrbeast recent video"*, *"play despacito on youtube"*
- **App Launching**: *"open notepad"*, *"open calculator"*, *"open chrome"*, *"open calendar"*
- **Website Navigation**: *"open amazon.com"*, *"go to reddit"*, *"visit github"*
- **Calendar & Meetings**: *"schedule a meeting with doctor tomorrow"* (opens pre-filled Google Calendar)
- **Screen Inspection**: *"what is on my screen"*, *"describe screen"*, *"summarize this page"*
- **Volume & Media**: *"volume up"*, *"volume down"*, *"mute"*
- **Google Search**: *"search weather in new york"*, *"google latest news"*

---

## 🖥️ Desktop Launchers

On your Desktop (`D:\OneDrive\Desktop\`):

| Launcher | What it Opens |
|---|---|
| **`Jarvis.exe`** | Standalone double-click executable (no terminal required) |
| **`Jarvis_Voice_Mode.bat`** | Opens directly into the Voice Talking Mode with hovering HUD |
| **`Jarvis_Chat_Mode.bat`** | Opens directly into the Chat Assistant Mode |
| **`Jarvis_Screen_Control.bat`**| Opens directly into Screen Control & Vision Mode |
| **`Jarvis_Desktop_App.bat`** | Launches the GUI desktop application |
| **`Run_OpenJarvis_ScreenAssistant.bat`** | Console fallback mode |

---

## 🛑 Safety & Emergency Stop

- **Big Red STOP Button**: Top right header, always visible. Halts all keyboard/mouse actions immediately.
- **Global Hotkey**: Press **Ctrl + Alt + Q** anywhere in Windows to trigger emergency abort.
- **Mouse Corner Failsafe**: Slam the mouse into any screen corner to trigger PyAutoGUI failsafe.
- **Sensitive Keywords Guard**: Passwords, OTP codes, credit card numbers, and banking terms are blocked from typing.
- **15-Step Limit**: Prevents infinite loops or runaway processes.
